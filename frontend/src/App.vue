<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from "vue";
import MarkdownIt from "markdown-it";
import { api, NoteMeta } from "./api";
import SearchView from "./SearchView.vue";
import SourcesView from "./SourcesView.vue";

const md = new MarkdownIt({ html: false, linkify: true });

// wikilink를 텍스트 토큰 단계에서 처리해 코드블록/인라인코드/HTML 속성 안에서는 렌더링되지 않게 한다.
md.inline.ruler.before("link", "wikilink", (state, silent) => {
  if (state.src.slice(state.pos, state.pos + 2) !== "[[") return false;
  const end = state.src.indexOf("]]", state.pos + 2);
  if (end === -1) return false;
  const inner = state.src.slice(state.pos + 2, end);
  if (!inner || inner.includes("[") || inner.includes("\n")) return false;
  if (!silent) {
    const token = state.push("wikilink", "", 0);
    token.content = inner;
  }
  state.pos = end + 2;
  return true;
});

md.renderer.rules.wikilink = (tokens, idx) => {
  const inner = tokens[idx].content;
  const pipe = inner.indexOf("|");
  const target = (pipe >= 0 ? inner.slice(0, pipe) : inner).trim();
  const label = (pipe >= 0 ? inner.slice(pipe + 1) : inner).trim();
  return `<a href="#" class="wikilink" data-target="${md.utils.escapeHtml(target)}">${md.utils.escapeHtml(label)}</a>`;
};

const mode = ref<"notes" | "search" | "sources">("notes");
const workspacePath = ref(""); // 입력창 초안
const activeWorkspace = ref(""); // 실제로 열린 워크스페이스 (표시/키잉 기준)
const workspaceOpen = ref(false);
const notes = ref<NoteMeta[]>([]);
const allNames = ref<NoteMeta[]>([]);
const current = ref<NoteMeta | null>(null);
const text = ref("");
const savedText = ref("");
const saveState = ref<"saved" | "dirty" | "saving" | "error">("saved");
const saveError = ref("");
const searchQ = ref("");
const searchResults = ref<{ path: string; name: string; in_title: boolean; snippet: string }[]>([]);
const backlinks = ref<NoteMeta[]>([]);
const newNoteName = ref("");
const status = ref("");
const busy = ref(false);

const textarea = ref<HTMLTextAreaElement | null>(null);
const completion = ref<{ open: boolean; items: { name: string; path: string; ambiguous: boolean }[]; start: number }>({
  open: false,
  items: [],
  start: 0,
});

let saveTimer: ReturnType<typeof setTimeout> | null = null;
let activeSave: Promise<boolean> | null = null;
let navSeq = 0;
let saveInflight = false;

async function refreshNotes() {
  const r = await api.listNotes();
  notes.value = r.notes;
  const n = await api.noteNames();
  allNames.value = n.notes;
  if (current.value) refreshBacklinks(current.value.path);
}

