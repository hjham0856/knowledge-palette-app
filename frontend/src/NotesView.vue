<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import MarkdownIt from "markdown-it";
import { api, NoteMeta } from "./api";

const props = defineProps<{
  openRequest: { path: string; nonce: number } | null;
  navigationBusy?: boolean;
  compact?: boolean; // split 모드에서는 노트 목록 대신 편집 캔버스만 보여준다.
}>();

const emit = defineEmits<{ (e: "busy-change", busy: boolean): void }>();

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

const listMedia = window.matchMedia("(min-width: 769px)");
const listOpen = ref(listMedia.matches);
function onListBreakpoint(e: MediaQueryListEvent) {
  listOpen.value = e.matches;
}
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
const localBusy = ref(false);
const busy = computed(() => localBusy.value || props.navigationBusy);
watch(localBusy, (value) => emit("busy-change", value), { flush: "sync" });

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

async function selectNote(note: NoteMeta) {
  if (busy.value || current.value?.path === note.path) return;
  localBusy.value = true; // flush와 로드가 끝날 때까지 잠근다.
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
    localBusy.value = false;
  }
}

async function createNote() {
  const name = newNoteName.value.trim();
  if (!name || busy.value) return;
  localBusy.value = true; // 생성과 뒤따르는 로드까지 한 작업으로 잠근다.
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
    localBusy.value = false;
  }
}

watch(
  () => props.openRequest,
  (req) => {
    if (!req) return;
    const name = req.path.replace(/\.md$/, "");
    selectNote({ path: req.path, name });
  }
);

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
  try {
    const r = await api.backlinks(path);
    if (current.value && current.value.path === path) {
      backlinks.value = r.backlinks;
    }
  } catch {
    if (current.value && current.value.path === path) backlinks.value = [];
  }
}

// 속성은 원문 그대로 보여주고 본문만 Markdown으로 렌더링한다. 편집·저장 원본에는 손대지 않는다.
const previewParts = computed(() => {
  const frontmatter = /^---[ \t]*\r?\n(?:([\s\S]*?)\r?\n)?---[ \t]*(?:\r?\n|$)/.exec(text.value);
  return {
    properties: frontmatter ? frontmatter[1] ?? "" : null,
    body: frontmatter ? text.value.slice(frontmatter[0].length) : text.value,
  };
});
const rendered = computed(() => md.render(previewParts.value.body));

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
  if (busy.value) return;
  if (!searchQ.value.trim()) {
    searchResults.value = [];
    return;
  }
  api.search(searchQ.value).then((r) => (searchResults.value = r.results));
}

function isDirty() {
  return saveState.value !== "saved" || saveInflight || activeSave !== null || text.value !== savedText.value;
}

onMounted(async () => {
  listMedia.addEventListener("change", onListBreakpoint);
  await refreshNotes();
});

onBeforeUnmount(() => {
  listMedia.removeEventListener("change", onListBreakpoint);
  if (saveTimer) clearTimeout(saveTimer);
});

defineExpose({ flushSave, isDirty, refreshNotes });
</script>

<template>
  <div class="notes-view card" :class="{ compact }">
    <div v-if="!compact" class="list-toggle">
      <button :aria-expanded="listOpen" aria-controls="note-list" @click="listOpen = !listOpen">{{ listOpen ? '목록 접기' : '노트 목록' }}</button>
    </div>
    <div class="notes-layout">
      <aside v-if="!compact && listOpen" id="note-list" class="note-list" aria-label="노트 목록">
        <label class="eyebrow" for="note-filter">Notes</label>
        <input id="note-filter" :disabled="busy" v-model="searchQ" placeholder="검색 (제목/파일/본문)" @input="onSearch" />
        <div v-if="searchResults.length" class="search-results">
          <button v-for="r in searchResults" :key="r.path" class="list-button result" :disabled="busy" :title="r.name" @click="selectNote(r)">
            <b>{{ r.name }}</b><small>{{ r.snippet }}</small>
          </button>
        </div>
        <div class="new-note">
          <input aria-label="새 노트 이름" :disabled="busy" v-model="newNoteName" placeholder="새 노트 (예: folder/이름)" @keyup.enter="createNote" />
          <button :disabled="busy" @click="createNote">+ 노트</button>
        </div>
        <ul class="notes">
          <li v-for="n in notes" :key="n.path">
            <button class="list-button" :class="{ active: current?.path === n.path }" :aria-pressed="current?.path === n.path" :disabled="busy" :title="n.path" @click="selectNote(n)">{{ n.path }}</button>
          </li>
        </ul>
        <p v-if="!notes.length" class="empty-state">아직 노트가 없습니다.</p>
      </aside>
      <section class="workspace-canvas" v-if="current" :aria-busy="busy">
        <div class="bar toolbar">
          <b class="note-path" :title="current.path">{{ current.path }}</b>
          <span class="save status-chip" :data-state="saveState" role="status">
            {{ saveState === "saving" ? "저장 중…" : saveState === "dirty" ? "변경됨" : saveState === "error" ? "저장 실패: " + saveError : "저장됨" }}
          </span>
          <button :disabled="busy" v-if="saveState === 'error'" data-state="error" @click="retrySave">다시 저장</button>
        </div>
        <p v-if="status" class="error" role="alert">{{ status }}</p>
        <div class="panes">
          <div class="editor">
            <label class="eyebrow" for="note-editor">Markdown</label>
            <textarea id="note-editor" ref="textarea" v-model="text" :disabled="busy" :aria-invalid="saveState === 'error'" @input="onEditorInput" @keydown="onEditorKeydown"></textarea>
            <ul v-if="completion.open" class="completion card" aria-label="Wikilink 자동완성">
              <li v-for="item in completion.items" :key="item.path">
                <button class="list-button" :disabled="busy" :title="completionInsertText(item)" @mousedown.prevent @click="pickCompletion(item)">[[{{ completionInsertText(item) }}]]</button>
              </li>
            </ul>
          </div>
          <div class="preview-pane">
            <span class="eyebrow">Preview</span>
            <div class="preview">
              <section v-if="previewParts.properties !== null" class="properties" aria-label="노트 속성">
                <span class="eyebrow">속성</span>
                <pre>{{ previewParts.properties }}</pre>
              </section>
              <div class="prose" v-html="rendered" @click="onPreviewClick"></div>
            </div>
          </div>
        </div>
        <details v-if="!compact && backlinks.length" class="backlinks">
          <summary>Backlinks · {{ backlinks.length }}</summary>
          <ul>
            <li v-for="b in backlinks" :key="b.path"><button class="link-button" :disabled="busy" :title="b.name" @click="selectNote(b)">[[{{ b.name }}]]</button></li>
          </ul>
        </details>
      </section>
      <section v-else class="empty empty-state">노트를 선택하세요.</section>
    </div>
  </div>
