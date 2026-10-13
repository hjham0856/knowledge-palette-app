<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { diffLines } from "diff";
import { api, type UpdateSummary, type UpdateDetail } from "./api";

const props = defineProps<{ request: { id: number; nonce: number } | null; busy: boolean }>();
const emit = defineEmits<{ (e: "open-note", path: string): void; (e: "undo", id: number): void }>();
const updates = ref<UpdateSummary[]>([]);
const selectedId = ref<number | null>(null);
const detail = ref<UpdateDetail | null>(null);
const loading = ref(false);
const detailLoading = ref(false);
const listError = ref("");
const detailError = ref("");
let selection = 0;

function state(status: UpdateSummary["status"]) {
  return { applied: "success", failed: "error", undone: "interrupted", running: "loading" }[status];
}
function timestamp(value: string) {
  return new Date(value).toLocaleString("ko-KR");
}

async function select(id: number) {
  const seq = ++selection;
  selectedId.value = id;
  detail.value = null;
  detailError.value = "";
  detailLoading.value = true;
  try {
    const result = await api.updateDetail(id);
    if (seq === selection) detail.value = result;
  } catch (e: any) {
    if (seq === selection) detailError.value = e.message;
  } finally {
    if (seq === selection) detailLoading.value = false;
  }
}

async function refresh() {
  loading.value = true;
  listError.value = "";
  try {
    updates.value = (await api.updateHistory()).updates.sort((a, b) => b.id - a.id);
    if (selectedId.value !== null) await select(selectedId.value);
  } catch (e: any) {
    listError.value = e.message;
  } finally {
    loading.value = false;
  }
}

watch(() => props.request, (request) => { if (request) select(request.id); }, { immediate: true });
refresh();
defineExpose({ refresh });

type Line = { before: number | null; after: number | null; text: string; sign: string; kind: string; noNewline: boolean };
const diffs = computed(() => detail.value?.changes.map(change => {
  let before = 1, after = 1;
  const parts = diffLines(change.before ?? "", change.after).map(part => {
    const lines = part.value.match(/[^\n]*\n|[^\n]+$/g) ?? [];
    return {
      unchanged: !part.added && !part.removed,
      lines: lines.map(text => ({
        before: part.added ? null : before++, after: part.removed ? null : after++,
        sign: part.added ? "+" : part.removed ? "-" : " ",
        kind: part.added ? "added" : part.removed ? "removed" : "unchanged",
        noNewline: !text.endsWith("\n"), text: text.replace(/\r?\n$/, ""),
      } satisfies Line)),
    };
  });
  // 변경 전후의 문맥 3줄은 남겨 긴 원문에서도 변경 위치를 파악할 수 있게 한다.
  const blocks = parts.flatMap((part, index) => {
    if (!part.unchanged || part.lines.length <= 8) return [{ lines: part.lines, folded: false }];
    const head = index > 0 ? 3 : 0;
    const tail = index < parts.length - 1 ? 3 : 0;
    return [
      { lines: part.lines.slice(0, head), folded: false },
      { lines: part.lines.slice(head, part.lines.length - tail), folded: true },
      { lines: tail ? part.lines.slice(-tail) : [], folded: false },
    ].filter(block => block.lines.length);
  });
  return { change, blocks };
}) ?? []);
</script>

