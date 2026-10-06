from __future__ import annotations

import hashlib
import os
from pathlib import Path

DEFAULT_DSN = "postgresql://palette:palette@127.0.0.1:54329/knowledge_palette"
EMBEDDING_MODEL = os.environ.get(
    "KP_EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
EMBEDDING_DIM = 384

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS workspaces (
  path TEXT PRIMARY KEY,
  embedding_model TEXT NOT NULL,
  dim INT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS documents (
  workspace TEXT NOT NULL REFERENCES workspaces(path) ON DELETE CASCADE,
  path TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('note','source')),
  fingerprint TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'indexed',
  error TEXT,
  PRIMARY KEY (workspace, path)
);
CREATE TABLE IF NOT EXISTS chunks (
  id BIGSERIAL PRIMARY KEY,
  workspace TEXT NOT NULL,
  doc_path TEXT NOT NULL,
  kind TEXT NOT NULL,
  ordinal INT NOT NULL,
  content TEXT NOT NULL,
  pages TEXT NOT NULL DEFAULT '',
  embedding VECTOR(384) NOT NULL,
  FOREIGN KEY (workspace, doc_path) REFERENCES documents(workspace, path) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS chunks_workspace_doc ON chunks(workspace, doc_path);
"""


def dsn() -> str:
    return os.environ.get("KP_DATABASE_URL", DEFAULT_DSN)


def connect():
    import psycopg

    # 깨진 DB 설정이 있어도 자동 저장을 오래 막지 않도록 접속 타임아웃을 짧게 둔다.
    return psycopg.connect(dsn(), autocommit=False, connect_timeout=3)


def available() -> bool:
    try:
        with connect() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


def ensure_schema() -> None:
    with connect() as conn:
        for stmt in SCHEMA.split(";"):
            if stmt.strip():
                conn.execute(stmt)
        conn.commit()


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()
