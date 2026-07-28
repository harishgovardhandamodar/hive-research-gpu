<script setup>
import { ref, computed, watch, onMounted, nextTick, onBeforeUnmount } from 'vue'
import { useAppStore } from '../stores/app.js'
import { useGraphStore } from '../stores/graph.js'
import { usePoolStore } from '../stores/pool.js'
import {
  getPoolPapers, getPoolTopics, getPoolInsights, getPoolGraph,
  addPoolTopic, removePoolTopic, importPoolPaper, importPoolBatch,
  queryPool, searchArxiv
} from '../api.js'

const app = useAppStore()
const graph = useGraphStore()
const pool = usePoolStore()

const activeTab = ref('browse')
const searchQuery = ref('')
const topicFilter = ref('')
const topicFilterOptions = computed(() => {
  const topics = pool.topics || []
  return [{ name: 'All Topics', value: '' }, ...topics.map(t => ({ name: t.name, value: t.name }))]
})

const showSettings = ref(false)
const expandedAbstracts = ref({})
const selectedPapers = ref({})
const importProgress = ref(null)
const importing = ref(false)
const showAddTopic = ref(false)
const newTopicName = ref('')
const newTopicQuery = ref('')
const showSubGraph = ref(false)
const subGraphTopic = ref('')
const showNodePreview = ref(null)
const splitPosition = ref(50)
const graphContainer = ref(null)
let simulation = null
let zoom = null

const TOPIC_COLORS = [
  '#60a5fa', '#f87171', '#34d399', '#fbbf24', '#c084fc',
  '#22d3ee', '#fb923c', '#a78bfa', '#f472b6', '#4ade80',
  '#e879f9', '#38bdf8', '#facc15', '#2dd4bf', '#818cf8'
]

function getTopicColor(index) {
  return TOPIC_COLORS[index % TOPIC_COLORS.length]
}

function getTopicColorByName(name) {
  const topics = pool.topics || []
  const idx = topics.findIndex(t => t.name === name)
  return getTopicColor(idx >= 0 ? idx : 0)
}

const insights = computed(() => pool.insights || {})
const observedCount = computed(() => insights.value.observed || insights.value.total || 0)
const importedCount = computed(() => insights.value.imported || 0)
const conversionRate = computed(() => {
  if (!observedCount.value) return 0
  return ((importedCount.value / observedCount.value) * 100).toFixed(1)
})
const newCount = computed(() => insights.value.new_count || insights.value.recent || 0)

const allPapers = computed(() => pool.papers || [])

const filteredPapers = computed(() => {
  let papers = allPapers.value
  if (topicFilter.value) {
    papers = papers.filter(p => {
      const topics = p.topics || p.topic || []
      if (typeof topics === 'string') return topics === topicFilter.value
      return topics.includes(topicFilter.value)
    })
  }
  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase()
    papers = papers.filter(p => {
      const title = (p.title || '').toLowerCase()
      const authors = (p.authors || []).join(' ').toLowerCase()
      const abstract = (p.abstract || '').toLowerCase()
      return title.includes(q) || authors.includes(q) || abstract.includes(q)
    })
  }
  return papers
})

const papersByTopic = computed(() => {
  const groups = {}
  const topics = pool.topics || []

  for (const paper of filteredPapers.value) {
    const paperTopics = paper.topics || paper.topic || []
    const topicNames = Array.isArray(paperTopics) ? paperTopics : [paperTopics]
    if (!topicNames.length) {
      if (!groups['Untagged']) groups['Untagged'] = []
      groups['Untagged'].push(paper)
    } else {
      for (const t of topicNames) {
        if (!groups[t]) groups[t] = []
        groups[t].push(paper)
      }
    }
  }
  return groups
})

const topicStats = computed(() => {
  const stats = {}
  const topics = pool.topics || []
  for (const paper of allPapers.value) {
    const paperTopics = paper.topics || paper.topic || []
    const topicNames = Array.isArray(paperTopics) ? paperTopics : [paperTopics]
    for (const t of topicNames) {
      if (!stats[t]) stats[t] = { name: t, observed: 0, imported: 0 }
      stats[t].observed++
      if (paper.imported || paper.is_imported) stats[t].imported++
    }
  }
  return stats
})

