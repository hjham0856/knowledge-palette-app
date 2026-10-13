import json
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import chat, db, knowledge
from app.main import app


@pytest.mark.skipif(not db.available(), reason="PostgreSQL/pgvector가 없으면 생략")
def test_undo_restores_create_and_link(tmp_path: Path, monkeypatch):
    # given: CREATE와 LINK를 실제 Phase 4 코드로 기록하고 외부 LLM HTTP만 대체한다.
    ws = tmp_path / "undo-success"
    original = "---\r\ntags: [rag]\r\n---\r\n\r\n# 검색 문제\r\n\r\n새 연결이 어렵다.  \r\n".encode()
    original_client = httpx.AsyncClient
    replies = iter([
        {"candidates": [
            {"kind": "통찰", "title": "MMR 탐색", "content": "MMR로 예상 밖 지식을 발견한다."},
            {"kind": "생각", "title": "검색 문제의 연결", "content": "검색 문제를 MMR 탐색과 연결한다."},
            {"kind": "생각", "title": "이미 아는 내용", "content": "저장할 새 내용이 없다."},
        ]},
        {"action": "CREATE", "title": "MMR 탐색", "content": "MMR은 관련성과 다양성을 함께 고려한다.",
         "links": ["검색 문제"], "reason": "새로운 탐색 관점"},
        {"action": "LINK", "target": "notes/검색 문제.md", "links": ["MMR 탐색"], "reason": "새 Note로 연결"},
        {"action": "NONE", "reason": "이미 충분한 지식"},
    ])

    def respond(request):
        assert json.loads(request.content)["stream"] is False
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                              "message": {"content": json.dumps(next(replies), ensure_ascii=False)}}]})

    monkeypatch.setenv("KP_LLM_BASE_URL", "http://llm.test/v1")
    monkeypatch.setenv("KP_CHAT_MODEL", "test-model")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(
        **kwargs, transport=httpx.MockTransport(respond)
    ))
    with TestClient(app) as client:
        assert client.post("/api/workspace/create", json={"path": str(ws)}).status_code == 200
        existing = ws / "notes/검색 문제.md"
        existing.write_bytes(original)
        created = ws / "notes/MMR 탐색.md"
        conv_id = chat.create_conversation(str(ws))["id"]
        chat._insert_message(conv_id, "user", "MMR로 새 지식을 발견하고 검색 문제와 연결하겠다.")
        chat._insert_message(conv_id, "assistant", "다양성과 관련성을 함께 고려할 수 있습니다.")
        try:
            requested = client.post(f"/api/conversations/{conv_id}/knowledge-update").json()
            assert requested["status"] == "running", requested
            update_id = requested["id"]
            for _ in range(300):
                detail = client.get(f"/api/knowledge-updates/{update_id}").json()
                if detail["status"] != "running" and not knowledge._tasks:
                    break
                time.sleep(0.1)
            assert detail["status"] == "applied", detail
            assert {c["op"] for c in detail["changes"]} == {"CREATE", "LINK"}
            # when: AI 변경 실행 1건 전체를 Undo한다.
            response = client.post(f"/api/knowledge-updates/{update_id}/undo")

            # then: 생성 파일을 삭제하고 기존 Note의 줄바꿈·공백까지 복원하며 undone으로 기록한다.
            assert response.status_code == 200, response.text
            result = response.json()
            assert result == {"id": update_id, "status": "undone", "undone_at": result["undone_at"],
                              "restored": ["notes/검색 문제.md"], "deleted": ["notes/MMR 탐색.md"],
                              "reindex_error": None}
            assert result["undone_at"]
            assert not created.exists()
            assert existing.read_bytes() == original
            summary = client.get("/api/knowledge-updates").json()["updates"][0]
            assert summary["id"] == update_id and summary["conversation_id"] == conv_id
            assert isinstance(summary["conversation_title"], str)
            assert summary["counts"] == {"CREATE": 1, "UPDATE": 0, "LINK": 2, "NONE": 1}
            assert summary["status"] == "undone" and summary["undone_at"] == result["undone_at"]
            after_detail = client.get(f"/api/knowledge-updates/{update_id}").json()
            assert after_detail["changes"] == detail["changes"]
            assert after_detail["decisions"][-1]["action"] == "NONE"
            assert after_detail["decisions"][-1]["reason"] == "이미 충분한 지식"
            assert all(d["dropped_links"] == [] for d in after_detail["decisions"])
            with db.connect() as conn:
                status, undone_at = conn.execute(
                    "SELECT status,undone_at FROM knowledge_updates WHERE workspace=%s AND id=%s",
                    (str(ws), update_id),
                ).fetchone()
                assert status == "undone" and str(undone_at) == result["undone_at"]
                assert conn.execute("SELECT path,status FROM documents WHERE workspace=%s", (str(ws),)).fetchall() == [
                    ("notes/검색 문제.md", "indexed")]
        finally:
            with db.connect() as conn:
                conn.execute("DELETE FROM conversations WHERE workspace=%s", (str(ws),))
                conn.execute("DELETE FROM workspaces WHERE path=%s", (str(ws),))
                conn.commit()


