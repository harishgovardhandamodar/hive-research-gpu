<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useAppStore } from '../stores/app.js'
import { useGraphStore } from '../stores/graph.js'
import { getOverlaps, getMetagraph, readFile, getDigests } from '../api.js'

const app = useAppStore()
const graph = useGraphStore()

const activeTab = ref('overlaps')
const overlapsData = ref(null)
const metagraphData = ref(null)
const overlapsLoading = ref(false)
const metagraphLoading = ref(false)
const overlapsFilter = ref('')
const overlapsViewMode = ref('list')
const showLabels = ref(true)

const overlapSubView = ref('list')
const graphContainer = ref(null)
const metaGraphContainer = ref(null)
const tooltip = ref({ visible: false, x: 0, y: 0, text: '' })

const previewVisible = ref(false)
const previewLoading = ref(false)
const previewPaper = ref(null)
const previewDigests = ref(null)

const hiveColors = [
  '#60a5fa', '#34d399', '#c084fc', '#fb923c', '#f87171',
  '#22d3ee', '#fbbf24', '#818cf8', '#e879f9', '#2dd4bf'
]

const relationColors = {
  shared_topic: '#60a5fa',
  shared_concept: '#c084fc',
  shared_theory: '#34d399',
  cross_relation: '#fb923c'
}

const filteredTopics = computed(() => {
  if (!overlapsData.value?.topics) return []
  const q = overlapsFilter.value.toLowerCase()
  if (!q) return overlapsData.value.topics
  return overlapsData.value.topics.filter(t =>
    (t.name || '').toLowerCase().includes(q) ||
    (t.papers || []).some(p => (p.title || p.id || '').toLowerCase().includes(q))
  )
})

const filteredConcepts = computed(() => {
  if (!overlapsData.value?.concepts) return []
  const q = overlapsFilter.value.toLowerCase()
  if (!q) return overlapsData.value.concepts
  return overlapsData.value.concepts.filter(c =>
    (c.name || '').toLowerCase().includes(q) ||
    (c.papers || []).some(p => (p.title || p.id || '').toLowerCase().includes(q))
  )
})

const filteredRelations = computed(() => {
  if (!overlapsData.value?.cross_relations) return []
  const q = overlapsFilter.value.toLowerCase()
  if (!q) return overlapsData.value.cross_relations
  return overlapsData.value.cross_relations.filter(r =>
    (r.source || '').toLowerCase().includes(q) ||
    (r.target || '').toLowerCase().includes(q) ||
    (r.relation || '').toLowerCase().includes(q)
  )
})

const overlapsSummary = computed(() => {
  if (!overlapsData.value) return ''
  const t = overlapsData.value.topics?.length || 0
  const c = overlapsData.value.concepts?.length || 0
  const r = overlapsData.value.cross_relations?.length || 0
  return `${t} shared topics, ${c} shared concepts, ${r} cross relations`
})

const metagraphSummary = computed(() => {
  if (!metagraphData.value) return ''
  const h = metagraphData.value.hives?.length || 0
  const n = metagraphData.value.nodes?.length || 0
  const e = metagraphData.value.edges?.length || 0
  return `${h} hives, ${n} papers, ${e} relations`
})

function hiveColor(index) {
  return hiveColors[index % hiveColors.length]
}

function relationColor(type) {
  return relationColors[type] || 'var(--text3)'
}

async function refreshOverlaps() {
  overlapsLoading.value = true
  try {
    overlapsData.value = await getOverlaps()
  } catch (e) {
    console.error('Failed to fetch overlaps:', e)
    app.addLog(`Overlaps fetch failed: ${e.message}`, 'ERROR')
  } finally {
    overlapsLoading.value = false
  }
}

