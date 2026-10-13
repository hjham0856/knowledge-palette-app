# 구현 중 결정한 사항

기획 문서가 에이전트에게 위임했거나 아직 정하지 않은 세부 사항을 Phase 3~6 구현 과정에서 다음과 같이 정했다. 각 항목은 선택과 그 이유를 함께 적는다. 이미 확정된 Phase 1·2 결정은 `knowledge-palette-architecture.md`의 "Phase 1/2 결정 사항"에 있다.

## 작업 방식

- **코드 작성은 Codex(`codex exec`, 모델 `gpt-6.1-sol`, 추론 강도 medium)에 위임한다.** Claude는 계획, 작업 조율, 코드 검토, 검증, Git 작업, 문서 기록을 맡는다. 이유: 사용자가 이렇게 역할을 나누라고 지시했다.
- **세션은 구현 단계마다 새로 열고, 같은 단계의 검토 수정만 `codex exec resume`으로 이어간다.** 이유: 같은 기능의 맥락은 유지하되, 다른 단계의 맥락이 섞여 범위를 넘는 구현이 생기지 않게 하기 위해서다.
- **Knowledge Delta의 결정 값은 `NONE`으로 쓴다.** 사용자가 MVP 범위 문서에서 `NOOP`을 `NONE`으로 바꿨고, 후보 유형에서 "프로젝트 판단/결정"을 뺐다. 이 수정을 확정 규칙으로 보고 다른 문서의 표기도 맞췄다.

## 디자인

- **"Tally 디자인"은 Hallmark 공개 예제 https://www.usehallmark.com/examples/tally/ 의 디자인 언어로 해석했다.** Hallmark 카탈로그에는 Tally라는 테마가 없고, 이 예제는 `theme: Pastel · genre: modern-minimal · nav: N5 Floating pill`로 표기되어 있다. 다음 요소를 앱 UI 토큰으로 옮긴다.
  - 차가운 파스텔 종이색(paper)과 짙은 남색 잉크(ink)
  - 인디고 액센트와 아껴 쓰는 라임 보조색
  - Geist / Geist Mono 폰트
  - 6·12·20·28px과 pill 반경
  - 4pt 간격
  - hairline 경계선
- **Instrument Serif 이탤릭 강조는 가져오지 않는다.** 원본 예제는 제목에 이탤릭 세리프 강조를 쓰지만, Hallmark 규칙은 제목 이탤릭을 금지한다. 또 이 앱은 랜딩 페이지가 아니라 작업 도구라 장식보다 읽기가 우선이다.
- **랜딩 페이지 구성 요소(마키 히어로, 가격표, 통계 줄)는 가져오지 않는다.** 지식 팔레트는 Main Canvas를 크게 쓰는 작업 화면이 원칙이다. 그래서 토큰, 플로팅 pill 내비게이션, mono eyebrow 라벨, 카드와 버튼 문법만 쓴다.

## LLM Provider

- **OpenAI 호환 Chat Completions API 하나만 지원한다.** 다음 환경 변수로 설정한다.
  - `KP_LLM_BASE_URL`, `KP_LLM_API_KEY`
  - `KP_CHAT_MODEL`
  - `KP_KNOWLEDGE_MODEL`: 비우면 Chat 모델을 함께 쓴다.

  이유: BYOK와 OpenAI 호환 API를 우선한다는 아키텍처 문서의 방향을 따랐다. 이 방식이면 Ollama, OpenAI, OpenRouter 같은 Provider를 코드 변경 없이 쓸 수 있다. 역할(Chat/Knowledge/Embedding)은 설정에서 나눈다.
- **실제 연결 검증은 로컬 Ollama의 `qwen2.5:7b-instruct`로 한다.** 사용자가 로컬 Ollama를 선택했다. 이 모델은 수 GB 크기로 받을 수 있는 모델 가운데 한국어 응답과 JSON 지시 수행이 비교적 안정적이다. 다만 한국어 답변에 중국어가 섞이는 경우가 관찰되어, 시스템 프롬프트에서 응답 언어를 명시한다.
- 자동 테스트는 외부 HTTP 경계만 대체(mock)한다. 실제 Provider 검증과 mock 검증은 작업 내역에 구분해 적는다.