@pytest.mark.skipif(not db.available(), reason="PostgreSQL/pgvector가 없으면 생략")
def test_undo_rejects_user_edit_without_partial_changes(tmp_path: Path, monkeypatch):
    # given: CREATE와 LINK를 실제 Phase 4 코드로 기록하고 외부 LLM HTTP만 대체한다.
    ws = tmp_path / "undo-conflict"
    original = "---\r\ntags: [rag]\r\n---\r\n\r\n# 검색 문제\r\n\r\n새 연결이 어렵다.  \r\n".encode()
    original_client = httpx.AsyncClient
    replies = iter([
        {"candidates": [
            {"kind": "통찰", "title": "MMR 탐색", "content": "MMR로 예상 밖 지식을 발견한다."},
            {"kind": "생각", "title": "검색 문제의 연결", "content": "검색 문제를 MMR 탐색과 연결한다."},
            {"kind": "생각", "title": "이미 아는 내용", "content": "저장할 새 내용이 없다."},
        ]},
        {"action": "CREATE", "title": "MMR 탐색", "content": "MMR은 관련성과 다양성을 함께 고려한다.",
         "links": ["검색 문제"], "reason": "새로운 탐색 관점"},
        {"action": "LINK", "target": "notes/검색 문제.md", "links": ["MMR 탐색"], "reason": "새 Note로 연결"},
        {"action": "NONE", "reason": "이미 충분한 지식"},
    ])

    def respond(request):
        assert json.loads(request.content)["stream"] is False
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                              "message": {"content": json.dumps(next(replies), ensure_ascii=False)}}]})

    monkeypatch.setenv("KP_LLM_BASE_URL", "http://llm.test/v1")
    monkeypatch.setenv("KP_CHAT_MODEL", "test-model")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(
        **kwargs, transport=httpx.MockTransport(respond)
    ))
    with TestClient(app) as client:
        assert client.post("/api/workspace/create", json={"path": str(ws)}).status_code == 200
        existing = ws / "notes/검색 문제.md"
        existing.write_bytes(original)
        created = ws / "notes/MMR 탐색.md"
        conv_id = chat.create_conversation(str(ws))["id"]
        chat._insert_message(conv_id, "user", "MMR로 새 지식을 발견하고 검색 문제와 연결하겠다.")
        chat._insert_message(conv_id, "assistant", "다양성과 관련성을 함께 고려할 수 있습니다.")
        try:
            requested = client.post(f"/api/conversations/{conv_id}/knowledge-update").json()
            assert requested["status"] == "running", requested
            update_id = requested["id"]
            for _ in range(300):
                detail = client.get(f"/api/knowledge-updates/{update_id}").json()
                if detail["status"] != "running" and not knowledge._tasks:
                    break
                time.sleep(0.1)
            assert detail["status"] == "applied", detail
            assert {c["op"] for c in detail["changes"]} == {"CREATE", "LINK"}
            edited = existing.read_bytes() + "\r\n사용자의 새 판단.\r\n".encode()
            existing.write_bytes(edited)
            created_after = created.read_bytes()

            # when: 사용자 편집이 있는 실행을 Undo하려 한다.
            response = client.post(f"/api/knowledge-updates/{update_id}/undo")

            # then: 충돌을 알리고 생성 파일을 포함한 모든 파일과 applied 상태를 유지한다.
            assert response.status_code == 409, response.text
            assert response.json()["detail"]["conflicts"] == [{"path": "notes/검색 문제.md", "reason": "modified"}]
            assert existing.read_bytes() == edited
            assert created.read_bytes() == created_after
            remaining = client.get(f"/api/knowledge-updates/{update_id}").json()
            assert remaining["status"] == "applied" and remaining["undone_at"] is None
        finally:
            with db.connect() as conn:
                conn.execute("DELETE FROM conversations WHERE workspace=%s", (str(ws),))
                conn.execute("DELETE FROM workspaces WHERE path=%s", (str(ws),))
                conn.commit()