function computeRelevance(paper, topicQuery) {
  if (!topicQuery) return 0
  const queryWords = topicQuery.toLowerCase().split(/\s+/).filter(w => w.length > 2)
  if (!queryWords.length) return 0
  const text = `${paper.title || ''} ${paper.abstract || ''} ${(paper.authors || []).join(' ')}`.toLowerCase()
  let matches = 0
  for (const w of queryWords) {
    if (text.includes(w)) matches++
  }
  return Math.round((matches / queryWords.length) * 100)
}

function formatAuthors(authors) {
  if (!authors || !authors.length) return ''
  if (authors.length <= 3) return authors.join(', ')
  return `${authors[0]}, ${authors[1]}, ... +${authors.length - 2}`
}

function getPaperId(paper) {
  return paper.arxiv_id || paper.id || paper.paper_id || ''
}

function isImported(paper) {
  return paper.imported || paper.is_imported || false
}

function isNew(paper) {
  if (paper.is_new !== undefined) return paper.is_new
  if (paper.added_date || paper.created_at) {
    const d = new Date(paper.added_date || paper.created_at)
    const now = Date.now()
    return (now - d.getTime()) < 7 * 24 * 60 * 60 * 1000
  }
  return false
}

function toggleAbstract(paperId) {
  expandedAbstracts.value[paperId] = !expandedAbstracts.value[paperId]
}

function toggleSelect(paperId) {
  selectedPapers.value[paperId] = !selectedPapers.value[paperId]
}

function selectAllInTopic(topicName) {
  const papers = papersByTopic.value[topicName] || []
  for (const p of papers) {
    const id = getPaperId(p)
    if (id && !isImported(p)) {
      selectedPapers.value[id] = true
    }
  }
}

function deselectAll() {
  selectedPapers.value = {}
}

const selectedCount = computed(() => Object.values(selectedPapers.value).filter(Boolean).length)

async function importSelected() {
  const ids = Object.entries(selectedPapers.value)
    .filter(([_, v]) => v)
    .map(([k]) => k)
  if (!ids.length) return

  importing.value = true
  importProgress.value = { current: 0, total: ids.length }

  try {
    await importPoolBatch(ids)
    app.addLog(`Imported ${ids.length} papers`, 'DONE')
    selectedPapers.value = {}
    await pool.fetchPoolPapers()
    await pool.fetchPoolInsights()
  } catch (e) {
    app.addLog(`Import failed: ${e.message}`, 'ERROR')
  } finally {
    importing.value = false
    importProgress.value = null
  }
}

async function importSingle(paper) {
  const id = getPaperId(paper)
  if (!id) return
  try {
    await importPoolPaper(id)
    app.addLog(`Imported ${id}`, 'DONE')
    paper.imported = true
    await pool.fetchPoolInsights()
  } catch (e) {
    app.addLog(`Import failed: ${e.message}`, 'ERROR')
  }
}

async function importAllInTopic(topicName) {
  const papers = (papersByTopic.value[topicName] || []).filter(p => !isImported(p))
  const ids = papers.map(p => getPaperId(p)).filter(Boolean)
  if (!ids.length) return

  importing.value = true
  importProgress.value = { current: 0, total: ids.length }
  try {
    await importPoolBatch(ids)
    app.addLog(`Imported ${ids.length} papers from ${topicName}`, 'DONE')
    await pool.fetchPoolPapers()
    await pool.fetchPoolInsights()
  } catch (e) {
    app.addLog(`Import failed: ${e.message}`, 'ERROR')
  } finally {
    importing.value = false
    importProgress.value = null
  }
}

async function addTopic() {
  if (!newTopicName.value.trim() || !newTopicQuery.value.trim()) return
  try {
    await addPoolTopic(newTopicName.value.trim(), newTopicQuery.value.trim())
    app.addLog(`Added topic: ${newTopicName.value}`, 'DONE')
    newTopicName.value = ''
    newTopicQuery.value = ''
    showAddTopic.value = false
    await pool.fetchPoolTopics()
  } catch (e) {
    app.addLog(`Failed to add topic: ${e.message}`, 'ERROR')
  }
}

async function deleteTopic(name) {
  try {
    await removePoolTopic(name)
    app.addLog(`Removed topic: ${name}`, 'DONE')
    await pool.fetchPoolTopics()
  } catch (e) {
    app.addLog(`Failed to remove topic: ${e.message}`, 'ERROR')
  }
}

