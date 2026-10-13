from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app


@pytest.mark.skipif(not db.available(), reason="PostgreSQL/pgvector 컨테이너가 없으면 생략")
def test_related_notes_happy_path(tmp_path: Path):
    # given: 같은 검색 주제를 다루며 양방향 링크가 있는 고유 Workspace를 사용한다.
    client = TestClient(app)
    ws = tmp_path / "related-ws"
    assert client.post("/api/workspace/create", json={"path": str(ws)}).status_code == 200
    try:
        for name, content in {
            "current": "---\ntags: [검색]\n---\n# MMR\n\nMMR은 검색 관련성과 다양성으로 지식 탐색을 돕는다. [[related]]\n",
            "related": "# 지식 탐색\n\nMMR은 관련성과 다양성을 고려해 비슷하지만 다른 노트를 찾는다. [[current]]\n",
        }.items():
            assert client.post("/api/notes", json={"path": name}).status_code == 200
            assert client.put("/api/notes/content", json={"path": f"{name}.md", "content": content}).status_code == 200

        # when: 별도 Source 색인 없이 현재 Note의 관련 Note를 요청한다.
        response = client.get("/api/notes/related", params={"path": "current.md"})

        # then: 자기 자신을 제외하고 실제 검색한 관련 Note와 직접 연결 표시를 반환한다.
        assert response.status_code == 200
        body = response.json()
        assert body["index_incomplete"] is False
        assert [note["path"] for note in body["results"]] == ["related.md"]
        note = body["results"][0]
        assert note["outgoing"] and note["backlink"]
        assert note["status"] == "indexed" and "vector" in note["via"]
    finally:
        with db.connect() as conn:
            conn.execute("DELETE FROM workspaces WHERE path=%s", (str(ws.resolve()),))
            conn.commit()
