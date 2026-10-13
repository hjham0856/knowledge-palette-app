from __future__ import annotations

import json
import re

import yaml
from fastapi.encoders import jsonable_encoder

from .workspace import Workspace


def frontmatter_notes(ws: Workspace) -> list[dict]:
    notes = []
    for path in ws.note_files():
        rel = str(path.relative_to(ws.root / "notes"))
        note = {"path": rel, "name": path.name, "title": path.stem, "frontmatter": {}, "error": None}
        try:
            text = ws.safe_note_path(rel).read_text(encoding="utf-8")
            lines = text.splitlines()
            body = lines
            if lines and lines[0].lstrip("\ufeff").strip() == "---":
                end = next((i for i in range(1, len(lines)) if lines[i].strip() in ("---", "...")), None)
                if end is None:
                    note["error"] = "frontmatter 종료 구분자가 없습니다."
                    body = []
                else:
                    body = lines[end + 1:]
                    try:
                        fields = yaml.safe_load("\n".join(lines[1:end]))
                        if fields is None:
                            fields = {}
                        if not isinstance(fields, dict):
                            raise ValueError("frontmatter must be a mapping")
                        # 날짜 등 YAML 타입은 응답용으로만 변환하고 Markdown 원문은 손대지 않는다.
                        note["frontmatter"] = json.loads(json.dumps(jsonable_encoder(fields), allow_nan=False))
                    except (yaml.YAMLError, ValueError, TypeError, RecursionError):
                        # 파서 예외에는 원문 값이 들어갈 수 있으므로 일반적인 오류 안내만 반환한다.
                        note["error"] = "frontmatter를 해석할 수 없습니다. YAML 필드 형식을 확인하세요."
            fence = ""
            for line in body:
                marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
                if marker:
                    if not fence:
                        fence = marker[1]
                    elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                        fence = ""
                    continue
                heading = re.match(r"^\s{0,3}#\s+(.+?)\s*#*\s*$", line)
                if not fence and heading:
                    note["title"] = heading[1]
                    break
        except (OSError, UnicodeDecodeError, ValueError):
            note["error"] = "Note 파일을 읽을 수 없습니다."
        notes.append(note)
    return notes