function openSubGraph(topicName) {
  subGraphTopic.value = topicName
  showSubGraph.value = true
  nextTick(() => renderSubGraph())
}

function openNodePreview(paper) {
  showNodePreview.value = paper
}

function closeNodePreview() {
  showNodePreview.value = null
}

function renderSubGraph() {
  const container = document.getElementById('subgraph-container')
  if (!container) return
  container.innerHTML = ''

  const papers = (pool.graphData?.nodes || []).filter(n => {
    const topics = n.topics || n.topic || []
    const names = Array.isArray(topics) ? topics : [topics]
    return names.includes(subGraphTopic.value)
  })

  if (!papers.length) {
    container.innerHTML = '<div style="color:var(--text3);padding:20px;text-align:center">No papers in this topic</div>'
    return
  }

  const width = container.clientWidth
  const height = container.clientHeight

  const svg = d3.select(container)
    .append('svg')
    .attr('width', width)
    .attr('height', height)

  const g = svg.append('g')

  const zoomBehavior = d3.zoom()
    .scaleExtent([0.1, 5])
    .on('zoom', (event) => g.attr('transform', event.transform))

  svg.call(zoomBehavior)

  const topicColor = getTopicColorByName(subGraphTopic.value)
  const nodes = papers.map((p, i) => ({
    ...p,
    index: i,
    x: width / 2 + (Math.random() - 0.5) * 200,
    y: height / 2 + (Math.random() - 0.5) * 200
  }))

  const links = []
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const shared = (nodes[i].topics || []).filter(t => (nodes[j].topics || []).includes(t))
      if (shared.length > 0) {
        links.push({ source: i, target: j, strength: shared.length * 0.2 })
      }
    }
  }

  const sim = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).id(d => d.index).distance(80).strength(d => d.strength || 0.3))
    .force('charge', d3.forceManyBody().strength(-120))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collision', d3.forceCollide().radius(20))

  const link = g.append('g')
    .selectAll('line')
    .data(links)
    .join('line')
    .attr('stroke', 'var(--border)')
    .attr('stroke-opacity', 0.4)
    .attr('stroke-width', 1)

  const node = g.append('g')
    .selectAll('circle')
    .data(nodes)
    .join('circle')
    .attr('r', 8)
    .attr('fill', topicColor)
    .attr('stroke', 'var(--bg)')
    .attr('stroke-width', 1.5)
    .style('cursor', 'pointer')
    .on('click', (event, d) => openNodePreview(d))
    .call(d3.drag()
      .on('start', (event, d) => {
        if (!event.active) sim.alphaTarget(0.3).restart()
        d.fx = d.x; d.fy = d.y
      })
      .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y })
      .on('end', (event, d) => {
        if (!event.active) sim.alphaTarget(0)
        d.fx = null; d.fy = null
      })
    )

  const label = g.append('g')
    .selectAll('text')
    .data(nodes)
    .join('text')
    .text(d => (d.title || '').substring(0, 30))
    .attr('font-size', '9px')
    .attr('fill', 'var(--text3)')
    .attr('dx', 12)
    .attr('dy', 3)

  sim.on('tick', () => {
    link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x).attr('y2', d => d.target.y)
    node.attr('cx', d => d.x).attr('cy', d => d.y)
    label.attr('x', d => d.x).attr('y', d => d.y)
  })

  // Fit to view button
  const fitBtn = document.getElementById('subgraph-fit-btn')
  if (fitBtn) {
    fitBtn.onclick = () => {
      svg.transition().duration(500).call(
        zoomBehavior.transform,
        d3.zoomIdentity.translate(0, 0).scale(1)
      )
    }
  }
}

