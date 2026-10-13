<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import MarkdownIt from "markdown-it";
import { api, ChatMessage, ChatStatus, Conversation, ContextItem, KnowledgeUpdate } from "./api";

const props = defineProps<{ busy: boolean; splitOn: boolean }>();

const wideScreen = window.matchMedia("(min-width: 769px)").matches;

const emit = defineEmits<{
  (e: "open-note", path: string): void;
  (e: "split-change", on: boolean): void;
  (e: "knowledge-changed", paths: string[]): void;
}>();

const status = ref<ChatStatus | null>(null);
const conversations = ref<Conversation[]>([]);
const currentId = ref<number | null>(null);
const messages = ref<ChatMessage[]>([]);
const draft = ref("");
const includeSources = ref(false);
const loading = ref(false);
const streaming = ref(false);
const streamText = ref("");
const streamContexts = ref<ContextItem[]>([]);
const streamNotesState = ref("");
const streamSourceState = ref("");
const streamError = ref("");
const listError = ref("");
const sourceModal = ref<ContextItem | null>(null);
const sourceDialog = ref<HTMLDialogElement | null>(null);
watch(sourceModal, async (item) => {
  if (!item) return;
  await nextTick();
  sourceDialog.value?.showModal();
});
let controller: AbortController | null = null;
let activeSend: Promise<void> | null = null;
// 취소 직후 서버의 저장이 끝나기 전에도 해당 대화의 부분 응답을 다시 보여준다.
const pendingMessages = new Map<number, ChatMessage[]>();

const updates = ref<KnowledgeUpdate[]>([]);
const knowledgeError = ref("");
const knowledgeNotice = ref("");
const knowledgeRequesting = ref(false);
const knowledgeRunning = computed(() => knowledgeRequesting.value || updates.value.some(u => u.status === "running"));
const knowledgeCounts = computed(() => {
  const counts = { CREATE: 0, UPDATE: 0, LINK: 0 };
  for (const update of updates.value.filter(u => u.status === "applied")) {
    for (const op of ["CREATE", "UPDATE", "LINK"] as const) counts[op] += update.counts[op] ?? 0;
  }
  return counts;
});
const changedNotes = computed(() => [...new Set(updates.value.filter(u => u.status === "applied").flatMap(u => u.changes.map(c => c.path)))]);
const latestFailure = computed(() => updates.value[0]?.status === "failed" ? updates.value[0].error : "");
const seenUpdates = new Set<number>();
const watchedConversations = new Set<number>();
let knowledgeTimer: ReturnType<typeof setTimeout> | null = null;
let disposed = false;

