<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from "vue";
import { api } from "./api";
import SearchView from "./SearchView.vue";
import SourcesView from "./SourcesView.vue";
import ChatView from "./ChatView.vue";
import NotesView from "./NotesView.vue";

const mode = ref<"notes" | "search" | "sources" | "chat">("notes");
const splitChat = ref(false); // Chat에서 노트를 명시적으로 함께 볼 때만 켠다.
const workspacePath = ref(""); // 입력창 초안
const activeWorkspace = ref(""); // 실제로 열린 워크스페이스 (표시/키잉 기준)
const workspaceOpen = ref(false);
const status = ref("");
const busy = ref(false);
const openNoteRequest = ref<{ path: string; nonce: number } | null>(null);

const notesView = ref<InstanceType<typeof NotesView> | null>(null);
const chatView = ref<InstanceType<typeof ChatView> | null>(null);

async function flushAll(): Promise<boolean> {
  const ok = (await notesView.value?.flushSave()) ?? true;
  if (!ok) return false;
  chatView.value?.cancelActiveStream();
  return true;
}

async function openPath(path: string) {
  if (busy.value) return;
  busy.value = true; // flush와 로드 전체 동안 잠근다.
  try {
    const flushed = await notesView.value?.flushSave().catch(() => false) ?? true;
    if (!flushed) {
      status.value = "저장 실패로 워크스페이스를 전환하지 않았습니다. 재시도해 주세요.";
      return;
    }
    chatView.value?.cancelActiveStream();
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
  if (busy.value) return;
  busy.value = true;
  try {
    const flushed = await notesView.value?.flushSave().catch(() => false) ?? true;
    if (!flushed) {
      status.value = "저장 실패로 새 Workspace를 만들지 않았습니다. 재시도해 주세요.";
      return;
    }
    chatView.value?.cancelActiveStream();
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
  if (m === mode.value || busy.value) return;
  busy.value = true; // flush 동안 다른 전환/편집이 섞이지 않게 잠근다.
  try {
    const flushed = await notesView.value?.flushSave().catch(() => false) ?? true;
    if (!flushed) {
      status.value = "저장 실패로 모드를 바꾸지 않았습니다. 재시도해 주세요.";
      return;
    }
    if (m !== "chat") chatView.value?.cancelActiveStream();
    if (m !== "chat") splitChat.value = false;
    mode.value = m;
    status.value = "";
  } finally {
    busy.value = false;
  }
}

function openNoteInNotes(path: string) {
  // 인용 점프는 항상 full Notes 화면으로: split을 끄고 해당 노트를 연다.
  splitChat.value = false;
  mode.value = "notes";
  openNoteRequest.value = { path, nonce: Date.now() };
}

function openNoteFromSearch(path: string) {
  splitChat.value = false;
  mode.value = "notes";
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
      <input v-model="workspacePath" :disabled="busy" placeholder="/absolute/path/to/workspace" />
      <button :disabled="busy" @click="openPath(workspacePath)">열기</button>
      <button :disabled="busy" @click="createPath(workspacePath)">새 Workspace</button>
      <span v-if="workspaceOpen" class="ok">● {{ activeWorkspace }}</span>
      <span v-if="busy">처리 중…</span>
      <nav v-if="workspaceOpen" class="modes">
        <button :class="{ active: mode === 'notes' }" @click="setMode('notes')">Notes</button>
        <button :class="{ active: mode === 'chat' }" @click="setMode('chat')">Chat</button>
        <button :class="{ active: mode === 'search' }" @click="setMode('search')">Search</button>
        <button :class="{ active: mode === 'sources' }" @click="setMode('sources')">Sources</button>
      </nav>
    </header>
    <p v-if="status" class="status">{{ status }}</p>

    <main v-if="workspaceOpen && mode === 'notes'">
      <NotesView :key="activeWorkspace" :open-request="openNoteRequest" ref="notesView" />
    </main>
    <SearchView :key="activeWorkspace" v-else-if="workspaceOpen && mode === 'search'" @open-note="openNoteFromSearch" />
    <SourcesView :key="activeWorkspace" v-else-if="workspaceOpen && mode === 'sources'" />
    <main v-else-if="workspaceOpen && mode === 'chat' && splitChat" class="split">
      <ChatView :key="activeWorkspace" ref="chatView" @open-note="openNoteInNotes" @split-change="splitChat = $event" />
      <NotesView :key="activeWorkspace + '-split'" :open-request="openNoteRequest" compact ref="notesView" />
    </main>
    <main v-else-if="workspaceOpen && mode === 'chat'" class="chat-main">
      <ChatView :key="activeWorkspace" ref="chatView" @open-note="openNoteInNotes" @split-change="splitChat = $event" />
    </main>
  </div>
</template>

<script lang="ts">
export default {
  computed: {
    modeTitle(): string {
      return this.mode === "notes" ? "Notes" : this.mode === "chat" ? "Chat" : this.mode === "search" ? "Search" : "Sources";
    },
  },
};
</script>

<style>
body { margin: 0; font-family: system-ui, sans-serif; }
.app { display: flex; flex-direction: column; height: 100vh; }
header { display: flex; gap: 8px; padding: 8px 12px; background: #1e1e2e; color: #eee; align-items: center; }
header input { flex: 1; padding: 6px; }
main { display: flex; flex: 1; min-height: 0; }
.chat-main { display: flex; flex: 1; min-height: 0; }
.split { display: flex; flex: 1; min-height: 0; }
.split > * { min-width: 0; }
.status { margin: 4px 12px; color: #b91c1c; }
.modes button { margin-left: 4px; }
.modes button.active { font-weight: bold; text-decoration: underline; }
</style>