function renderPoolGraph() {
  const container = graphContainer.value
  if (!container) return
  container.innerHTML = ''

  const data = pool.graphData
  if (!data || !data.nodes || !data.nodes.length) {
    container.innerHTML = '<div style="color:var(--text3);padding:20px;text-align:center">No graph data</div>'
    return
  }

  const width = container.clientWidth
  const height = container.clientHeight

  const svg = d3.select(container)
    .append('svg')
    .attr('width', width)
    .attr('height', height)

  const g = svg.append('g')

  zoom = d3.zoom()
    .scaleExtent([0.1, 5])
    .on('zoom', (event) => g.attr('transform', event.transform))

  svg.call(zoom)

  const nodes = data.nodes.map((n, i) => ({
    ...n,
    index: i,
    x: width / 2 + (Math.random() - 0.5) * 400,
    y: height / 2 + (Math.random() - 0.5) * 400
  }))

  const nodeLinks = (data.links || []).map(l => ({
    source: typeof l.source === 'object' ? l.source.index : l.source,
    target: typeof l.target === 'object' ? l.target.index : l.target
  }))

  simulation = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(nodeLinks).id(d => d.index).distance(60))
    .force('charge', d3.forceManyBody().strength(-80))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collision', d3.forceCollide().radius(14))

  const link = g.append('g')
    .selectAll('line')
    .data(nodeLinks)
    .join('line')
    .attr('stroke', 'var(--border)')
    .attr('stroke-opacity', 0.3)
    .attr('stroke-width', 0.8)

  const node = g.append('g')
    .selectAll('circle')
    .data(nodes)
    .join('circle')
    .attr('r', 6)
    .attr('fill', d => {
      const topics = d.topics || d.topic || []
      const name = Array.isArray(topics) ? topics[0] : topics
      return name ? getTopicColorByName(name) : 'var(--text3)'
    })
    .attr('stroke', 'var(--bg)')
    .attr('stroke-width', 1)
    .style('cursor', 'pointer')
    .on('click', (event, d) => openNodePreview(d))
    .call(d3.drag()
      .on('start', (event, d) => {
        if (!event.active) simulation.alphaTarget(0.3).restart()
        d.fx = d.x; d.fy = d.y
      })
      .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y })
      .on('end', (event, d) => {
        if (!event.active) simulation.alphaTarget(0)
        d.fx = null; d.fy = null
      })
    )

  simulation.on('tick', () => {
    link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x).attr('y2', d => d.target.y)
    node.attr('cx', d => d.x).attr('cy', d => d.y)
  })
}

// Split pane dragging
let draggingSplit = false
function onSplitMouseDown(e) {
  draggingSplit = true
  e.preventDefault()
}

function onSplitMouseMove(e) {
  if (!draggingSplit) return
  const container = document.getElementById('topics-graph-container')
  if (!container) return
  const rect = container.getBoundingClientRect()
  const pct = ((e.clientX - rect.left) / rect.width) * 100
  splitPosition.value = Math.max(20, Math.min(80, pct))
}

function onSplitMouseUp() {
  draggingSplit = false
}

