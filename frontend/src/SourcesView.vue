<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api, SourceStatus } from "./api";

const sources = ref<SourceStatus[]>([]);
const dbAvailable = ref(true);
const message = ref("");
const messageError = ref(false);
const failures = ref<{ path: string; error: string }[]>([]);
const busy = ref(false);

const STATUS_LABEL: Record<string, string> = {
  indexed: "인덱싱됨",
  stale: "수정됨 (재인덱싱 필요)",
  error: "오류",
  "not-indexed": "미인덱싱",
};

async function refresh() {
  try {
    const r = await api.listSources();
    sources.value = r.sources;
    dbAvailable.value = r.db_available;
  } catch (e: any) {
    messageError.value = true;
    message.value = `목록을 불러오지 못했습니다: ${e.message}`;
  }
}

async function action(fn: () => Promise<any>) {
  if (busy.value) return;
  busy.value = true;
  message.value = "";
  messageError.value = false;
  failures.value = [];
  try {
    const r = await fn();
    const errors: any[] = r.errors ?? [];
    failures.value = errors;
    messageError.value = errors.length > 0;
    message.value = `인덱싱 ${(r.indexed ?? []).length}건, 변경 없음 ${(r.unchanged ?? []).length}건, 실패 ${errors.length}건, 삭제됨 ${(r.deleted ?? []).length}건`;
    await refresh();
  } catch (e: any) {
    messageError.value = true;
    message.value = e.message;
  } finally {
    busy.value = false;
  }
}

onMounted(() => {
  refresh();
});
</script>

<template>
  <section class="sources-view card">
    <h2>Sources</h2>
    <p v-if="!dbAvailable" class="error">
      PostgreSQL/pgvector가 꺼져 있습니다. `docker compose -f docker/docker-compose.yml up -d`로 기동한 뒤 다시 시도하세요.
      이 상태에서도 Notes 편집은 가능하며, 인덱싱/검색만 "준비 필요"로 동작합니다.
    </p>
    <div class="actions toolbar">
      <button class="btn--primary" :disabled="busy" :aria-busy="busy" @click="action(() => api.rescanSources())">변경분 스캔/인덱싱</button>
      <button :disabled="busy" @click="action(() => api.reindexSources(true))">전체 재구축</button>
      <button :disabled="busy" @click="refresh()">새로고침</button>
    </div>
    <p v-if="busy" class="status-chip" data-state="loading" role="status">인덱싱 중…</p>
    <p v-if="message" class="banner" :class="{ 'banner--error': messageError }" :role="messageError ? 'alert' : 'status'">{{ message }}</p>
    <ul v-if="failures.length" class="failures error" role="alert">
      <li v-for="f in failures" :key="f.path">{{ f.path }}: {{ f.error }}</li>
    </ul>
    <table>
      <thead><tr><th>경로</th><th>상태</th><th>오류</th></tr></thead>
      <tbody>
        <tr v-for="s in sources" :key="s.path">
          <td data-label="경로">{{ s.path }}</td>
          <td data-label="상태"><span class="status-chip" :data-state="s.status">{{ STATUS_LABEL[s.status] ?? s.status }}</span></td>
          <td class="source-error" data-label="오류">{{ s.error || "—" }}</td>
        </tr>
      </tbody>
    </table>
    <p v-if="!sources.length" class="empty">sources/ 아래에 PDF/Markdown 파일이 없습니다.</p>
  </section>
</template>

<style scoped>
.sources-view { flex: 1; min-width: 0; padding: var(--space-lg) var(--space-xl); overflow: auto; }
h2 { margin: 0 0 var(--space-lg); }
.actions { margin-bottom: var(--space-lg); }
table { border-collapse: collapse; width: 100%; table-layout: fixed; font-variant-numeric: tabular-nums; }
th { color: var(--color-ink-2); font-size: var(--text-xs); font-weight: 500; }
td, th { border-bottom: var(--rule-hair); padding: var(--space-md); text-align: left; overflow-wrap: anywhere; }
th:first-child { width: 45%; }
td:first-child { font-family: var(--font-mono); font-size: var(--text-xs); }
.source-error { color: var(--color-error); }
.failures { list-style-position: inside; font-size: var(--text-xs); }
@media (max-width: 768px) {
  .sources-view { padding: var(--space-md); }
  thead { display: none; }
  table, tbody, tr, td { display: block; width: 100%; }
  tr { margin-bottom: var(--space-md); border: var(--rule-hair); border-radius: var(--radius-md); padding: var(--space-xs); }
  td { border: 0; padding: var(--space-xs); }
  td::before { content: attr(data-label); display: block; color: var(--color-ink-2); font-family: var(--font-body); font-size: var(--text-xs); margin-bottom: var(--space-2xs); }
}
</style>
