<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useAppStore } from '../stores/app.js'
import { useGraphStore } from '../stores/graph.js'
import { getPapers, getSimilarity } from '../api.js'

const app = useAppStore()
const graph = useGraphStore()

const allPapers = ref([])
const searchQuery = ref('')
const selectedPapers = ref([])
const algorithm = ref('combined')
const loading = ref(false)
const results = ref(null)
const viewMode = ref('list')
const showResults = ref(false)

const algorithms = [
  { value: 'combined', label: 'Combined' },
  { value: 'vector_combined', label: 'Vector Combined' },
  { value: 'vector', label: 'Vector' },
  { value: 'abstract', label: 'Abstract' },
  { value: 'author', label: 'Author' },
  { value: 'concept', label: 'Concept' }
]

const filteredPapers = computed(() => {
  const q = searchQuery.value.toLowerCase().trim()
  if (!q) return []
  return allPapers.value
    .filter(p => {
      const id = (p.id || p.arxiv_id || '').toLowerCase()
      const title = (p.title || '').toLowerCase()
      return (id.includes(q) || title.includes(q)) &&
        !selectedPapers.value.find(s => s.id === p.id)
    })
    .slice(0, 20)
})

const matrixLabels = computed(() => {
  if (!results.value?.matrix) return []
  return results.value.matrix.map(m => m.paper_id)
})

function similarityColor(score) {
  if (score > 30) return 'var(--green)'
  if (score > 15) return 'var(--yellow)'
  return 'var(--red)'
}

function matrixCellColor(score) {
  if (score == null) return 'transparent'
  const max = 100
  const ratio = Math.min(score / max, 1)
  if (ratio > 0.3) return 'var(--green)'
  if (ratio > 0.15) return 'var(--yellow)'
  return 'var(--red)'
}

function addPaper(paper) {
  if (!selectedPapers.value.find(p => p.id === paper.id)) {
    selectedPapers.value.push(paper)
  }
  searchQuery.value = ''
}

function removePaper(index) {
  selectedPapers.value.splice(index, 1)
}

function paperLabel(p) {
  const id = p.id || p.arxiv_id || ''
  const title = p.title || ''
  return title.length > 40 ? title.slice(0, 37) + '...' : (title || id)
}

async function compute() {
  if (selectedPapers.value.length < 2) return
  loading.value = true
  showResults.value = false
  try {
    const ids = selectedPapers.value.map(p => p.id || p.arxiv_id)
    results.value = await getSimilarity(ids, algorithm.value)
    showResults.value = true
  } catch (e) {
    console.error('Similarity computation failed:', e)
    app.addLog(`Similarity failed: ${e.message}`, 'ERROR')
  } finally {
    loading.value = false
  }
}

function clearAll() {
  selectedPapers.value = []
  results.value = null
  showResults.value = false
  searchQuery.value = ''
}

function getMatrixCellScore(aIdx, bIdx) {
  if (!results.value?.matrix) return null
  if (aIdx === bIdx) return 100
  const row = results.value.matrix[aIdx]
  if (!row?.scores) return null
  const entry = row.scores.find(s => s.paper_id === matrixLabels.value[bIdx])
  return entry?.score ?? null
}

onMounted(async () => {
  try {
    const data = await getPapers()
    allPapers.value = data.papers || data || []
  } catch (e) {
    console.error('Failed to load papers:', e)
  }
})
</script>

