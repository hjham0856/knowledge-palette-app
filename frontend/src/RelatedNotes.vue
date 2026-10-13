<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { api, NoteMeta, RelatedNote } from "./api";

const props = defineProps<{
  path: string;
  savedContent: string;
  dirty: boolean;
  busy?: boolean;
  prepareLoad: () => Promise<boolean>;
}>();
const emit = defineEmits<{ (e: "open-note", note: NoteMeta): void }>();
const open = ref(false);
const loading = ref(false);
const loaded = ref(false);
const outdated = ref(false);
const error = ref("");
const incomplete = ref(false);
const results = ref<RelatedNote[]>([]);
let requestSeq = 0;

watch(() => props.savedContent, () => { outdated.value = true; });
onBeforeUnmount(() => { requestSeq++; });

async function load() {
  if (props.busy || loading.value) return;
  const seq = ++requestSeq;
  loading.value = true;
  error.value = "";
  results.value = [];
  loaded.value = false;
  incomplete.value = false;
  try {
    if (!(await props.prepareLoad())) {
      error.value = "저장 실패로 관련 Note를 불러오지 않았습니다. Note 저장을 재시도해 주세요.";
      return;
    }
    if (seq !== requestSeq) return;
    const searchedContent = props.savedContent;
    const response = await api.relatedNotes(props.path);
    if (seq !== requestSeq) return;
    results.value = response.results;
    incomplete.value = response.index_incomplete;
    outdated.value = props.savedContent !== searchedContent;
    loaded.value = true;
  } catch (e: any) {
    if (seq === requestSeq) error.value = e.message;
  } finally {
    if (seq === requestSeq) loading.value = false;
  }
}

function onToggle(event: Event) {
  open.value = (event.target as HTMLDetailsElement).open;
  if (open.value) load();
}
</script>

<template>
  <details class="related-notes" @toggle="onToggle">
    <summary>Related Notes · 관련 노트</summary>
    <div v-if="open" class="related-content">
      <div class="toolbar">
        <p class="hint">본문으로 단어·의미 검색 후, 비슷한 결과의 반복을 줄여 찾습니다.</p>
        <button class="btn btn--ghost" :disabled="busy || loading" :aria-busy="loading" @click="load">다시 찾기</button>
      </div>
      <p v-if="loading" class="status-chip" data-state="loading" role="status">관련 Note 찾는 중…</p>
      <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
      <p v-if="incomplete" class="banner banner--warning">일부 Note를 재색인하지 못했습니다. 오래된 결과는 재색인 필요로 표시합니다.</p>
      <p v-if="loaded && (dirty || outdated)" class="banner banner--warning">본문이 바뀌었습니다. 다시 찾기를 누르면 저장 후 결과를 갱신합니다.</p>
      <p v-if="loaded && !results.length" class="empty-state">관련 Note 결과가 없습니다.</p>
      <ul v-if="results.length">
        <li v-for="note in results" :key="note.path" class="card">
          <button class="link-button" :disabled="busy" :title="note.path" @click="emit('open-note', note)">{{ note.name }}</button>
          <small class="muted">{{ note.path }}</small>
          <div class="toolbar">
            <span v-if="note.outgoing" class="status-chip">나가는 링크</span>
            <span v-if="note.backlink" class="status-chip">Backlink</span>
            <span v-if="note.status !== 'indexed'" class="status-chip" data-state="stale">재색인 필요</span>
          </div>
          <p class="snippet">{{ note.content.slice(0, 240) }}</p>
        </li>
      </ul>
    </div>
  </details>
</template>

<style scoped>
.related-notes { padding: var(--space-xs) var(--space-lg); border-top: var(--rule-hair); max-height: 280px; overflow: auto; }
.related-content { display: grid; gap: var(--space-sm); padding-bottom: var(--space-sm); }
.toolbar .hint { flex: 1; min-width: 140px; margin: 0; }
ul { display: grid; gap: var(--space-sm); list-style: none; padding: 0; margin: 0; }
li { padding: var(--space-sm) var(--space-md); min-width: 0; }
small { display: block; overflow-wrap: anywhere; }
.link-button { max-width: 100%; }
.snippet { white-space: pre-wrap; margin: var(--space-xs) 0 0; font-size: var(--text-xs); color: var(--color-ink-1); }
</style>
