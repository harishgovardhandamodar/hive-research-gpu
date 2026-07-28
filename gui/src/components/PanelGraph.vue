<script setup>
import { ref, reactive, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useAppStore } from '../stores/app.js'
import { useGraphStore } from '../stores/graph.js'
import { getDigests, getHelpNoob, getSimilarity, detailGraph, generateDefinitions } from '../api.js'

const app = useAppStore()
const graph = useGraphStore()

const graphWrap = ref(null)
const showSettings = ref(false)
const controlsOpen = ref(false)
const loading = ref(false)

const filterText = ref('')
const filterOpen = ref(false)
const filterIdx = ref(-1)
const selectedNode = ref(null)
const previewTab = ref('similarity')
const previewContent = ref('')
const previewLoading = ref(false)
const tooltip = reactive({ visible: false, x: 0, y: 0, text: '' })

let svg = null
let g = null
let simulation = null
let zoomBehavior = null
let nodeElements = null
let linkElements = null
let linkLabelElements = null

const styleForm = reactive({ ...graph.graphStyle })

const paperCount = computed(() => graph.data.nodes?.filter(n => n.type === 'paper').length || 0)

const filteredNodes = computed(() => {
  const q = filterText.value.toLowerCase().trim()
  if (!q) return []
  return (graph.data.nodes || []).filter(n =>
    (n.id || '').toLowerCase().includes(q) ||
    (n.label || '').toLowerCase().includes(q)
  ).slice(0, 12)
})

const previewTabs = [
  { id: 'similarity', label: 'Similarity' },
  { id: 'digests', label: 'Digests' },
  { id: 'helpNoob', label: 'Help-Noob' },
  { id: 'priorWorks', label: 'Prior Works' },
  { id: 'citedBy', label: 'Cited By' }
]

function getTextColor(color) {
  if (!color) return '#fff'
  const hex = color.replace('#', '')
  const r = parseInt(hex.substring(0, 2), 16)
  const g = parseInt(hex.substring(2, 4), 16)
  const b = parseInt(hex.substring(4, 6), 16)
  return (r * 0.299 + g * 0.587 + b * 0.114) > 150 ? '#080c18' : '#fff'
}

function nodeColor(type) {
  const s = graph.graphStyle
  switch (type) {
    case 'paper': return s.paperColor
    case 'lineage': return s.lineageColor
    case 'web': return s.webColor
    case 'concept': return s.conceptColor
    case 'cites': return s.citeColor
    default: return s.edgeColor
  }
}

function linkColor(link) {
  if (link.type === 'cite') return graph.graphStyle.citeColor
  return graph.graphStyle.edgeColor
}

function nodeRadius(d) {
  if (d.type === 'paper' || d.type === 'web') return graph.graphStyle.paperSize
  return graph.graphStyle.conceptSize
}

async function refresh() {
  loading.value = true
  await graph.fetchGraph()
  loading.value = false
}

async function fillDefinitions() {
  try {
    await generateDefinitions()
    app.addLog('Definitions generated', 'DONE')
    await graph.fetchGraph()
  } catch (e) {
    app.addLog(`Definitions failed: ${e.message}`, 'ERROR')
  }
}

async function openDetailGraph() {
  try {
    await detailGraph()
    app.addLog('Detail graph generated', 'DONE')
    await graph.fetchGraph()
  } catch (e) {
    app.addLog(`Detail graph failed: ${e.message}`, 'ERROR')
  }
}

function applyStyle() {
  graph.updateGraphStyle({ ...styleForm })
}

function resetStyle() {
  graph.resetGraphStyle()
  Object.assign(styleForm, graph.graphStyle)
}

function closePreview() {
  selectedNode.value = null
  previewTab.value = 'similarity'
  previewContent.value = ''
}

function onFilterInput() {
  filterIdx.value = -1
  filterOpen.value = filterText.value.trim().length > 0
}

function onFilterKeydown(e) {
  if (!filterOpen.value) return
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    filterIdx.value = Math.min(filterIdx.value + 1, filteredNodes.value.length - 1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    filterIdx.value = Math.max(filterIdx.value - 1, 0)
  } else if (e.key === 'Enter') {
    e.preventDefault()
    const idx = filterIdx.value >= 0 ? filterIdx.value : 0
    if (filteredNodes.value[idx]) {
      selectSearchNode(filteredNodes.value[idx])
    }
  } else if (e.key === 'Escape') {
    filterOpen.value = false
  }
}