<template>
  <div class="similarity-panel">
    <div class="card paper-selector">
      <div class="card-header">Paper Selector</div>
      <div class="search-wrap">
        <input
          v-model="searchQuery"
          type="text"
          placeholder="Search papers by title or ID..."
          class="search-input"
        />
        <ul v-if="filteredPapers.length" class="dropdown-list">
          <li
            v-for="p in filteredPapers"
            :key="p.id"
            class="dropdown-item"
            @click="addPaper(p)"
          >
            <span class="dropdown-id">{{ p.id || p.arxiv_id }}</span>
            <span class="dropdown-title">{{ p.title }}</span>
          </li>
        </ul>
      </div>
      <div v-if="selectedPapers.length" class="selected-chips">
        <span
          v-for="(p, i) in selectedPapers"
          :key="p.id"
          class="chip"
        >
          <span class="chip-label" :title="p.title">{{ paperLabel(p) }}</span>
          <button class="chip-remove" @click="removePaper(i)">✕</button>
        </span>
      </div>
      <div v-else class="empty-hint">No papers selected. Search above to add papers.</div>
    </div>

    <div class="controls-row">
      <select v-model="algorithm" class="algo-select">
        <option v-for="a in algorithms" :key="a.value" :value="a.value">{{ a.label }}</option>
      </select>
      <button class="btn" :disabled="selectedPapers.length < 2 || loading" @click="compute">
        {{ loading ? 'Computing...' : 'Compute' }}
      </button>
      <button class="btn btn-outline" @click="clearAll">Clear</button>
    </div>

    <div v-if="showResults" class="view-toggle">
      <button
        :class="['toggle-btn', { active: viewMode === 'list' }]"
        @click="viewMode = 'list'"
      >List</button>
      <button
        :class="['toggle-btn', { active: viewMode === 'matrix' }]"
        @click="viewMode = 'matrix'"
      >Matrix</button>
    </div>

    <div v-if="showResults && viewMode === 'list' && results?.pairs" class="results-list">
      <div class="results-scroll">
        <table class="sim-table">
          <thead>
            <tr>
              <th>Paper A</th>
              <th>Paper B</th>
              <th>Similarity</th>
              <th>Author Overlap</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(pair, idx) in results.pairs" :key="idx">
              <td class="paper-cell">{{ pair.paper_a?.title || pair.paper_a?.id || pair.paper_a }}</td>
              <td class="paper-cell">{{ pair.paper_b?.title || pair.paper_b?.id || pair.paper_b }}</td>
              <td class="score-cell">
                <span
                  class="score-badge"
                  :style="{ background: similarityColor(pair.score) }"
                >
                  {{ pair.score != null ? pair.score.toFixed(1) + '%' : '—' }}
                </span>
              </td>
              <td class="overlap-cell">
                {{ pair.author_overlap != null ? pair.author_overlap : '—' }}
              </td>
            </tr>
            <tr v-if="!results.pairs.length">
              <td colspan="4" class="empty-cell">No similarity pairs found.</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="showResults && viewMode === 'matrix' && results?.matrix" class="results-matrix">
      <div class="matrix-scroll">
        <table class="matrix-table">
          <thead>
            <tr>
              <th class="corner-cell"></th>
              <th v-for="label in matrixLabels" :key="label" class="matrix-header">
                <span class="matrix-label" :title="label">{{ label }}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, aIdx) in matrixLabels" :key="row">
              <th class="row-header">
                <span class="matrix-label" :title="row">{{ row }}</span>
              </th>
              <td
                v-for="(_, bIdx) in matrixLabels"
                :key="bIdx"
                class="matrix-cell"
              >
                <span
                  class="cell-score"
                  v-if="aIdx === bIdx"
                  style="opacity: 0.3;"
                >—</span>
                <span
                  v-else
                  class="cell-score"
                  :style="{ color: matrixCellColor(getMatrixCellScore(aIdx, bIdx)) }"
                >{{ getMatrixCellScore(aIdx, bIdx) != null ? getMatrixCellScore(aIdx, bIdx).toFixed(1) : '—' }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="matrix-legend">
        <span class="legend-item"><span class="legend-dot" style="background:var(--red)"></span> Low</span>
        <span class="legend-item"><span class="legend-dot" style="background:var(--yellow)"></span> Medium</span>
        <span class="legend-item"><span class="legend-dot" style="background:var(--green)"></span> High</span>
      </div>
    </div>

    <div v-if="loading" class="loading-overlay">
      <div class="spinner"></div>
      <span>Computing similarity...</span>
    </div>
  </div>
</template>

<style scoped>
.similarity-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  overflow: hidden;
}

.paper-selector {
  flex-shrink: 0;
}

.search-wrap {
  position: relative;
}

.search-input {
  width: 100%;
}

.dropdown-list {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  z-index: 30;
  max-height: 240px;
  overflow-y: auto;
  background: var(--glass-bg4);
  backdrop-filter: blur(8px);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin-top: 4px;
  list-style: none;
}

.dropdown-item {
  display: flex;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 12px;
  transition: background 0.15s;
}

.dropdown-item:hover {
  background: var(--surface2);
}

.dropdown-id {
  color: var(--accent);
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
}

.dropdown-title {
  color: var(--text2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selected-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 3px 10px 3px 10px;
  font-size: 11px;
}

.chip-label {
  color: var(--text);
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chip-remove {
  background: none;
  border: none;
  color: var(--text3);
  cursor: pointer;
  padding: 0 2px;
  font-size: 11px;
  line-height: 1;
  transition: color 0.15s;
}

.chip-remove:hover {
  color: var(--red);
}

.empty-hint {
  margin-top: 10px;
  font-size: 11px;
  color: var(--text3);
  font-style: italic;
}

.controls-row {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-shrink: 0;
}

.algo-select {
  flex: 1;
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

.results-list {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.results-scroll {
  height: 100%;
  overflow-y: auto;
}

.sim-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.sim-table th {
  position: sticky;
  top: 0;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 8px 10px;
  text-align: left;
  font-size: 10px;
  font-weight: 600;
  color: var(--text3);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  z-index: 2;
}

.sim-table td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
  color: var(--text);
}

.sim-table tr:hover td {
  background: var(--surface2);
}

.paper-cell {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.score-cell {
  white-space: nowrap;
}

.score-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 12px;
  font-weight: 700;
  font-size: 11px;
  color: #080c18;
}

.overlap-cell {
  color: var(--text2);
}

.empty-cell {
  text-align: center;
  color: var(--text3);
  font-style: italic;
}

.results-matrix {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.matrix-scroll {
  flex: 1;
  overflow: auto;
}

.matrix-table {
  border-collapse: collapse;
  font-size: 11px;
}

.matrix-table th,
.matrix-table td {
  padding: 4px 6px;
  border: 1px solid var(--border);
  text-align: center;
  white-space: nowrap;
}

.corner-cell {
  background: var(--surface);
}

.matrix-header {
  background: var(--surface);
  writing-mode: vertical-rl;
  text-orientation: mixed;
  transform: rotate(180deg);
  max-width: 36px;
  font-weight: 600;
  color: var(--text2);
}

.row-header {
  background: var(--surface);
  font-weight: 600;
  color: var(--text2);
  text-align: right;
  padding-right: 8px;
}

.matrix-cell {
  background: var(--bg);
  min-width: 52px;
  cursor: default;
}

.matrix-cell:hover {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}

.cell-score {
  font-weight: 600;
  font-size: 11px;
}

.matrix-label {
  display: inline-block;
  max-width: 80px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.matrix-legend {
  display: flex;
  gap: 14px;
  justify-content: center;
  padding: 8px 0 2px;
  flex-shrink: 0;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--text3);
}

.legend-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
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
</style>