async function refreshMetagraph() {
  metagraphLoading.value = true
  try {
    metagraphData.value = await getMetagraph()
    await nextTick()
    renderMetagraph()
  } catch (e) {
    console.error('Failed to fetch metagraph:', e)
    app.addLog(`Metagraph fetch failed: ${e.message}`, 'ERROR')
  } finally {
    metagraphLoading.value = false
  }
}

async function renderOverlapsGraph() {
  await nextTick()
  const container = graphContainer.value
  if (!container || !overlapsData.value) return

  container.innerHTML = ''

  const nodes = []
  const links = []
  const seen = new Set()

  for (const c of (overlapsData.value.concepts || [])) {
    const cid = 'c:' + c.name
    if (!seen.has(cid)) {
      seen.add(cid)
      nodes.push({ id: cid, type: 'concept', name: c.name, papers: c.papers })
    }
    for (const p of (c.papers || [])) {
      const pid = 'p:' + (p.id || p.arxiv_id)
      if (!seen.has(pid)) {
        seen.add(pid)
        nodes.push({ id: pid, type: 'paper', name: p.title || p.id, data: p })
      }
      links.push({ source: cid, target: pid })
    }
  }

  for (const t of (overlapsData.value.topics || [])) {
    const tid = 't:' + t.name
    if (!seen.has(tid)) {
      seen.add(tid)
      nodes.push({ id: tid, type: 'topic', name: t.name, papers: t.papers })
    }
    for (const p of (t.papers || [])) {
      const pid = 'p:' + (p.id || p.arxiv_id)
      if (!seen.has(pid)) {
        seen.add(pid)
        nodes.push({ id: pid, type: 'paper', name: p.title || p.id, data: p })
      }
      links.push({ source: tid, target: pid })
    }
  }

  if (nodes.length === 0) return

  const width = container.clientWidth
  const height = container.clientHeight

  const svg = d3.select(container)
    .append('svg')
    .attr('width', width)
    .attr('height', height)

  const g = svg.append('g')

  const zoom = d3.zoom().scaleExtent([0.2, 5]).on('zoom', (e) => g.attr('transform', e.transform))
  svg.call(zoom)

  const sim = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).id(d => d.id).distance(60))
    .force('charge', d3.forceManyBody().strength(-120))
    .force('center', d3.forceCenter(width / 2, height / 2))

  const link = g.append('g')
    .selectAll('line')
    .data(links)
    .join('line')
    .attr('stroke', 'var(--border)')
    .attr('stroke-width', 1)
    .attr('stroke-opacity', 0.5)

  const node = g.append('g')
    .selectAll('circle')
    .data(nodes)
    .join('circle')
    .attr('r', d => d.type === 'paper' ? 7 : 5)
    .attr('fill', d => {
      if (d.type === 'concept') return 'var(--purple)'
      if (d.type === 'topic') return 'var(--accent)'
      return 'var(--green)'
    })
    .attr('stroke', 'var(--bg)')
    .attr('stroke-width', 1.5)
    .style('cursor', 'pointer')
    .on('mouseover', (e, d) => {
      tooltip.value = {
        visible: true,
        x: e.pageX,
        y: e.pageY,
        text: d.name || d.id
      }
    })
    .on('mouseout', () => {
      tooltip.value.visible = false
    })
    .on('click', (e, d) => {
      if (d.type === 'paper' && d.data) openPreview(d.data)
    })
    .call(d3.drag()
      .on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y })
      .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y })
      .on('end', (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null }))

  sim.on('tick', () => {
    link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x).attr('y2', d => d.target.y)
    node.attr('cx', d => d.x).attr('cy', d => d.y)
  })
}