function selectSearchNode(node) {
  filterOpen.value = false
  filterText.value = ''
  showNodePreview(node)
}

function showNodePreview(node) {
  selectedNode.value = node
  previewTab.value = 'similarity'
  previewContent.value = ''
  loadTabContent()
}

async function loadTabContent() {
  if (!selectedNode.value) return
  previewLoading.value = true
  previewContent.value = ''
  const id = selectedNode.value.id
  try {
    switch (previewTab.value) {
      case 'similarity': {
        const data = await getSimilarity([id])
        previewContent.value = formatSimilarity(data)
        break
      }
      case 'digests': {
        const data = await getDigests(id)
        previewContent.value = formatDigests(data)
        break
      }
      case 'helpNoob': {
        const data = await getHelpNoob(id)
        previewContent.value = data.explanation || data.text || JSON.stringify(data, null, 2)
        break
      }
      case 'priorWorks': {
        const data = await getDigests(id, 'prior')
        previewContent.value = formatDigests(data)
        break
      }
      case 'citedBy': {
        const data = await getSimilarity([id], 'cited_by')
        previewContent.value = formatSimilarity(data)
        break
      }
    }
  } catch (e) {
    previewContent.value = `Error: ${e.message}`
  }
  previewLoading.value = false
}

function formatSimilarity(data) {
  if (!data) return 'No data'
  if (data.similar && data.similar.length) {
    return data.similar.map(s =>
      `<div class="sim-item"><strong>${s.title || s.id}</strong><br><small>${s.score ? (s.score * 100).toFixed(1) + '% match' : ''}</small></div>`
    ).join('')
  }
  return '<pre>' + JSON.stringify(data, null, 2) + '</pre>'
}

function formatDigests(data) {
  if (!data) return 'No data'
  if (data.digests && data.digests.length) {
    return data.digests.map(d =>
      `<div class="digest-item"><strong>${d.type || 'Digest'}</strong><div class="markdown-body">${d.content || d.text || ''}</div></div>`
    ).join('')
  }
  if (data.content) return `<div class="markdown-body">${data.content}</div>`
  return '<pre>' + JSON.stringify(data, null, 2) + '</pre>'
}

function handleNodeClick(e, d) {
  e.stopPropagation()
  showNodePreview(d)
}

function handleNodeHover(e, d) {
  if (!d) {
    tooltip.visible = false
    return
  }
  const neighbors = new Set()
  neighbors.add(d.id)
  graph.data.links.forEach(l => {
    const sid = typeof l.source === 'object' ? l.source.id : l.source
    const tid = typeof l.target === 'object' ? l.target.id : l.target
    if (sid === d.id) neighbors.add(tid)
    if (tid === d.id) neighbors.add(sid)
  })

  nodeElements.attr('opacity', n => neighbors.has(n.id) ? 1 : 0.15)
  linkElements.attr('opacity', l => {
    const sid = typeof l.source === 'object' ? l.source.id : l.source
    const tid = typeof l.target === 'object' ? l.target.id : l.target
    return (sid === d.id || tid === d.id) ? 1 : 0.08
  })
  linkLabelElements.attr('opacity', l => {
    const sid = typeof l.source === 'object' ? l.source.id : l.source
    const tid = typeof l.target === 'object' ? l.target.id : l.target
    return (sid === d.id || tid === d.id) ? 1 : 0.08
  })

  const labelText = d.label || d.id
  tooltip.text = labelText
  tooltip.x = e.clientX + 14
  tooltip.y = e.clientY - 10
  tooltip.visible = true
}

function handleNodeLeave() {
  if (nodeElements) nodeElements.attr('opacity', 1)
  if (linkElements) linkElements.attr('opacity', 1)
  if (linkLabelElements) linkLabelElements.attr('opacity', 1)
  tooltip.visible = false
}

