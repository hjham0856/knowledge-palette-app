<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from "vue";
import { api, ApiError } from "./api";
import SearchView from "./SearchView.vue";
import SourcesView from "./SourcesView.vue";
import ChatView from "./ChatView.vue";
import NotesView from "./NotesView.vue";
import GraphView from "./GraphView.vue";
import BaseView from "./BaseView.vue";
import HistoryView from "./HistoryView.vue";

const modes = [
  { id: "chat", label: "Chat" },
  { id: "notes", label: "Notes" },
  { id: "search", label: "Search" },
  { id: "sources", label: "Sources" },
  { id: "history", label: "History" },
  { id: "graph", label: "Graph" },
  { id: "base", label: "Base" },
] as const;
const mode = ref<(typeof modes)[number]["id"]>("chat");
const splitChat = ref(false); // Chat에서 노트를 명시적으로 함께 볼 때만 켠다.
const workspacePath = ref(""); // 입력창 초안
const activeWorkspace = ref(""); // 실제로 열린 워크스페이스 (표시/키잉 기준)
const workspaceOpen = ref(false);
const status = ref("");
const busy = ref(false);
const noteBusy = ref(false);
const locked = computed(() => busy.value || noteBusy.value);
const openNoteRequest = ref<{ path: string; nonce: number } | null>(null);

const notesView = ref<InstanceType<typeof NotesView> | null>(null);
const chatView = ref<InstanceType<typeof ChatView> | null>(null);
const historyView = ref<InstanceType<typeof HistoryView> | null>(null);
const historyRequest = ref<{ id: number; nonce: number } | null>(null);
const undoMessage = ref("");
const undoFailed = ref(false);
const undoConflicts = ref<{ path: string; reason: "modified" | "missing" }[]>([]);

async function openHistory(id: number) {
  await setMode("history");
  if (mode.value === "history" && !locked.value) historyRequest.value = { id, nonce: Date.now() };
}