function renderMetagraph() {
  const container = metaGraphContainer.value
  if (!container || !metagraphData.value) return

  container.innerHTML = ''

  const mNodes = metagraphData.value.nodes || []
  const mEdges = metagraphData.value.edges || []
  const hives = metagraphData.value.hives || []

  if (mNodes.length === 0) return

  const width = container.clientWidth
  const height = container.clientHeight

  const svg = d3.select(container)
    .append('svg')
    .attr('width', width)
    .attr('height', height)

  const defs = svg.append('defs')
  for (let i = 0; i < hives.length; i++) {
    const grad = defs.append('radialGradient').attr('id', `hive-grad-${i}`)
    grad.append('stop').attr('offset', '0%').attr('stop-color', hiveColor(i)).attr('stop-opacity', 1)
    grad.append('stop').attr('offset', '100%').attr('stop-color', hiveColor(i)).attr('stop-opacity', 0.5)
  }

  const g = svg.append('g')
  const zoom = d3.zoom().scaleExtent([0.15, 5]).on('zoom', (e) => g.attr('transform', e.transform))
  svg.call(zoom)

  const sim = d3.forceSimulation(mNodes)
    .force('link', d3.forceLink(mEdges).id(d => d.id).distance(80))
    .force('charge', d3.forceManyBody().strength(-200))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collision', d3.forceCollide(12))

  const link = g.append('g')
    .selectAll('line')
    .data(mEdges)
    .join('line')
    .attr('stroke', d => relationColor(d.relation || d.type))
    .attr('stroke-width', 1.5)
    .attr('stroke-opacity', 0.6)

  const node = g.append('g')
    .selectAll('circle')
    .data(mNodes)
    .join('circle')
    .attr('r', 8)
    .attr('fill', d => {
      const hi = d.hive_index ?? d.hive ?? 0
      return hiveColor(hi)
    })
    .attr('stroke', 'var(--bg)')
    .attr('stroke-width', 2)
    .style('cursor', 'pointer')
    .on('mouseover', (e, d) => {
      tooltip.value = {
        visible: true,
        x: e.pageX,
        y: e.pageY,
        text: d.title || d.name || d.id
      }
    })
    .on('mouseout', () => {
      tooltip.value.visible = false
    })
    .on('click', (e, d) => {
      openPreview(d)
    })
    .call(d3.drag()
      .on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y })
      .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y })
      .on('end', (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null }))

  if (showLabels.value) {
    const labels = g.append('g')
      .selectAll('text')
      .data(mNodes)
      .join('text')
      .text(d => {
        const t = d.title || d.name || d.id || ''
        return t.length > 20 ? t.slice(0, 18) + '...' : t
      })
      .attr('font-size', 9)
      .attr('fill', 'var(--text2)')
      .attr('dx', 12)
      .attr('dy', 3)
      .style('pointer-events', 'none')

    sim.on('tick', () => {
      link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x).attr('y2', d => d.target.y)
      node.attr('cx', d => d.x).attr('cy', d => d.y)
      labels.attr('x', d => d.x).attr('y', d => d.y)
    })
  } else {
    sim.on('tick', () => {
      link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x).attr('y2', d => d.target.y)
      node.attr('cx', d => d.x).attr('cy', d => d.y)
    })
  }
}

async function openPreview(paper) {
  previewPaper.value = paper
  previewVisible.value = true
  previewDigests.value = null
  previewLoading.value = true
  try {
    const id = paper.id || paper.arxiv_id
    const data = await getDigests(id)
    previewDigests.value = data
  } catch (e) {
    console.error('Failed to load digests:', e)
  } finally {
    previewLoading.value = false
  }
}

function closePreview() {
  previewVisible.value = false
  previewPaper.value = null
  previewDigests.value = null
}

watch(overlapsViewMode, (val) => {
  if (val === 'graph') {
    nextTick(() => renderOverlapsGraph())
  }
})

watch(showLabels, () => {
  if (activeTab.value === 'metagraph' && metagraphData.value) {
    renderMetagraph()
  }
})

watch(activeTab, (val) => {
  if (val === 'overlaps' && !overlapsData.value) refreshOverlaps()
  if (val === 'metagraph' && !metagraphData.value) refreshMetagraph()
})

onMounted(() => {
  refreshOverlaps()
})

