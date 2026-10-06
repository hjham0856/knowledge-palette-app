# 지식 팔레트 MVP

## 1. MVP의 목표

MVP의 성공 여부는 기능 개수로 판단하지 않는다.

다음 경험이 제대로 작동하면 된다.

> 사용자와 AI가 대화한 뒤 앱을 닫아도, 그 과정에서 얻은 중요한 생각이나 이해가 기존 지식과 연결된 Markdown Note로 남아 있다.

---

# 2. MVP 핵심 범위

## Workspace

로컬 서버를 실행하고 브라우저에서 사용하는 앱으로 만든다.

기존 로컬 디렉터리를 Knowledge Workspace로 여는 기능과 새 Workspace 폴더를 생성하는 기능을 모두 지원한다.

```text
notes/
sources/
```

를 기본으로 사용한다.

앱에서 변경한 내용은 실제 filesystem에 반영되어야 한다. 외부 편집기로 발생한 파일 변경 감지와 동시 수정 충돌 처리는 이번 구현 범위에 포함하지 않는다.

---

## Notes

지원 범위:

```text
Markdown 읽기/쓰기
[[wikilink]]
frontmatter
backlink
제목/본문 검색
```

초기에는 완전한 Obsidian급 Live Preview는 목표로 하지 않는다.

편집 내용은 Markdown 원본 파일에 자동 저장한다. 편집기 라이브러리, 세부 편집 UI와 자동 저장 타이밍은 에이전트가 구현 과정에서 선택한다.

`[[wikilink]]`의 연결 대상은 Note의 파일명을 기준으로 찾는다. 본문의 제목을 링크 식별자로 사용하지 않는다.

---

## Chat

대화가 가능하고 응답을 streaming으로 출력한다.

현재 Knowledge Base의 Note를 검색해 Context로 사용할 수 있다.

필요한 경우 Source도 검색한다.

---

## Retrieval

MVP부터 의미 검색을 포함한다.

```text
Lexical Search
+
Embedding Search
↓
Candidate
↓
MMR
↓
Context
```

MMR은 지식 팔레트의 연결 탐색 방향과 잘 맞기 때문에 초기에 포함한다.

---

## PDF

PDF를 `sources/`에 넣으면 인식할 수 있어야 한다.

PDF → text/Markdown → chunk → embedding 흐름을 지원한다.

초기 목표는 모든 PDF를 완벽하게 변환하는 것이 아니라 일반적인 강의 자료와 문서를 실제로 검색할 수 있는 수준이다.

---

## Knowledge Delta

대화에서 저장 가치가 있는 후보를 자동으로 추출한다.

후보 유형:

```text
생각
질문
통찰
중요한 일반 지식
프로젝트 판단/결정
```

각 후보에 대해 기존 Note를 검색한 뒤:

```text
CREATE
UPDATE
LINK
NOOP
```

중 하나를 결정한다.

---

## 자동 반영

Knowledge Delta는 사용자의 매번 승인을 기다리지 않고 적용한다.

다만 초기에는 기존 Note를 파괴적으로 다시 쓰지 않고 append 중심으로 처리한다.

---

## History / Undo

각 Knowledge Update가 무엇을 변경했는지 확인할 수 있다.

한 번의 Update 전체를 Undo할 수 있다.

---

# 3. MVP에서 제외

초기에는 다음을 만들지 않는다.

```text
로그인
계정
Cloud Sync
협업
모바일 앱
Plugin system
Obsidian plugin 호환
Canvas
완전한 Dataview
완전한 Base
Task manager
Calendar
Agent swarm
복잡한 Ontology
자동 웹 크롤링
```

Graph 역시 지식 팔레트의 최종 기능으로는 중요하지만 최초 검증에는 필수로 두지 않는다.

---

# 4. 이후 추가할 기능

## Graph

먼저 Local Graph부터 지원한다.

현재 Note와 직접 연결된 Note를 중심으로 탐색한다.

Global Graph는 이후 추가한다.

## Base Lite

frontmatter를 기준으로:

```text
filter
sort
group
table
list
```

정도를 지원한다.

Dataview 전체를 복제하지 않는다.

## Advanced Retrieval

필요성이 확인되면:

```text
Reranker
Graph expansion
Query rewriting
Multi-query retrieval
```

등을 추가한다.

## Advanced Knowledge Maintenance

장기적으로:

```text
Note merge
Note split
Contradiction detection
오래된 지식 갱신
연결 추천
```

등을 검토한다.

---

# 5. 구현 순서

Phase는 구현 순서이며 사용자 승인을 다시 받아야 하는 작업 경계가 아니다. 특정 Phase에서 멈추도록 제한하지 않고 가용 시간 안에서 가능한 작업을 순서대로 계속 진행한다.

후속 단계에 배치된 기능은 해당 단계에서 완성한다. 예를 들어 Phase 4는 Knowledge Update를 구현하고 Phase 5는 History와 Undo를 구현한다. Phase 4에 History와 Undo가 아직 없다는 이유로 착수를 막거나 Phase 5 전체를 앞당기지 않는다. 전체 MVP의 완료 시점에는 핵심 범위의 자동 변경 기록과 Undo까지 동작해야 한다.

