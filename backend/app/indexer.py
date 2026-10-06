from __future__ import annotations

import os
from pathlib import Path

from . import db, embeddings, parsers
from .workspace import Workspace

CHUNK_CHARS = 800
CHUNK_OVERLAP = 150


def chunk_pages(pages: list[parsers.ParsedPage]) -> list[dict]:
    """페이지 경계를 주체로 재단하면서 문단(빈 줄)에 가능하면 맞추고, 약간의 오버랩을 둔다."""
    chunks: list[dict] = []
    for page in pages:
        text = page.text.strip()
        if not text:
            continue
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        buf: list[str] = []
        buf_len = 0
        for para in paragraphs:
            if buf_len + len(para) > CHUNK_CHARS and buf:
                chunks.append({"content": "\n\n".join(buf), "pages": str(page.page or "")})
                tail = buf[-1]
                buf, buf_len = [tail], len(tail) if len(tail) <= CHUNK_OVERLAP else 0
                if buf_len == 0:
                    buf = []
            buf.append(para)
            buf_len += len(para)
        if buf:
            chunks.append({"content": "\n\n".join(buf), "pages": str(page.page or "")})
        # 긴 단일 문단은 강제 분할
        out = []
        for c in chunks:
            if len(c["content"]) <= CHUNK_CHARS * 2:
                out.append(c)
            else:
                i = 0
                while i < len(c["content"]):
                    out.append({"content": c["content"][i : i + CHUNK_CHARS], "pages": c["pages"]})
                    i += CHUNK_CHARS - CHUNK_OVERLAP
        chunks = out
    return [c for c in chunks if c["content"].strip()]


def derived_markdown(ws: Workspace, rel: str, parsed: parsers.ParsedDocument) -> Path:
    workspace = ws.root
    # 원본(notes/sources)과 충돌하지 않도록 derived 경로는 실제 .palette/derived 내부로만 제한한다.
    palette = workspace / ".palette"
    if palette.is_symlink():
        raise RuntimeError(".palette 가 심볼릭 링크라 derived를 쓸 수 없습니다")
    derived_root = palette / "derived"
    if derived_root.is_symlink():
        raise RuntimeError(".palette/derived 가 심볼릭 링크라 쓸 수 없습니다")
    derived_root.mkdir(parents=True, exist_ok=True)
    real_root = Path(os.path.realpath(derived_root))
    if real_root != ws.root_real and ws.root_real not in real_root.parents:
        raise RuntimeError(".palette/derived 가 워크스페이스 밖을 가리킵니다")
    target = derived_root / (rel + ".md")
    # mkdir 전에 realpath를 검사해, 탈출하는 디렉터리 심볼릭 링크로 워크스페이스 밖 폴더가 생기지 않게 한다.
    real_parent = Path(os.path.realpath(target.parent))
    if real_parent != real_root and real_root not in real_parent.parents:
        raise RuntimeError("파생 경로가 derived 밖으로 빠져나갑니다")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise RuntimeError("파생 파일이 심볼릭 링크라 덮어쓸 수 없습니다")
    target.write_text(parsed.text, encoding="utf-8")
    return target


def source_files(ws: Workspace) -> list[Path]:
    root = ws.root / "sources"
    if root.is_symlink() or not root.is_dir():
        return []
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink() and parsers.parser_for(p) is not None:
            try:
                real = Path(os.path.realpath(p))
                if Path(os.path.realpath(root)) in real.parents:
                    out.append(p)
            except OSError:
                continue
    return out


def index_status(conn, ws_key: str) -> "tuple[str|None,str|None,int|None]":
    row = conn.execute(
        "SELECT embedding_model, dim, 1 FROM workspaces WHERE path = %s", (ws_key,)
    ).fetchone()
    if row is None:
        return (None, None, None)
    return (row[0], row[1], row[2])