function renderGraph() {
  if (!graphWrap.value) return
  const d3 = window.d3
  if (!d3) return

  const nodes = graph.data.nodes || []
  const links = graph.data.links || []

  if (svg) svg.remove()

  const width = graphWrap.value.clientWidth
  const height = graphWrap.value.clientHeight

  svg = d3.select(graphWrap.value)
    .append('svg')
    .attr('width', width)
    .attr('height', height)
    .style('background', 'transparent')

  const defs = svg.append('defs')
  defs.append('marker')
    .attr('id', 'arrow')
    .attr('viewBox', '0 -5 10 10')
    .attr('refX', 22)
    .attr('refY', 0)
    .attr('markerWidth', 6)
    .attr('markerHeight', 6)
    .attr('orient', 'auto')
    .append('path')
    .attr('d', 'M0,-5L10,0L0,5')
    .attr('fill', graph.graphStyle.edgeColor)

  g = svg.append('g')

  zoomBehavior = d3.zoom()
    .scaleExtent([0.1, 6])
    .on('zoom', (event) => {
      g.attr('transform', event.transform)
    })

  svg.call(zoomBehavior)

  simulation = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).id(d => d.id).distance(80))
    .force('charge', d3.forceManyBody().strength(-180))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collision', d3.forceCollide().radius(d => nodeRadius(d) + 4))

  linkElements = g.append('g')
    .attr('class', 'links')
    .selectAll('line')
    .data(links)
    .join('line')
    .attr('stroke', d => linkColor(d))
    .attr('stroke-width', 1.2)
    .attr('stroke-opacity', 0.6)
    .attr('marker-end', 'url(#arrow)')

  linkLabelElements = g.append('g')
    .attr('class', 'link-labels')
    .selectAll('text')
    .data(links)
    .join('text')
    .attr('font-size', 8)
    .attr('fill', 'var(--text3)')
    .attr('text-anchor', 'middle')
    .attr('dominant-baseline', 'middle')
    .attr('pointer-events', 'none')
    .text(d => d.label || '')

  nodeElements = g.append('g')
    .attr('class', 'nodes')
    .selectAll('.node')
    .data(nodes)
    .join('g')
    .attr('class', 'node')
    .style('cursor', 'pointer')
    .call(d3.drag()
      .on('start', (event, d) => {
        if (!event.active) simulation.alphaTarget(0.3).restart()
        d.fx = d.x
        d.fy = d.y
      })
      .on('drag', (event, d) => {
        d.fx = event.x
        d.fy = event.y
      })
      .on('end', (event, d) => {
        if (!event.active) simulation.alphaTarget(0)
        d.fx = null
        d.fy = null
      }))

  nodeElements.each(function (d) {
    const el = d3.select(this)
    const color = nodeColor(d.type)
    const r = nodeRadius(d)
    if (d.type === 'paper' || d.type === 'web') {
      el.append('rect')
        .attr('x', -r)
        .attr('y', -r)
        .attr('width', r * 2)
        .attr('height', r * 2)
        .attr('rx', 3)
        .attr('fill', color)
        .attr('stroke', d3.color(color).brighter(0.5))
        .attr('stroke-width', 1)
    } else {
      el.append('circle')
        .attr('r', r)
        .attr('fill', color)
        .attr('stroke', d3.color(color).brighter(0.5))
        .attr('stroke-width', 1)
    }
    el.append('text')
      .attr('dx', r + 4)
      .attr('dy', 3)
      .attr('font-size', 9)
      .attr('fill', 'var(--text2)')
      .attr('pointer-events', 'none')
      .text(d.label ? (d.label.length > 24 ? d.label.slice(0, 22) + '..' : d.label) : '')
  })

  nodeElements
    .on('click', (e, d) => handleNodeClick(e, d))
    .on('mouseenter', (e, d) => handleNodeHover(e, d))
    .on('mousemove', (e) => {
      tooltip.x = e.clientX + 14
      tooltip.y = e.clientY - 10
    })
    .on('mouseleave', () => handleNodeLeave())

  simulation.on('tick', () => {
    linkElements
      .attr('x1', d => d.source.x)
      .attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x)
      .attr('y2', d => d.target.y)

    linkLabelElements
      .attr('x', d => (d.source.x + d.target.x) / 2)
      .attr('y', d => (d.source.y + d.target.y) / 2)

    nodeElements.attr('transform', d => `translate(${d.x},${d.y})`)
  })
}