async function refreshKnowledge(id: number, notify = true) {
  try {
    const result = await api.knowledgeUpdates(id);
    if (disposed) return false;
    if (currentId.value === id) {
      updates.value = result.updates;
      knowledgeError.value = "";
    }
    for (const update of result.updates) {
      if (update.status === "applied" && !seenUpdates.has(update.id)) {
        seenUpdates.add(update.id);
        if (notify) emit("knowledge-changed", update.changes.map(c => c.path.replace(/^notes\//, "")));
      }
    }
    return result.updates.some(u => u.status === "running");
  } catch (e: any) {
    if (currentId.value === id) knowledgeError.value = e.message;
    return false;
  }
}

function pollKnowledge(id: number) {
  watchedConversations.add(id);
  if (knowledgeTimer) return;
  let polls = 0;
  const tick = async () => {
    if (disposed) return;
    for (const convId of [...watchedConversations]) {
      const running = await refreshKnowledge(convId);
      if (!running && polls > 1) watchedConversations.delete(convId);
    }
    polls++;
    // 늦은 로컬 모델도 기다리되 무한 폴링은 하지 않는다. 수동 버튼으로 다시 조회할 수 있다.
    if (watchedConversations.size && polls < 130) knowledgeTimer = setTimeout(tick, 2000);
    else { knowledgeTimer = null; watchedConversations.clear(); }
  };
  knowledgeTimer = setTimeout(tick, 500);
}

async function requestKnowledge(id: number | null = currentId.value) {
  if (!id) return;
  knowledgeRequesting.value = true;
  try {
    const result = await api.knowledgeUpdate(id);
    if (currentId.value === id) {
      knowledgeNotice.value = result.status === "idle" ? "정리할 완료 턴이 없습니다." :
        result.skipped ? "이미 정리 중입니다. 새 요청은 건너뛰었습니다." : "";
    }
    pollKnowledge(id);
    await refreshKnowledge(id);
  } catch (e: any) {
    if (currentId.value === id) knowledgeError.value = e.message;
  } finally {
    knowledgeRequesting.value = false;
  }
}

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
  if (loading.value || props.busy || currentId.value === id) return;
  loading.value = true;
  await cancelActiveStream();
  await requestKnowledge(currentId.value);
  try {
    const c = await api.getConversation(id);
    currentId.value = id;
    updates.value = [];
    knowledgeNotice.value = "";
    await refreshKnowledge(id, false);
    pollKnowledge(id);
    const pending = pendingMessages.get(id);
    if (pending && c.messages[c.messages.length - 1]?.role !== "assistant") {
      messages.value = pending;
    } else {
      messages.value = c.messages;
      pendingMessages.delete(id);
    }
    streamNotesState.value = "";
    streamSourceState.value = "";
    streamError.value = "";
  } catch (e: any) {
    listError.value = e.message;
  } finally {
    loading.value = false;
  }
}

async function newConversation() {
  if (loading.value || props.busy) return;
  loading.value = true;
  await cancelActiveStream();
  await requestKnowledge(currentId.value);
  try {
    const c = await api.createConversation("");
    currentId.value = c.id;
    updates.value = [];
    knowledgeNotice.value = "";
    knowledgeError.value = "";
    messages.value = [];
    streamNotesState.value = "";
    streamSourceState.value = "";
    streamError.value = "";
    await loadConversations();
  } catch (e: any) {
    listError.value = e.message;
  } finally {
    loading.value = false;
  }
}

function setSplit(v: boolean) {
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
  else if (event === "context") {
    streamContexts.value = payload.contexts ?? [];
    streamNotesState.value = payload.notes_state ?? "";
    streamSourceState.value = payload.source_state ?? "";
  } else if (event === "error") streamError.value = payload.detail ?? "오류가 발생했습니다.";

}

async function send() {
  if (activeSend || loading.value || props.busy || !status.value?.configured) return;
  activeSend = sendMessage();
  try { await activeSend; } finally { activeSend = null; }
}

async function sendMessage() {
  const text = draft.value.trim();
  if (!text || streaming.value) return;
  streaming.value = true;
  const requestController = new AbortController();
  controller = requestController;
  if (!currentId.value) {
    try {
      const c = await api.createConversation("");
      currentId.value = c.id;
      await loadConversations();
    } catch (e: any) {
      streamError.value = e.message;
      streaming.value = false;
      controller = null;
      return;
    }
  }
  if (requestController.signal.aborted) {
    streaming.value = false;
    controller = null;
    return;
  }
  const convId = currentId.value;
  messages.value = [...messages.value, { id: -1, role: "user", content: text, status: "complete", citations: null, context: null, created_at: "" }];
  draft.value = "";
  streaming.value = true;
  streamText.value = "";
  streamContexts.value = [];
  streamError.value = "";
  streamNotesState.value = "preparing";
  streamSourceState.value = "preparing";
  let terminalStatus = "interrupted";
  try {
    const res = await fetch(`/api/conversations/${convId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: text, include_sources: includeSources.value }),
      signal: requestController.signal,
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
        if (block.startsWith("event: done")) terminalStatus = "complete";
        if (block.startsWith("event: error")) terminalStatus = JSON.parse(block.split("data:")[1]).status ?? "error";
      }
    }
    buf += decoder.decode();
    if (buf.trim()) handleSseEvent(buf);
  } catch (e: any) {
    if (e?.name !== "AbortError") streamError.value = e?.message ?? "요청 실패";
  } finally {
    const partialMessage: ChatMessage = {
      id: -2, role: "assistant", content: streamText.value,
      status: requestController.signal.aborted ? "interrupted" : terminalStatus,
      citations: streamContexts.value.filter((c) => streamText.value.includes(`[${c.label}]`)),
      context: streamContexts.value, created_at: "",
    };
    // 중단 직후 DB 보존이 아직 끝나지 않은 경우에도 화면의 부분 응답을 유지한다.
    try {
      const c = await api.getConversation(convId);
      const last = c.messages[c.messages.length - 1];
      messages.value = last?.role === "assistant" ? c.messages : [...c.messages, partialMessage];
      if (last?.role !== "assistant") pendingMessages.set(convId, messages.value);
      else pendingMessages.delete(convId);
    } catch {
      messages.value = [...messages.value, partialMessage];
      pendingMessages.set(convId, messages.value);
    }
    streaming.value = false;
    controller = null;
    streamText.value = "";
    await loadConversations();
    pollKnowledge(convId);
  }
}

function stop() {
  controller?.abort();
}

async function cancelActiveStream() {
  controller?.abort();
  await activeSend;
}

function contextLabels(m: ChatMessage): ContextItem[] {
  return m.context ?? [];
}

function citedSet(m: ChatMessage): Set<string> {
  const s = new Set<string>();
  for (const c of m.citations ?? []) s.add(c.label);
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

function onSourceDialogClick(event: MouseEvent) {
  const dialog = sourceDialog.value;
  if (!dialog || event.target !== dialog) return;
  const bounds = dialog.getBoundingClientRect();
  if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) {
    sourceModal.value = null;
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
  try { status.value = await api.chatStatus(); }
  catch { listError.value = "Provider 설정 상태를 불러오지 못했습니다."; }
  await loadConversations();
});

onBeforeUnmount(() => {
  disposed = true;
  if (knowledgeTimer) clearTimeout(knowledgeTimer);
  if (controller) controller.abort();
});

defineExpose({ cancelActiveStream });
</script>

<template>
  <div class="chat-view card">
    <details v-if="status?.configured" class="convs" :open="wideScreen">
      <summary>대화 목록</summary>
      <button :disabled="loading || busy" @click="newConversation">+ 새 대화</button>
      <ul>
        <li v-for="c in conversations" :key="c.id">
          <button class="list-button" :class="{ active: c.id === currentId }" :aria-pressed="c.id === currentId" :disabled="loading || busy" :title="c.title || '새 대화'" @click="selectConversation(c.id)">{{ c.title || "새 대화" }}</button>
        </li>
      </ul>
      <p v-if="listError" class="error">{{ listError }}</p>
    </details>

    <section class="main">
      <div v-if="status?.configured" class="bar toolbar">
        <h2>Chat</h2>
        <label class="toggle"><input type="checkbox" v-model="includeSources" /> Sources 근거 포함</label>
        <label class="toggle"><input type="checkbox" :disabled="busy" :checked="splitOn" @change="setSplit(($event.target as HTMLInputElement).checked)" /> 노트 함께 보기</label>
      </div>

      <div v-if="status && !status.configured" class="not-configured banner banner--warning">
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

      <p v-if="!status && listError" class="error">{{ listError }}</p>
      <div v-if="status?.configured" class="messages">
        <p v-if="!messages.length && !streaming" class="empty-state">질문을 입력해 대화를 시작하세요.</p>
        <p v-if="streamNotesState" class="state">Notes: {{ streamNotesState }} · Sources: {{ streamSourceState }}</p>
        <div v-for="m in messages" :key="m.id" class="msg" :class="m.role">
          <div class="turn-document">
            <div class="turn-heading"><span class="eyebrow">{{ m.role === 'user' ? '나' : 'Assistant' }}</span><span class="status-chip" :data-state="m.status">{{ m.status === 'complete' ? '완료' : m.status === 'interrupted' ? '중단됨' : '오류' }}</span></div>
            <div v-if="m.role === 'assistant'" class="content prose" v-html="renderMessage(m)" @click="onMessageClick($event, m)"></div>
            <div v-else class="content prose">{{ m.content }}</div>
            <p v-if="m.status === 'interrupted'" class="warn">응답이 중단되었습니다 (부분 내용 보존).</p>
            <p v-if="m.status === 'error'" class="error">응답 생성에 실패했습니다. 잠시 후 다시 시도하세요.</p>
          </div>
          <details v-if="m.role === 'assistant' && (m.context ?? []).length" class="refs">
            <summary>참고 자료 {{ (m.context ?? []).length }}건</summary>
            <ul>
              <li v-for="c in contextLabels(m)" :key="c.label">
                <span class="label badge">[{{ c.label }}]</span>
                {{ c.kind === "note" ? "Note" : "Source" }} · {{ c.path }}<span v-if="c.pages"> · p.{{ c.pages }}</span>
                <span v-if="citedSet(m).has(c.label)" class="used">(인용됨)</span> · {{ c.status }}
              </li>
            </ul>
          </details>
        </div>

        <div v-if="streaming || streamText" class="msg assistant">
          <div class="turn-document">
            <div class="turn-heading"><span class="eyebrow">Assistant</span><span class="status-chip" data-state="loading" role="status">응답 생성 중…</span></div>
            <div class="content prose" v-html="renderMessage({ content: streamText, context: streamContexts } as ChatMessage)" @click="onStreamClick"></div>
          </div>
          <details v-if="streamContexts.length" class="refs" open>
            <summary>참고 자료 {{ streamContexts.length }}건</summary>
            <ul>
              <li v-for="c in streamContexts" :key="c.label">
                <span class="label badge">[{{ c.label }}]</span> {{ c.kind === "note" ? "Note" : "Source" }} · {{ c.path }}<span v-if="c.pages"> · p.{{ c.pages }}</span> · {{ c.status }}
              </li>
            </ul>
            <p class="state">
              Notes 인덱스: {{ streamNotesState }}<span v-if="includeSources"> · Sources 인덱스: {{ streamSourceState }}</span>
            </p>
          </details>
        </div>
        <p v-if="streamError" class="error" role="alert">{{ streamError }}</p>
      </div>

      <section class="knowledge-summary" aria-label="대화의 지식 정리" aria-live="polite">
        <div class="toolbar">
          <span>이번 대화에서 + 새 Note {{ knowledgeCounts.CREATE }} · ~ 보강 {{ knowledgeCounts.UPDATE }} · ↔ 링크 {{ knowledgeCounts.LINK }}</span>
          <span v-if="knowledgeRunning" class="status-chip" data-state="loading">정리 중…</span>
          <button :disabled="!currentId || streaming || loading || busy || knowledgeRequesting" @click="requestKnowledge()">지금 정리</button>
        </div>
        <p v-if="knowledgeError || latestFailure" class="error">{{ knowledgeError || latestFailure }}</p>
        <p v-if="knowledgeNotice" class="muted">{{ knowledgeNotice }}</p>
        <div class="toolbar">
          <button v-for="path in changedNotes" :key="path" class="link-button" :disabled="busy" @click="emit('open-note', path.replace(/^notes\//, ''))">{{ path.replace(/^notes\//, '') }}</button>
        </div>
      </section>

      <div v-if="status?.configured" class="composer">
        <textarea aria-label="Chat 질문" :aria-invalid="!!streamError" v-model="draft" placeholder="질문을 입력하세요" :disabled="streaming || loading || busy" @keydown.enter.meta.prevent="send" @keydown.enter.ctrl.prevent="send" />
        <button v-if="streaming" @click="stop">중지</button>
        <button v-else class="btn--primary" :disabled="loading || busy || !draft.trim()" @click="send">보내기</button>
      </div>
    </section>

    <dialog v-if="sourceModal" ref="sourceDialog" class="modal card" aria-label="Source 근거" @click="onSourceDialogClick" @cancel="sourceModal = null" @close="sourceModal = null">
      <h3>Source 근거</h3>
      <p><b>{{ sourceModal.path }}</b><span v-if="sourceModal.pages"> · p.{{ sourceModal.pages }}</span> · {{ sourceModal.status }}</p>
      <pre>{{ sourceModal.snippet }}</pre>
      <p class="hint">전체 내용은 Sources 탭의 원본 문서에서 확인할 수 있습니다.</p>
      <button @click="sourceModal = null">닫기</button>
    </dialog>
  </div>
</template>

<style scoped>
.chat-view { display: flex; flex: 1; min-width: 0; min-height: 0; overflow: clip; }
.convs { width: 212px; flex-shrink: 0; border-right: var(--rule-hair); padding: var(--space-md); overflow: auto; }
.convs:not([open]) { width: 112px; }
.convs summary { font-weight: 600; margin-bottom: var(--space-sm); }
.convs ul { list-style: none; padding: 0; margin: var(--space-sm) 0; }
.convs .list-button { font-size: var(--text-xs); }
.main { flex: 1; display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.bar { padding: var(--space-md) var(--space-lg); border-bottom: var(--rule-hair); }
.bar h2 { margin: 0 auto 0 0; font-size: var(--text-lg); }
.toggle { display: inline-flex; align-items: center; gap: var(--space-xs); font-size: var(--text-xs); cursor: pointer; white-space: nowrap; }
.toggle:has(:disabled) { opacity: 0.55; cursor: not-allowed; }
.provider { padding: var(--space-xs) var(--space-lg); color: var(--color-ink-2); font-size: var(--text-xs); overflow-wrap: anywhere; }
.not-configured { margin: var(--space-lg); overflow: auto; }
.messages { flex: 1; min-height: 0; overflow: auto; padding: var(--space-lg) max(var(--space-lg), calc((100% - 840px) / 2)); }
.msg { padding: var(--space-lg) 0; border-bottom: var(--rule-hair); }
.msg:first-of-type { padding-top: var(--space-sm); }
.turn-heading { display: flex; align-items: center; gap: var(--space-sm); margin-bottom: var(--space-sm); }
.turn-document { max-width: 100%; }
.msg.user .content { font-size: var(--text-md); font-weight: 500; white-space: pre-wrap; }
.content { color: var(--color-ink-1); }
.refs { font-size: var(--text-xs); color: var(--color-ink-2); margin-top: var(--space-md); }
.refs ul { padding-left: var(--space-md); }
.refs li { overflow-wrap: anywhere; margin-bottom: var(--space-xs); }
.refs .label { color: var(--color-accent); font-family: var(--font-mono); }
.refs .used { color: var(--color-success-ink); }
.knowledge-summary { padding: var(--space-sm) var(--space-lg); border-top: var(--rule-hair); font-size: var(--text-xs); max-height: 180px; overflow: auto; }
.composer { display: flex; align-items: flex-end; gap: var(--space-sm); padding: var(--space-md) var(--space-lg); border-top: var(--rule-hair); background: var(--color-paper-0); }
.composer textarea { flex: 1; min-height: 80px; max-height: 240px; resize: vertical; }
.error { margin: var(--space-sm); }
.warn { margin: var(--space-sm) 0 0; font-size: var(--text-xs); }
.state { color: var(--color-ink-2); font-size: var(--text-xs); }
.modal::backdrop { background: var(--color-overlay); }
.modal { width: min(calc(100% - var(--space-xl)), 640px); padding: var(--space-lg); color: var(--color-ink-0); max-height: 85dvh; overflow: auto; }
.modal pre { white-space: pre-wrap; overflow-wrap: anywhere; }
@media (max-width: 768px) {
  .chat-view { flex-direction: column; }
  .convs, .convs:not([open]) { width: 100%; max-height: 200px; border-right: 0; border-bottom: var(--rule-hair); padding: var(--space-xs) var(--space-md); }
  .convs summary { margin: 0; }
  .bar { padding: var(--space-sm) var(--space-md); }
  .messages { padding: var(--space-md); }
  .provider { padding-inline: var(--space-md); }
  .composer { padding: var(--space-sm); gap: var(--space-xs); }
  .composer textarea { padding: var(--space-sm); }
}
</style>