onMounted(async () => {
  await Promise.all([
    pool.fetchPoolPapers(),
    pool.fetchPoolTopics(),
    pool.fetchPoolInsights(),
    pool.fetchPoolGraph()
  ])

  document.addEventListener('mousemove', onSplitMouseMove)
  document.addEventListener('mouseup', onSplitMouseUp)

  if (activeTab.value === 'graph') {
    nextTick(() => renderPoolGraph())
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('mousemove', onSplitMouseMove)
  document.removeEventListener('mouseup', onSplitMouseUp)
  if (simulation) simulation.stop()
})

watch(activeTab, (tab) => {
  if (tab === 'graph') {
    nextTick(() => {
      if (simulation) simulation.stop()
      renderPoolGraph()
    })
  }
})

watch(showSubGraph, (val) => {
  if (val) nextTick(() => renderSubGraph())
})
</script>

<template>
  <div class="pool-panel">
    <!-- Insights Bar -->
    <div class="insights-bar">
      <div class="insight-item">
        <span class="insight-num">{{ observedCount }}</span>
        <span class="insight-label">Observed</span>
      </div>
      <div class="insight-divider"></div>
      <div class="insight-item">
        <span class="insight-num">{{ importedCount }}</span>
        <span class="insight-label">Imported</span>
      </div>
      <div class="insight-divider"></div>
      <div class="insight-item">
        <span class="insight-num">{{ conversionRate }}%</span>
        <span class="insight-label">Conversion</span>
      </div>
      <div class="insight-divider"></div>
      <div class="insight-item">
        <span class="insight-num accent">{{ newCount }}</span>
        <span class="insight-label">New</span>
      </div>
    </div>

    <!-- Sub-tabs -->
    <div class="sub-tabs">
      <button
        :class="['sub-tab', { active: activeTab === 'browse' }]"
        @click="activeTab = 'browse'"
      >Browse</button>
      <button
        :class="['sub-tab', { active: activeTab === 'graph' }]"
        @click="activeTab = 'graph'"
      >Topics & Graph</button>
    </div>

    <!-- Toolbar -->
    <div class="pool-toolbar">
      <div class="toolbar-search">
        <input
          v-model="searchQuery"
          type="text"
          placeholder="Free-form query..."
          class="toolbar-input"
          @keyup.enter="queryPool(searchQuery)"
        />
        <button class="btn btn-sm" @click="queryPool(searchQuery)">Search</button>
      </div>
      <select v-model="topicFilter" class="toolbar-select">
        <option v-for="opt in topicFilterOptions" :key="opt.value" :value="opt.value">
          {{ opt.name }}
        </option>
      </select>
      <button class="toolbar-icon-btn" @click="showSettings = !showSettings" title="Settings">
        ⚙
      </button>

      <!-- Batch import bar -->
      <div v-if="selectedCount > 0" class="batch-bar">
        <span class="batch-count">{{ selectedCount }} selected</span>
        <button class="btn btn-sm btn-success" @click="importSelected" :disabled="importing">
          {{ importing ? 'Importing...' : 'Import Selected' }}
        </button>
        <button class="btn btn-sm btn-outline" @click="deselectAll">Clear</button>
      </div>
    </div>

    <!-- Browse Sub-tab -->
    <div v-if="activeTab === 'browse'" class="browse-tab">
      <div v-for="(topicName, topicIdx) in Object.keys(papersByTopic)" :key="topicName" class="topic-group">
        <div class="topic-group-header" :style="{ borderLeftColor: getTopicColorByName(topicName) }">
          <div class="topic-group-info">
            <span class="topic-group-name">{{ topicName }}</span>
            <span class="topic-group-count">{{ papersByTopic[topicName].length }} papers</span>
          </div>
          <div class="topic-group-actions">
            <button class="btn btn-sm btn-outline" @click="selectAllInTopic(topicName)">Select All</button>
            <button class="btn btn-sm btn-outline" @click="importAllInTopic(topicName)">Import All</button>
            <button class="btn btn-sm btn-outline" @click="openSubGraph(topicName)">Sub-graph</button>
          </div>
        </div>

        <div class="topic-papers">
          <div v-for="paper in papersByTopic[topicName]" :key="getPaperId(paper)" class="pool-card">
            <div class="pool-card-left">
              <input
                v-if="!isImported(paper)"
                type="checkbox"
                :checked="selectedPapers[getPaperId(paper)]"
                @change="toggleSelect(getPaperId(paper))"
                class="pool-checkbox"
              />
              <span v-else class="imported-check">✓</span>
            </div>
            <div class="pool-card-content">
              <div class="pool-card-title" @click="openNodePreview(paper)">
                {{ paper.title || 'Untitled' }}
              </div>
              <div class="pool-card-meta">
                <span v-if="paper.authors" class="pool-card-authors">{{ formatAuthors(paper.authors) }}</span>
                <span v-if="paper.published || paper.date" class="pool-card-date">{{ paper.published || paper.date }}</span>
              </div>
              <div v-if="paper.abstract" class="pool-card-abstract-wrap">
                <button class="abstract-toggle" @click="toggleAbstract(getPaperId(paper))">
                  {{ expandedAbstracts[getPaperId(paper)] ? '▲ Hide' : '▼ Abstract' }}
                </button>
                <div v-if="expandedAbstracts[getPaperId(paper)]" class="pool-card-abstract">
                  {{ paper.abstract }}
                </div>
              </div>
              <div class="pool-card-bottom">
                <span v-if="paper.relevance !== undefined" class="relevance-badge">
                  {{ paper.relevance }}% relevant
                </span>
                <span v-else-if="topicFilter && paper.abstract" class="relevance-badge">
                  {{ computeRelevance(paper, (pool.topics.find(t => t.name === topicFilter) || {}).query || '') }}% relevant
                </span>
                <a v-if="paper.arxiv_url || paper.arxiv_id" :href="paper.arxiv_url || `https://arxiv.org/abs/${paper.arxiv_id}`" target="_blank" class="pool-link">
                  arXiv
                </a>
                <a v-if="paper.pdf_url" :href="paper.pdf_url" target="_blank" class="pool-link">
                  PDF
                </a>
                <span v-if="isNew(paper)" class="new-badge">New</span>
                <button
                  v-if="!isImported(paper)"
                  class="btn btn-sm btn-success"
                  @click="importSingle(paper)"
                >Import</button>
                <span v-else class="imported-label">Imported</span>
              </div>
            </div>
          </div>

          <div v-if="!papersByTopic[topicName].length" class="topic-empty">
            No papers match filters
          </div>
        </div>
      </div>

      <div v-if="!Object.keys(papersByTopic).length" class="empty-browse">
        No pool papers found. Try adding topics or running a search.
      </div>
    </div>

    <!-- Topics & Graph Sub-tab -->
    <div v-if="activeTab === 'graph'" id="topics-graph-container" class="graph-tab">
      <!-- Left: Topic Cards -->
      <div class="topics-pane" :style="{ width: splitPosition + '%' }">
        <div class="topics-list">
          <div v-for="(topic, i) in pool.topics" :key="topic.name" class="topic-card" :style="{ borderLeftColor: getTopicColor(i) }">
            <div class="topic-card-header">
              <span class="topic-card-name">{{ topic.name }}</span>
              <span class="topic-card-count">{{ (topicStats[topic.name] || {}).observed || 0 }}</span>
            </div>
            <div class="topic-card-stats">
              <div class="topic-stat-row">
                <span>Observed: {{ (topicStats[topic.name] || {}).observed || 0 }}</span>
                <span>Imported: {{ (topicStats[topic.name] || {}).imported || 0 }}</span>
              </div>
              <div class="conversion-bar-track">
                <div
                  class="conversion-bar-fill"
                  :style="{
                    width: ((topicStats[topic.name] || {}).observed ? (((topicStats[topic.name] || {}).imported / (topicStats[topic.name] || {}).observed) * 100) : 0) + '%',
                    background: getTopicColor(i)
                  }"
                ></div>
              </div>
            </div>
            <div class="topic-card-actions">
              <button class="btn btn-sm btn-outline" @click="openSubGraph(topic.name)">Sub-graph</button>
              <button class="btn btn-sm btn-danger" @click="deleteTopic(topic.name)">Remove</button>
            </div>
          </div>
        </div>

        <!-- Add Topic -->
        <div class="add-topic-section">
          <button v-if="!showAddTopic" class="btn btn-sm btn-outline" @click="showAddTopic = true">
            + Add Topic
          </button>
          <div v-else class="add-topic-form">
            <input v-model="newTopicName" type="text" placeholder="Topic name" class="add-topic-input" />
            <input v-model="newTopicQuery" type="text" placeholder="Search query" class="add-topic-input" />
            <div class="add-topic-actions">
              <button class="btn btn-sm" @click="addTopic">Add</button>
              <button class="btn btn-sm btn-outline" @click="showAddTopic = false">Cancel</button>
            </div>
          </div>
        </div>
      </div>

      <!-- Draggable Divider -->
      <div class="split-divider" @mousedown="onSplitMouseDown">
        <div class="divider-handle"></div>
      </div>

      <!-- Right: D3 Graph -->
      <div class="graph-pane" :style="{ width: (100 - splitPosition) + '%' }">
        <div ref="graphContainer" class="graph-container"></div>
      </div>
    </div>

    <!-- Sub-graph Overlay -->
    <div v-if="showSubGraph" class="overlay-backdrop" @click.self="showSubGraph = false">
      <div class="overlay-fullscreen">
        <div class="overlay-header">
          <span class="overlay-title">Sub-graph: {{ subGraphTopic }}</span>
          <div class="overlay-header-actions">
            <button id="subgraph-fit-btn" class="btn btn-sm btn-outline">Fit</button>
            <button class="overlay-close" @click="showSubGraph = false">✕</button>
          </div>
        </div>
        <div id="subgraph-container" class="overlay-graph"></div>
      </div>
    </div>

    <!-- Node Preview Overlay -->
    <div v-if="showNodePreview" class="overlay-backdrop" @click.self="closeNodePreview">
      <div class="node-preview-overlay">
        <div class="overlay-header">
          <span class="overlay-title">Paper Preview</span>
          <button class="overlay-close" @click="closeNodePreview">✕</button>
        </div>
        <div class="node-preview-content">
          <h3 class="node-preview-title">{{ showNodePreview.title || 'Untitled' }}</h3>
          <div class="node-preview-meta">
            <span v-if="showNodePreview.authors">{{ formatAuthors(showNodePreview.authors) }}</span>
            <span v-if="showNodePreview.arxiv_id">ID: {{ showNodePreview.arxiv_id }}</span>
            <span v-if="showNodePreview.published">{{ showNodePreview.published }}</span>
          </div>
          <div v-if="showNodePreview.abstract" class="node-preview-abstract">
            {{ showNodePreview.abstract }}
          </div>
          <div class="node-preview-actions">
            <a
              v-if="showNodePreview.arxiv_id"
              :href="`https://arxiv.org/abs/${showNodePreview.arxiv_id}`"
              target="_blank"
              class="btn btn-sm btn-outline"
            >arXiv</a>
            <a
              v-if="showNodePreview.pdf_url"
              :href="showNodePreview.pdf_url"
              target="_blank"
              class="btn btn-sm btn-outline"
            >PDF</a>
            <button
              v-if="!isImported(showNodePreview)"
              class="btn btn-sm btn-success"
              @click="importSingle(showNodePreview); closeNodePreview()"
            >Import</button>
            <span v-else class="imported-label">Imported</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Import Progress Overlay -->
    <div v-if="importProgress" class="overlay-backdrop">
      <div class="progress-modal">
        <div class="progress-title">Importing Papers</div>
        <div class="progress-bar-track">
          <div
            class="progress-bar-fill"
            :style="{ width: (importProgress.total ? (importProgress.current / importProgress.total) * 100 : 0) + '%' }"
          ></div>
        </div>
        <div class="progress-count">{{ importProgress.current }} / {{ importProgress.total }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pool-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.insights-bar {
  display: flex;
  align-items: center;
  gap: 0;
  padding: 10px 16px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.insight-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 0 20px;
}

.insight-num {
  font-size: 20px;
  font-weight: 700;
  color: var(--text);
  line-height: 1.2;
}

.insight-num.accent { color: var(--accent); }

.insight-label {
  font-size: 10px;
  color: var(--text3);
  text-transform: uppercase;
  letter-spacing: 0.4px;
}

.insight-divider {
  width: 1px;
  height: 30px;
  background: var(--border);
}

.sub-tabs {
  display: flex;
  gap: 0;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  flex-shrink: 0;
}

.sub-tab {
  padding: 8px 20px;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text3);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}