function destroyGraph() {
  if (simulation) {
    simulation.stop()
    simulation = null
  }
  if (svg) {
    svg.remove()
    svg = null
    g = null
  }
}

watch(() => graph.data, () => {
  nextTick(() => renderGraph())
}, { deep: true })

watch(() => graph.graphStyle, (s) => {
  Object.assign(styleForm, s)
  if (nodeElements) {
    nodeElements.each(function (d) {
      const el = d3.select(this)
      const color = nodeColor(d.type)
      el.select('rect, circle').attr('fill', color)
    })
  }
  if (linkElements) {
    linkElements.attr('stroke', d => linkColor(d))
  }
}, { deep: true })

function handleThemeChange() {
  if (!svg) return
  const root = getComputedStyle(document.documentElement)
  const text3 = root.getPropertyValue('--text3').trim()
  if (linkLabelElements) linkLabelElements.attr('fill', text3)
}

let themeObserver = null

onMounted(() => {
  Object.assign(styleForm, graph.graphStyle)
  renderGraph()

  themeObserver = new MutationObserver(() => handleThemeChange())
  themeObserver.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['class']
  })
})

onBeforeUnmount(() => {
  destroyGraph()
  if (themeObserver) themeObserver.disconnect()
})
</script>

<template>
  <div class="panel-graph">
    <div class="panel-header">
      <div class="header-left">
        <span class="panel-title">Knowledge Graph</span>
        <span class="badge" v-if="paperCount">{{ paperCount }} papers</span>
      </div>
      <div class="header-actions">
        <button class="btn btn-sm" @click="refresh" :disabled="loading">
          {{ loading ? 'Loading...' : 'Refresh' }}
        </button>
        <button class="btn btn-sm btn-outline" @click="fillDefinitions">Fill Definitions</button>
        <button class="btn btn-sm btn-outline" @click="openDetailGraph">Detail Graph</button>
        <button class="btn-icon" @click="controlsOpen = !controlsOpen" title="Graph settings">
          {{ controlsOpen ? '▾' : '▸' }} Settings
        </button>
      </div>
    </div>

    <transition name="slide">
      <div v-if="controlsOpen" class="controls-section">
        <div class="controls-grid">
          <label class="control-item">
            <span>Paper</span>
            <input type="color" v-model="styleForm.paperColor" @change="applyStyle" />
          </label>
          <label class="control-item">
            <span>Lineage</span>
            <input type="color" v-model="styleForm.lineageColor" @change="applyStyle" />
          </label>
          <label class="control-item">
            <span>Web</span>
            <input type="color" v-model="styleForm.webColor" @change="applyStyle" />
          </label>
          <label class="control-item">
            <span>Concept</span>
            <input type="color" v-model="styleForm.conceptColor" @change="applyStyle" />
          </label>
          <label class="control-item">
            <span>Edge</span>
            <input type="color" v-model="styleForm.edgeColor" @change="applyStyle" />
          </label>
          <label class="control-item">
            <span>Cite</span>
            <input type="color" v-model="styleForm.citeColor" @change="applyStyle" />
          </label>
          <label class="control-item control-slider">
            <span>Paper size</span>
            <input type="range" v-model.number="styleForm.paperSize" min="4" max="40" @change="applyStyle" />
            <small>{{ styleForm.paperSize }}</small>
          </label>
          <label class="control-item control-slider">
            <span>Concept size</span>
            <input type="range" v-model.number="styleForm.conceptSize" min="2" max="24" @change="applyStyle" />
            <small>{{ styleForm.conceptSize }}</small>
          </label>
        </div>
        <button class="btn btn-sm btn-outline" @click="resetStyle">Reset defaults</button>
      </div>
    </transition>

    <div class="graph-container" ref="graphWrap">
      <div v-if="!graph.data.nodes?.length && !loading" class="empty-state">
        No graph data. Add papers or click Refresh.
      </div>

      <div class="filter-box">
        <input
          v-model="filterText"
          @input="onFilterInput"
          @keydown="onFilterKeydown"
          @focus="filterOpen = filterText.trim().length > 0"
          @blur="setTimeout(() => filterOpen = false, 200)"
          placeholder="Filter nodes..."
          class="filter-input"
        />
        <div v-if="filterOpen && filteredNodes.length" class="filter-dropdown">
          <div
            v-for="(node, i) in filteredNodes"
            :key="node.id"
            :class="['filter-item', { active: i === filterIdx }]"
            @mousedown.prevent="selectSearchNode(node)"
          >
            <span class="filter-type" :style="{ background: nodeColor(node.type) }">{{ node.type }}</span>
            <span class="filter-label">{{ node.label || node.id }}</span>
          </div>
        </div>
      </div>

      <div class="graph-legend">
        <span class="legend-item"><i class="legend-dot" style="background: var(--accent)"></i> Paper</span>
        <span class="legend-item"><i class="legend-dot" style="background: var(--cyan)"></i> Lineage</span>
        <span class="legend-item"><i class="legend-dot" style="background: #fb923c"></i> Web</span>
        <span class="legend-item"><i class="legend-dot" style="background: var(--purple)"></i> Concept</span>
        <span class="legend-item"><i class="legend-dot" style="background: var(--green)"></i> Cites</span>
      </div>

      <div
        v-if="tooltip.visible"
        class="tooltip-popup"
        :style="{ left: tooltip.x + 'px', top: tooltip.y + 'px' }"
      >
        {{ tooltip.text }}
      </div>
    </div>

    <transition name="slide-right">
      <div v-if="selectedNode" class="node-preview">
        <div class="preview-header">
          <h3>{{ selectedNode.label || selectedNode.id }}</h3>
          <button class="btn-close" @click="closePreview">&times;</button>
        </div>

        <div class="preview-meta">
          <span class="preview-type" :style="{ background: nodeColor(selectedNode.type), color: getTextColor(nodeColor(selectedNode.type)) }">
            {{ selectedNode.type }}
          </span>
          <span class="preview-id">{{ selectedNode.id }}</span>
        </div>

        <p v-if="selectedNode.abstract" class="preview-abstract">{{ selectedNode.abstract }}</p>

        <div class="preview-actions">
          <a
            v-if="selectedNode.type === 'paper'"
            :href="`https://arxiv.org/abs/${selectedNode.id}`"
            target="_blank"
            class="btn btn-sm btn-outline"
          >arXiv</a>
          <button class="btn btn-sm btn-outline" @click="app.addLog(`Browse note: ${selectedNode.id}`, 'INFO')">Browse note</button>
          <button class="btn btn-sm btn-outline" @click="app.addLog(`Browse PDF: ${selectedNode.id}`, 'INFO')">Browse PDF</button>
        </div>

        <div class="preview-tabs">
          <button
            v-for="tab in previewTabs"
            :key="tab.id"
            :class="['tab-btn', { active: previewTab === tab.id }]"
            @click="previewTab = tab.id; loadTabContent()"
          >
            {{ tab.label }}
          </button>
        </div>

        <div class="preview-body">
          <div v-if="previewLoading" class="preview-loading">
            <span class="spinner"></span> Loading...
          </div>
          <div v-else v-html="previewContent" class="markdown-body"></div>
        </div>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.panel-graph {
  display: flex;
  flex-direction: column;
  height: 100%;
  position: relative;
  overflow: hidden;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  flex-shrink: 0;
  gap: 8px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.panel-title {
  font-weight: 600;
  font-size: 13px;
}

.badge {
  background: var(--accent);
  color: #080c18;
  font-size: 10px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 10px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.btn-icon {
  background: none;
  border: none;
  color: var(--text2);
  cursor: pointer;
  font-size: 12px;
  padding: 4px 8px;
  border-radius: 6px;
  transition: all 0.15s;
}

.btn-icon:hover {
  background: var(--surface2);
  color: var(--text);
}

.controls-section {
  padding: 10px 12px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.controls-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 8px;
  margin-bottom: 8px;
}

.control-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text2);
}

