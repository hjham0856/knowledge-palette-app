<script setup lang="ts">
import { computed, ref } from "vue";
import { api, SearchHit } from "./api";

const emit = defineEmits<{ (e: "open-note", path: string): void }>();

const q = ref("");
const noteResults = ref<SearchHit[]>([]);
const sourceResults = ref<SearchHit[]>([]);
const error = ref("");
const busy = ref(false);
const searched = ref(false);

const staleCount = computed(
  () => [...noteResults.value, ...sourceResults.value].filter((r) => r.status !== "indexed").length
);

async function run() {
  if (busy.value || !q.value.trim()) return;
  busy.value = true;
  error.value = "";
  try {
    const [n, s] = await Promise.all([api.searchNotes(q.value), api.searchSources(q.value)]);
    noteResults.value = n.results;
    sourceResults.value = s.results;
    searched.value = true;
  } catch (e: any) {
    error.value = e.message;
    noteResults.value = [];
    sourceResults.value = [];
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section class="search-view card">
    <h2>Search</h2>
    <div class="bar toolbar">
      <input aria-label="검색어 또는 질문" :aria-invalid="!!error" v-model="q" placeholder="검색어 또는 질문" :disabled="busy" @keyup.enter="run" />
      <button class="btn--primary" :disabled="busy || !q.trim()" :aria-busy="busy" @click="run">{{ busy ? "검색 중…" : "검색" }}</button>
    </div>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="staleCount > 0" class="notice">
      편집/수정 후 아직 재인덱싱되지 않은 문서가 {{ staleCount }}건 있습니다. 최신 내용은 Sources 탭에서 스캔/인덱싱 후 검색됩니다.
    </p>
    <p v-if="searched && staleCount === 0" class="hint">
      노트를 편집하거나 원본 파일을 바꿨다면 Sources 탭에서 재인덱싱해야 검색에 반영됩니다.
    </p>
    <p v-if="!searched && !busy && !error" class="empty-state">검색어를 입력하면 Notes와 Sources에서 관련 내용을 찾습니다.</p>
    <div class="cols">
      <div>
        <h3>Notes</h3>
        <div v-for="r in noteResults" :key="r.path + r.rank" class="hit">
          <button class="link-button" :title="r.path" @click="emit('open-note', r.path.replace(/^notes\//, ''))">{{ r.path }}</button>
          <span class="status-chip" :data-state="r.status">{{ r.status === 'indexed' ? '인덱싱됨' : r.status === 'error' ? '오류 · 재인덱싱 필요' : r.status === 'stale' ? '수정됨 · 재인덱싱 필요' : '미인덱싱' }}</span>
          <p>{{ r.content.slice(0, 160) }}</p>
        </div>
        <p v-if="searched && !noteResults.length" class="empty">결과 없음</p>
      </div>
      <div>
        <h3>Sources</h3>
        <div v-for="r in sourceResults" :key="r.path + r.rank" class="hit">
          <b>{{ r.path }}</b> <span v-if="r.pages" class="page badge">p.{{ r.pages }}</span>
          <span class="status-chip" :data-state="r.status">{{ r.status === 'indexed' ? '인덱싱됨' : r.status === 'error' ? '오류 · 재인덱싱 필요' : r.status === 'stale' ? '수정됨 · 재인덱싱 필요' : '미인덱싱' }}</span>
          <p>{{ r.content.slice(0, 160) }}</p>
        </div>
        <p v-if="searched && !sourceResults.length" class="empty">결과 없음</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.search-view { flex: 1; min-width: 0; padding: var(--space-lg) var(--space-xl); overflow: auto; }
h2 { margin: 0 0 var(--space-lg); }
.bar { margin-bottom: var(--space-lg); }
.bar input { flex: 1; }
.cols { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: var(--space-xl); }
.cols > div { min-width: 0; }
h3 { padding-bottom: var(--space-md); border-bottom: var(--rule-hair); }
.hit { border-bottom: var(--rule-hair); padding: var(--space-md) 0; overflow-wrap: anywhere; }
.hit .link-button { max-width: 100%; font-weight: 600; }
.hit .status-chip { margin: var(--space-xs) 0; }
.hit p { margin: var(--space-xs) 0; color: var(--color-ink-1); white-space: pre-wrap; }
.page { margin-left: var(--space-xs); }
@media (max-width: 768px) { .search-view { padding: var(--space-md); } .cols { grid-template-columns: minmax(0, 1fr); gap: var(--space-md); } }
</style>