async function openPath(path: string) {
  if (busy.value) return;
  busy.value = true; // flush와 로드 전체 동안 잠근다.
  try {
    const flushed = await flushSave();
    if (!flushed) {
      status.value = "저장 실패로 워크스페이스를 전환하지 않았습니다. 재시도해 주세요.";
      return;
    }
    try {
      const opened = await api.openWorkspace(path);
      activeWorkspace.value = opened.path;
      workspacePath.value = opened.path;
      workspaceOpen.value = true;
      current.value = null;
      text.value = "";
      savedText.value = "";
      saveState.value = "saved";
      status.value = "";
      searchResults.value = [];
      backlinks.value = [];
      completion.value = { open: false, items: [], start: 0 };
      await refreshNotes();
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
    const flushed = await flushSave();
    if (!flushed) {
      status.value = "저장 실패로 새 Workspace를 만들지 않았습니다. 재시도해 주세요.";
      return;
    }
    try {
      const created = await api.createWorkspace(path);
      activeWorkspace.value = created.path;
      workspacePath.value = created.path;
      workspaceOpen.value = true;
      current.value = null;
      text.value = "";
      savedText.value = "";
      saveState.value = "saved";
      status.value = "";
      searchResults.value = [];
      backlinks.value = [];
      completion.value = { open: false, items: [], start: 0 };
      await refreshNotes();
    } catch (e: any) {
      status.value = `생성 실패: ${e.message}`;
    }
  } finally {
    busy.value = false;
  }
}

async function selectNote(note: NoteMeta) {
  if (busy.value || current.value?.path === note.path) return;
  busy.value = true; // flush와 로드가 끝날 때까지 잠근다.
  const seq = ++navSeq;
  try {
    const flushed = await flushSave();
    if (!flushed) {
      status.value = "저장에 실패해 이동하지 않았습니다. 재시도 버튼으로 다시 저장해 주세요.";
      return;
    }
    try {
      const r = await api.readNote(note.path);
      // 로드 도중 다른 선택이 있었다면 이 결과는 버린다.
      if (seq !== navSeq) return;
      current.value = note;
      text.value = r.content;
      savedText.value = r.content;
      saveState.value = "saved";
      status.value = "";
      backlinks.value = [];
      searchResults.value = [];
      completion.value = { open: false, items: [], start: 0 };
      refreshBacklinks(note.path);
    } catch (e: any) {
      if (seq === navSeq) status.value = `노트 로드 실패: ${e.message} (현재 노트 유지)`;
    }
  } finally {
    busy.value = false;
  }
}

async function createNote() {
  const name = newNoteName.value.trim();
  if (!name || busy.value) return;
  busy.value = true; // 생성과 뒤따르는 로드까지 한 작업으로 잠근다.
  try {
    const flushed = await flushSave();
    if (!flushed) {
      status.value = "저장에 실패해 새 노트를 만들지 않았습니다.";
      return;
    }
    try {
      const created = await api.createNote(name);
      newNoteName.value = "";
      await refreshNotes();
      const r = await api.readNote(created.path);
      current.value = created;
      text.value = r.content;
      savedText.value = r.content;
      saveState.value = "saved";
      backlinks.value = [];
      refreshBacklinks(created.path);
    } catch (e: any) {
      status.value = `노트 생성 실패: ${e.message}`;
    }
  } finally {
    busy.value = false;
  }
}

async function setMode(m: "notes" | "search" | "sources") {
  if (m === mode.value || busy.value) return;
  busy.value = true; // flush 동안 다른 전환/편집이 섞이지 않게 잠근다.
  try {
    const flushed = await flushSave();
    if (!flushed) {
      status.value = "저장 실패로 모드를 바꾸지 않았습니다. 재시도해 주세요.";
      return;
    }
    mode.value = m;
    status.value = "";
  } finally {
    busy.value = false;
  }
}

async function openNoteFromSearch(path: string) {
  const relative = path.replace(/\.md$/, "");
  mode.value = "notes";
  await selectNote({ path: path, name: relative });
}

const AUTO_SAVE_MS = 800;

function scheduleSave() {
  if (!current.value) return;
  saveState.value = "dirty";
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    flushSave();
  }, AUTO_SAVE_MS);
}

// 직렬화는 "활성 저장 하나"로 보장한다: 이전 저장이 완전히 끝난 뒤에만 현재 텍스트를 판단하고 새 저장을 시작한다.
async function flushSave(): Promise<boolean> {
  if (saveTimer) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
  while (activeSave) {
    await activeSave.catch(() => {});
  }
  const target = current.value;
  if (!target || text.value === savedText.value) {
    if (target && saveState.value !== "error") saveState.value = "saved";
    return saveState.value !== "error";
  }
  const snapshot = text.value;
  saveState.value = "saving";
  saveInflight = true;
  activeSave = (async () => {
    try {
      await api.writeNote(target.path, snapshot);
      if (current.value && current.value.path === target.path) {
        savedText.value = snapshot;
        if (text.value === snapshot) saveState.value = "saved";
        else scheduleSave(); // 저장 중 추가 편집이 있었다면 다시 예약
      }
      return true;
    } catch (e: any) {
      // 실패 시 초안을 그대로 두고 재시도할 수 있게 한다.
      if (current.value && current.value.path === target.path) {
        saveState.value = "error";
        saveError.value = e.message;
      }
      return false;
    } finally {
      saveInflight = false;
      activeSave = null;
    }
  })();
  return activeSave;
}

function retrySave() {
  if (busy.value) return;
  saveState.value = "dirty";
  flushSave();
}

async function refreshBacklinks(path: string) {
  // 같은 파일명이 다른 워크스페이스에 있어도 섞이지 않도록 호출 시점의 워크스페이스를 캡처한다.
  const wsSnapshot = activeWorkspace.value;
  try {
    const r = await api.backlinks(path);
    // 이전 노트/워크스페이스의 늦은 응답이 현재 화면을 덮지 않게 한다.
    if (current.value && current.value.path === path && activeWorkspace.value === wsSnapshot) {
      backlinks.value = r.backlinks;
    }
  } catch {
    if (current.value && current.value.path === path && activeWorkspace.value === wsSnapshot) backlinks.value = [];
  }
}

const rendered = computed(() => md.render(text.value));

function onPreviewClick(e: MouseEvent) {
  if (busy.value) return;
  const el = (e.target as HTMLElement).closest("a.wikilink") as HTMLElement | null;
  if (!el) return;
  e.preventDefault();
  gotoLink(el.dataset.target || "");
}

