# 지식 팔레트 시스템 설계

## 1. 기술 스택

현재 기본 스택은 다음과 같다.

실행 형태는 로컬 서버와 브라우저다. Frontend는 브라우저에서 사용하고 Backend가 로컬 Workspace 파일을 읽고 쓴다.

```text
Frontend
Vue 3 + TypeScript

Backend
FastAPI + Python

Knowledge Storage
Markdown filesystem

Operational DB
PostgreSQL

Vector Search
pgvector

AI
Python AI ecosystem
필요한 라이브러리만 선택적으로 활용
```

PostgreSQL과 pgvector 등 필요한 개발 의존성은 Docker로 구성하고 사용한다. 각 의존성은 필요한 구현 단계에서 도입하며, 세부 구성은 에이전트가 결정한다.

LangChain은 애플리케이션 전체를 지배하는 프레임워크로 사용하지 않는다.

Document Loader, splitter, retriever 등 유용한 부분이 있으면 선택적으로 사용한다.

LangGraph 역시 처음부터 사용하지 않는다.

Knowledge Delta 흐름이 복잡한 agent workflow로 발전할 경우에만 재검토한다.

---

## 2. 전체 구조

```text
┌─────────────────────────────┐
│       Vue + TypeScript      │
│                             │
│ Chat / Notes / Search       │
│ Sources / History / Graph   │
└──────────────┬──────────────┘
               │ HTTP / SSE
               ▼
┌─────────────────────────────┐
│           FastAPI           │
│                             │
│ Chat Service                │
│ Knowledge Service           │
│ Note Service                │
│ Source Service              │
│ Search Service              │
│ History Service             │
└──────────┬────────┬─────────┘
           │        │
           │        └──────────────┐
           ▼                       ▼
   Markdown Files             PostgreSQL
                             + pgvector
           │
           └───────────┐
                       ▼
                 AI Providers
```

---

## 3. 저장 구조

예상 Workspace 구조:

```text
KnowledgePalette/
│
├── notes/
│   ├── mmr과-지식-탐색.md
│   └── ...
│
├── sources/
│   ├── lecture.pdf
│   ├── papers/
│   └── ...
│
├── attachments/
│
├── source_index.md
│
├── .palette/
│   ├── derived/
│   ├── cache/
│   └── config/
│
└── ...
```

`notes/`가 사용자의 실제 Knowledge Base다.

기존 Workspace 폴더 열기와 새 Workspace 폴더 생성을 모두 지원한다. 앱의 편집 내용은 Markdown 원본 파일에 자동 저장한다. 외부 편집 변경 감지와 동시 수정 충돌 처리는 이번 범위에서 제외한다.

`sources/`는 원본 자료다.

`.palette/derived/`에는 PDF를 변환한 Markdown이나 parsing 결과처럼 다시 만들 수 있는 파생 데이터를 둘 수 있다.

---

## 4. PostgreSQL 역할

PostgreSQL은 Note 본문 자체의 원본 저장소가 아니다.

주요 용도는:

```text
파일 인덱스
Source metadata
Chunk metadata
Embedding
Conversation
자동 변경 History
검색 보조 데이터
```

등이다.

Knowledge Base의 핵심 내용은 Markdown에 남긴다.

---

## 5. Note 모델

초기 Note는 최대한 단순하게 유지한다.

```markdown
---
id: kp-20261006-001
created: 2026-10-06
updated: 2026-10-06
tags:
  - rag
  - zettelkasten
sources:
  - lecture-03
---

# MMR은 지식 탐색의 다양성을 높일 수 있다

...

관련: [[제텔카스텐의 검색 문제]]
```

최소 metadata 후보:

```text
id
created
updated
tags
sources
```

Note 종류를

```text
concept
insight
question
decision
```

등으로 강하게 분류하는 것은 초기에는 하지 않는다.

---

## 6. Retrieval

Chat RAG는 단순 Vector Search 하나로 끝내지 않는다.

초기 목표 구조는 다음과 같다.

```text
               ┌─ Lexical Search
Query ─────────┤
               └─ Embedding Search
                        │
                        ▼
                 Candidate Pool
                        │
                        ▼
                       MMR
                        │
                        ▼
                  Context Notes
```

Lexical Search는 정확한 이름이나 용어 탐색에 사용한다.

Embedding Search는 의미적으로 관련된 Note를 찾는다.

MMR은 비슷한 Note만 반복적으로 Context에 들어가는 것을 줄이고 서로 다른 관점의 관련 Note를 확보한다.

이후 필요할 경우:

```text
Reranker
Graph expansion
Query expansion
```

등을 추가한다.

---

## 7. Notes와 Sources 검색 분리

Notes와 Sources는 같은 종류의 문서로 취급하지 않는다.

```text
Knowledge Retrieval
notes/
→ 내가 이미 무엇을 알고 있는가?

Evidence Retrieval
sources/
→ 그 생각의 근거가 되는 자료는 무엇인가?
```

