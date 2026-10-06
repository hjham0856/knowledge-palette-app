import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _db_up() -> bool:
    import socket

    try:
        with socket.create_connection(("127.0.0.1", 54329), timeout=1):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not _db_up(), reason="PostgreSQL/pgvector 컨테이너가 없으면 생략")
def test_source_rag_happy_path(tmp_path: Path):
    # given: note 1개와 텍스트 기반 PDF 1개가 있는 새 워크스페이스
    ws = tmp_path / "ws"
    assert client.post("/api/workspace/create", json={"path": str(ws)}).status_code == 200
    client.post("/api/notes", json={"path": "a"})
    client.put(
        "/api/notes/content",
        json={"path": "a.md", "content": "# MMR\n\nMMR은 검색 결과의 다양성을 확보한다.\n"},
    )
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "MMR diversifies retrieval results with relevance.")
    doc.save(ws / "sources" / "mmr.pdf")
    import hashlib

    expected_pdf_hash = hashlib.sha256((ws / "sources" / "mmr.pdf").read_bytes()).hexdigest()

    # when: 스캔/인덱싱 후 Notes/Sources를 각각 검색한다
    rescan = client.post("/api/sources/rescan").json()
    assert rescan["errors"] == [] and "mmr.pdf" in rescan["indexed"]
    notes = client.get("/api/search/notes", params={"q": "MMR"}).json()["results"]
    sources = client.get("/api/search/sources", params={"q": "MMR"}).json()["results"]

    # then: kind/path/page/content/ranking이 구분되어 반환되고 원본은 그대로다
    assert notes and notes[0]["kind"] == "note" and notes[0]["path"].startswith("notes/")
    assert sources and sources[0]["kind"] == "source" and sources[0]["path"].startswith("sources/")
    assert sources[0]["pages"] == "1"
    import hashlib

    assert hashlib.sha256((ws / "sources" / "mmr.pdf").read_bytes()).hexdigest() == expected_pdf_hash
    assert (ws / ".palette" / "derived" / "sources" / "mmr.pdf.md").exists()
