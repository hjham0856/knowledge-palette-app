from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .workspace import Workspace

app = FastAPI(title="Knowledge Palette")

# Local dev: the Vite dev server runs on 5173 and proxies /api, but allow
# direct local origins too.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_workspace: Workspace | None = None


def current() -> Workspace:
    if _workspace is None:
        raise HTTPException(status_code=409, detail="no workspace open")
    return _workspace


class WorkspacePath(BaseModel):
    path: str


class NoteCreate(BaseModel):
    path: str


class NoteWrite(BaseModel):
    path: str
    content: str


@app.get("/api/workspace")
def get_workspace():
    return {"path": str(_workspace.root) if _workspace else None}


@app.post("/api/workspace/open")
def open_workspace(body: WorkspacePath):
    root = Path(body.path).expanduser()
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="directory does not exist")
    candidate = Workspace(root)
    try:
        candidate.ensure()
    except ValueError as e:
        # 실패한 open이 기존 활성 워크스페이스를 덮어쓰지 않도록 성공 후에만 교체한다.
        raise HTTPException(status_code=400, detail=str(e))
    global _workspace
    _workspace = candidate
    return {"path": str(_workspace.root)}


@app.post("/api/workspace/create")
def create_workspace(body: WorkspacePath):
    root = Path(body.path).expanduser()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise HTTPException(status_code=400, detail=str(e))
    candidate = Workspace(root)
    try:
        candidate.ensure()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    global _workspace
    _workspace = candidate
    return {"path": str(_workspace.root)}


@app.get("/api/notes")
def list_notes():
    ws = current()
    return {
        "notes": [
            {"path": str(p.relative_to(ws.root / "notes")), "name": p.stem} for p in ws.note_files()
        ]
    }


@app.get("/api/notes/content")
def read_note(path: str = Query(...)):
    ws = current()
    try:
        p = ws.safe_note_path(path)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid path")
    if not p.is_file():
        raise HTTPException(status_code=404, detail="note not found")
    return {"path": path, "content": p.read_text(encoding="utf-8")}


@app.post("/api/notes")
def create_note(body: NoteCreate):
    ws = current()
    rel = body.path if body.path.endswith(".md") else body.path + ".md"
    try:
        p = ws.safe_note_path(rel)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid path")
    if p.exists():
        raise HTTPException(status_code=409, detail="note already exists")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"# {p.stem}\n", encoding="utf-8")
    return {"path": rel, "name": p.stem}


@app.put("/api/notes/content")
def write_note(body: NoteWrite):
    ws = current()
    if not body.path.endswith(".md"):
        raise HTTPException(status_code=400, detail="only .md notes can be written")
    try:
        p = ws.safe_note_path(body.path)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid path")
    if not p.is_file():
        raise HTTPException(status_code=404, detail="note not found")
    p.write_text(body.content, encoding="utf-8")
    return {"path": body.path}


@app.get("/api/search")
def search(q: str = Query(...)):
    return {"results": current().search(q)}


@app.get("/api/notes/backlinks")
def backlinks(path: str = Query(...)):
    ws = current()
    try:
        ws.safe_note_path(path)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid path")
    return {"backlinks": ws.backlinks(path)}


@app.get("/api/links/resolve")
def resolve(target: str = Query(...)):
    ws = current()
    status, matches = ws.resolve_target(target)
    return {
        "status": status,
        "matches": [str(p.relative_to(ws.root / "notes")) for p in matches],
    }


@app.get("/api/notes/names")
def note_names():
    ws = current()
    return {
        "notes": [
            {"name": p.stem, "path": str(p.relative_to(ws.root / "notes"))} for p in ws.note_files()
        ]
    }