Chat에서는 질문에 따라 두 검색 결과를 조합한다.

대체로:

```text
기존 Notes
→ 필요한 Sources
→ 모델 자체 지식
```

순서로 활용한다.

---

## 8. PDF Ingestion

PDF는 초기 버전부터 지원한다.

기본 흐름:

```text
PDF
 ↓
Parsing
 ↓
Markdown / structured text
 ↓
Chunking
 ↓
Embedding
 ↓
Search Index
```

PDF 자체를 Note로 자동 변환하지 않는다.

변환된 내용은 Source 검색을 위한 자료다.

복잡한 문서에 대응하기 위해 Python 생태계의 PDF 도구를 비교해 선택한다.

후보:

```text
PyMuPDF
Marker
Docling
OCR 도구
```

하나로 고정하기보다는 Parser interface를 둔다.

```python
class DocumentParser:
    def parse(self, file: Path) -> ParsedDocument:
        ...
```

그러면 향후 문서 유형에 따라 parser를 교체할 수 있다.

---

## 9. Chat 처리

기본 Chat 흐름:

```text
User message
     ↓
질문 분석
     ↓
Note retrieval
     ↓
필요하면 Source retrieval
     ↓
Context 구성
     ↓
LLM 호출
     ↓
Streaming response
```

Chat 응답 생성과 Knowledge 저장은 별도의 과정이다.

---

## 10. Knowledge Update

대화 중 또는 일정 시점에 Knowledge Delta를 계산한다.

```text
Conversation
      ↓
Knowledge Candidate Extraction
      ↓
기존 Note 검색
      ↓
Candidate ↔ Existing Note 비교
      ↓
CREATE / UPDATE / LINK / NOOP
      ↓
Operation 생성
      ↓
Markdown 반영
      ↓
History 기록
```

LLM이 파일을 직접 수정하게 하지 않는다.

LLM은 변경 계획만 생성한다.

예:

```json
{
  "operation": "UPDATE",
  "target": "notes/mmr.md",
  "append": "...",
  "links": [
    "제텔카스텐의 검색 문제"
  ]
}
```

실제 파일 변경은 애플리케이션 코드가 수행한다.

---

## 11. UPDATE 정책

초기에는 append 중심으로 간다.

LLM에게 기존 Note 전체를 자유롭게 다시 쓰게 하지 않는다.

허용:

```text
새 단락 추가
기존 단락 뒤 설명 추가
wikilink 추가
metadata 일부 추가
```

초기에는 신중하게 처리:

```text
기존 문장 삭제
기존 주장 의미 변경
대규모 재구성
자동 Note merge
자동 Note split
```

Knowledge Base가 쌓이면서 필요성이 확인될 경우 확장한다.

---

## 12. History와 Undo

AI가 수행한 모든 변경은 하나의 transaction처럼 묶는다.

```text
Knowledge Update #128

CREATE
notes/mmr과-지식-탐색.md

UPDATE
notes/제텔카스텐의-검색-문제.md

LINK
A → B
```

각 변경 전 상태 또는 diff를 저장한다.

사용자가 Undo하면 해당 Knowledge Update 전체를 되돌릴 수 있어야 한다.

Git을 사용자에게 직접 노출하는 방식보다는 앱 자체 History를 우선한다.

내부 구현에서 Git을 활용할지는 별도 판단한다.

---

## 13. UI 구조

고정 3-pane UI는 사용하지 않는다.

상단 또는 주요 navigation을 통해 작업 공간을 전환한다.

```text
Chat
Notes
Search
Sources
Graph
```

각 화면은 Main Canvas를 크게 사용한다.

### Chat mode

Chat을 넓게 사용한다.

필요할 때 관련 Note/Source를 Drawer 또는 임시 Panel로 연다.

### Note mode

Markdown Editor가 Main Canvas를 차지한다.

Backlink와 Related Notes는 필요할 때 보조 영역으로 표시한다.

### Split mode

명시적으로 사용자가 요청했을 때만:

```text
┌─────────────────────┬─────────────────────┐
│        Chat         │        Note         │
│                     │                     │
│                     │                     │
└─────────────────────┴─────────────────────┘
```

형태로 사용한다.

---

## 14. Obsidian 최소 호환

초기 호환 목표:

```text
Markdown
[[wikilink]]
YAML frontmatter
```

필수 편집 기능:

```text
Markdown 편집
wikilink 이동
wikilink 자동완성
backlink
파일명/본문 검색
```

`[[wikilink]]`는 Note 파일명을 기준으로 연결한다. 본문 제목은 링크 식별자로 사용하지 않는다. 링크 대상이 없거나 파일명이 중복되는 경우의 처리 방식, 편집기와 자동 저장 타이밍은 확정된 제품 규칙 안에서 에이전트가 선택한다.