onBeforeUnmount(() => {
  tooltip.value.visible = false
})
</script>

<template>
  <div class="analytics-panel">
    <div class="tab-bar">
      <button
        :class="['tab-btn', { active: activeTab === 'overlaps' }]"
        @click="activeTab = 'overlaps'"
      >Overlaps</button>
      <button
        :class="['tab-btn', { active: activeTab === 'metagraph' }]"
        @click="activeTab = 'metagraph'"
      >Metagraph</button>
    </div>

    <!-- Overlaps Tab -->
    <div v-if="activeTab === 'overlaps'" class="tab-content">
      <div class="controls-row">
        <button class="btn btn-sm btn-outline" @click="refreshOverlaps" :disabled="overlapsLoading">
          {{ overlapsLoading ? 'Loading...' : '↻ Refresh' }}
        </button>
        <input v-model="overlapsFilter" type="text" placeholder="Filter..." class="filter-input" />
      </div>
      <div v-if="overlapsSummary" class="summary-text">{{ overlapsSummary }}</div>

      <div class="view-toggle">
        <button
          :class="['toggle-btn', { active: overlapsViewMode === 'list' }]"
          @click="overlapsViewMode = 'list'"
        >List</button>
        <button
          :class="['toggle-btn', { active: overlapsViewMode === 'graph' }]"
          @click="overlapsViewMode = 'graph'"
        >Graph</button>
      </div>

      <div v-if="overlapsViewMode === 'list'" class="overlaps-list">
        <div class="card">
          <div class="card-header">Shared Topics ({{ filteredTopics.length }})</div>
          <div v-if="!filteredTopics.length" class="empty-state">No shared topics found.</div>
          <div v-for="(topic, i) in filteredTopics" :key="'topic-'+i" class="overlap-item">
            <div class="overlap-name">{{ topic.name }}</div>
            <div class="overlap-papers">
              <span v-for="p in (topic.papers || [])" :key="p.id" class="mini-tag">{{ p.title || p.id }}</span>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-header">Shared Concepts ({{ filteredConcepts.length }})</div>
          <div v-if="!filteredConcepts.length" class="empty-state">No shared concepts found.</div>
          <div v-for="(concept, i) in filteredConcepts" :key="'concept-'+i" class="overlap-item">
            <div class="overlap-name">{{ concept.name }}</div>
            <div class="overlap-papers">
              <span v-for="p in (concept.papers || [])" :key="p.id" class="mini-tag">{{ p.title || p.id }}</span>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-header">Cross Relations ({{ filteredRelations.length }})</div>
          <div v-if="!filteredRelations.length" class="empty-state">No cross relations found.</div>
          <div v-for="(rel, i) in filteredRelations" :key="'rel-'+i" class="overlap-item rel-item">
            <span class="rel-source">{{ rel.source }}</span>
            <span class="rel-arrow">→</span>
            <span class="rel-target">{{ rel.target }}</span>
            <span class="rel-type">{{ rel.relation }}</span>
          </div>
        </div>
      </div>

      <div v-if="overlapsViewMode === 'graph'" class="overlaps-graph-wrap">
        <div ref="graphContainer" class="d3-container"></div>
      </div>
    </div>

    <!-- Metagraph Tab -->
    <div v-if="activeTab === 'metagraph'" class="tab-content">
      <div class="controls-row">
        <button class="btn btn-sm btn-outline" @click="refreshMetagraph" :disabled="metagraphLoading">
          {{ metagraphLoading ? 'Loading...' : '↻ Refresh' }}
        </button>
        <label class="checkbox-label">
          <input type="checkbox" v-model="showLabels" /> Labels
        </label>
      </div>
      <div v-if="metagraphSummary" class="summary-text">{{ metagraphSummary }}</div>

      <div v-if="metagraphData && metagraphData.nodes?.length" class="metagraph-area">
        <div ref="metaGraphContainer" class="d3-container"></div>
        <div class="metagraph-legend">
          <div class="legend-section">
            <span class="legend-heading">Hives</span>
            <span v-for="(h, i) in (metagraphData.hives || [])" :key="'h'+i" class="legend-item">
              <span class="legend-dot" :style="{ background: hiveColor(i) }"></span>
              {{ h.name || h.id || `Hive ${i+1}` }}
            </span>
          </div>
          <div class="legend-section">
            <span class="legend-heading">Relations</span>
            <span class="legend-item">
              <span class="legend-dot" style="background: var(--accent)"></span> shared_topic
            </span>
            <span class="legend-item">
              <span class="legend-dot" style="background: var(--purple)"></span> shared_concept
            </span>
            <span class="legend-item">
              <span class="legend-dot" style="background: var(--green)"></span> shared_theory
            </span>
            <span class="legend-item">
              <span class="legend-dot" style="background: var(--yellow)"></span> cross_relation
            </span>
          </div>
        </div>
      </div>

      <div v-else-if="!metagraphLoading" class="empty-graph-state">
        <span class="empty-icon">📊</span>
        <span>No metagraph data available. Click Refresh to load.</span>
      </div>

      <div v-if="metagraphLoading" class="loading-overlay">
        <div class="spinner"></div>
        <span>Loading metagraph...</span>
      </div>
    </div>

    <!-- Tooltip -->
    <Teleport to="body">
      <div
        v-if="tooltip.visible"
        class="tooltip-popup"
        :style="{ left: tooltip.x + 'px', top: tooltip.y + 'px' }"
      >{{ tooltip.text }}</div>
    </Teleport>

    <!-- Preview Overlay -->
    <Teleport to="body">
      <div v-if="previewVisible" class="preview-overlay" @click.self="closePreview">
        <div class="preview-modal">
          <div class="preview-header">
            <div>
              <h3 class="preview-title">{{ previewPaper?.title || previewPaper?.name || 'Paper Preview' }}</h3>
              <div class="preview-meta">
                <span v-if="previewPaper?.id || previewPaper?.arxiv_id" class="preview-id">{{ previewPaper.id || previewPaper.arxiv_id }}</span>
                <span v-if="previewPaper?.authors" class="preview-authors">{{ previewPaper.authors }}</span>
              </div>
            </div>
            <button class="preview-close" @click="closePreview">✕</button>
          </div>
          <div class="preview-body">
            <div v-if="previewLoading" class="loading-overlay">
              <div class="spinner"></div>
            </div>
            <div v-else-if="previewDigests" class="preview-content">
              <div v-if="previewDigests.abstract" class="digest-section">
                <div class="card-header">Abstract</div>
                <p>{{ previewDigests.abstract }}</p>
              </div>
              <div v-if="previewDigests.summary" class="digest-section">
                <div class="card-header">Summary</div>
                <p>{{ previewDigests.summary }}</p>
              </div>
              <div v-if="previewDigests.key_findings?.length" class="digest-section">
                <div class="card-header">Key Findings</div>
                <ul>
                  <li v-for="(f, i) in previewDigests.key_findings" :key="i">{{ f }}</li>
                </ul>
              </div>
              <div v-if="previewDigests.noober_summary" class="digest-section">
                <div class="card-header">Beginner Summary</div>
                <p>{{ previewDigests.noober_summary }}</p>
              </div>
            </div>
          </div>
          <div class="preview-actions">
            <button class="btn btn-sm" @click="closePreview">Close</button>
          </div>
        </div>
      </div>
    </Teleport>

    <div v-if="overlapsLoading && activeTab === 'overlaps'" class="loading-overlay">
      <div class="spinner"></div>
      <span>Loading overlaps...</span>
    </div>
  </div>
