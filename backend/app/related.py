from __future__ import annotations

import re

from . import indexer, retrieval
from .workspace import Workspace, extract_wikilinks

QUERY_CHARS = 1200
RESULT_LIMIT = 8
FRONTMATTER = re.compile(r"^---[ \t]*\r?\n(?:(.*?)\r?\n)?---[ \t]*(?:\r?\n|$)", re.DOTALL)


def find_related(ws: Workspace, path: str) -> dict:
    note = ws.safe_note_path(path)
    text = note.read_text(encoding="utf-8")
    query = FRONTMATTER.sub("", text, count=1).strip()[:QUERY_CHARS]
    indexed = indexer.reindex(ws, kinds=("note",))
    # 빈 본문에도 DB·임베딩 준비 실패를 숨기지 않도록 같은 검색 경계를 거친다.
    hits = retrieval.search(
        str(ws.root), "note", query, top_k=2 * retrieval.CANDIDATES,
        exclude_path=f"notes/{note.relative_to(ws.root / 'notes')}",
    )
    if not query:
        return {"results": [], "index_incomplete": bool(indexed["errors"])}
    outgoing = set()
    for target, _alias in extract_wikilinks(text):
        status, matches = ws.resolve_target(target)
        if status == "ok":
            outgoing.add(matches[0].resolve())
    incoming = {item["path"] for item in ws.backlinks(path)}
    seen = {note}
    results = []
    for hit in hits:
        rel = hit["path"].removeprefix("notes/")
        try:
            candidate = ws.safe_note_path(rel)
        except ValueError:
            continue
        if candidate in seen or not candidate.is_file():
            continue
        seen.add(candidate)
        results.append({
            **hit, "path": rel, "name": candidate.stem,
            "outgoing": candidate in outgoing, "backlink": rel in incoming,
        })
        if len(results) == RESULT_LIMIT:
            break
    return {"results": results, "index_incomplete": bool(indexed["errors"])}