def index_document(conn, ws: Workspace, path: Path, rel: str, kind: str, force: bool = False) -> dict:
    """파싱/임베딩 후 해당 문서의 행을 호출자의 트랜잭션(세이브포인트) 안에서 원자 교체한다."""
    fingerprint = db.sha256_of(path)
    existing = conn.execute(
        "SELECT fingerprint, status FROM documents WHERE workspace=%s AND path=%s",
        (str(ws.root), rel),
    ).fetchone()
    if not force and existing and existing[0] == fingerprint and existing[1] == "indexed":
        return {"path": rel, "status": "unchanged"}
    parser = parsers.parser_for(path)
    if kind == "note":
        parsed = parsers.ParsedDocument([parsers.ParsedPage(None, path.read_text(encoding="utf-8"))])
    else:
        parsed = parser.parse(path)
    derived_markdown(ws, rel, parsed)
    chunks = chunk_pages(parsed.pages)
    vectors = embeddings.embed_passages([c["content"] for c in chunks]) if chunks else []
    conn.execute(
        "DELETE FROM chunks WHERE workspace=%s AND doc_path=%s", (str(ws.root), rel)
    )
    conn.execute(
        "INSERT INTO documents(workspace, path, kind, fingerprint, status, error) VALUES (%s,%s,%s,%s,'indexed',NULL) "
        "ON CONFLICT (workspace, path) DO UPDATE SET fingerprint=EXCLUDED.fingerprint, status='indexed', error=NULL, kind=EXCLUDED.kind",
        (str(ws.root), rel, kind, fingerprint),
    )
    for i, (c, v) in enumerate(zip(chunks, vectors)):
        conn.execute(
            "INSERT INTO chunks(workspace, doc_path, kind, ordinal, content, pages, embedding) VALUES (%s,%s,%s,%s,%s,%s,%s::vector)",
            (str(ws.root), rel, kind, i, c["content"], c["pages"], _vec_lit(v)),
        )
    return {"path": rel, "status": "indexed", "chunks": len(chunks)}


def _vec_lit(v: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in v) + "]"


def reconcile_deleted(conn, ws: Workspace, live_paths: set[str]) -> list[str]:
    rows = conn.execute("SELECT path FROM documents WHERE workspace=%s", (str(ws.root),)).fetchall()
    deleted = []
    for (path,) in rows:
        if path not in live_paths:
            conn.execute("DELETE FROM chunks WHERE workspace=%s AND doc_path=%s", (str(ws.root), path))
            conn.execute("DELETE FROM documents WHERE workspace=%s AND path=%s", (str(ws.root), path))
            deleted.append(path)
    return deleted


