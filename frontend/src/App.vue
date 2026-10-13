<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from "vue";
import { api } from "./api";
import SearchView from "./SearchView.vue";
import SourcesView from "./SourcesView.vue";
import ChatView from "./ChatView.vue";
import NotesView from "./NotesView.vue";

const mode = ref<"notes" | "search" | "sources" | "chat">("chat");
const splitChat = ref(false); // Chat에서 노트를 명시적으로 함께 볼 때만 켠다.
const workspacePath = ref(""); // 입력창 초안
const activeWorkspace = ref(""); // 실제로 열린 워크스페이스 (표시/키잉 기준)
const workspaceOpen = ref(false);
const status = ref("");
const busy = ref(false);
const noteBusy = ref(false);
const locked = computed(() => busy.value || noteBusy.value);
const modeTitle = computed(() => ({ notes: "Notes", chat: "Chat", search: "Search", sources: "Sources" })[mode.value]);
const openNoteRequest = ref<{ path: string; nonce: number } | null>(null);

const notesView = ref<InstanceType<typeof NotesView> | null>(null);
const chatView = ref<InstanceType<typeof ChatView> | null>(null);

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
      status.value = "";
    } catch (e: any) {
      status.value = `생성 실패: ${e.message}`;
    }
  } finally {
    busy.value = false;
  }
}

async function setMode(m: "notes" | "search" | "sources" | "chat") {
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
    <header>
      <h1>Knowledge Palette — {{ modeTitle }}</h1>
      <input v-model="workspacePath" :disabled="locked" placeholder="/absolute/path/to/workspace" />
      <button :disabled="locked" @click="openPath(workspacePath)">열기</button>
      <button :disabled="locked" @click="createPath(workspacePath)">새 Workspace</button>
      <span v-if="workspaceOpen" class="ok">● {{ activeWorkspace }}</span>
      <span v-if="busy">처리 중…</span>
      <nav v-if="workspaceOpen" class="modes">
        <button :disabled="locked" :class="{ active: mode === 'notes' }" @click="setMode('notes')">Notes</button>
        <button :disabled="locked" :class="{ active: mode === 'chat' }" @click="setMode('chat')">Chat</button>
        <button :disabled="locked" :class="{ active: mode === 'search' }" @click="setMode('search')">Search</button>
        <button :disabled="locked" :class="{ active: mode === 'sources' }" @click="setMode('sources')">Sources</button>
      </nav>
    </header>
    <p v-if="status" class="status">{{ status }}</p>

    <main v-if="workspaceOpen" :key="activeWorkspace" :class="{ split: mode === 'chat' && splitChat }">
      <ChatView v-show="mode === 'chat'" ref="chatView" :busy="locked" :split-on="splitChat" @open-note="openNoteInNotes" @split-change="setSplit" />
      <div v-show="mode === 'notes' || (mode === 'chat' && splitChat)" class="notes-main">
        <NotesView :open-request="openNoteRequest" :compact="mode === 'chat'" :navigation-busy="busy" @busy-change="noteBusy = $event" ref="notesView" />
      </div>
      <SearchView v-if="mode === 'search'" @open-note="openNoteInNotes" />
      <SourcesView v-if="mode === 'sources'" />
    </main>
  </div>
</template>

<style>
body { margin: 0; font-family: system-ui, sans-serif; }
.app { display: flex; flex-direction: column; height: 100vh; }
header { display: flex; gap: 8px; padding: 8px 12px; background: #1e1e2e; color: #eee; align-items: center; }
header input { flex: 1; padding: 6px; }
main { display: flex; flex: 1; min-height: 0; }
.notes-main { display: flex; flex: 1; min-height: 0; }
.split { display: flex; flex: 1; min-height: 0; }
.split > * { min-width: 0; flex: 1; width: 50%; }
.status { margin: 4px 12px; color: #b91c1c; }
.modes button { margin-left: 4px; }
.modes button.active { font-weight: bold; text-decoration: underline; }
</style>
