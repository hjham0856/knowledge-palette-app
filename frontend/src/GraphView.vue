<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { api, type NoteGraph } from "./api";

const props = defineProps<{ path: string | null; busy: boolean }>();
const emit = defineEmits<{
  (e: "open-note", path: string): void;
  (e: "choose-note"): void;
}>();
const graph = ref<NoteGraph | null>(null);
const loading = ref(false);
const error = ref("");
const graphScroll = ref<HTMLDivElement | null>(null);
let request = 0;

async function load() {
  const seq = ++request;
  graph.value = null;
  error.value = "";
  loading.value = !!props.path;
  if (!props.path) return;
  try {
    const result = await api.graph(props.path);
    if (seq === request) {
      graph.value = result;
      loading.value = false;
      await nextTick();
      const viewport = graphScroll.value;
      if (seq === request && viewport) viewport.scrollLeft = (viewport.scrollWidth - viewport.clientWidth) / 2;
    }
  } catch (e: any) {
    if (seq === request) error.value = `그래프를 불러오지 못했습니다: ${e.message}`;
  } finally {
    if (seq === request) loading.value = false;
  }
}
watch(() => props.path, load, { immediate: true });

const labels = { outgoing: "나가는 링크", incoming: "들어오는 링크 (backlink)", both: "양방향 링크" };
// 연결이 많을 때는 원을 넓히고 스크롤을 허용해 노드 간격과 글자 크기를 유지한다.
const radius = computed(() => Math.max(190, ((graph.value?.nodes.length ?? 1) - 1) * 100 / (2 * Math.PI)));
const size = computed(() => radius.value * 2 + 200);
const positions = computed(() => {
  const nodes = graph.value?.nodes ?? [];
  return nodes.map((node, index) => {
    const angle = -Math.PI / 2 + (index - 1) * 2 * Math.PI / Math.max(1, nodes.length - 1);
    return {
      ...node, index,
      x: size.value / 2 + (index ? radius.value * Math.cos(angle) : 0),
      y: size.value / 2 + (index ? radius.value * Math.sin(angle) : 0),
    };
  });
});
const lines = computed(() => (graph.value?.edges ?? []).map((edge) => {
  const source = positions.value.find((node) => node.path === edge.source)!;
  const target = positions.value.find((node) => node.path === edge.target)!;
  const distance = Math.hypot(target.x - source.x, target.y - source.y);
  const dx = (target.x - source.x) / distance;
  const dy = (target.y - source.y) / distance;
  return { ...edge, x1: source.x + dx * 30, y1: source.y + dy * 30, x2: target.x - dx * 34, y2: target.y - dy * 34 };
}));

function navigate(path: string) {
  if (!props.busy && !loading.value) emit("open-note", path);
}
</script>