<template>
  <section class="history-view card" aria-label="Knowledge Update History">
    <header class="toolbar">
      <h2>History</h2>
      <button :disabled="busy || loading || detailLoading" @click="refresh">새로고침</button>
      <span v-if="loading" class="status-chip" data-state="loading" role="status">목록 조회 중…</span>
    </header>
    <p v-if="listError" class="error" role="alert">History 조회 실패: {{ listError }}</p>
    <div class="history-layout">
      <aside class="update-list" aria-label="최신순 지식 변경 목록">
        <p v-if="!updates.length && !loading && !listError" class="empty-state">아직 지식 변경 기록이 없습니다.</p>
        <button v-for="update in updates" :key="update.id" class="list-button update" :aria-pressed="selectedId === update.id" :disabled="busy" @click="select(update.id)">
          <time :datetime="update.created_at">{{ timestamp(update.created_at) }}</time>
          <b>{{ update.conversation_title || '새 대화' }} · #{{ update.id }}</b>
          <span>+ 새 Note {{ update.counts.CREATE }} · ~ 보강 {{ update.counts.UPDATE }} · ↔ 링크 {{ update.counts.LINK }}</span>
          <span class="status-chip" :data-state="state(update.status)">{{ update.status }}</span>
          <span v-if="update.error" class="error">{{ update.error }}</span>
        </button>
      </aside>
      <section class="update-detail" aria-label="변경 상세" :aria-busy="detailLoading">
        <p v-if="detailLoading" class="muted" role="status">변경 내용 조회 중…</p>
        <p v-else-if="detailError" class="error" role="alert">변경 조회 실패: {{ detailError }} <button :disabled="busy" @click="select(selectedId!)">다시 조회</button></p>
        <template v-else-if="detail">
          <div class="toolbar">
            <h3>{{ detail.conversation_title || '새 대화' }} · #{{ detail.id }}</h3>
            <span class="status-chip" :data-state="state(detail.status)">{{ detail.status }}</span>
            <button v-if="detail.status === 'applied'" :disabled="busy" @click="emit('undo', detail.id)">Undo</button>
          </div>
          <p class="muted">{{ timestamp(detail.created_at) }}<span v-if="detail.undone_at"> · 되돌림 {{ timestamp(detail.undone_at) }}</span></p>
          <p v-if="detail.error" class="error" role="alert">{{ detail.error }}</p>
          <p class="muted">before → after · − 삭제 / + 추가 · 왼쪽은 이전 줄 번호, 오른쪽은 이후 줄 번호</p>
          <article v-for="{ change, blocks } in diffs" :key="change.id" class="change card">
            <div class="toolbar">
              <span class="badge">{{ change.op }}</span>
              <button class="link-button note-path" :disabled="busy" @click="emit('open-note', change.path.replace(/^notes\//, ''))">{{ change.path }}</button>
            </div>
            <p v-if="change.before === null" class="muted">새 Note · 이전 파일 없음</p>
            <div class="diff" :aria-label="`${change.path} 줄 단위 변경`">
              <template v-for="(block, index) in blocks" :key="index">
                <details v-if="block.folded">
                  <summary>변경 없는 {{ block.lines.length }}줄 펼치기</summary>
                  <div v-for="(line, i) in block.lines" :key="i" class="diff-line unchanged">
                    <span class="line-number">{{ line.before }}</span><span class="line-number">{{ line.after }}</span><span>{{ line.sign }}</span><span class="line-text">{{ line.text }}<small v-if="line.noNewline"> (끝 줄바꿈 없음)</small></span>
                  </div>
                </details>
                <template v-else>
                  <div v-for="(line, i) in block.lines" :key="i" class="diff-line" :class="line.kind">
                    <span class="line-number">{{ line.before }}</span><span class="line-number">{{ line.after }}</span><span>{{ line.sign }}</span><span class="line-text">{{ line.text }}<small v-if="line.noNewline"> (끝 줄바꿈 없음)</small></span>
                  </div>
                </template>
              </template>
            </div>
          </article>
          <p v-if="!detail.changes.length" class="empty-state">파일 변경이 없습니다.</p>
          <details v-if="detail.decisions.length" class="decisions">
            <summary>결정과 이유 · NONE {{ detail.counts.NONE }}건</summary>
            <article v-for="(decision, index) in detail.decisions" :key="index" class="decision card">
              <span class="badge">{{ decision.action }}</span>
              <b>{{ decision.candidate.title }}</b>
              <p class="muted">{{ decision.candidate.kind }}<span v-if="decision.path"> · {{ decision.path }}</span></p>
              <p>{{ decision.reason }}</p>
              <details><summary>후보 내용</summary><p class="candidate">{{ decision.candidate.content }}</p></details>
              <p v-if="decision.dropped_links.length" class="notice">제외된 링크: {{ decision.dropped_links.join(', ') }}</p>
            </article>
          </details>
        </template>
        <p v-else class="empty-state">기록을 선택해 변경 내용을 확인하세요.</p>
      </section>
    </div>
  </section>
</template>

<style scoped>
.history-view { display: flex; flex-direction: column; flex: 1; min-width: 0; min-height: 0; overflow: auto; padding: var(--space-md); }
h2, h3 { margin: 0; }
.history-layout { display: grid; grid-template-columns: minmax(0, 300px) minmax(0, 1fr); gap: var(--space-lg); margin-top: var(--space-md); min-height: 0; flex: 1; }
.update-list, .update-detail { min-width: 0; overflow: auto; }
.update { white-space: normal; overflow-wrap: anywhere; margin-bottom: var(--space-xs); }
.update > time, .update > b, .update > span:not(.status-chip) { display: block; margin-bottom: var(--space-xs); }
time { font-size: var(--text-xs); color: var(--color-ink-2); }
.change, .decision { padding: var(--space-sm); margin-top: var(--space-md); }
.note-path { white-space: normal; overflow-wrap: anywhere; }
.diff { margin-top: var(--space-sm); font-family: var(--font-mono); font-size: var(--text-xs); }
.diff-line { display: grid; grid-template-columns: 3ch 3ch 1ch minmax(0, 1fr); gap: var(--space-2xs); padding: var(--space-2xs); }
.line-number { color: var(--color-ink-2); text-align: right; overflow-wrap: anywhere; }
.line-text { white-space: pre-wrap; overflow-wrap: anywhere; }
.added { background: var(--color-success-tint); color: var(--color-success-ink); }
.removed { background: var(--color-error-tint); color: var(--color-error); }
summary { white-space: normal; overflow-wrap: anywhere; }
.decisions { margin-top: var(--space-md); }
.decision b { margin-left: var(--space-xs); overflow-wrap: anywhere; }
.candidate { white-space: pre-wrap; }
@media (max-width: 768px) { .history-layout { display: block; } .update-list { max-height: 260px; border-bottom: var(--rule-soft); margin-bottom: var(--space-md); } .update-detail { overflow: visible; } }
</style>
