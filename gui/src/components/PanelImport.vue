<script setup>
import { ref, onMounted } from 'vue'
import { useAppStore } from '../stores/app.js'
import { useGraphStore } from '../stores/graph.js'
import { addPaper, searchArxiv, importSearch, ingestWeb, getWebList } from '../api.js'

const app = useAppStore()
const graph = useGraphStore()

const activeTab = ref('arxiv')

const arxivInput = ref('')
const arxivLoading = ref(false)

const webUrl = ref('')
const webLoading = ref(false)
const webResult = ref(null)
const webList = ref([])

const searchQuery = ref('')
const searchLoading = ref(false)
const searchResults = ref([])

const tabs = [
  { id: 'arxiv', label: 'arXiv Paper' },
  { id: 'web', label: 'Web Link' },
  { id: 'search', label: 'Search' }
]

function extractArxivId(input) {
  const trimmed = input.trim()
  const urlMatch = trimmed.match(/arxiv\.org\/(?:abs|pdf|html)\/(\d{4}\.\d{4,5}(?:v\d+)?)/i)
  if (urlMatch) return urlMatch[1]
  if (/^\d{4}\.\d{4,5}(?:v\d+)?$/.test(trimmed)) return trimmed
  return null
}

async function handleAddPaper() {
  const id = extractArxivId(arxivInput.value)
  if (!id) {
    app.addLog('Invalid arXiv ID or URL', 'ERROR')
    return
  }
  arxivLoading.value = true
  try {
    await addPaper(id)
    app.addLog(`Added paper: ${id}`, 'DONE')
    arxivInput.value = ''
    await graph.fetchGraph()
  } catch (e) {
    app.addLog(`Failed to add paper: ${e.message}`, 'ERROR')
  }
  arxivLoading.value = false
}

async function handleIngestWeb() {
  if (!webUrl.value.trim()) return
  webLoading.value = true
  webResult.value = null
  try {
    const data = await ingestWeb(webUrl.value.trim())
    webResult.value = data
    app.addLog(`Web link ingested: ${webUrl.value.trim()}`, 'DONE')
    webUrl.value = ''
    await fetchWebList()
  } catch (e) {
    app.addLog(`Web ingest failed: ${e.message}`, 'ERROR')
  }
  webLoading.value = false
}

async function fetchWebList() {
  try {
    const data = await getWebList()
    webList.value = data.articles || data.web || data || []
  } catch (e) {
    console.error('Failed to fetch web list:', e)
  }
}

async function handleSearch() {
  if (!searchQuery.value.trim()) return
  searchLoading.value = true
  searchResults.value = []
  try {
    const data = await searchArxiv(searchQuery.value.trim())
    searchResults.value = data.results || data.papers || data || []
    if (!searchResults.value.length) {
      app.addLog('No search results found', 'INFO')
    }
  } catch (e) {
    app.addLog(`Search failed: ${e.message}`, 'ERROR')
  }
  searchLoading.value = false
}

async function handleImportResult(item) {
  try {
    const id = item.id || item.arxiv_id
    await addPaper(id)
    app.addLog(`Imported: ${item.title || id}`, 'DONE')
  } catch (e) {
    app.addLog(`Import failed: ${e.message}`, 'ERROR')
  }
}

async function handleImportAll() {
  if (!searchResults.value.length) return
  app.addLog(`Importing ${searchResults.value.length} papers...`, 'INFO')
  for (const item of searchResults.value) {
    try {
      const id = item.id || item.arxiv_id
      await importSearch(id)
      app.addLog(`Imported: ${item.title || id}`, 'DONE')
    } catch (e) {
      app.addLog(`Import failed for ${item.title || item.id}: ${e.message}`, 'WARN')
    }
  }
  await graph.fetchGraph()
  app.addLog('Batch import complete', 'DONE')
}

function formatAuthors(authors) {
  if (!authors) return ''
  if (typeof authors === 'string') return authors
  if (Array.isArray(authors)) return authors.map(a => a.name || a).join(', ')
  return String(authors)
}

function formatDate(date) {
  if (!date) return ''
  try {
    return new Date(date).toLocaleDateString()
  } catch {
    return date
  }
}

onMounted(() => {
  fetchWebList()
})
</script>