</template>

<style scoped>
.notes-view { display: flex; flex-direction: column; flex: 1; min-width: 0; min-height: 0; overflow: clip; }
.list-toggle { padding: var(--space-xs) var(--space-md); border-bottom: var(--rule-hair); }
.list-toggle button { min-height: 32px; font-size: var(--text-xs); }
.notes-layout { display: flex; flex: 1; min-width: 0; min-height: 0; }
.note-list { width: 248px; flex-shrink: 0; padding: var(--space-md); border-right: var(--rule-hair); overflow: auto; }
.note-list > input { width: 100%; margin: var(--space-xs) 0 var(--space-md); }
.new-note { display: flex; flex-wrap: wrap; gap: var(--space-xs); }
.new-note input { width: 100%; }
ul { list-style: none; padding: 0; }
.notes { display: grid; gap: var(--space-2xs); }
.result b, .result small { display: block; overflow: hidden; text-overflow: ellipsis; }
.result small { color: var(--color-ink-2); }
.workspace-canvas { flex: 1; display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.bar { padding: var(--space-md) var(--space-lg); border-bottom: var(--rule-hair); }
.note-path { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 80px; }
.save { max-width: 100%; overflow-wrap: anywhere; }
.error { margin: var(--space-sm); }
.panes { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); flex: 1; min-height: 0; }
.editor, .preview-pane { min-width: 0; min-height: 0; padding: var(--space-md) var(--space-lg); }
.editor { position: relative; display: flex; flex-direction: column; gap: var(--space-sm); }
.editor textarea { flex: 1; width: 100%; min-height: 200px; padding: var(--space-sm); font-family: var(--font-mono); font-size: var(--text-sm); line-height: 1.8; resize: none; background: var(--color-paper-0); }
.preview-pane { display: flex; flex-direction: column; border-left: var(--rule-hair); }
.preview { overflow: auto; flex: 1; }
.properties { margin-top: var(--space-sm); padding: var(--space-sm) var(--space-md); background: var(--color-paper-2); border-radius: var(--radius-md); }
.properties pre { margin: var(--space-xs) 0 0; padding: 0; font-family: var(--font-mono); font-size: var(--text-xs); color: var(--color-ink-1); white-space: pre-wrap; overflow-wrap: anywhere; }
.completion { position: absolute; bottom: 10%; left: var(--space-lg); right: var(--space-lg); margin: 0; padding: var(--space-xs); max-height: 200px; overflow: auto; background: var(--color-paper-0); }
.backlinks { padding: var(--space-xs) var(--space-lg); border-top: var(--rule-hair); max-height: 160px; overflow: auto; }
.backlinks .link-button { max-width: 100%; }
.empty { flex: 1; display: grid; place-items: center; }
.compact .panes { grid-template-columns: minmax(0, 1fr); overflow: auto; }
.compact .preview-pane { border-left: 0; border-top: var(--rule-hair); }
@media (max-width: 1000px) { .panes { grid-template-columns: minmax(0, 1fr); overflow: auto; } .preview-pane { border-left: 0; border-top: var(--rule-hair); } .preview { overflow: visible; } }
@media (max-width: 768px) { .notes-layout { flex-direction: column; overflow: auto; } .note-list { width: 100%; max-height: 240px; flex-shrink: 0; border-right: 0; border-bottom: var(--rule-hair); } .workspace-canvas { flex: none; min-height: 520px; } .editor, .preview-pane, .bar { padding: var(--space-md); } .preview { overflow: visible; } }
</style>