.sub-tab:hover { color: var(--text2); }

.sub-tab.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

.pool-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  background: var(--surface2);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  flex-wrap: wrap;
}

.toolbar-search {
  display: flex;
  gap: 6px;
  flex: 1;
  min-width: 200px;
}

.toolbar-input {
  flex: 1;
}

.toolbar-select {
  width: 160px;
  flex-shrink: 0;
}

.toolbar-icon-btn {
  background: none;
  border: 1px solid var(--border);
  color: var(--text2);
  width: 32px;
  height: 32px;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  transition: background 0.15s;
}

.toolbar-icon-btn:hover {
  background: var(--surface);
  color: var(--text);
}

.batch-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-left: 10px;
  border-left: 1px solid var(--border);
}

.batch-count {
  font-size: 11px;
  color: var(--accent);
  font-weight: 600;
}

.browse-tab {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
}

.topic-group {
  margin-bottom: 16px;
}

.topic-group-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-left: 3px solid;
  border-radius: 8px;
  margin-bottom: 6px;
}

.topic-group-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.topic-group-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
}

.topic-group-count {
  font-size: 11px;
  color: var(--text3);
}

.topic-group-actions {
  display: flex;
  gap: 6px;
}

.topic-papers {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-left: 8px;
}

.pool-card {
  display: flex;
  gap: 10px;
  padding: 10px 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  transition: border-color 0.15s;
}