<template>
  <div class="panel-import">
    <div class="panel-header">
      <span class="panel-title">Import</span>
    </div>

    <div class="import-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        :class="['tab-btn', { active: activeTab === tab.id }]"
        @click="activeTab = tab.id"
      >
        {{ tab.label }}
      </button>
    </div>

    <div class="tab-content">
      <div v-if="activeTab === 'arxiv'" class="tab-panel">
        <div class="input-row">
          <input
            v-model="arxivInput"
            @keydown.enter="handleAddPaper"
            placeholder="arXiv ID or URL (e.g. 1706.03762)"
            class="import-input"
          />
          <button
            class="btn"
            @click="handleAddPaper"
            :disabled="arxivLoading || !arxivInput.trim()"
          >
            <span v-if="arxivLoading" class="spinner"></span>
            {{ arxivLoading ? 'Adding...' : 'Add Paper' }}
          </button>
        </div>
        <p class="input-hint">
          Enter an arXiv ID (1706.03762) or a full URL (https://arxiv.org/abs/1706.03762)
        </p>
      </div>

      <div v-if="activeTab === 'web'" class="tab-panel">
        <div class="input-row">
          <input
            v-model="webUrl"
            @keydown.enter="handleIngestWeb"
            placeholder="https://example.com/article"
            class="import-input"
          />
          <button
            class="btn"
            @click="handleIngestWeb"
            :disabled="webLoading || !webUrl.trim()"
          >
            <span v-if="webLoading" class="spinner"></span>
            {{ webLoading ? 'Ingesting...' : 'Ingest Web Link' }}
          </button>
        </div>

        <div v-if="webResult" class="web-result card">
          <div class="card-header">Ingested successfully</div>
          <p v-if="webResult.title" class="result-title">{{ webResult.title }}</p>
          <p v-if="webResult.summary" class="result-summary">{{ webResult.summary }}</p>
        </div>

        <div v-if="webList.length" class="web-list">
          <h4 class="list-heading">Ingested Web Articles</h4>
          <div
            v-for="(article, i) in webList"
            :key="article.id || i"
            class="web-item card"
          >
            <p class="web-title">{{ article.title || article.url }}</p>
            <a v-if="article.url" :href="article.url" target="_blank" class="web-url">{{ article.url }}</a>
            <p v-if="article.summary" class="web-summary">{{ article.summary }}</p>
          </div>
        </div>
      </div>

      <div v-if="activeTab === 'search'" class="tab-panel">
        <div class="input-row">
          <input
            v-model="searchQuery"
            @keydown.enter="handleSearch"
            placeholder="Search arXiv papers..."
            class="import-input"
          />
          <button
            class="btn"
            @click="handleSearch"
            :disabled="searchLoading || !searchQuery.trim()"
          >
            <span v-if="searchLoading" class="spinner"></span>
            {{ searchLoading ? 'Searching...' : 'Search' }}
          </button>
          <button
            v-if="searchResults.length"
            class="btn btn-success"
            @click="handleImportAll"
            :disabled="searchLoading"
          >
            Import All ({{ searchResults.length }})
          </button>
        </div>

        <div v-if="searchResults.length" class="search-results">
          <div
            v-for="item in searchResults"
            :key="item.id || item.arxiv_id"
            class="search-card card"
            @click="handleImportResult(item)"
          >
            <div class="search-card-header">
              <h4 class="search-title">{{ item.title }}</h4>
              <span class="search-id">{{ item.id || item.arxiv_id }}</span>
            </div>
            <p v-if="item.authors" class="search-authors">{{ formatAuthors(item.authors) }}</p>
            <p v-if="item.published || item.date" class="search-date">{{ formatDate(item.published || item.date) }}</p>
            <p v-if="item.abstract" class="search-abstract">{{ item.abstract }}</p>
            <div v-if="item.categories?.length" class="search-cats">
              <span v-for="cat in item.categories" :key="cat" class="cat-tag">{{ cat }}</span>
            </div>
            <span class="search-import-hint">Click to import</span>
          </div>
        </div>

        <div v-else-if="!searchLoading && searchQuery" class="empty-hint">
          No results. Try a different query.
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.panel-import {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.panel-header {
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  flex-shrink: 0;
}

.panel-title {
  font-weight: 600;
  font-size: 13px;
}

.import-tabs {
  display: flex;
  gap: 2px;
  padding: 8px 14px 0;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.tab-btn {
  background: none;
  border: none;
  color: var(--text3);
  font-size: 12px;
  padding: 8px 14px;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all 0.15s;
  font-weight: 500;
}

.tab-btn:hover {
  color: var(--text2);
}

.tab-btn.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

.tab-content {
  flex: 1;
  overflow-y: auto;
  padding: 14px;
}

.tab-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.input-row {
  display: flex;
  gap: 8px;
  align-items: stretch;
}

.import-input {
  flex: 1;
}

.input-hint {
  font-size: 11px;
  color: var(--text3);
  margin-top: -4px;
}

.spinner {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid rgba(8, 12, 24, 0.3);
  border-top-color: #080c18;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
  margin-right: 4px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.web-result {
  border-color: var(--green);
}

.result-title {
  font-weight: 600;
  font-size: 13px;
  margin-bottom: 4px;
}

.result-summary {
  font-size: 12px;
  color: var(--text2);
  line-height: 1.5;
}

.web-list {
  margin-top: 8px;
}

.list-heading {
  font-size: 12px;
  font-weight: 600;
  color: var(--text2);
  margin-bottom: 8px;
}

.web-item {
  margin-bottom: 6px;
}

.web-title {
  font-weight: 600;
  font-size: 12px;
  margin-bottom: 2px;
}

.web-url {
  font-size: 11px;
  color: var(--accent);
  word-break: break-all;
}

.web-summary {
  font-size: 11px;
  color: var(--text2);
  margin-top: 4px;
  line-height: 1.4;
}

.search-results {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
}

.search-card {
  cursor: pointer;
  transition: all 0.15s;
  padding: 12px;
}

.search-card:hover {
  border-color: var(--accent);
  background: var(--surface2);
}

.search-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 4px;
}

.search-title {
  font-size: 13px;
  font-weight: 600;
  line-height: 1.3;
  flex: 1;
}

.search-id {
  font-size: 10px;
  color: var(--text3);
  font-family: monospace;
  flex-shrink: 0;
}

.search-authors {
  font-size: 11px;
  color: var(--text2);
  margin-bottom: 2px;
}

.search-date {
  font-size: 10px;
  color: var(--text3);
  margin-bottom: 4px;
}

.search-abstract {
  font-size: 11px;
  color: var(--text3);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  margin-bottom: 6px;
}

.search-cats {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}

.cat-tag {
  font-size: 9px;
  background: var(--surface2);
  color: var(--text3);
  padding: 1px 6px;
  border-radius: 4px;
  font-family: monospace;
}

.search-import-hint {
  font-size: 10px;
  color: var(--accent);
  opacity: 0;
  transition: opacity 0.15s;
}

.search-card:hover .search-import-hint {
  opacity: 1;
}

.empty-hint {
  text-align: center;
  color: var(--text3);
  font-size: 12px;
  padding: 24px 0;
}
</style>
