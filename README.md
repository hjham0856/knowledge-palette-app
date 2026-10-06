# Knowledge Palette

로컬 Markdown Knowledge Base(Local Wiki)를 위한 로컬 우선 PKM 앱.
Phase 1은 AI 없이 Markdown PKM 기본 기능을 제공한다.

## 요구 사항

- Python 3.11+ 및 [uv](https://docs.astral.sh/uv/)
- Node.js 20+ 및 npm

## 설치 (저장소 루트에서)

```bash
cp .env.example .env                          # 개발용 DB 설정 복사 (실제 키는 넣지 않음)
cd backend && uv sync && cd ..                # backend/.venv 생성
cd frontend && npm ci && cd ..                # lockfile 기준 설치
docker compose -f docker/docker-compose.yml up -d   # Phase 2 DB (pgvector). Notes만 쓸 거면 생략 가능
```

`.env`가 없어도 기본 개발용 DB 설정(`127.0.0.1:54329`)으로 백엔드가 동작한다.

## 실행 (저장소 루트에서)

```bash
cd backend
uv run --env-file ../.env uvicorn app.main:app --host 127.0.0.1 --port 8000
```

다른 터미널:

```bash
cd frontend
npm run dev
```

브라우저에서 http://127.0.0.1:5173 접속 후, 상단 입력창에 Workspace 절대 경로를 입력해
"열기"(기존 폴더) 또는 "새 Workspace"(없으면 생성)를 선택한다.
예시: 이 저장소의 `example-workspace` 경로를 열어 바로 확인할 수 있다.

> Offline Notes 모드: `.env`를 만들지 않고 Notes(Phase 1)만 쓰려면 `uv run uvicorn app.main:app --host 127.0.0.1 --port 8000`처럼
> `--env-file` 없이 실행해도 된다. Notes 편집/위키링크/Phase 1 검색은 그대로 동작하고, Sources 인덱싱과 시맨틱 검색만
> DB 비활성 오류를 반환한다.

## 테스트 / 검증

```bash
cd backend && uv run pytest -q
cd ../frontend && npm run typecheck && npm run build
```

(두 명령은 각각 `backend/`와 `frontend/` 디렉터리에서 실행한다.)

## Phase 2 — Source & RAG

위 "설치"에서 `.env` 복사와 Docker DB 기동이 Phase 2에 필요하다. 이후 흐름:

### 실행

위 "실행"과 동일. `--env-file ../.env`가 `.env`를 로드한다(KP_DATABASE_URL 등).

### 사용 흐름

1. `sources/`에 PDF 또는 Markdown 파일을 둔다(중첩 디렉터리 가능).
2. Sources 탭에서 "변경분 스캔/인덱싱"(전체 재구축은 "전체 재구축"). 최초 실행 시 임베딩 모델을 로컬로 다운로드한다.
3. Search 탭에서 검색어/질문을 실행하면 Notes와 Sources 결과가 별도 섹션으로 나온다. Source 결과에는 페이지(p.) 정보가 표시된다.
4. Search의 Note 결과 경로를 클릭하면 해당 Note가 Notes 탭에서 열린다.

### 모델과 재구축 규칙

- 기본 임베딩 모델은 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`(384차원, 한국어/영어 다국어)다. E5 계열의 `"query: "`/`"passage: "` 접두사는 사용하지 않는다.
- 스키마가 `VECTOR(384)`로 고정되어 있으므로 **384차원 모델만** 지원한다. 다른 차원의 모델로 교체하면 전체 재구축만으로는 바꿀 수 없고, 임베딩 스키마 정의 자체를 바꿔야 한다(OpenAI 등 외부 provider는 아직 범위 밖).
- "전체 재구축"(same model)은 기존 청크를 지우지 않고 문서별로 원자 교체한다. 일부 문서가 실패해도 해당 문서의 이전 인덱스와 오류 상태가 남는다.
- 모델을 바꾸는 경우 반드시 "전체 재구축"을 해야 한다. 이때 기존 인덱스와 새 인덱스를 하나의 트랜잭션으로 교체하며, 실패 시 기존 인덱스를 그대로 둔다. 모델이 다른 상태에서 일반 스캔이나 검색을 하면 조용히 섞이는 대신 명확한 오류를 낸다.
- 노트를 편집하면 해당 문서는 `stale`로 표시되고 Search 결과의 "재인덱싱 필요" 배지와 상단 안내로 드러난다(Sources 탭은 source 파일 상태만 보여준다). 재인덱싱 전까지 검색에는 이전 인덱스가 사용된다.

### 오프라인/장애 동작

- DB나 모델을 사용할 수 없을 때 Notes(=Phase 1) 기능은 정상 동작하고, 시맨틱 검색/인덱싱만 "준비 필요"/"비활성" 오류를 반환한다. 가짜 임베딩이나 조용한 폴백은 없다.
- Sources 상태는 파일의 sha256 지문과 DB 기록을 비교해 `indexed / stale(수정됨) / error / not-indexed`로 표시한다.

- Notes 본문이 Markdown 원본이므로 DB 인덱스보다 항상 우선이다. Note 저장 시 해당 문서는 `stale`이 되고 다음 스캔에서 다시 인덱싱된다. DB가 꺼져 있어도 Notes 편집은 정상 동작하고, RAG 검색만 "비활성" 오류를 반환한다.
- 원본 PDF/Markdown은 수정·이동되지 않는다. 파싱 결과는 `.palette/derived/`에 다시 만들 수 있는 파생 데이터로만 둔다.
- 인덱스는 운영/파생 데이터이며, Markdown/PDF 원본에서 언제든 재구축할 수 있다.

설계 결정과 제약은 `docs/knowledge-palette-architecture.md`의 Phase 2 결정 사항 참고.

## Phase 1 기능

- Workspace 열기/새로 만들기 (`notes/`, `sources/` 자동 생성)
- 노트 목록(중첩 디렉터리), 읽기/생성/편집, Markdown 원본 자동 저장
- YAML frontmatter 보존, 원본 Markdown 그대로 저장
- `[[wikilink]]` 이동 및 `[[` 자동완성, `[[파일명|별칭]]` 지원
- Backlinks, 제목/파일명/본문 검색
- 렌더링된 Markdown 미리보기 (원시 HTML 비활성화)

정책 및 세부 동작은 `docs/knowledge-palette-architecture.md`의 Phase 1 결정 사항 참고.