.control-item input[type="color"] {
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid var(--border);
  border-radius: 6px;
  cursor: pointer;
  background: transparent;
}

.control-slider {
  flex-direction: column;
  align-items: flex-start;
}

.control-slider input[type="range"] {
  width: 100%;
  height: 4px;
  accent-color: var(--accent);
  cursor: pointer;
}

.control-slider small {
  font-size: 10px;
  color: var(--text3);
  align-self: flex-end;
}

.graph-container {
  flex: 1;
  position: relative;
  overflow: hidden;
  min-height: 200px;
}

.empty-state {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text3);
  font-size: 13px;
  pointer-events: none;
  z-index: 5;
}

.filter-box {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 20;
  width: 220px;
}

.filter-input {
  width: 100%;
  padding: 6px 10px;
  font-size: 11px;
  background: var(--glass-bg3);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  backdrop-filter: blur(8px);
}

.filter-dropdown {
  margin-top: 2px;
  background: var(--glass-bg4);
  border: 1px solid var(--border);
  border-radius: 8px;
  max-height: 240px;
  overflow-y: auto;
  box-shadow: var(--shadow);
}

.filter-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  cursor: pointer;
  font-size: 11px;
  transition: background 0.1s;
}

.filter-item:hover, .filter-item.active {
  background: var(--surface2);
}