각 단계의 완료 기준과 최소 검증은 해당 기능의 요구사항에 맞춰 에이전트가 구체화한다. 완료한 내용, 검증 결과와 남은 작업을 기록해 다음 작업에서 이어갈 수 있게 한다.

## Phase 1 — Local Wiki

AI 없이 Knowledge Base를 사용할 수 있게 한다.

```text
Workspace
Markdown Editor
wikilink
frontmatter
backlink
검색
```

여기까지 되면 최소 Markdown PKM이다.

---

## Phase 2 — Source & RAG

```text
PDF 등록
Parsing
Chunking
Embedding
pgvector
Hybrid Search
MMR
```

Chat에서 Notes와 Sources를 활용할 수 있게 한다.

---

## Phase 3 — Chat

```text
LLM Provider
Streaming Chat
Context assembly
Note / Source citation
```

Knowledge Base와 실제 대화가 연결된다.

---

## Phase 4 — Knowledge Update

프로젝트의 핵심.

```text
Knowledge Candidate 추출
↓
관련 Note 검색
↓
CREATE / UPDATE / LINK / NOOP
↓
Markdown 자동 갱신
```

이 단계가 완료되어야 지식 팔레트라고 부를 수 있다.

---

## Phase 5 — History

```text
AI 변경 표시
Diff
Undo
```

자동화를 안심하고 사용할 수 있게 만든다.

---

## Phase 6 — Knowledge Navigation

그 후:

```text
Local Graph
Related Notes
Base Lite
```

를 붙인다.

---

# 6. 첫 프로토타입의 테스트 시나리오

Workspace에 다음 Note가 존재한다.

```markdown
# 제텔카스텐의 검색 문제

노트가 늘어나면 기존에 작성한 관련 생각을 사람이 직접 다시 찾기가 어렵다.
```

사용자가 Chat에서 질문한다.

```text
MMR이 제텔카스텐에 도움이 될까?
```

대화 후 다음 결론에 도달한다.

```text
MMR은 검색 정확도를 높이는 것보다
서로 관련되면서도 다른 관점의 Note를 발견하게 하는 데
더 의미가 있을 수 있겠다.
```

시스템은 기존 Note를 검색한다.

새로운 지식이라고 판단하면:

```text
CREATE
[[MMR과 지식 탐색]]
```

을 수행하고,

```text
LINK
[[제텔카스텐의 검색 문제]]
```

를 연결한다.

History에는:

```text
Knowledge Update #1

+ MMR과 지식 탐색.md
↔ 제텔카스텐의 검색 문제
```

가 남는다.

Undo하면 모든 변경이 원상복구된다.

이 시나리오가 제대로 동작하는 것이 첫 번째 목표다.

---

# 7. 아직 확정하지 않아도 되는 것

지금 구현을 막지 않는 문제는 일단 미룬다.

대표적으로:

```text
정확한 Markdown Editor 라이브러리
정확한 PDF Parser
Embedding 모델
LLM Provider 기본값
Note tag 자동 생성 여부
Graph library
Base query 문법
Git 활용 여부
```

실제 구현 중 비교해서 결정해도 된다.

이 목록은 구현을 중단하고 사용자 결정을 기다려야 하는 항목이 아니다. 에이전트가 관련 단계에서 제품 방향에 맞게 선택하고 문서에 반영한다. Note tag 자동 생성 여부처럼 사용자 동작에 영향을 주는 세부 정책도 같은 기준으로 결정한다.

---

# 8. 구현 과정에 위임한 세부 결정

다음 내용은 착수 전 사용자 확인이 필요한 조건이 아니다. 에이전트가 해당 기능을 구현할 때 기존 제품 원칙 안에서 결정한다. 큰 제품 방향 변경이나 진행을 막는 실제 장애가 생길 때만 사용자에게 질문한다.

### Knowledge Update 실행 시점

언제 Knowledge Delta를 추출할지는 Phase 4에서 결정한다.

후보:

```text
매 턴
몇 턴마다
주제가 바뀔 때
사용자가 Chat을 나갈 때
일정 idle 시간이 지난 뒤
```

현재 제안은 **대화가 어느 정도 진행된 뒤 비동기적으로 후보를 누적하고, 주제 전환이나 Chat 종료에 가까운 시점에 통합하는 방식**이다. 확정된 실행 규칙은 아니며, 에이전트가 구현 과정에서 구체화한다.

### Conversation 보존

대화 원문의 저장과 보존 정책은 Conversation 기능을 구현할 때 결정한다.

초기에는 저장하는 편이 디버깅과 Undo에 유리하다.

### Note 편집 UX와 링크 세부 동작

Markdown 원본 자동 저장과 파일명 기준 링크는 확정된 규칙이다. 편집 UI, 저장 타이밍, 링크 대상이 없거나 파일명이 중복될 때의 세부 동작은 Phase 1에서 에이전트가 결정한다. 외부 편집 대응은 구현하지 않는다.
