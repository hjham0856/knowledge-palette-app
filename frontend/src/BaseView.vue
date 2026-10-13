<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { api, type BaseNote } from "./api";

const props = defineProps<{ navigationBusy: boolean }>();
const emit = defineEmits<{ (e: "open-note", path: string): void }>();
const notes = ref<BaseNote[]>([]);
const busy = ref(false);
const error = ref("");
const filterField = ref("");
const filterOperator = ref("contains");
const filterValue = ref("");
const sortField = ref("");
const descending = ref(false);
const groupField = ref("");
const view = ref("table");
const locked = computed(() => busy.value || props.navigationBusy);
const fields = computed(() => [...new Set(notes.value.flatMap(n => Object.keys(n.frontmatter)))].sort());
const errorCount = computed(() => notes.value.filter(n => n.error).length);

function display(value: unknown): string {
  if (value === undefined || value === null) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function values(note: BaseNote, field: string): unknown[] {
  const value = note.frontmatter[field];
  return Array.isArray(value) ? value : [value];
}

const visible = computed(() => {
  const result = notes.value.filter(note => {
    if (!filterField.value) return true;
    if (filterOperator.value === "exists") return Object.hasOwn(note.frontmatter, filterField.value);
    return values(note, filterField.value).some(value => {
      if (value === undefined || value === null) return false;
      const text = display(value);
      return filterOperator.value === "equals" ? text === filterValue.value : text.toLocaleLowerCase().includes(filterValue.value.toLocaleLowerCase());
    });
  });
  return result.sort((a, b) => {
    if (!sortField.value) return a.path.localeCompare(b.path);
    const av = a.frontmatter[sortField.value];
    const bv = b.frontmatter[sortField.value];
    // 빈 값은 정렬 방향과 관계없이 뒤에 둬 속성이 있는 Note부터 읽을 수 있게 한다.
    if (av == null && bv != null) return 1;
    if (bv == null && av != null) return -1;
    const order = typeof av === "number" && typeof bv === "number" ? av - bv : display(av).localeCompare(display(bv), "ko", { numeric: true });
    return (descending.value ? -order : order) || a.path.localeCompare(b.path);
  });
});

const groups = computed(() => {
  if (!groupField.value) return [{ key: "all", label: "전체 Notes", notes: visible.value }];
  const result = new Map<string, { key: string; label: string; notes: BaseNote[] }>();
  for (const note of visible.value) {
    const items = values(note, groupField.value);
    // 여러 태그를 가진 Note는 각 태그 그룹에서 발견할 수 있다.
    for (const value of items.length ? items : [undefined]) {
      const key = value == null ? "missing" : `${typeof value}:${display(value)}`;
      if (!result.has(key)) result.set(key, { key, label: value == null ? "값 없음" : display(value) || "빈 문자열", notes: [] });
      const group = result.get(key)!;
      if (!group.notes.includes(note)) group.notes.push(note);
    }
  }
  return [...result.values()].sort((a, b) => a.label.localeCompare(b.label, "ko", { numeric: true }));
});

async function load() {
  if (locked.value) return;
  busy.value = true;
  error.value = "";
  try {
    notes.value = (await api.noteFrontmatter()).notes;
    for (const field of [filterField, sortField, groupField]) {
      if (field.value && !fields.value.includes(field.value)) field.value = "";
    }
  } catch (e: any) {
    error.value = e.message;
    notes.value = [];
  } finally {
    busy.value = false;
  }
}

function open(note: BaseNote) {
  if (!locked.value) emit("open-note", note.path);
}

onMounted(load);
</script>

<template>
  <section class="base-view card" :aria-busy="busy">
    <div class="toolbar">
      <h2>Base</h2>
      <span class="badge">{{ visible.length }} / {{ notes.length }} Notes</span>
      <button :disabled="locked" @click="load">{{ busy ? "불러오는 중…" : "새로고침" }}</button>
    </div>
    <p class="hint">frontmatter는 Markdown 맨 위의 YAML 속성입니다. 이 화면에서는 원본을 바꾸지 않고 모아 봅니다.</p>
    <fieldset :disabled="locked" class="controls">
      <legend class="eyebrow">보기 설정</legend>
      <label>필터 필드<select v-model="filterField"><option value="">필터 없음</option><option v-for="field in fields" :key="field" :value="field">{{ field }}</option></select></label>
      <label>조건<select v-model="filterOperator" :disabled="!filterField"><option value="contains">포함</option><option value="equals">같음</option><option value="exists">존재</option></select></label>
      <label>필터 값<input v-model="filterValue" :disabled="!filterField || filterOperator === 'exists'" placeholder="비교할 값" /></label>
      <label>정렬 필드<select v-model="sortField"><option value="">경로 순</option><option v-for="field in fields" :key="field" :value="field">{{ field }}</option></select></label>
      <label>정렬 방향<select v-model="descending" :disabled="!sortField"><option :value="false">오름차순</option><option :value="true">내림차순</option></select></label>
      <label>그룹 필드<select v-model="groupField"><option value="">그룹 없음</option><option v-for="field in fields" :key="field" :value="field">{{ field }}</option></select></label>
      <label>보기<select v-model="view"><option value="table">표</option><option value="list">목록</option></select></label>
    </fieldset>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="errorCount" class="notice" role="status">속성 오류가 있는 Note {{ errorCount }}개가 있습니다. Note를 열어 원문을 확인하세요.</p>
    <p v-if="!busy && !error && !visible.length" class="empty-state">{{ notes.length ? "조건에 맞는 Note가 없습니다." : "아직 Note가 없습니다." }}</p>
    <section v-for="group in groups" :key="group.key" class="group">
      <h3 v-if="groupField">{{ group.label }} <span class="badge">{{ group.notes.length }}</span></h3>
      <div v-if="view === 'table' && group.notes.length" class="table-container" tabindex="0" aria-label="Note 속성 표, 가로로 스크롤할 수 있습니다">
        <table>
          <thead><tr><th>Note</th><th>파일명</th><th v-for="field in fields" :key="field">{{ field }}</th><th>속성 오류</th></tr></thead>
          <tbody><tr v-for="note in group.notes" :key="note.path" :class="{ locked }" @click="open(note)">
            <td><button class="link-button" :disabled="locked" @click.stop="open(note)">{{ note.title }}</button><small>{{ note.path }}</small></td>
            <td>{{ note.name }}</td><td v-for="field in fields" :key="field">{{ display(note.frontmatter[field]) }}</td>
            <td><span v-if="note.error" class="status-chip" data-state="error">{{ note.error }}</span></td>
          </tr></tbody>
        </table>
      </div>
      <ul v-else-if="view === 'list'" class="note-list">
        <li v-for="note in group.notes" :key="note.path">
          <button class="list-button" :disabled="locked" @click="open(note)">
            <strong>{{ note.title }}</strong><small>{{ note.path }} · {{ note.name }}</small>
            <span v-for="field in Object.keys(note.frontmatter)" :key="field" class="property">{{ field }}: {{ display(note.frontmatter[field]) }}</span>
            <span v-if="note.error" class="status-chip" data-state="error">{{ note.error }}</span>
          </button>
        </li>
      </ul>
    </section>
  </section>
</template>

<style scoped>
.base-view { flex: 1; min-width: 0; max-width: 100%; padding: var(--space-lg) var(--space-xl); overflow-y: auto; }
h2 { margin: 0; }
.controls { display: flex; flex-wrap: wrap; gap: var(--space-sm); margin: var(--space-lg) 0; padding: var(--space-md); border: var(--rule-soft); border-radius: var(--radius-md); min-width: 0; }
label { display: flex; flex-direction: column; gap: var(--space-2xs); flex: 1 1 140px; min-width: 0; font-size: var(--text-xs); }
select, input { width: 100%; }
.group { min-width: 0; margin-top: var(--space-lg); }
h3 { font-size: var(--text-md); }
.table-container { width: 100%; min-width: 0; overflow-x: auto; border: var(--rule-hair); border-radius: var(--radius-md); }
table { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }
th, td { padding: var(--space-sm) var(--space-md); text-align: left; border-bottom: var(--rule-hair); min-width: 160px; max-width: 320px; overflow-wrap: anywhere; }
th { background: var(--color-paper-2); white-space: nowrap; }
tbody tr { cursor: pointer; }
tbody tr:hover { background: var(--color-accent-tint); }
tbody tr.locked { cursor: default; }
td .link-button { white-space: normal; overflow-wrap: anywhere; }
small { display: block; color: var(--color-ink-2); font-size: var(--text-xs); white-space: normal; overflow-wrap: anywhere; }
.note-list { list-style: none; padding: 0; margin: 0; }
.note-list li { border-bottom: var(--rule-hair); }
.note-list button { padding: var(--space-md); white-space: normal; overflow-wrap: anywhere; }
.property { display: block; color: var(--color-ink-1); font-size: var(--text-xs); }
.status-chip { white-space: normal; }
@media (max-width: 768px) { .base-view { padding: var(--space-md); } }
</style>