def reindex(ws: Workspace, full: bool = False) -> dict:
    db.ensure_schema()
    results = {"indexed": [], "unchanged": [], "errors": [], "deleted": []}
    live: set[str] = set()
    notes_dir = ws.root / "notes"
    docs: list[tuple[Path, str, str]] = []
    for p in ws.note_files():
        docs.append((p, str(p.relative_to(notes_dir)), "note"))
    for p in source_files(ws):
        docs.append((p, str(p.relative_to(ws.root / "sources")), "source"))
    ws_key = str(ws.root)
    with db.connect() as conn:
        stored_model, stored_dim, _ = index_status(conn, ws_key)
        model_mismatch = stored_model is not None and (stored_model != db.EMBEDDING_MODEL or stored_dim != db.EMBEDDING_DIM)
        if model_mismatch and not full:
            raise RuntimeError(
                f"인덱스가 {stored_model}(dim {stored_dim})로 만들어졌습니다. 현재 모델과 다르므로 전체 재구축(full rebuild)이 필요합니다."
            )
        if model_mismatch and full:
            # 모델 변경 재구축은 워크스페이스 전체를 하나의 트랜잭션으로 교체한다.
            # 하나라도 실패하면 채택하지 않고 기존 인덱스/모델 식별자를 그대로 둔다.
            try:
                with conn.transaction():
                    conn.execute("DELETE FROM chunks WHERE workspace=%s", (ws_key,))
                    conn.execute("DELETE FROM documents WHERE workspace=%s", (ws_key,))
                    # 운영 식별자인 workspaces 행은 지우지 않는다. Conversation/History 데이터가
                    # 이 워크스페이스를 참조할 수 있으므로 model/dim만 원자적으로 교체한다.
                    conn.execute(
                        "UPDATE workspaces SET embedding_model=%s, dim=%s, updated_at=now() WHERE path=%s",
                        (db.EMBEDDING_MODEL, db.EMBEDDING_DIM, ws_key),
                    )
                    for path, rel, kind in docs:
                        db_rel = f"notes/{rel}" if kind == "note" else f"sources/{rel}"
                        index_document(conn, ws, path, db_rel, kind, force=True)
                    reconcile_deleted(conn, ws, {f"notes/{r}" if k == "note" else f"sources/{r}" for _, r, k in docs})
                conn.commit()
                return {"indexed": [r for _, r, _ in docs], "unchanged": [], "errors": [], "deleted": [], "rebuilt": True}
            except Exception as e:
                conn.rollback()
                raise RuntimeError(f"모델 변경 전체 재구축 실패 — 기존 인덱스를 그대로 유지합니다: {e}") from e
        if stored_model is None:
            conn.execute(
                "INSERT INTO workspaces(path, embedding_model, dim) VALUES (%s,%s,%s) ON CONFLICT (path) DO NOTHING",
                (ws_key, db.EMBEDDING_MODEL, db.EMBEDDING_DIM),
            )
        for path, rel, kind in docs:
            db_rel = f"notes/{rel}" if kind == "note" else f"sources/{rel}"
            live.add(db_rel)
            try:
                with conn.transaction():  # 문서 단위 세이브포인트: 실패 시 해당 문서만 롤백
                    r = index_document(conn, ws, path, db_rel, kind, force=full)
                conn.commit()
                (results["indexed"] if r["status"] == "indexed" else results["unchanged"]).append(rel)
            except Exception as e:  # 한 문서 실패가 다른 문서의 인덱스를 비우지 않도록 한다
                try:
                    with conn.transaction():
                        conn.execute(
                            "INSERT INTO documents(workspace, path, kind, fingerprint, status, error) VALUES (%s,%s,%s,%s,'error',%s) "
                            "ON CONFLICT (workspace, path) DO UPDATE SET status='error', error=EXCLUDED.error",
                            (ws_key, db_rel, kind, db.sha256_of(path), str(e)[:500]),
                        )
                    conn.commit()
                except Exception:
                    conn.rollback()
                results["errors"].append({"path": rel, "error": str(e)[:200]})
        try:
            with conn.transaction():
                results["deleted"] = reconcile_deleted(conn, ws, live)
            conn.commit()
        except Exception:
            conn.rollback()
    return results


def source_statuses(ws: Workspace) -> list[dict]:
    out = []
    rows = {}
    try:
        with db.connect() as conn:
            for path, kind, status, error, fingerprint in conn.execute(
                "SELECT path, kind, status, error, fingerprint FROM documents WHERE workspace=%s", (str(ws.root),)
            ):
                rows[path] = (status, error, fingerprint)
    except Exception:
        pass
    for p in source_files(ws):
        rel = f"sources/{p.relative_to(ws.root / 'sources')}"
        row = rows.get(rel)
        if row is None:
            out.append({"path": str(p.relative_to(ws.root / "sources")), "indexed_path": rel, "status": "not-indexed", "error": None})
            continue
        status, err, fp = row
        if status == "error":
            shown, shown_err = "error", err
        elif status == "stale" or fp != db.sha256_of(p):
            # 원본이 바뀌었는데 인덱스가 옛날 상태면 stale로 보고한다 (변경 감지)
            shown, shown_err = "stale", None
        else:
            shown, shown_err = "indexed", None
        out.append({"path": str(p.relative_to(ws.root / "sources")), "indexed_path": rel, "status": shown, "error": shown_err})
    return out
