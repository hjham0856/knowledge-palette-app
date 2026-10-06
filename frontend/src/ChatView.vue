<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import MarkdownIt from "markdown-it";
import { api, ChatMessage, ChatStatus, Conversation, ContextItem } from "./api";

const emit = defineEmits<{
  (e: "open-note", path: string): void;
  (e: "split-change", on: boolean): void;
}>();

const status = ref<ChatStatus | null>(null);
const conversations = ref<Conversation[]>([]);
const currentId = ref<number | null>(null);
const messages = ref<ChatMessage[]>([]);
const draft = ref("");
const includeSources = ref(false);
const splitOn = ref(false);
const streaming = ref(false);
const streamText = ref("");
const streamContexts = ref<ContextItem[]>([]);
const streamNotesState = ref("");
const streamSourceState = ref("");
const streamError = ref("");
const listError = ref("");
const sourceModal = ref<ContextItem | null>(null);
let controller: AbortController | null = null;

// 인용 라벨([N1] 등)을 링크로 바꾸는 마크다운 확장. 컨텍스트에 실제 존재하는 라벨만 클릭 가능하게 한다.
function makeMd(contextLabels: Set<string>) {
  const md = new MarkdownIt({ html: false, linkify: true });
  md.inline.ruler.before("link", "cite", (state, silent) => {
    const m = /^\[([NS]\d+)\]/.exec(state.src.slice(state.pos));
    if (!m) return false;
    const label = m[1];
    if (!contextLabels.has(label)) return false; // 모르는 라벨은 링크가 아니라 본문 그대로
    if (!silent) {
      const token = state.push("cite", "", 0);
      token.content = label;
    }
    state.pos += m[0].length;
    return true;
  });
  md.renderer.rules.cite = (tokens, idx) =>
    `<a href="#" class="cite" data-label="${tokens[idx].content}">[${tokens[idx].content}]</a>`;
  return md;
}

function renderMessage(m: ChatMessage): string {
  const labels = new Set<string>();
  for (const c of m.context ?? []) labels.add(c.label);
  return makeMd(labels).render(m.content);
}

async function loadConversations() {
  try {
    const r = await api.listConversations();
    conversations.value = r.conversations;
    listError.value = "";
  } catch (e: any) {
    listError.value = `대화 목록을 불러오지 못했습니다: ${e.message}`;
  }
}

async function selectConversation(id: number) {
  if (streaming.value || currentId.value === id) return;
  currentId.value = id;
  try {
    const c = await api.getConversation(id);
    if (currentId.value === id) messages.value = c.messages;
  } catch (e: any) {
    listError.value = e.message;
  }
}

async function newConversation() {
  if (streaming.value) return;
  try {
    const c = await api.createConversation("");
    currentId.value = c.id;
    messages.value = [];
    await loadConversations();
  } catch (e: any) {
    listError.value = e.message;
  }
}

function setSplit(v: boolean) {
  splitOn.value = v;
  emit("split-change", v);
}

function handleSseEvent(block: string) {
  let event = "message";
  let data = "";
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!data) return;
  let payload: any;
  try {
    payload = JSON.parse(data);
  } catch {
    streamError.value = "서버 응답 형식이 올바르지 않습니다.";
    return;
  }
  if (event === "delta") streamText.value += payload.text ?? "";
  else if (event === "citations") {
    streamContexts.value = payload.contexts ?? [];
    streamNotesState.value = payload.notes_state ?? "";
    streamSourceState.value = payload.source_state ?? "";
  } else if (event === "error") streamError.value = payload.detail ?? "오류가 발생했습니다.";
  else if (event === "done") {
    /* 완료 시점의 본문은 DB에 저장된 버전을 다시 읽는다 */
  }
}