<template>
  <section class="graph-view card" aria-label="Local Graph" :aria-busy="loading || busy">
    <header class="toolbar">
      <div>
        <span class="eyebrow">Local Graph · 1-hop</span>
        <h2>현재 Note의 연결</h2>
      </div>
      <button :disabled="busy" @click="emit('choose-note')">Notes에서 보기</button>
    </header>
    <div v-if="!path" class="empty-state">
      <p>Notes에서 노트를 선택한 뒤 Graph를 열어 주세요.</p>
      <p>선택한 Note와 직접 연결된 Note를 탐색할 수 있습니다.</p>
    </div>
    <p v-else-if="loading" class="banner" role="status">연결을 불러오는 중…</p>
    <div v-else-if="error" class="error" role="alert">
      <p>{{ error }}</p>
      <button :disabled="busy" @click="load">다시 불러오기</button>
    </div>
    <template v-else-if="graph">
      <p class="center-path">중심 · {{ graph.center }}</p>
      <ul class="legend" aria-label="연결선 범례">
        <li><span class="line-sample outgoing">→</span> 실선 → 나가는 링크</li>
        <li><span class="line-sample incoming">←</span> 점선 ← 들어오는 링크 (backlink)</li>
        <li><span class="line-sample both">↔</span> 굵은 선 ↔ 양방향 링크</li>
      </ul>
      <p class="muted">노드를 누르면 해당 Note를 선택하고 중심을 옮깁니다. 넓은 그래프는 좌우로 스크롤하세요.</p>
      <div ref="graphScroll" class="graph-scroll" tabindex="0" aria-label="연결 그래프 스크롤 영역">
        <svg :viewBox="`0 0 ${size} ${size}`" :style="{ width: `${size}px`, height: `${size}px` }" role="group" aria-label="현재 Note와 직접 연결된 Note">
          <defs>
            <marker id="graph-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" class="arrow" />
            </marker>
          </defs>
          <line v-for="line in lines" :key="`${line.source}:${line.target}`" v-bind="{ x1: line.x1, y1: line.y1, x2: line.x2, y2: line.y2 }" :class="['edge', line.direction]" marker-end="url(#graph-arrow)" :marker-start="line.bidirectional ? 'url(#graph-arrow)' : undefined" />
          <g v-for="node in positions" :key="node.path" :transform="`translate(${node.x}, ${node.y})`" class="node" :class="{ center: node.index === 0 }" role="button" :tabindex="busy ? -1 : 0" :aria-disabled="busy" :aria-label="`${node.path}${node.index === 0 ? ' (현재 중심)' : '로 이동'}`" @click="navigate(node.path)" @keydown.enter.prevent="navigate(node.path)" @keydown.space.prevent="navigate(node.path)">
            <title>{{ node.path }}</title>
            <circle r="28" />
            <text text-anchor="middle" dominant-baseline="central">{{ node.index === 0 ? '중심' : node.index }}</text>
            <text class="node-label" text-anchor="middle" y="48">{{ node.name.length > 12 ? node.name.slice(0, 11) + '…' : node.name }}</text>
          </g>
        </svg>
      </div>
      <p v-if="!graph.edges.length" class="banner">직접 연결된 다른 Note가 없습니다.</p>
      <ul class="connections" aria-label="연결된 Note 목록">
        <li v-for="(edge, index) in graph.edges" :key="index">
          <span class="status-chip">{{ index + 1 }} · {{ labels[edge.direction] }}</span>
          <button class="link-button" :disabled="busy" @click="navigate(edge.source === graph.center ? edge.target : edge.source)">{{ edge.source === graph.center ? edge.target : edge.source }}</button>
        </li>
      </ul>
      <section v-if="graph.unresolved.length" class="unresolved" aria-label="연결되지 않은 wikilink">
        <h3>연결을 확인할 wikilink</h3>
        <p class="muted">대상이 없거나 여러 개여서 그래프의 Note로 연결하지 않았습니다.</p>
        <ul>
          <li v-for="link in graph.unresolved" :key="link.target">
            <span class="status-chip" data-state="stale">{{ link.status === 'missing' ? '대상 없음' : '모호한 대상' }}</span>
            <span>[[{{ link.target }}]]</span>
            <p v-if="link.matches.length" class="muted">후보: {{ link.matches.join(', ') }}</p>
          </li>
        </ul>
      </section>
    </template>
  </section>
</template>

<style scoped>
.graph-view { flex: 1; min-width: 0; min-height: 0; overflow: auto; padding: var(--space-lg); }
.toolbar { justify-content: space-between; }
h2 { margin: var(--space-xs) 0; }
.center-path { font-family: var(--font-mono); overflow-wrap: anywhere; }
.legend { display: flex; flex-wrap: wrap; gap: var(--space-sm) var(--space-lg); list-style: none; padding: 0; }
.legend li { display: flex; align-items: center; gap: var(--space-xs); }
.line-sample { width: 40px; text-align: right; border-bottom: 2px solid var(--color-ink-1); }
.line-sample.incoming { border-bottom-style: dashed; }
.line-sample.both { border-bottom-width: 4px; }
.graph-scroll { overflow: auto; max-height: 640px; border: var(--rule-hair); border-radius: var(--radius-md); background: var(--color-paper-0); }
svg { display: block; margin: auto; font-family: var(--font-body); font-size: 14px; }
.edge { stroke: var(--color-ink-2); stroke-width: 2; }
.edge.incoming { stroke-dasharray: 6 5; }
.edge.both { stroke-width: 4; }
.arrow { fill: var(--color-ink-2); }
.node { cursor: pointer; }
.node[aria-disabled="true"] { cursor: progress; opacity: 0.55; }
.node circle { fill: var(--color-paper-2); stroke: var(--color-ink-2); }
.node.center circle { fill: var(--color-accent-tint); stroke: var(--color-accent); stroke-width: 2; }
.node text { fill: var(--color-ink-0); }
.node:hover circle, .node:focus-visible circle { stroke: var(--color-focus); stroke-width: 3; }
.connections, .unresolved ul { list-style: none; padding: 0; }
.connections li { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-xs); margin: var(--space-sm) 0; }
.connections .link-button { white-space: normal; overflow-wrap: anywhere; }
.unresolved { border-top: var(--rule-hair); margin-top: var(--space-lg); }
.unresolved li { margin: var(--space-md) 0; overflow-wrap: anywhere; }
@media (max-width: 768px) { .graph-view { padding: var(--space-md); } }
</style>
