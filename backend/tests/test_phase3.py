import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app


@pytest.mark.skipif(not db.available(), reason="PostgreSQL/pgvector 컨테이너가 없으면 생략")
def test_stream_saves_complete_with_note_citation(tmp_path: Path, monkeypatch):
    # given: 실제 Note 검색과 DB를 사용하고 외부 LLM HTTP 응답만 대체한다.
    ws = tmp_path / "success"
    question = "MMR의 다양성을 설명해 줘"
    original_client = httpx.AsyncClient

    def respond(request):
        payload = json.loads(request.content)
        assert sum(m["content"] == question for m in payload["messages"]) == 1
        assert "[N1] Note: notes/mmr.md" in payload["messages"][0]["content"]
        return httpx.Response(200, text=(
            'data: {"choices":[{"index":0,"delta":{"content":"다양성 [N1] [N99]"},"finish_reason":null}]}\n\n'
            'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
            'data: [DONE]\n\n'
        ))

    monkeypatch.setenv("KP_LLM_BASE_URL", "http://llm.test/v1")
    monkeypatch.setenv("KP_CHAT_MODEL", "test-model")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(
        **kwargs, transport=httpx.MockTransport(respond)
    ))
    with TestClient(app) as client:
        client.post("/api/workspace/create", json={"path": str(ws)})
        client.post("/api/notes", json={"path": "mmr"})
        client.put("/api/notes/content", json={"path": "mmr.md", "content": "# MMR\nMMR은 관련성과 다양성을 함께 고려한다."})
        conv_id = client.post("/api/conversations", json={}).json()["id"]
        try:
            # when: 질문에 대한 SSE 스트림을 끝까지 소비한다.
            response = client.post(f"/api/conversations/{conv_id}/messages", json={"content": question})
            saved = client.get(f"/api/conversations/{conv_id}").json()["messages"][-1]

            # then: 토큰과 정상 완료 이벤트가 나오고 실제 근거만 인용으로 보존한다.
            assert response.status_code == 200
            assert 'event: delta' in response.text and '다양성 [N1]' in response.text
            assert 'event: done' in response.text
            assert saved["status"] == "complete"
            assert saved["citations"] == [{"label": "N1", "kind": "note", "path": "notes/mmr.md", "pages": ""}]
            assert (ws / "notes/mmr.md").read_text() == "# MMR\nMMR은 관련성과 다양성을 함께 고려한다."
        finally:
            with db.connect() as conn:
                conn.execute("DELETE FROM conversations WHERE workspace=%s", (str(ws),))
                conn.execute("DELETE FROM workspaces WHERE path=%s", (str(ws),))
                conn.commit()


@pytest.mark.skipif(not db.available(), reason="PostgreSQL/pgvector 컨테이너가 없으면 생략")
def test_broken_stream_preserves_interrupted_message(tmp_path: Path, monkeypatch):
    # given: 외부 LLM 연결은 일부 텍스트를 보낸 뒤 끊어진다. 내부 검색과 저장은 실제로 실행한다.
    ws = tmp_path / "interrupted"
    original_client = httpx.AsyncClient

    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"partial"},"finish_reason":null}]}\n\n'
            raise httpx.ReadError("connection lost")

    monkeypatch.setenv("KP_LLM_BASE_URL", "http://llm.test/v1")
    monkeypatch.setenv("KP_CHAT_MODEL", "test-model")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(
        **kwargs, transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=BrokenStream()))
    ))
    with TestClient(app) as client:
        client.post("/api/workspace/create", json={"path": str(ws)})
        conv_id = client.post("/api/conversations", json={}).json()["id"]
        try:
            # when: 연결이 끊기는 스트리밍 요청을 수행한다.
            response = client.post(f"/api/conversations/{conv_id}/messages", json={"content": "설명해 줘"})
            saved = client.get(f"/api/conversations/{conv_id}").json()["messages"][-1]

            # then: 부분 응답은 보존하지만 정상 완료 이벤트나 complete 상태로 처리하지 않는다.
            assert 'event: delta' in response.text and 'event: error' in response.text
            assert 'event: done' not in response.text
            assert saved["content"] == "partial"
            assert saved["status"] == "interrupted"
        finally:
            with db.connect() as conn:
                conn.execute("DELETE FROM conversations WHERE workspace=%s", (str(ws),))
                conn.execute("DELETE FROM workspaces WHERE path=%s", (str(ws),))
                conn.commit()