async function send() {
  const text = draft.value.trim();
  if (!text || streaming.value) return;
  if (!currentId.value) {
    try {
      const c = await api.createConversation("");
      currentId.value = c.id;
      await loadConversations();
    } catch (e: any) {
      streamError.value = e.message;
      return;
    }
  }
  const convId = currentId.value;
  messages.value = [...messages.value, { id: -1, role: "user", content: text, status: "completed", citations: null, context: null, created_at: "" }];
  draft.value = "";
  streaming.value = true;
  streamText.value = "";
  streamContexts.value = [];
  streamError.value = "";
  controller = new AbortController();
  try {
    const res = await fetch(`/api/conversations/${convId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: text, include_sources: includeSources.value }),
      signal: controller.signal,
    });
    if (!res.ok || !res.body) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail ?? `${res.status}`);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      // UTF-8 멀티바이트가 청크 경계에 걸려도 깨지지 않게 스트리밍 디코더를 쓴다.
      buf += decoder.decode(value, { stream: true });
      let idx: number;
      while ((idx = buf.search(/\r?\n\r?\n/)) >= 0) {
        const block = buf.slice(0, idx);
        const sepLen = /^(?:\r\n\r\n|\n\n|\r\r)/.exec(buf.slice(idx))?.[0].length ?? 2;
        buf = buf.slice(idx + sepLen);
        handleSseEvent(block);
      }
    }
    buf += decoder.decode();
    if (buf.trim()) handleSseEvent(buf);
  } catch (e: any) {
    if (e?.name !== "AbortError") streamError.value = e?.message ?? "요청 실패";
  } finally {
    streaming.value = false;
    controller = null;
    // 저장된 최종 상태(완료/중단/실패 포함)를 다시 읽어 화면과 DB를 일치시킨다.
    if (currentId.value === convId) {
      try {
        const c = await api.getConversation(convId);
        messages.value = c.messages;
      } catch {
        /* 목록 갱신 실패는 다음 선택에서 복구된다 */
      }
    }
    streamText.value = "";
    await loadConversations();
  }
}

function stop() {
  controller?.abort();
}

function cancelActiveStream() {
  // 워크스페이스/모드 전환으로 화면이 잠기기 전에 응답 생성을 중단한다.
  if (controller) controller.abort();
}

function contextLabels(m: ChatMessage): ContextItem[] {
  return m.context ?? [];
}

function citedSet(m: ChatMessage): Set<string> {
  const s = new Set<string>();
  for (const c of m.citations ?? []) s.add(String(c).replace(/[\[\]]/g, ""));
  return s;
}

function onMessageClick(e: MouseEvent, m: ChatMessage) {
  const el = (e.target as HTMLElement).closest("a.cite") as HTMLElement | null;
  if (!el) return;
  e.preventDefault();
  const label = el.dataset.label || "";
  const item = (m.context ?? []).find((c) => c.label === label);
  if (!item) return; // 모르는 라벨은 링크로 렌더링되지 않으므로 도달하지 않는다.
  if (item.kind === "note") {
    emit("open-note", item.path.replace(/^notes\//, ""));
  } else {
    sourceModal.value = item;
  }
}

function onStreamClick(e: MouseEvent) {
  const el = (e.target as HTMLElement).closest("a.cite") as HTMLElement | null;
  if (!el) return;
  e.preventDefault();
  const label = el.dataset.label || "";
  const item = streamContexts.value.find((c) => c.label === label);
  if (!item) return;
  if (item.kind === "note") emit("open-note", item.path.replace(/^notes\//, ""));
  else sourceModal.value = item;
}

onMounted(async () => {
  status.value = await api.chatStatus();
  await loadConversations();
});

onBeforeUnmount(() => {
  if (controller) controller.abort();
});

defineExpose({ cancelActiveStream });
</script>

<template>
  <div class="chat-view">
    <nav class="convs">
      <button :disabled="streaming" @click="newConversation">+ 새 대화</button>
      <ul>
        <li v-for="c in conversations" :key="c.id" :class="{ active: c.id === currentId }" @click="selectConversation(c.id)">
          {{ c.title || "새 대화" }}
        </li>
      </ul>
      <p v-if="listError" class="error">{{ listError }}</p>
    </nav>

    <section class="main">
      <div class="bar">
        <b>Chat</b>
        <label class="toggle"><input type="checkbox" v-model="includeSources" /> Sources 근거 포함</label>
        <label class="toggle"><input type="checkbox" :checked="splitOn" @change="setSplit(($event.target as HTMLInputElement).checked)" /> 노트 함께 보기</label>
      </div>

      <div v-if="status && !status.configured" class="not-configured">
        <h3>LLM provider가 설정되지 않았습니다</h3>
        <p>실제 LLM 응답을 받으려면 저장소 루트의 <code>.env</code>에 아래를 지정하세요.</p>
        <pre>KP_LLM_BASE_URL=https://api.openai.com/v1   # 또는 로컬 호환 API 주소
KP_LLM_API_KEY=...                              # 로컬 API는 비워둘 수 있음
KP_CHAT_MODEL=사용-모델-이름</pre>
        <p>그 뒤 <code>uv run --env-file ../.env uvicorn app.main:app --host 127.0.0.1 --port 8000</code>로 다시 시작하세요.</p>
      </div>
      <div v-else-if="status" class="provider">
        모델: <b>{{ status.model }}</b> · 호스트: {{ status.base_host }}
      </div>

      <div class="messages">
        <div v-for="m in messages" :key="m.id" class="msg" :class="m.role">
          <div class="bubble">
            <div v-if="m.role === 'assistant'" class="content" v-html="renderMessage(m)" @click="onMessageClick($event, m)"></div>
            <div v-else class="content">{{ m.content }}</div>
            <p v-if="m.status === 'interrupted'" class="warn">응답이 중단되었습니다 (부분 내용 보존).</p>
            <p v-if="m.status === 'failed'" class="warn">응답 생성에 실패했습니다. 잠시 후 다시 시도하세요.</p>
          </div>
          <details v-if="m.role === 'assistant' && (m.context ?? []).length" class="refs">
            <summary>참고 자료 {{ (m.context ?? []).length }}건</summary>
            <ul>
              <li v-for="c in contextLabels(m)" :key="c.label">
                <span class="label">[{{ c.label }}]</span>
                {{ c.kind === "note" ? "Note" : "Source" }} · {{ c.path }}<span v-if="c.pages"> · p.{{ c.pages }}</span>
                <span v-if="citedSet(m).has(c.label)" class="used">(인용됨)</span> · {{ c.status }}
              </li>
            </ul>
          </details>
        </div>

        <div v-if="streaming || streamText" class="msg assistant">
          <div class="bubble">
            <div class="content" v-html="renderMessage({ content: streamText, context: streamContexts, citations: streamContexts.map((c) => '[' + c.label + ']') } as any)" @click="onStreamClick"></div>
            <p v-if="streaming" class="hint">응답 생성 중…</p>
          </div>
          <details v-if="streamContexts.length" class="refs" open>
            <summary>참고 자료 {{ streamContexts.length }}건</summary>
            <ul>
              <li v-for="c in streamContexts" :key="c.label">
                <span class="label">[{{ c.label }}]</span> {{ c.kind === "note" ? "Note" : "Source" }} · {{ c.path }}<span v-if="c.pages"> · p.{{ c.pages }}</span> · {{ c.status }}
              </li>
            </ul>
            <p class="state">
              Notes 인덱스: {{ streamNotesState }}<span v-if="includeSources"> · Sources 인덱스: {{ streamSourceState }}</span>
            </p>
          </details>
        </div>
        <p v-if="streamError" class="error">{{ streamError }}</p>
      </div>

      <div class="composer">
        <textarea v-model="draft" placeholder="질문을 입력하세요" :disabled="streaming" @keydown.enter.meta.prevent="send" @keydown.enter.ctrl.prevent="send" />
        <button v-if="streaming" @click="stop">중지</button>
        <button v-else @click="send">보내기</button>
      </div>
    </section>

    <div v-if="sourceModal" class="modal-backdrop" @click.self="sourceModal = null">
      <div class="modal">
        <h3>Source 근거</h3>
        <p><b>{{ sourceModal.path }}</b><span v-if="sourceModal.pages"> · p.{{ sourceModal.pages }}</span> · {{ sourceModal.status }}</p>
        <pre>{{ sourceModal.snippet }}</pre>
        <p class="hint">전체 내용은 Sources 탭의 원본 문서에서 확인할 수 있습니다.</p>
        <button @click="sourceModal = null">닫기</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-view { display: flex; flex: 1; min-height: 0; }
.convs { width: 200px; border-right: 1px solid #ddd; padding: 8px; overflow: auto; }
.convs ul { list-style: none; padding: 0; margin: 8px 0; }
.convs li { padding: 4px 6px; cursor: pointer; border-radius: 4px; }
.convs li.active { background: #e0e7ff; }
.main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.bar { display: flex; gap: 12px; align-items: center; padding: 6px 12px; background: #f3f3f3; }
.toggle { font-size: 13px; }
.provider { padding: 4px 12px; color: #555; font-size: 13px; }
.not-configured { margin: 16px; padding: 12px; border: 1px solid #f0c; border-radius: 6px; background: #fff7ed; }
.not-configured pre { background: #f3f3f3; padding: 8px; overflow: auto; }
.messages { flex: 1; overflow: auto; padding: 12px; }
.msg { margin-bottom: 12px; }
.msg.user .bubble { background: #e5edff; }
.msg.assistant .bubble { background: #f6f6f6; }
.bubble { padding: 8px 12px; border-radius: 8px; max-width: 80%; }
.content :deep(.cite) { color: #2563eb; cursor: pointer; text-decoration: underline; }
.refs { font-size: 12px; color: #555; margin-top: 4px; }
.refs .label { color: #2563eb; font-weight: bold; }
.refs .used { color: #047857; }
.composer { display: flex; gap: 8px; padding: 8px; border-top: 1px solid #ddd; }
.composer textarea { flex: 1; min-height: 48px; }
.error { color: #b91c1c; padding: 4px 12px; }
.warn { color: #b45309; margin: 4px 0 0; font-size: 12px; }
.hint { color: #888; font-size: 12px; }
.modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,.4); display: grid; place-items: center; }
.modal { background: white; padding: 16px; max-width: 640px; max-height: 80%; overflow: auto; border-radius: 8px; }
.modal pre { white-space: pre-wrap; background: #f6f6f6; padding: 8px; }
</style>