Obsidian의 전체 플러그인 생태계, Canvas, Dataview 문법 등을 복제하지 않는다.

---

## 15. LLM Provider

특정 서비스에 Knowledge Engine을 종속시키지 않는다.

애플리케이션 내부에서는 Provider abstraction을 둔다.

```text
Chat Model
Knowledge Model
Embedding Model
```

역할을 논리적으로 분리한다.

MVP에서는 같은 Provider/Model을 사용해도 되지만 구조상 분리할 수 있도록 한다.

BYOK 및 OpenAI-compatible API 지원을 우선 후보로 둔다.

---

## Phase 1 결정 사항

Phase 1 (Local Wiki)에서 문서에 위임된 세부 정책을 다음과 같이 확정한다.

### Wikilink 식별자와 해석

- `[[target]]`의 식별자는 Note의 **파일명(stem, 확장자 제외)** 이다. 본문 제목(H1 등)은 식별자로 사용하지 않는다.
- `[[파일명|별칭]]` 형식의 alias를 지원한다. alias는 표시용이며 해석에는 쓰지 않는다.
- 해석 규칙:
  - 순수 basename → notes/ 전체에서 같은 stem을 가진 모든 파일과 매칭. 정확히 하나면 ok, 여러 개면 **ambiguous**(어느 쪽도 임의 선택하지 않음, 후보 경로 표시), 없으면 missing.
  - `sub/note`처럼 "/" 포함 → notes/ 기준 상대 경로와 정확히 일치해야 함.
  - `./note` → notes/ 루트의 note에 해당(루트와 하위의 중복을 구분하는 관례).
- 편집기 자동완성에서 basename이 중복인 후보는 `notes/ 기준 상대 경로`를 삽입해 다시 ambiguous가 되지 않게 한다.
- Markdown 렌더링에서 wikilink는 markdown-it inline rule로 텍스트 토큰에서만 처리한다. 코드 블록/인라인 코드/HTML 속성 안에서는 링크로 변환되지 않으며, 파일명과 별칭은 이스케이프된다. `html:false`는 그대로 유지한다.

### 자동 저장과 내비게이션

- 편집 후 **800ms** 디바운스로 자동 저장한다.
- 저장 순서는 하나의 활성 저장 promise로 직렬화한다. 이전 저장이 settle된 뒤에야 현재 텍스트를 판단해 새 저장을 시작하므로, 늦은 스냅샷이 디스크에서 덮어쓰지 않는다.
- 탭 닫기/새로고침 시 `beforeunload` 경고로 미저장 변경(dirty/saving/error/진행 중 저장)을 알린다. 이는 경고일 뿐 브라우저 종료 시 저장을 보장하지는 않는다.
- 노트 전환/워크스페이스 열기·생성 전에는 보류 중인 저장을 await하고, **저장 실패 시 전환을 중단**하며 현재 노트와 초안을 유지한다. 오류 표시와 "다시 저장" 버튼을 제공한다.
- 노트 로드 중에는 navigation busy 플래그로 노트 목록/검색/backlink/워크스페이스 조작 버튼, 경로 입력창, 편집기 textarea를 비활성화해, 노트 A 내용이 노트 B 아래에 섞여 보이거나 도중 편집이 버려지는 것을 막는다. 대상 로드 실패 시에는 현재 노트를 유지한다.
- 열기/생성/노트 선택/노트 생성은 busy 잠금을 유지한 채 전체 동작을 수행해, 워크스페이스 전환과 노트 생성이 서로 경합하지 않게 한다.

### 안전성

- 모든 note 접근(목록/검색/링크/읽기/쓰기)은 같은 경계 검사를 사용한다: 대상 realpath가 workspace `notes/` realpath 안에 있어야 한다.
- `notes/` 디렉터리 자체는 심볼릭 링크일 수 없다. `ensure()`와 `safe_note_path()` 양쪽에서 거부하며, notes/ 자체가 외부나 sources/를 가리키면 open이 실패하고 기존 활성 워크스페이스가 유지된다.
- 워크스페이스 밖을 가리키는 노트 파일 심볼릭 링크는 목록/검색에서 제외하고 읽기도 거부한다. 워크스페이스 안이라도 realpath가 notes/를 벗어나면 동일하게 거부한다.
- 쓰기는 `.md` 파일로 제한한다. `sources/` 원본은 Phase 1에서 읽기만 하며 수정하지 않는다.
- Markdown 미리보기는 `markdown-it`를 `html: false`로 렌더링해 원시 HTML/`<script>`가 실행되지 않게 한다.

### 그 외

- Backend는 기본적으로 `127.0.0.1`에서만 서빙한다(로컬 전용).
- 외부 편집 감지와 동시 수정 충돌 처리는 문서대로 Phase 1 범위에서 제외한다.
- 아직 미구현: AI/Chat, PDF, PostgreSQL/pgvector, History/Undo, Graph.

---
