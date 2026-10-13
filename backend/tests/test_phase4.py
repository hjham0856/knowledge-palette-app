import hashlib
import json
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import chat, db
from app.main import app


@pytest.mark.skipif(not db.available(), reason="PostgreSQL/pgvector가 없으면 생략")
def test_create_knowledge_note_linked_to_existing_note(tmp_path: Path, monkeypatch):
    # given: 사용자 결론과 기존 Note를 실제 DB·검색으로 비교하며 LLM HTTP만 대체한다.
    ws = tmp_path / "create"
    original = "# 제텔카스텐의 검색 문제\n\n비슷한 노트만 반복해서 찾으면 새로운 연결이 어렵다.\n"
    original_client = httpx.AsyncClient
    replies = iter([
        {"candidates": [{"kind": "통찰", "title": "MMR과 지식 탐색",
                         "content": "MMR은 검색 정확도보다 예상하지 못한 관련 지식 발견에 의미가 있다."}]},
        {"action": "CREATE", "title": "MMR과 지식 탐색", "content": "관련성을 유지하며 서로 다른 지식을 발견하는 데 MMR을 활용할 수 있다.",
         "links": ["제텔카스텐의 검색 문제"], "reason": "사용자가 발견한 새 연결 관점"},
    ])

    def respond(request):
        payload = json.loads(request.content)
        assert payload["stream"] is False
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                              "message": {"content": json.dumps(next(replies), ensure_ascii=False)}}]})

    monkeypatch.setenv("KP_LLM_BASE_URL", "http://llm.test/v1")
    monkeypatch.setenv("KP_CHAT_MODEL", "test-model")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(
        **kwargs, transport=httpx.MockTransport(respond)
    ))
    with TestClient(app) as client:
        client.post("/api/workspace/create", json={"path": str(ws)})
        (ws / "notes/제텔카스텐의 검색 문제.md").write_bytes(original.encode())
        conv_id = chat.create_conversation(str(ws))["id"]
        chat._insert_message(conv_id, "user", "MMR이 제텔카스텐에 도움이 될까? 검색 정확도보다 예상 밖 관련 지식 발견에 의미가 있겠네.")
        chat._insert_message(conv_id, "assistant", "관련성과 다양성을 함께 고려할 수 있습니다.")
        try:
            # when: 수동 요청으로 정리를 시작하고 백그라운드 적용 결과를 기다린다.
            result = client.post(f"/api/conversations/{conv_id}/knowledge-update").json()
            assert result["status"] == "running"
            for _ in range(300):
                updates = client.get(f"/api/conversations/{conv_id}/knowledge-updates").json()["updates"]
                if updates and updates[0]["status"] != "running":
                    break
                time.sleep(0.1)

            # then: 새 생각은 연결된 Markdown으로 남고 원본·변경 전후 기록이 보존된다.
            assert updates[0]["status"] == "applied", updates
            note = ws / "notes/MMR과 지식 탐색.md"
            assert "[[제텔카스텐의 검색 문제]]" in note.read_text()
            assert (ws / "notes/제텔카스텐의 검색 문제.md").read_bytes() == original.encode()
            assert updates[0]["counts"]["CREATE"] == 1
            with db.connect() as conn:
                change = conn.execute("SELECT op,path,before,after,after_sha256 FROM knowledge_changes WHERE update_id=%s",
                                      (result["id"],)).fetchone()
                assert change[:3] == ("CREATE", "notes/MMR과 지식 탐색.md", None)
                assert change[3].encode() == note.read_bytes()
                assert change[4] == hashlib.sha256(note.read_bytes()).hexdigest()
        finally:
            with db.connect() as conn:
                conn.execute("DELETE FROM conversations WHERE workspace=%s", (str(ws),))
                conn.execute("DELETE FROM workspaces WHERE path=%s", (str(ws),))
                conn.commit()


@pytest.mark.skipif(not db.available(), reason="PostgreSQL/pgvector가 없으면 생략")
def test_update_preserves_existing_body_bytes(tmp_path: Path, monkeypatch):
    # given: 줄바꿈과 속성 서식을 가진 Note에서 본문 재작성은 금지된다.
    ws = tmp_path / "append"
    original = b'---\r\nid: existing\r\nupdated: "2020-01-01" # keep\r\ntags: [rag]\r\n---\r\n\r\n# MMR\r\n\r\nOriginal body.  \r\n'
    original_client = httpx.AsyncClient
    replies = iter([
        {"candidates": [{"kind": "생각", "title": "MMR의 활용", "content": "검색의 다양성을 탐색에 활용한다."}]},
        {"action": "UPDATE", "target": "notes/MMR.md", "content": "다양한 노트의 발견을 돕는 데 활용한다.",
         "links": [], "reason": "기존 지식의 활용 관점 보강"},
    ])

    def respond(request):
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                              "message": {"content": json.dumps(next(replies), ensure_ascii=False)}}]})

    monkeypatch.setenv("KP_LLM_BASE_URL", "http://llm.test/v1")
    monkeypatch.setenv("KP_CHAT_MODEL", "test-model")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(
        **kwargs, transport=httpx.MockTransport(respond)
    ))
    with TestClient(app) as client:
        client.post("/api/workspace/create", json={"path": str(ws)})
        note = ws / "notes/MMR.md"
        note.write_bytes(original)
        conv_id = chat.create_conversation(str(ws))["id"]
        chat._insert_message(conv_id, "user", "MMR의 다양성을 노트 탐색에 활용하겠다.")
        chat._insert_message(conv_id, "assistant", "기존 지식을 발전시키는 관점입니다.")
        try:
            # when: UPDATE 결정을 자동 반영한다.
            client.post(f"/api/conversations/{conv_id}/knowledge-update")
            for _ in range(300):
                updates = client.get(f"/api/conversations/{conv_id}/knowledge-updates").json()["updates"]
                if updates and updates[0]["status"] != "running":
                    break
                time.sleep(0.1)

            # then: updated 값 외 속성은 그대로이고 기존 본문 바이트 뒤에만 새 단락이 붙는다.
            assert updates[0]["status"] == "applied", updates
            after = note.read_bytes()
            body = original.split(b'---\r\n', 2)[2]
            assert after.split(b'---\r\n', 2)[2].startswith(body)
            assert after.endswith("\n\n다양한 노트의 발견을 돕는 데 활용한다.\n".encode())
            assert b'id: existing\r\n' in after and b'" # keep\r\ntags: [rag]\r\n' in after
            with db.connect() as conn:
                assert conn.execute("SELECT before FROM knowledge_changes WHERE update_id=%s",
                                    (updates[0]["id"],)).fetchone()[0].encode() == original
        finally:
            with db.connect() as conn:
                conn.execute("DELETE FROM conversations WHERE workspace=%s", (str(ws),))
                conn.execute("DELETE FROM workspaces WHERE path=%s", (str(ws),))
                conn.commit()