.pool-card:hover { border-color: var(--text3); }

.pool-card-left {
  display: flex;
  align-items: flex-start;
  padding-top: 2px;
  flex-shrink: 0;
}

.pool-checkbox {
  width: 16px;
  height: 16px;
  accent-color: var(--accent);
}

.imported-check {
  color: var(--green);
  font-size: 16px;
  font-weight: 700;
}

.pool-card-content {
  flex: 1;
  min-width: 0;
}

.pool-card-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  cursor: pointer;
  line-height: 1.4;
  margin-bottom: 3px;
}

.pool-card-title:hover { color: var(--accent); }

.pool-card-meta {
  font-size: 11px;
  color: var(--text3);
  margin-bottom: 4px;
}

.pool-card-authors { margin-right: 10px; }

.pool-card-abstract-wrap {
  margin-bottom: 4px;
}

.abstract-toggle {
  background: none;
  border: none;
  color: var(--text3);
  font-size: 11px;
  cursor: pointer;
  padding: 0;
}

.abstract-toggle:hover { color: var(--accent); }

.pool-card-abstract {
  font-size: 11px;
  color: var(--text2);
  line-height: 1.5;
  margin-top: 4px;
  padding: 8px;
  background: var(--bg);
  border-radius: 6px;
}

.pool-card-bottom {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.relevance-badge {
  font-size: 10px;
  background: var(--surface2);
  padding: 2px 6px;
  border-radius: 4px;
  color: var(--text3);
}

.pool-link {
  font-size: 11px;
  color: var(--accent);
  text-decoration: none;
}

.pool-link:hover { text-decoration: underline; }

.new-badge {
  font-size: 10px;
  background: var(--accent);
  color: #080c18;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 700;
}

.imported-label {
  font-size: 11px;
  color: var(--green);
  font-weight: 600;
}

.topic-empty, .empty-browse {
  padding: 20px;
  text-align: center;
  color: var(--text3);
  font-size: 12px;
}

/* Topics & Graph Tab */
.graph-tab {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.topics-pane {
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border);
  overflow: hidden;
}

.topics-list {
  flex: 1;
  overflow-y: auto;
  padding: 10px;
}

.topic-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-left: 3px solid;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 8px;
}

