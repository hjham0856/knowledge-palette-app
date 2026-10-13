# Knowledge Palette

로컬 Markdown Knowledge Base(Local Wiki)를 위한 로컬 우선 PKM 앱.
Phase 1은 AI 없이 Markdown PKM 기본 기능을 제공한다.

전체 코드 검토 가이드: [`docs/review-guide.html`](docs/review-guide.html) · 구현 중 고른 명시되지 않은 선택: [`작업 내역.md`](작업%20내역.md)

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
cd backend && uv run --env-file ../.env pytest -q
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

## Phase 3 — Chat

루트 `.env`에 `.env.example`의 `KP_LLM_BASE_URL`, `KP_CHAT_MODEL`을 지정한 뒤 backend를 다시 시작한다.
Ollama는 `http://127.0.0.1:11434/v1`과 `qwen3.5:4b-mlx`를 사용하고 API 키는 비워 둔다.
OpenAI를 사용하려면 주소를 `https://api.openai.com/v1`, `KP_CHAT_MODEL`을 해당 계정에서 사용할 수 있는 모델,
`KP_LLM_API_KEY`를 개인 API 키로 지정한다. 다른 OpenAI 호환 서비스도 제공받은 `/v1` 주소·모델·키로 설정한다.
`KP_KNOWLEDGE_MODEL`은 비우면 Chat 모델을 사용한다. 키는 `.env`에만 두고 공유하지 않는다.

`KP_LLM_PROVIDER`의 기본값이자 현재 지원 값은 `openai-compatible`이다. Chat은 `get_client("chat")`에서 받은 `LLMClient` 인터페이스로 호출하며, 실제 HTTP 통신은 `OpenAICompatibleClient`가 맡는다. 새 Provider를 추가하려면 `stream_chat(messages)`로 본문 스트림을 반환하고 기존 설정·중단·오류 예외 계약을 지키는 구현체를 만든 뒤, `get_client(role)`의 선택 분기에 연결한다. 역할은 `chat`/`knowledge`이며 `complete(messages, json_mode)`는 비스트리밍 본문을 반환한다.

`KP_LLM_REASONING_EFFORT=none`은 Ollama에서 thinking을 끄는 설정이다. 값이 있으면 요청에 `reasoning_effort`로 그대로 전달한다. 이 파라미터를 지원하지 않는 서비스에서는 값을 비워 보내지 않도록 한다. 스트림의 reasoning 필드는 답변 본문에 포함하지 않는다.

1. Workspace를 연 뒤 Chat에서 새 대화를 만들거나 질문을 보낸다. 답변은 생성되는 대로 표시된다.
2. 기존 Notes를 hybrid 검색(단어+의미)과 MMR(비슷한 근거의 반복 줄이기)로 찾는다. `Sources 근거 포함`을 켜면 자료도 검색한다.
3. 답변의 `[N1]` 같은 인용을 클릭하면 Note가 열린다. `[S1]`은 Source 경로·페이지를 표시한다.
4. 기본은 Chat 전체 화면이다. `노트 함께 보기`를 켤 때만 Chat과 Note를 나란히 표시한다.
5. 모드를 바꿔도 Note 초안과 Chat 응답은 유지된다. Note 저장 실패 시 전환을 중단한다.
   대화를 바꾸거나 중지하면 이전 생성은 취소되고 부분 응답은 `interrupted`로 보존된다.

Chat은 Markdown을 수정하지 않는다. 대화·메시지·인용은 PostgreSQL에 Workspace별로 보존한다.
검색 준비 실패는 화면에 표시하며 근거 없이 대화를 계속한다. 오래된 근거는 제외한다.
빈 응답과 형식 오류는 `error`, 연결 끊김이나 정상 종료가 아닌 응답은 `interrupted`이며 `complete`와 구분한다.
Provider를 설정하지 않아도 Notes/Search/Sources는 사용할 수 있다.

