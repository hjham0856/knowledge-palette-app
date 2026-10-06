# Knowledge Palette

로컬 Markdown Knowledge Base(Local Wiki)를 위한 로컬 우선 PKM 앱.
Phase 1은 AI 없이 Markdown PKM 기본 기능을 제공한다.

## 요구 사항

- Python 3.11+ 및 [uv](https://docs.astral.sh/uv/)
- Node.js 20+ 및 npm

## 설치

```bash
# 백엔드: uv가 backend/.venv를 만들고 의존성을 설치한다
cd backend
uv sync

# 프론트엔드: lockfile 기준으로 설치
cd ../frontend
npm ci
```

백엔드 Python 가상환경은 `backend/.venv/`에 있다. `uv run ...`을 쓰면 자동으로 활성화되므로 별도 activate가 필요 없다. 직접 활성화하려면 `source backend/.venv/bin/activate`.

## 실행

터미널 1:

```bash
cd backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

터미널 2:

```bash
cd frontend
npm run dev
```

브라우저에서 http://127.0.0.1:5173 접속 후, 상단 입력창에 Workspace 절대 경로를 입력해
"열기"(기존 폴더) 또는 "새 Workspace"(없으면 생성)를 선택한다.
예시: 이 저장소의 `example-workspace` 경로를 열어 바로 확인할 수 있다.

## 테스트 / 검증

```bash
cd backend && uv run pytest -q
cd ../frontend && npm run typecheck && npm run build
```

(두 명령은 각각 `backend/`와 `frontend/` 디렉터리에서 실행한다.)

## Phase 1 기능

- Workspace 열기/새로 만들기 (`notes/`, `sources/` 자동 생성)
- 노트 목록(중첩 디렉터리), 읽기/생성/편집, Markdown 원본 자동 저장
- YAML frontmatter 보존, 원본 Markdown 그대로 저장
- `[[wikilink]]` 이동 및 `[[` 자동완성, `[[파일명|별칭]]` 지원
- Backlinks, 제목/파일명/본문 검색
- 렌더링된 Markdown 미리보기 (원시 HTML 비활성화)

정책 및 세부 동작은 `docs/knowledge-palette-architecture.md`의 Phase 1 결정 사항 참고.
