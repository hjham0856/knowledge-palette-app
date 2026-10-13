from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_frontmatter_fields_and_parse_error(tmp_path: Path):
    # given: 속성이 있는 Note와 잘못된 YAML도 원본 그대로 탐색할 수 있어야 한다.
    notes = tmp_path / "notes"
    notes.mkdir()
    valid = "---\ntags: [rag, 지식]\nstatus: draft\ncreated: 2026-10-13\npriority: 2\n---\n# 본문 제목\n내용\n"
    invalid = "---\ntags: [닫히지 않음\n---\n본문\n"
    (notes / "valid.md").write_text(valid, encoding="utf-8")
    (notes / "invalid.md").write_text(invalid, encoding="utf-8")
    with TestClient(app) as client:
        assert client.post("/api/workspace/open", json={"path": str(tmp_path)}).status_code == 200

        # when: DB나 임베딩 없이 Markdown 속성 목록을 요청한다.
        response = client.get("/api/notes/frontmatter")

    # then: 정상 필드와 개별 파싱 오류를 반환하고 어느 원문도 고치지 않는다.
    assert response.status_code == 200
    result = {note["path"]: note for note in response.json()["notes"]}
    assert result["valid.md"] == {
        "path": "valid.md", "name": "valid.md", "title": "본문 제목",
        "frontmatter": {"tags": ["rag", "지식"], "status": "draft", "created": "2026-10-13", "priority": 2},
        "error": None,
    }
    assert result["invalid.md"]["title"] == "invalid"
    assert result["invalid.md"]["frontmatter"] == {}
    assert result["invalid.md"]["error"]
    assert (notes / "valid.md").read_text(encoding="utf-8") == valid
    assert (notes / "invalid.md").read_text(encoding="utf-8") == invalid