.topic-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.topic-card-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
}

.topic-card-count {
  font-size: 18px;
  font-weight: 700;
  color: var(--accent);
}

.topic-card-stats {
  margin-bottom: 8px;
}

.topic-stat-row {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--text3);
  margin-bottom: 4px;
}

.conversion-bar-track {
  height: 4px;
  background: var(--surface2);
  border-radius: 2px;
  overflow: hidden;
}

.conversion-bar-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s ease;
}

.topic-card-actions {
  display: flex;
  gap: 6px;
}

.add-topic-section {
  padding: 10px;
  border-top: 1px solid var(--border);
}

.add-topic-form {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.add-topic-input {
  width: 100%;
}

.add-topic-actions {
  display: flex;
  gap: 6px;
}

.split-divider {
  width: 6px;
  background: var(--border);
  cursor: col-resize;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background 0.15s;
}

.split-divider:hover { background: var(--accent); }

.divider-handle {
  width: 2px;
  height: 30px;
  background: var(--text3);
  border-radius: 1px;
}

.graph-pane {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.graph-container {
  flex: 1;
  background: var(--bg);
  overflow: hidden;
}

/* Overlays */
.overlay-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  backdrop-filter: blur(4px);
}

.overlay-fullscreen {
  width: 90vw;
  height: 90vh;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: var(--shadow);
}

.overlay-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  background: var(--surface2);
}

.overlay-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.overlay-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
}

.overlay-close {
  background: none;
  border: none;
  color: var(--text3);
  font-size: 18px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
  transition: background 0.15s;
}

.overlay-close:hover {
  background: var(--surface);
  color: var(--text);
}

.overlay-graph {
  flex: 1;
  background: var(--bg);
}

.node-preview-overlay {
  width: 500px;
  max-width: 90vw;
  max-height: 80vh;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow-y: auto;
  box-shadow: var(--shadow);
}

.node-preview-content {
  padding: 16px;
}

.node-preview-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 8px;
  line-height: 1.3;
}

.node-preview-meta {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 12px;
  color: var(--text3);
  margin-bottom: 12px;
}

.node-preview-abstract {
  font-size: 12px;
  color: var(--text2);
  line-height: 1.6;
  padding: 10px;
  background: var(--bg);
  border-radius: 8px;
  margin-bottom: 12px;
}

.node-preview-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.progress-modal {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 24px;
  min-width: 300px;
  box-shadow: var(--shadow);
}

.progress-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 12px;
}

.progress-bar-track {
  height: 6px;
  background: var(--surface2);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 6px;
}

.progress-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent), var(--accent2));
  border-radius: 3px;
  transition: width 0.3s ease;
}

.progress-count {
  font-size: 11px;
  color: var(--text3);
  text-align: right;
}
</style>