async function gotoLink(target: string) {
  if (busy.value) return;
  const r = await api.resolve(target);
  if (r.status === "ok") {
    await selectNote({ path: r.matches[0], name: r.matches[0].replace(/\.md$/, "") });
  } else if (r.status === "missing") {
    status.value = `대상 없음: [[${target}]]`;
  } else {
    status.value = `모호한 대상 (파일명 중복): [[${target}]] — ${r.matches.join(", ")}`;
  }
}

function onEditorInput() {
  scheduleSave();
  updateCompletion();
}

function onTab(e: KeyboardEvent) {
  const el = textarea.value;
  if (!el) return;
  e.preventDefault();
  const start = el.selectionStart;
  const end = el.selectionEnd;
  el.setRangeText("  ", start, end, "end");
  text.value = el.value;
  scheduleSave();
  updateCompletion();
}

function updateCompletion() {
  const el = textarea.value;
  if (!el) return;
  const pos = el.selectionStart;
  const before = text.value.slice(0, pos);
  const m = before.match(/\[\[([^\[\]|]*)$/);
  if (!m) {
    completion.value = { open: false, items: [], start: 0 };
    return;
  }
  const prefix = m[1].toLowerCase();
  // basename이 중복인 이름은 어떤 파일인지 구분할 수 있도록 상대 경로를 함께 보여준다.
  const stemCount = new Map<string, number>();
  for (const n of allNames.value) stemCount.set(n.name, (stemCount.get(n.name) ?? 0) + 1);
  const items = allNames.value
    .filter((n) => n.name.toLowerCase().includes(prefix) || n.path.toLowerCase().includes(prefix))
    .slice(0, 8)
    .map((n) => ({ name: n.name, path: n.path, ambiguous: (stemCount.get(n.name) ?? 0) > 1 }));
  completion.value = { open: items.length > 0, items, start: pos - m[1].length };
}

function completionInsertText(item: { name: string; path: string; ambiguous: boolean }) {
  // 중복 basename은 plain 이름으로 넣으면 다시 ambiguous가 되므로 경로로 넣는다.
  // 루트 파일은 ./ 접두사로 하위 파일과 구분한다.
  if (!item.ambiguous) return item.name;
  const rel = item.path.replace(/\.md$/, "");
  return rel.includes("/") ? rel : "./" + rel;
}

function pickCompletion(item: { name: string; path: string; ambiguous: boolean }) {
  if (busy.value) return;
  const el = textarea.value;
  if (!el) return;
  const pos = el.selectionStart;
  const before = text.value.slice(0, completion.value.start - 2);
  const after = text.value.slice(pos);
  const insert = completionInsertText(item);
  // 커서 뒤에 이미 ']]'가 붙어 있으면 중복으로 닫지 않는다.
  const closing = after.startsWith("]]") ? "" : "]]";
  text.value = before + "[[" + insert + closing + after;
  completion.value.open = false;
  requestAnimationFrame(() => {
    el.focus();
    const cursor = before.length + 2 + insert.length + closing.length;
    el.selectionStart = el.selectionEnd = cursor;
  });
  scheduleSave();
}

function onEditorKeydown(e: KeyboardEvent) {
  if (e.key === "Escape") {
    completion.value.open = false;
    return;
  }
  if (e.key === "Tab") onTab(e);
}

function onSearch() {
  if (!searchQ.value.trim()) {
    searchResults.value = [];
    return;
  }
  api.search(searchQ.value).then((r) => (searchResults.value = r.results));
}

function beforeunloadDirty() {
  return saveState.value !== "saved" || saveInflight || activeSave !== null || text.value !== savedText.value;
}

function onBeforeUnload(e: BeforeUnloadEvent) {
  // 닫기 직전 변경을 보장 저장하지는 않는다. 사용자가 저장 시점을 놓치지 않도록 경고만 띄운다.
  if (beforeunloadDirty()) {
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
    await refreshNotes();
  }
});

onBeforeUnmount(() => {
  window.removeEventListener("beforeunload", onBeforeUnload);
});
</script>

<template>
  <div class="app">
    <header>
      <h1>Knowledge Palette — {{ mode === "notes" ? "Notes" : mode === "search" ? "Search" : "Sources" }}</h1>
      <input v-model="workspacePath" :disabled="busy" placeholder="/absolute/path/to/workspace" />
      <button :disabled="busy" @click="openPath(workspacePath)">열기</button>
      <button :disabled="busy" @click="createPath(workspacePath)">새 Workspace</button>
      <span v-if="workspaceOpen" class="ok">● {{ activeWorkspace }}</span>
      <span v-if="busy">처리 중…</span>
      <nav v-if="workspaceOpen" class="modes">
        <button :class="{ active: mode === 'notes' }" @click="setMode('notes')">Notes</button>
        <button :class="{ active: mode === 'search' }" @click="setMode('search')">Search</button>
        <button :class="{ active: mode === 'sources' }" @click="setMode('sources')">Sources</button>
      </nav>
    </header>
    <p v-if="status" class="status">{{ status }}</p>

    <main v-if="workspaceOpen && mode === 'notes'">
      <aside>
        <input v-model="searchQ" placeholder="검색 (제목/파일/본문)" @input="onSearch" />
        <div v-if="searchResults.length" class="search-results">
          <div v-for="r in searchResults" :key="r.path" class="result" @click="selectNote(r)">
            <b>{{ r.name }}</b>
            <small>{{ r.snippet }}</small>
          </div>
        </div>

        <input v-model="newNoteName" placeholder="새 노트 (예: folder/이름)" @keyup.enter="createNote" />
        <button :disabled="busy" @click="createNote">+ 노트</button>

        <ul class="notes">
          <li v-for="n in notes" :key="n.path" :class="{ active: current?.path === n.path, disabled: busy }" @click="selectNote(n)">
            {{ n.path }}
          </li>
        </ul>

        <h3>Backlinks</h3>
        <ul>
          <li v-for="b in backlinks" :key="b.path" class="link" @click="selectNote(b)">[[{{ b.name }}]]</li>
        </ul>
      </aside>

      <section class="workspace-canvas" v-if="current">
        <div class="bar">
          <b>{{ current.path }}</b>
          <span class="save" :class="saveState">
            {{ saveState === "saving" ? "저장 중…" : saveState === "dirty" ? "변경됨" : saveState === "error" ? "저장 실패: " + saveError : "저장됨" }}
          </span>
          <button v-if="saveState === 'error'" @click="retrySave">다시 저장</button>
        </div>
        <div class="panes">
          <div class="editor">
            <textarea
              ref="textarea"
              v-model="text"
              :disabled="busy"
              @input="onEditorInput"
              @keydown="onEditorKeydown"
            ></textarea>
            <ul v-if="completion.open" class="completion">
              <li v-for="item in completion.items" :key="item.path" @mousedown.prevent="pickCompletion(item)">
                [[{{ completionInsertText(item) }}]]
              </li>
            </ul>
          </div>
          <div class="preview" v-html="rendered" @click="onPreviewClick"></div>
        </div>
      </section>
      <section v-else class="empty">노트를 선택하세요.</section>
    </main>
    <SearchView :key="activeWorkspace" v-else-if="workspaceOpen && mode === 'search'" @open-note="openNoteFromSearch" />
    <SourcesView :key="activeWorkspace" v-else-if="workspaceOpen && mode === 'sources'" />
  </div>
</template>

<style>
body { margin: 0; font-family: system-ui, sans-serif; }
.app { display: flex; flex-direction: column; height: 100vh; }
header { display: flex; gap: 8px; padding: 8px 12px; background: #1e1e2e; color: #eee; align-items: center; }
header input { flex: 1; padding: 6px; }
main { display: flex; flex: 1; min-height: 0; }
aside { width: 260px; padding: 8px; border-right: 1px solid #ddd; overflow: auto; }
.workspace-canvas { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.bar { display: flex; gap: 8px; justify-content: space-between; padding: 6px 12px; background: #f3f3f3; }
.panes { display: flex; flex: 1; min-height: 0; }
.editor, .preview { flex: 1; min-width: 0; }
.editor textarea { width: 100%; height: 100%; border: none; outline: none; padding: 12px; font-family: monospace; box-sizing: border-box; resize: none; }
.preview { padding: 12px; overflow: auto; border-left: 1px solid #ddd; }
.editor { position: relative; display: flex; }
.completion { position: absolute; bottom: 10%; left: 12px; background: white; border: 1px solid #ccc; list-style: none; padding: 4px; margin: 0; max-height: 200px; overflow: auto; }
.completion li { padding: 2px 8px; cursor: pointer; }
.completion li:hover { background: #eee; }
.notes li { cursor: pointer; padding: 2px 4px; }
.notes li.active { background: #e0e7ff; }
.notes li.disabled { opacity: 0.5; pointer-events: none; }
a.wikilink { color: #2563eb; cursor: pointer; }
.save.error { color: #b91c1c; }
.search-results .result { cursor: pointer; padding: 4px; border-bottom: 1px solid #eee; }
.link { cursor: pointer; color: #2563eb; }
.status { margin: 4px 12px; color: #b91c1c; }
.empty { flex: 1; display: grid; place-items: center; color: #888; }
.modes button { margin-left: 4px; }
.modes button.active { font-weight: bold; text-decoration: underline; }
</style>
