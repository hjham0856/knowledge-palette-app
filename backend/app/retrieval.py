from __future__ import annotations

import json
import math
import re
from typing import Any

from . import db, embeddings

MMR_LAMBDA = 0.7  # relevance(lambda) vs 선택 집합과의 유사도 페널티(1-lambda)
CANDIDATES = 20


def _lex_score(query: str, text: str) -> float:
    q = query.lower().strip()
    if not q:
        return 0.0
    t = text.lower()
    score = 0.0
    for tok in re.split(r"\s+", q):
        if tok and tok in t:
            score += t.count(tok)
    if q in t:
        score += 2.0
    return score


def _parse_vec(raw: Any) -> list[float]:
    if isinstance(raw, str):
        return json.loads(raw)
    return list(raw)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def search(ws_root: str, kind: str, query: str, top_k: int = 10) -> list[dict]:
    qvec = embeddings.embed_query(query)
    vec_lit = "[" + ",".join(repr(float(x)) for x in qvec) + "]"
    try:
        db.ensure_schema()
    except Exception as e:
        raise RuntimeError(f"DB 사용 불가: {e}")
    with db.connect() as conn:
        row = conn.execute(
            "SELECT embedding_model, dim FROM workspaces WHERE path=%s", (ws_root,)
        ).fetchone()
        if row is None:
            raise RuntimeError("검색 준비가 필요합니다. Sources 탭에서 먼저 스캔/인덱싱하세요.")
        # 현재 모델과 다른 차원/모델로 만든 벡터를 조용히 조회하지 않는다.
        if row[0] != db.EMBEDDING_MODEL or row[1] != db.EMBEDDING_DIM:
            raise RuntimeError(
                f"인덱스가 {row[0]}(dim {row[1]})로 만들어졌습니다. 전체 재구축(full rebuild) 후 검색하세요."
            )
        vec_rows = conn.execute(
            "SELECT c.id, c.doc_path, c.kind, c.content, c.pages, c.embedding <=> %s::vector AS dist, c.embedding::text, d.status "
            "FROM chunks c JOIN documents d ON d.workspace=c.workspace AND d.path=c.doc_path "
            "WHERE c.workspace=%s AND c.kind=%s ORDER BY dist LIMIT %s",
            (vec_lit, ws_root, kind, CANDIDATES),
        ).fetchall()
        all_rows = conn.execute(
            "SELECT c.id, c.doc_path, c.kind, c.content, c.pages, c.embedding::text, d.status "
            "FROM chunks c JOIN documents d ON d.workspace=c.workspace AND d.path=c.doc_path "
            "WHERE c.workspace=%s AND c.kind=%s",
            (ws_root, kind),
        ).fetchall()

    lex_scored = []
    for r in all_rows:
        s = _lex_score(query, f"{r[1]}\n{r[3]}")
        if s > 0:
            lex_scored.append((r, s))
    lex_scored.sort(key=lambda x: x[1], reverse=True)

    pool: dict[int, dict] = {}
    lex_max = lex_scored[0][1] if lex_scored else 1.0
    for r, s in lex_scored[:CANDIDATES]:
        pool[r[0]] = {
            "id": r[0], "path": r[1], "kind": r[2], "content": r[3], "pages": r[4],
            "embedding": _parse_vec(r[5]), "lex": s / lex_max, "vector": 0.0, "via": ["lexical"], "status": r[6],
        }
    for r in vec_rows:
        sim = 1.0 - float(r[5])
        entry = pool.get(r[0])
        if entry is None:
            entry = {
                "id": r[0], "path": r[1], "kind": r[2], "content": r[3], "pages": r[4],
                "embedding": _parse_vec(r[6]), "lex": 0.0, "vector": 0.0, "via": [], "status": r[7],
            }
            pool[r[0]] = entry
        entry["vector"] = max(entry["vector"], sim)
        if "vector" not in entry["via"]:
            entry["via"].append("vector")

    for e in pool.values():
        e["score"] = 0.5 * e["lex"] + 0.5 * e["vector"]

    candidates = sorted(pool.values(), key=lambda e: e["score"], reverse=True)
    selected: list[dict] = []
    remaining = candidates[:]
    while remaining and len(selected) < top_k:
        if not selected:
            best = max(remaining, key=lambda e: e["score"])
        else:
            best = max(
                remaining,
                key=lambda e: MMR_LAMBDA * e["score"]
                - (1 - MMR_LAMBDA) * max(_cosine(e["embedding"], s["embedding"]) for s in selected),
            )
        selected.append(best)
        remaining.remove(best)

    return [
        {
            "kind": e["kind"], "path": e["path"], "content": e["content"], "pages": e["pages"],
            "score": round(e["score"], 4), "lex_score": round(e["lex"], 4),
            "vector_score": round(e["vector"], 4), "via": e["via"], "rank": i + 1,
            "status": e["status"],
        }
        for i, e in enumerate(selected)
    ]