.filter-type {
  font-size: 9px;
  font-weight: 600;
  padding: 1px 5px;
  border-radius: 4px;
  text-transform: uppercase;
  flex-shrink: 0;
}

.filter-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.graph-legend {
  position: absolute;
  bottom: 8px;
  left: 8px;
  z-index: 10;
  display: flex;
  gap: 10px;
  background: var(--glass-bg3);
  backdrop-filter: blur(8px);
  padding: 5px 10px;
  border-radius: 8px;
  border: 1px solid var(--border);
  font-size: 10px;
  color: var(--text2);
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.legend-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.node-preview {
  position: absolute;
  top: 0;
  right: 0;
  width: 360px;
  height: 100%;
  background: var(--glass-bg3);
  backdrop-filter: blur(12px);
  border-left: 1px solid var(--border);
  z-index: 30;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: -4px 0 24px rgba(0,0,0,0.3);
}

.preview-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 12px 14px 8px;
  flex-shrink: 0;
}

.preview-header h3 {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.3;
  flex: 1;
  margin-right: 8px;
}

.btn-close {
  background: none;
  border: none;
  color: var(--text3);
  font-size: 20px;
  cursor: pointer;
  padding: 0 4px;
  line-height: 1;
}

.btn-close:hover {
  color: var(--text);
}

.preview-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 14px 8px;
  flex-shrink: 0;
}

.preview-type {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 6px;
  text-transform: uppercase;
}

.preview-id {
  font-size: 11px;
  color: var(--text3);
  font-family: monospace;
}

.preview-abstract {
  padding: 0 14px 10px;
  font-size: 12px;
  color: var(--text2);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.preview-actions {
  display: flex;
  gap: 6px;
  padding: 0 14px 10px;
  flex-shrink: 0;
}

.preview-tabs {
  display: flex;
  gap: 2px;
  padding: 0 14px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  overflow-x: auto;
}

.tab-btn {
  background: none;
  border: none;
  color: var(--text3);
  font-size: 11px;
  padding: 8px 10px;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all 0.15s;
  white-space: nowrap;
}

.tab-btn:hover {
  color: var(--text2);
}

.tab-btn.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

.preview-body {
  flex: 1;
  overflow-y: auto;
  padding: 10px 14px;
  font-size: 12px;
}

.preview-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text3);
  font-size: 12px;
  padding: 16px 0;
}

.spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.slide-enter-active, .slide-leave-active {
  transition: all 0.2s ease;
}

.slide-enter-from, .slide-leave-to {
  max-height: 0;
  opacity: 0;
  padding-top: 0;
  padding-bottom: 0;
  overflow: hidden;
}

.slide-enter-to, .slide-leave-from {
  max-height: 300px;
  opacity: 1;
}

.slide-right-enter-active, .slide-right-leave-active {
  transition: transform 0.2s ease;
}

.slide-right-enter-from, .slide-right-leave-to {
  transform: translateX(100%);
}
</style>