async function undoUpdate(id: number) {
  if (locked.value || !window.confirm(`Knowledge Update #${id} 전체를 되돌릴까요? 새 Note는 삭제되고 보강·링크는 이전 내용으로 복원됩니다.`)) return;
  busy.value = true;
  undoMessage.value = "";
  undoConflicts.value = [];
  undoFailed.value = false;
  try {
    await notesView.value?.pauseForUndo();
    const result = await api.undoUpdate(id);
    undoMessage.value = `Knowledge Update #${id}를 되돌렸습니다.`;
    if (result.reindex_error) undoMessage.value += ` 검색 재색인 실패: ${result.reindex_error}`;
    const restored = result.restored.map(path => path.replace(/^notes\//, ""));
    const deleted = result.deleted.map(path => path.replace(/^notes\//, ""));
    if (await notesView.value?.knowledgeChanged([...restored, ...deleted], deleted, true) === false) {
      undoMessage.value += " Note 화면 갱신 실패 — Notes에서 오류를 확인하세요.";
    }
    await Promise.all([historyView.value?.refresh(), chatView.value?.historyChanged()]);
  } catch (e: any) {
    undoFailed.value = true;
    if (e instanceof ApiError && e.status === 409 && typeof e.detail !== "string") {
      undoMessage.value = "이후 편집된 Note가 있어 되돌릴 수 없음";
      undoConflicts.value = e.detail.conflicts;
    } else undoMessage.value = `Undo 실패: ${e.message}`;
  } finally {
    notesView.value?.resumeAfterUndo();
    busy.value = false;
  }
}

async function openPath(path: string) {
  if (locked.value) return;
  busy.value = true; // flush와 로드 전체 동안 잠근다.
  try {
    const flushed = await notesView.value?.flushSave().catch(() => false) ?? true;
    if (!flushed) {
      status.value = "저장 실패로 워크스페이스를 전환하지 않았습니다. 재시도해 주세요.";
      return;
    }
    await chatView.value?.cancelActiveStream();
    try {
      const opened = await api.openWorkspace(path);
      activeWorkspace.value = opened.path;
      workspacePath.value = opened.path;
      workspaceOpen.value = true;
      openNoteRequest.value = null;
      historyRequest.value = null;
      undoMessage.value = "";
      undoConflicts.value = [];
      status.value = "";
    } catch (e: any) {
      status.value = `열기 실패: ${e.message}`;
    }
  } finally {
    busy.value = false;
  }
}

async function createPath(path: string) {
  if (locked.value) return;
  busy.value = true;
  try {
    const flushed = await notesView.value?.flushSave().catch(() => false) ?? true;
    if (!flushed) {
      status.value = "저장 실패로 새 Workspace를 만들지 않았습니다. 재시도해 주세요.";
      return;
    }
    await chatView.value?.cancelActiveStream();
    try {
      const created = await api.createWorkspace(path);
      activeWorkspace.value = created.path;
      workspacePath.value = created.path;
      workspaceOpen.value = true;
      openNoteRequest.value = null;
      historyRequest.value = null;
      undoMessage.value = "";
      undoConflicts.value = [];
      status.value = "";
    } catch (e: any) {
      status.value = `생성 실패: ${e.message}`;
    }
  } finally {
    busy.value = false;
  }
}

async function setMode(m: (typeof modes)[number]["id"]) {
  if (m === mode.value || locked.value) return;
  busy.value = true; // flush 동안 다른 전환/편집이 섞이지 않게 잠근다.
  try {
    const flushed = await notesView.value?.flushSave().catch(() => false) ?? true;
    if (!flushed) {
      status.value = "저장 실패로 모드를 바꾸지 않았습니다. 재시도해 주세요.";
      return;
    }
    if (m !== "chat") splitChat.value = false;
    mode.value = m;
    status.value = "";
  } finally {
    busy.value = false;
  }
}

async function setSplit(on: boolean) {
  if (locked.value) return;
  busy.value = true;
  try {
    if (!(await notesView.value?.flushSave() ?? true)) {
      status.value = "저장 실패로 Split을 바꾸지 않았습니다.";
      return;
    }
    splitChat.value = on;
  } finally {
    busy.value = false;
  }
}

async function openNoteInNotes(path: string) {
  if (locked.value) return;
  if (mode.value !== "chat" || !splitChat.value) {
    await setMode("notes");
    if (mode.value !== "notes") return;
  }
  openNoteRequest.value = { path, nonce: Date.now() };
}

async function openGraphNote(path: string) {
  if (locked.value) return;
  await notesView.value?.selectNote({ path, name: path.split("/").pop()!.replace(/\.md$/, "") });
  status.value = notesView.value?.current?.path === path ? "" : "Note를 옮기지 못했습니다. Notes에서 저장 또는 로드 오류를 확인해 주세요.";
}

function onBeforeUnload(e: BeforeUnloadEvent) {
  // 닫기 직전 변경을 보장 저장하지는 않는다. 사용자가 저장 시점을 놓치지 않도록 경고만 띄운다.
  if (notesView.value?.isDirty()) {
    e.preventDefault();
    e.returnValue = "";
  }
}

onMounted(async () => {
  window.addEventListener("beforeunload", onBeforeUnload);
  const w = await api.workspace();
  if (w.path) {
    workspaceOpen.value = true;
    activeWorkspace.value = w.path;
    workspacePath.value = w.path;
  }
});

onBeforeUnmount(() => {
  window.removeEventListener("beforeunload", onBeforeUnload);
});
</script>

<template>
  <div class="app">
    <header class="app-header">
      <div class="nav-pill">
        <h1 class="wordmark">Knowledge Palette</h1>
        <nav v-if="workspaceOpen" class="modes" aria-label="작업 모드">
          <button v-for="item in modes" :key="item.id" :disabled="locked" :aria-pressed="mode === item.id" :class="{ active: mode === item.id }" @click="setMode(item.id)">{{ item.label }}</button>
        </nav>
      </div>
      <div class="workspace-bar">
        <label class="eyebrow" for="workspace-path">Workspace</label>
        <input id="workspace-path" v-model="workspacePath" :disabled="locked" :aria-invalid="!!status" placeholder="/absolute/path/to/workspace" />
        <button class="btn--primary" :disabled="locked" :aria-busy="busy" @click="openPath(workspacePath)">열기</button>
        <button :disabled="locked" @click="createPath(workspacePath)">새 Workspace</button>
        <span v-if="busy" class="status-chip" data-state="loading" role="status">처리 중…</span>
      </div>
      <p v-if="workspaceOpen" class="workspace-path muted" :title="activeWorkspace">현재 Workspace · {{ activeWorkspace }}</p>
    </header>
    <p v-if="status" class="error app-status" role="alert">{{ status }}</p>
    <section v-if="undoMessage" class="undo-message banner" :class="{ 'banner--error': undoFailed }" :role="undoFailed ? 'alert' : 'status'">
      <p>{{ undoMessage }}</p>
      <ul v-if="undoConflicts.length"><li v-for="conflict in undoConflicts" :key="conflict.path">{{ conflict.path }} · {{ conflict.reason === 'missing' ? '파일 없음' : '이후 수정됨' }}</li></ul>
      <button :disabled="locked" @click="undoMessage = ''; undoConflicts = []">닫기</button>
    </section>
    <section v-if="!workspaceOpen" class="workspace-empty card empty-state">
      <h2>Workspace를 열어 시작하세요.</h2>
      <p>기존 폴더의 경로를 입력하거나 새 Workspace를 만드세요.</p>
    </section>

    <main v-if="workspaceOpen" :key="activeWorkspace" :class="{ split: mode === 'chat' && splitChat }">
      <ChatView v-show="mode === 'chat'" ref="chatView" :busy="locked" :split-on="splitChat" @open-note="openNoteInNotes" @open-history="openHistory" @undo="undoUpdate" @knowledge-changed="notesView?.knowledgeChanged($event)" @split-change="setSplit" />
      <div v-show="mode === 'notes' || (mode === 'chat' && splitChat)" class="notes-main">
        <NotesView :open-request="openNoteRequest" :compact="mode === 'chat'" :navigation-busy="busy" @busy-change="noteBusy = $event" ref="notesView" />
      </div>
      <SearchView v-if="mode === 'search'" @open-note="openNoteInNotes" />
      <SourcesView v-if="mode === 'sources'" />
      <HistoryView v-if="mode === 'history'" ref="historyView" :request="historyRequest" :busy="locked" @open-note="openNoteInNotes" @undo="undoUpdate" />
      <GraphView v-if="mode === 'graph'" :path="notesView?.current?.path ?? null" :busy="locked" @open-note="openGraphNote" @choose-note="setMode('notes')" />
      <BaseView v-if="mode === 'base'" :navigation-busy="locked" @open-note="openNoteInNotes" />
    </main>
  </div>
</template>

<style scoped>
.app { display: flex; flex-direction: column; height: 100dvh; min-height: 0; padding: var(--space-md) var(--space-lg); gap: var(--space-sm); }
.app-header { flex-shrink: 0; }
.nav-pill { display: flex; align-items: center; justify-content: center; gap: var(--space-lg); width: fit-content; max-width: 100%; margin: 0 auto var(--space-md); padding: var(--space-xs) var(--space-sm) var(--space-xs) var(--space-lg); border: var(--rule-soft); border-radius: var(--radius-pill); background: var(--color-paper-0); box-shadow: var(--shadow-nav); }
.wordmark { margin: 0; font-size: var(--text-base); font-weight: 600; letter-spacing: -0.03em; white-space: nowrap; }
.modes { display: flex; flex-wrap: wrap; justify-content: center; gap: var(--space-2xs); }
.modes button { border: 0; background: var(--color-transparent); padding-inline: var(--space-md); }
.modes button.active { background: var(--color-ink-0); color: var(--color-paper-0); }
.workspace-bar { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-xs); max-width: 1000px; margin: auto; }
.workspace-bar input { flex: 1; min-width: 160px; font-family: var(--font-mono); font-size: var(--text-xs); }
.workspace-path { max-width: 1000px; margin: var(--space-xs) auto 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.app-status { margin: 0; }
.undo-message { flex-shrink: 0; max-height: 30dvh; overflow: auto; }
.undo-message p { margin: 0 0 var(--space-xs); }
.undo-message li { overflow-wrap: anywhere; }
main { display: flex; flex: 1; min-height: 0; min-width: 0; gap: var(--space-md); }
.notes-main { display: flex; flex: 1; min-height: 0; min-width: 0; }
.split > * { min-width: 0; flex: 1; width: 50%; }
.workspace-empty { margin: auto; width: min(100%, 640px); }
@media (max-width: 900px) { .split { flex-direction: column; overflow: auto; } .split > * { width: 100%; flex: none; min-height: 500px; } }
@media (max-width: 768px) {
  .app { padding: var(--space-sm); }
  .nav-pill { flex-direction: column; gap: var(--space-xs); padding: var(--space-xs) var(--space-sm); border-radius: var(--radius-xl); }
  .wordmark { font-size: var(--text-sm); }
  .modes button { min-height: 36px; padding: var(--space-xs) var(--space-sm); font-size: var(--text-xs); }
  .workspace-bar .eyebrow { width: 100%; }
  .workspace-bar input { flex-basis: 100%; }
}
</style>