</template>

<style scoped>
.analytics-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.tab-bar {
  display: flex;
  gap: 4px;
  margin-bottom: 12px;
  flex-shrink: 0;
}

.tab-btn {
  flex: 1;
  padding: 8px 14px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text2);
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  transition: all 0.2s;
}

.tab-btn.active {
  background: var(--accent);
  color: #080c18;
  border-color: var(--accent);
}

.tab-btn:hover:not(.active) {
  background: var(--surface2);
  border-color: var(--text3);
}

.tab-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.controls-row {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-shrink: 0;
}

.filter-input {
  flex: 1;
}

.summary-text {
  font-size: 11px;
  color: var(--text3);
  flex-shrink: 0;
}

.view-toggle {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.toggle-btn {
  flex: 1;
  padding: 7px 14px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text2);
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  transition: all 0.2s;
}

.toggle-btn.active {
  background: var(--accent);
  color: #080c18;
  border-color: var(--accent);
}

.toggle-btn:hover:not(.active) {
  background: var(--surface2);
  border-color: var(--text3);
}

.overlaps-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.overlap-item {
  padding: 6px 0;
  border-bottom: 1px solid var(--border);
}

.overlap-item:last-child {
  border-bottom: none;
}

.overlap-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 4px;
}

.overlap-papers {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.mini-tag {
  display: inline-block;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 1px 8px;
  font-size: 10px;
  color: var(--text2);
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rel-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}

.rel-source {
  color: var(--accent);
  font-weight: 600;
}

.rel-arrow {
  color: var(--text3);
}

.rel-target {
  color: var(--accent);
  font-weight: 600;
}

.rel-type {
  margin-left: auto;
  font-size: 10px;
  color: var(--text3);
  background: var(--surface2);
  padding: 1px 6px;
  border-radius: 8px;
}

.overlaps-graph-wrap {
  flex: 1;
  min-height: 300px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  background: var(--bg);
}

.d3-container {
  width: 100%;
  height: 100%;
  min-height: 300px;
}

.metagraph-area {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.metagraph-area .d3-container {
  flex: 1;
  min-height: 400px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  background: var(--bg);
}

.metagraph-legend {
  display: flex;
  gap: 24px;
  padding: 8px 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  flex-shrink: 0;
}

.legend-section {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.legend-heading {
  font-size: 10px;
  font-weight: 600;
  color: var(--text3);
  text-transform: uppercase;
  letter-spacing: 0.4px;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--text2);
}

.legend-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--text2);
  cursor: pointer;
  white-space: nowrap;
}

