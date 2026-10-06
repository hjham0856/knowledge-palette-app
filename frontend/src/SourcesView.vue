<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api, SourceStatus } from "./api";

const sources = ref<SourceStatus[]>([]);
const dbAvailable = ref(true);
const message = ref("");
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
    message.value = `목록을 불러오지 못했습니다: ${e.message}`;
  }
}

async function action(fn: () => Promise<any>) {
  if (busy.value) return;
  busy.value = true;
  message.value = "";
  failures.value = [];
  try {
    const r = await fn();
    const errors: any[] = r.errors ?? [];
    failures.value = errors;
    message.value = `인덱싱 ${(r.indexed ?? []).length}건, 변경 없음 ${(r.unchanged ?? []).length}건, 실패 ${errors.length}건, 삭제됨 ${(r.deleted ?? []).length}건`;
    await refresh();
  } catch (e: any) {
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
  <section class="sources-view">
    <h2>Sources</h2>
    <p v-if="!dbAvailable" class="error">
      PostgreSQL/pgvector가 꺼져 있습니다. `docker compose -f docker/docker-compose.yml up -d`로 기동한 뒤 다시 시도하세요.
      이 상태에서도 Notes 편집은 가능하며, 인덱싱/검색만 "준비 필요"로 동작합니다.
    </p>
    <div class="actions">
      <button :disabled="busy" @click="action(() => api.rescanSources())">변경분 스캔/인덱싱</button>
      <button :disabled="busy" @click="action(() => api.reindexSources(true))">전체 재구축</button>
      <button :disabled="busy" @click="refresh()">새로고침</button>
    </div>
    <p v-if="message" class="msg">{{ message }}</p>
    <ul v-if="failures.length" class="failures">
      <li v-for="f in failures" :key="f.path">{{ f.path }}: {{ f.error }}</li>
    </ul>
    <table>
      <thead><tr><th>경로</th><th>상태</th><th>오류</th></tr></thead>
      <tbody>
        <tr v-for="s in sources" :key="s.path">
          <td>{{ s.path }}</td>
          <td>{{ STATUS_LABEL[s.status] ?? s.status }}</td>
          <td class="error">{{ s.error }}</td>
        </tr>
      </tbody>
    </table>
    <p v-if="!sources.length" class="empty">sources/ 아래에 PDF/Markdown 파일이 없습니다.</p>
  </section>
</template>

<style scoped>
.sources-view { padding: 16px; overflow: auto; }
.actions { display: flex; gap: 8px; margin-bottom: 12px; }
table { border-collapse: collapse; width: 100%; }
td, th { border: 1px solid #ddd; padding: 6px 10px; text-align: left; }
.error { color: #b91c1c; }
.msg { color: #555; }
.failures { color: #b91c1c; font-size: 13px; }
.empty { color: #999; }
</style>
