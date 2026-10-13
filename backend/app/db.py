from __future__ import annotations

import hashlib
import os
import threading
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
CREATE TABLE IF NOT EXISTS conversations (
  id BIGSERIAL PRIMARY KEY,
  workspace TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS conversations_workspace ON conversations(workspace);
CREATE TABLE IF NOT EXISTS messages (
  id BIGSERIAL PRIMARY KEY,
  conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user','assistant')),
  content TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'complete',
  citations JSONB,
  context JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id);
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS knowledge_watermark BIGINT NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS knowledge_updates (
  id BIGSERIAL PRIMARY KEY,
  workspace TEXT NOT NULL,
  conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  status TEXT NOT NULL CHECK (status IN ('running','applied','failed')),
  message_start BIGINT NOT NULL,
  message_end BIGINT NOT NULL,
  counts JSONB NOT NULL DEFAULT '{}',
  decisions JSONB NOT NULL DEFAULT '[]',
  error TEXT
);
ALTER TABLE knowledge_updates ADD COLUMN IF NOT EXISTS undone_at TIMESTAMPTZ;
ALTER TABLE knowledge_updates DROP CONSTRAINT IF EXISTS knowledge_updates_status_check;
ALTER TABLE knowledge_updates ADD CONSTRAINT knowledge_updates_status_check
  CHECK (status IN ('running','applied','failed','undone'));
CREATE UNIQUE INDEX IF NOT EXISTS knowledge_running ON knowledge_updates(conversation_id) WHERE status='running';
CREATE TABLE IF NOT EXISTS knowledge_changes (
  id BIGSERIAL PRIMARY KEY,
  update_id BIGINT NOT NULL REFERENCES knowledge_updates(id) ON DELETE CASCADE,
  workspace TEXT NOT NULL,
  op TEXT NOT NULL,
  path TEXT NOT NULL,
  before TEXT,
  after TEXT NOT NULL,
  after_sha256 TEXT NOT NULL
);
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


_schema_lock = threading.Lock()
_ready_databases: set[str] = set()


def ensure_schema() -> None:
    # 백그라운드 정리와 Chat 조회가 DDL 잠금을 동시에 승격하면 deadlock이 생길 수 있다.
    # 같은 DB의 스키마 준비는 성공한 뒤 프로세스 수명 동안 재실행하지 않는다.
    with _schema_lock:
        database = dsn()
        if database in _ready_databases:
            return
        with connect() as conn:
            for stmt in SCHEMA.split(";"):
                if stmt.strip():
                    conn.execute(stmt)
            conn.commit()
        _ready_databases.add(database)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()