.checkbox-label input {
  width: auto;
}

.empty-graph-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--text3);
  font-size: 13px;
}

.empty-icon {
  font-size: 32px;
  opacity: 0.5;
}

.empty-state {
  font-size: 11px;
  color: var(--text3);
  font-style: italic;
  padding: 8px 0;
}

.loading-overlay {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 24px;
  color: var(--text2);
  font-size: 12px;
}

.spinner {
  width: 18px;
  height: 18px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Preview Overlay */
.preview-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
}

.preview-modal {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  width: 90%;
  max-width: 640px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow);
}

.preview-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  gap: 12px;
}

.preview-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text);
  line-height: 1.3;
  margin: 0;
}

.preview-meta {
  display: flex;
  gap: 10px;
  margin-top: 6px;
  font-size: 11px;
  color: var(--text3);
}

.preview-id {
  color: var(--accent);
  font-weight: 600;
}

.preview-close {
  background: none;
  border: none;
  color: var(--text3);
  cursor: pointer;
  font-size: 18px;
  padding: 4px;
  line-height: 1;
  flex-shrink: 0;
  transition: color 0.15s;
}

.preview-close:hover {
  color: var(--red);
}

.preview-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

.preview-content {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.digest-section p {
  font-size: 12.5px;
  color: var(--text);
  line-height: 1.6;
}

.digest-section ul {
  padding-left: 18px;
  font-size: 12.5px;
  color: var(--text);
  line-height: 1.6;
}

.preview-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 20px;
  border-top: 1px solid var(--border);
}
</style>
