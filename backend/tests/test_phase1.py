import os
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_local_wiki_happy_path(tmp_path: Path):
    # given: a fresh workspace directory
    # when: workspace is created and two linked notes are written
    assert client.post("/api/workspace/create", json={"path": str(tmp_path / "ws")}).status_code == 200
    assert client.post("/api/notes", json={"path": "제텔카스텐의-검색-문제"}).status_code == 200
    assert client.post("/api/notes", json={"path": "MMR과-지식-탐색"}).status_code == 200
    body = "관련: [[제텔카스텐의-검색-문제]]\n"
    assert client.put("/api/notes/content", json={"path": "MMR과-지식-탐색.md", "content": body}).status_code == 200

    # then: the filesystem holds the original markdown and links/search reflect it
    on_disk = (tmp_path / "ws" / "notes" / "MMR과-지식-탐색.md").read_text(encoding="utf-8")
    assert on_disk == body
    assert client.get("/api/links/resolve", params={"target": "제텔카스텐의-검색-문제"}).json()["status"] == "ok"
    backlinks = client.get("/api/notes/backlinks", params={"path": "제텔카스텐의-검색-문제.md"}).json()["backlinks"]
    assert [b["name"] for b in backlinks] == ["MMR과-지식-탐색"]
    results = client.get("/api/search", params={"q": "MMR"}).json()["results"]
    assert any(r["name"] == "MMR과-지식-탐색" for r in results)


def test_wikilink_uses_filename_identity(tmp_path: Path):
    # given: basename이 같은 노트가 루트와 하위 디렉터리에 있고, 각각 다른 H1을 가진다
    assert client.post("/api/workspace/create", json={"path": str(tmp_path / "ws2")}).status_code == 200
    assert client.post("/api/notes", json={"path": "same"}).status_code == 200
    assert client.post("/api/notes", json={"path": "sub/same"}).status_code == 200
    client.put("/api/notes/content", json={"path": "same.md", "content": "# 루트 노트\n"})
    client.put("/api/notes/content", json={"path": "sub/same.md", "content": "# 하위 노트\n"})

    # when / then: plain [[same]]은 모든 복사본에서 모호하므로 ambiguous
    assert client.get("/api/links/resolve", params={"target": "same"}).json()["status"] == "ambiguous"
    # 명시적 상대 경로는 정확히 하나를 가리킨다 (./same은 루트)
    assert client.get("/api/links/resolve", params={"target": "sub/same"}).json()["matches"] == ["sub/same.md"]
    assert client.get("/api/links/resolve", params={"target": "./same"}).json()["matches"] == ["same.md"]
    # 본문 H1은 링크 식별자가 아니다
    assert client.get("/api/links/resolve", params={"target": "루트 노트"}).json()["status"] == "missing"


def test_notes_cannot_escape_workspace(tmp_path: Path):
    # given: notes/ 밖에 비밀 파일이 있고, notes/ 안에 그것을 가리키는 심볼릭 링크가 있다
    ws = tmp_path / "ws3"
    assert client.post("/api/workspace/create", json={"path": str(ws)}).status_code == 200
    secret = ws / "secret.md"
    secret.write_text("top secret", encoding="utf-8")
    link = ws / "notes" / "evil.md"
    link.symlink_to(secret)

    # when / then: 목록/검색은 링크를 노출하지 않고, 경로 우회와 링크 읽기도 거부된다
    names = [n["name"] for n in client.get("/api/notes").json()["notes"]]
    assert "evil" not in names
    assert client.get("/api/notes/content", params={"path": "../secret.md"}).status_code == 400
    assert client.get("/api/notes/content", params={"path": "evil.md"}).status_code == 400
    assert all("top secret" not in r["snippet"] for r in client.get("/api/search", params={"q": "top"}).json()["results"])

    # notes/ 디렉터리 자체를 심볼릭 링크로 바꾸면 open이 거부되고 기존 workspace가 유지된다
    ws4 = tmp_path / "ws4"
    (ws4 / "sources").mkdir(parents=True)
    (ws4 / "notes").symlink_to(ws4 / "sources")
    assert client.post("/api/workspace/open", json={"path": str(ws4)}).status_code == 400
    assert client.get("/api/workspace").json()["path"] == str(ws.resolve())
