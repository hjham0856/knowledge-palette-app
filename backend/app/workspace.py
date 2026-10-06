from __future__ import annotations

import os
import re
from pathlib import Path

WIKILINK_RE = re.compile(r"\[\[([^\[\]|]+)(?:\|([^\[\]]+))?\]\]")


def extract_wikilinks(text: str) -> list[tuple[str, str | None]]:
    return [(m.group(1).strip(), (m.group(2) or "").strip() or None) for m in WIKILINK_RE.finditer(text)]


class Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve()
        # 심볼릭 링크를 통한 워크스페이스 탈출을 막기 위해 경계는 realpath 기준으로 잡는다.
        self.root_real = Path(os.path.realpath(self.root))
        self.notes_real = Path(os.path.realpath(self.root / "notes"))

    def ensure(self) -> None:
        notes = self.root / "notes"
        if notes.is_symlink():
            # notes/를 심볼릭 링크로 두면 sources 등 원본이나 외부를 덮어쓸 수 있어 거부한다.
            raise ValueError("notes/ must be a real directory, not a symlink")
        notes.mkdir(parents=True, exist_ok=True)
        (self.root / "sources").mkdir(parents=True, exist_ok=True)
        self.notes_real = Path(os.path.realpath(notes))
        if self.notes_real != self.root_real and self.root_real not in self.notes_real.parents:
            raise ValueError("notes/ must resolve inside the workspace")

    def _inside_notes(self, path: Path) -> bool:
        try:
            real = Path(os.path.realpath(path))
        except OSError:
            return False
        return real == self.notes_real or self.notes_real in real.parents

    def note_files(self) -> list[Path]:
        notes = self.root / "notes"
        if notes.is_symlink() or not notes.is_dir():
            return []
        # notes/ 자체가 심볼릭 링크로 워크스페이스 밖을 가리키면 목록을 비운다.
        if self.notes_real != self.root_real and self.root_real not in self.notes_real.parents:
            return []
        out = []
        for p in sorted(notes.rglob("*.md")):
            if p.is_symlink() and not self._inside_notes(p):
                continue
            if p.is_file() and self._inside_notes(p):
                out.append(p)
        return out

    def iter_notes(self) -> list[tuple[Path, str]]:
        out = []
        for p in self.note_files():
            try:
                out.append((p, p.read_text(encoding="utf-8")))
            except (OSError, UnicodeDecodeError):
                continue
        return out

    def safe_note_path(self, rel: str) -> Path:
        if not rel or rel.startswith(("/", "\\")):
            raise ValueError("path must be relative")
        if not rel.endswith(".md"):
            raise ValueError("only .md note paths are allowed")
        notes = self.root / "notes"
        if notes.is_symlink() or not notes.is_dir():
            raise ValueError("notes/ must be a real directory, not a symlink")
        # 직접 read/write 엔드포인트도 같은 경계 검사를 지나야 한다.
        notes_real = Path(os.path.realpath(notes))
        if notes_real != self.root_real and self.root_real not in notes_real.parents:
            raise ValueError("notes/ must resolve inside the workspace")
        candidate = Path(os.path.realpath(notes / rel))
        if candidate != notes_real and notes_real not in candidate.parents:
            raise ValueError("path escapes workspace")
        return candidate

    def resolve_target(self, target: str) -> tuple[str, list[Path]]:
        """Wikilink 해석.

        - "/"를 포함하거나 "./"로 시작하는 대상은 notes/ 기준 상대 경로(확장자 제외)와 정확히 일치해야 한다.
          "./same"은 notes/ 루트의 same.md를, "sub/same"은 하위 경로를 가리킨다.
        - 그 외 순수 basename은 모든 notes/ 아래의 같은 stem 파일과 매칭한다.
          복사본이 하나면 ok, 여러 개면 ambiguous(어느 쪽도 임의 선택하지 않음), 없으면 missing.
        """
        target = target.strip()
        if target.endswith(".md"):
            target = target[:-3]
        notes_dir = self.root / "notes"
        matches: list[Path] = []
        if "/" in target:
            rel = target[2:] if target.startswith("./") else target
            for p in self.note_files():
                if str(p.relative_to(notes_dir).with_suffix("")) == rel:
                    matches.append(p)
        else:
            for p in self.note_files():
                if p.stem == target:
                    matches.append(p)
        if len(matches) == 1:
            return "ok", matches
        if len(matches) == 0:
            return "missing", []
        return "ambiguous", matches

    def backlinks(self, rel_path: str) -> list[dict]:
        target_abs = self.safe_note_path(rel_path)
        out = []
        for p, text in self.iter_notes():
            if p == target_abs:
                continue
            for link_target, _alias in extract_wikilinks(text):
                status, matches = self.resolve_target(link_target)
                if status == "ok" and matches[0] == target_abs:
                    out.append({"path": str(p.relative_to(self.root / "notes")), "name": p.stem})
                    break
        return out

    def search(self, q: str) -> list[dict]:
        q_lower = q.lower()
        out = []
        for p, text in self.iter_notes():
            try:
                rel = str(p.relative_to(self.root / "notes"))
            except ValueError:
                continue
            in_title = q_lower in p.stem.lower()
            in_path = q_lower in rel.lower()
            body_idx = text.lower().find(q_lower)
            if in_title or in_path or body_idx >= 0:
                snippet = ""
                if body_idx >= 0:
                    start = max(0, body_idx - 40)
                    snippet = text[start : body_idx + len(q) + 40].replace("\n", " ")
                out.append({"path": rel, "name": p.stem, "in_title": in_title or in_path, "snippet": snippet})
        return out