## Phase 6-A — Local Graph

Notes에서 Note를 선택한 뒤 상단 **Graph**를 누르면 현재 Note와 직접 연결된 Note(1-hop)가 보인다.
실선 화살표는 나가는 wikilink, 점선 화살표는 들어오는 backlink, 굵은 양끝 화살표는 양방향 연결이다.
노드나 아래 경로 목록을 누르면 Note 선택과 그래프 중심이 함께 이동한다. 보류 중인 저장이 실패하면 이동하지 않는다.
전체 이름은 경로 목록에서 확인하고, 좁은 화면이나 연결이 많은 그래프는 좌우로 스크롤한다.
missing(대상 없음)·ambiguous(파일명 중복)는 별도 목록에 표시하며 임의의 Note로 연결하지 않는다.
DB·임베딩 없이 Markdown 원본에서 계산한다. Related Notes, Base Lite, Global Graph는 이 단계에 포함하지 않는다.

## Related Notes

Notes 화면에서 `Related Notes · 관련 노트`를 펼치면 보류 중인 편집을 저장하고,
frontmatter를 제외한 본문 앞 1,200자로 Notes만 재색인·hybrid+MMR 검색한다.
자기 자신을 제외한 최대 8개 Note를 보여주며 나가는 링크/Backlink와 재색인 필요 상태를 표시한다.
결과를 클릭하면 저장 완료 후 이동한다. 본문 변경 후에는 `다시 찾기`로 갱신한다.
DB·임베딩을 사용할 수 없으면 `의미 검색 비활성` 오류를 보여준다. LLM 설정은 필요 없다.

## Phase 6-C — Base Lite

Workspace를 연 뒤 **Base**에서 Note의 YAML frontmatter를 표/목록으로 모아 본다. 데이터에 있는 필드로 포함/같음/존재 필터, 오름/내림 정렬, 그룹을 선택한다. 리스트 값은 항목별로 필터링하고 각 값의 그룹에 표시한다. 행을 누르면 기존 저장 대기 규칙을 거쳐 Note를 연다.

DB·임베딩은 필요 없다. 원본은 수정하지 않으며 잘못된 YAML은 Note별 오류로 표시한다. 최신 파일을 읽으려면 새로고침하거나 Base를 다시 연다. 쿼리 문법·Dataview 호환은 지원하지 않는다.


## Phase 4 — Knowledge Update

정상 완료된 대화에서 다시 찾거나 발전시킬 가치가 있는 사용자 생각·질문·통찰·이해를 최대 5개 추출한다.
미처리 완료 턴이 3개 쌓이면 답변 저장 뒤 백그라운드에서 실행한다. 다른 대화로 전환하거나 새 대화를 시작할 때,
또는 Chat의 **지금 정리**를 누르면 완료 턴 1개부터 실행한다. 중단·실패 응답과 그 사용자 턴은 제외한다.

기존 Note를 hybrid+MMR로 검색한 뒤 새 Note 생성(CREATE), 끝에 단락 추가(UPDATE), 연결 추가(LINK),
저장하지 않음(NONE)을 결정한다. 기존 본문은 보존하고 frontmatter의 기존 updated 값만 갱신한다.
sources 원본, tags, sources 속성은 자동 변경하지 않는다. Knowledge 모델은 get_client("knowledge")만 사용한다.

Chat 아래에 새 Note·보강·추가 연결의 누적 수와 변경된 Note를 표시한다. 링크를 누르면 Note가 열린다.
열린 Note가 갱신되면 저장된 편집기는 다시 불러오고, 미저장 초안이 있으면 덮어쓰지 않고 경고한다.
요청 직후와 응답 완료 뒤에는 2초 간격으로 최대 약 4분 20초 동안 상태를 확인한다.
실패하면 **지금 정리**로 재시도할 수 있다.

