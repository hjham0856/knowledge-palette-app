from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_local_graph_happy_path(tmp_path: Path):
    # given: 중심에 나가는 링크, backlink, 양방향 링크와 미해결 링크가 함께 있다
    ws = tmp_path / "graph-workspace"
    notes = ws / "notes"
    (notes / "sub").mkdir(parents=True)
    contents = {
        "center.md": "[[out|별칭]] [[out]] [[both]] [[missing]] [[same]]",
        "out.md": "[[second-hop]]",
        "in.md": "[[center]]",
        "both.md": "[[center]]",
        "second-hop.md": "# 직접 연결되지 않은 Note",
        "same.md": "# 루트",
        "sub/same.md": "# 하위",
    }
    for path, content in contents.items():
        (notes / path).write_text(content, encoding="utf-8")
    with TestClient(app) as client:
        assert client.post("/api/workspace/open", json={"path": str(ws)}).status_code == 200

        # when: 현재 Note의 직접 연결만 요청한다 (DB나 임베딩은 필요 없다)
        response = client.get("/api/notes/graph", params={"path": "center.md"})

    # then: 중복 링크는 하나로 합치고 방향을 보존하며 미해결 후보는 노드로 선택하지 않는다
    assert response.status_code == 200
    assert response.json() == {
        "center": "center.md",
        "nodes": [
            {"path": "center.md", "name": "center"},
            {"path": "both.md", "name": "both"},
            {"path": "in.md", "name": "in"},
            {"path": "out.md", "name": "out"},
        ],
        "edges": [
            {"source": "center.md", "target": "both.md", "direction": "both", "bidirectional": True},
            {"source": "in.md", "target": "center.md", "direction": "incoming", "bidirectional": False},
            {"source": "center.md", "target": "out.md", "direction": "outgoing", "bidirectional": False},
        ],
        "unresolved": [
            {"target": "missing", "status": "missing", "matches": []},
            {"target": "same", "status": "ambiguous", "matches": ["same.md", "sub/same.md"]},
        ],
    }
