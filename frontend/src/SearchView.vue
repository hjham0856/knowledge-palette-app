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
  <section class="search-view">
    <h2>Search</h2>
    <div class="bar">
      <input v-model="q" placeholder="검색어 또는 질문" :disabled="busy" @keyup.enter="run" />
      <button :disabled="busy" @click="run">검색</button>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="staleCount > 0" class="notice">
      편집/수정 후 아직 재인덱싱되지 않은 문서가 {{ staleCount }}건 있습니다. 최신 내용은 Sources 탭에서 스캔/인덱싱 후 검색됩니다.
    </p>
    <p v-if="searched && staleCount === 0" class="hint">
      노트를 편집하거나 원본 파일을 바꿨다면 Sources 탭에서 재인덱싱해야 검색에 반영됩니다.
    </p>
    <div class="cols">
      <div>
        <h3>Notes</h3>
        <div v-for="r in noteResults" :key="r.path + r.rank" class="hit">
          <b class="link" @click="emit('open-note', r.path.replace(/^notes\//, ''))">{{ r.path }}</b>
          <span v-if="r.status !== 'indexed'" class="stale">재인덱싱 필요</span>
          <p>{{ r.content.slice(0, 160) }}</p>
        </div>
        <p v-if="searched && !noteResults.length" class="empty">결과 없음</p>
      </div>
      <div>
        <h3>Sources</h3>
        <div v-for="r in sourceResults" :key="r.path + r.rank" class="hit">
          <b>{{ r.path }}</b> <span v-if="r.pages" class="page">p.{{ r.pages }}</span>
          <span v-if="r.status !== 'indexed'" class="stale">재인덱싱 필요</span>
          <p>{{ r.content.slice(0, 160) }}</p>
        </div>
        <p v-if="searched && !sourceResults.length" class="empty">결과 없음</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.search-view { padding: 16px; overflow: auto; }
.bar { display: flex; gap: 8px; margin-bottom: 12px; }
.bar input { flex: 1; padding: 8px; }
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.hit { border-bottom: 1px solid #eee; padding: 6px 0; }
.hit p { margin: 4px 0; color: #444; font-size: 13px; white-space: pre-wrap; }
.link { cursor: pointer; color: #2563eb; }
.page { background: #eef2ff; padding: 0 6px; border-radius: 4px; font-size: 12px; }
.stale { background: #fef3c7; padding: 0 6px; border-radius: 4px; font-size: 12px; color: #92400e; margin-left: 6px; }
.error { color: #b91c1c; }
.notice { color: #92400e; }
.hint { color: #888; font-size: 12px; }
.empty { color: #999; }
</style>