한 실행의 변경 전후 원문과 SHA-256은 DB에 기록한다. 반영 중 실패하면 전체 파일 변경을 복구하고,
실패한 실행은 처리 위치를 옮기지 않는다. 반영 후 재색인 실패는 Markdown을 유지하고 stale로 남긴다.
DB 연결 자체가 불가능하면 실행/실패 기록도 DB에 남길 수 없으며 요청 오류로 알린다.
## Phase 5 — History / Diff / Undo 사용법

1. **History**를 열면 현재 Workspace의 Knowledge Update(한 번의 지식 정리 실행)가 최신순으로 보인다. 출처 대화, 시각, 새 Note·보강·링크 수와 applied(반영됨) / undone(되돌림) / failed(실패) / running(진행 중) 상태를 확인한다.
2. 기록을 선택해 변경 전(before) → 변경 후(after)의 줄 단위 Diff를 읽는다. `+`와 초록 배경은 추가, `-`와 오류색 배경은 삭제다. 긴 미변경 구간은 접고 변경 주변 3줄을 남긴다. 접힌 구간과 결정·이유(NONE 포함)는 펼쳐 볼 수 있다. Note 경로를 누르면 기존 저장 대기(flush) 후 Note가 열린다.
3. Chat의 지식 정리 요약 아래에도 실행별 **변경 내용**과 **Undo**가 있다. 변경 내용은 해당 History 기록을 연다. 누적 수에는 applied 실행만 포함한다.
4. applied 기록의 **Undo**를 누르고 전체 되돌리기를 확인한다. 이후 수정되거나 사라진 파일 때문에 서버가 409를 반환하면 충돌 경로를 표시한다. 부분 Undo와 Redo는 제공하지 않는다.
5. 성공 후 History·Chat·Note 목록을 갱신한다. 열린 Note가 복원됐으면 다시 읽고, 삭제됐으면 닫는다. 미저장 초안은 덮어쓰지 않으며 예약 저장을 멈추고 경고한다. 이때 **다시 저장**은 복원 내용을 덮거나 삭제된 파일을 다시 만들 수 있으므로 초안을 먼저 확인한다. 검색 재색인 실패는 Undo 성공과 구분해 표시한다.

입문자 코드 검토 순서: `HistoryView.vue`(목록·Diff) → `ChatView.vue`(실행별 버튼) → `App.vue`(Undo와 화면 연결) → `NotesView.vue`(저장·복원·삭제 처리) → `api.ts`(서버 응답 형식).

### History / Undo API

- `GET /api/knowledge-updates`: 현재 Workspace의 실행 목록(최신 id부터), 대화 제목·상태·카운트·오류·Undo 시각.
- `GET /api/knowledge-updates/{id}`: 변경 전후 원문과 CREATE/UPDATE/LINK/NONE 결정 및 이유.
- `POST /api/knowledge-updates/{id}/undo`: applied 실행 전체를 역순으로 되돌린다. CREATE 파일은 삭제하고 UPDATE/LINK는 변경 전 바이트를 복원한다.

Undo 전에 모든 대상 파일의 SHA-256(내용 지문)을 AI 반영 직후 기록과 비교한다.
사용자 편집이나 이후 AI 변경이 있거나 파일이 없으면 **409**와 충돌 경로(`modified`/`missing`)를 반환하고 어떤 파일도 바꾸지 않는다.
같은 Note를 바꾼 최신 실행부터 Undo해야 이전 실행도 되돌릴 수 있다.
쓰기 실패 시 이미 되돌린 파일을 AI 반영 후 내용으로 복구하며 상태는 applied로 남긴다.
성공하면 undone과 undone_at을 기록하고 Notes만 재색인한다. 재색인 실패는 Markdown을 유지하며 stale(검색 색인이 이전 상태)로 표시하고 `reindex_error`로 알린다.
다른 Workspace의 실행은 404, applied가 아닌 실행은 400이다. 기존 Chat의 대화별 API는 유지하며 Redo는 지원하지 않는다.
