<script setup>
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { useAppStore } from '../stores/app.js'
import { useGraphStore } from '../stores/graph.js'
import { usePoolStore } from '../stores/pool.js'
import { getBrowse, readFile, getDigests, getHelpNoob, refreshPaper, fetchLineage, getDuplicatePapers } from '../api.js'

const app = useAppStore()
const graph = useGraphStore()
const pool = usePoolStore()

const papers = ref([])
const selectedPaper = ref(null)
const searchQuery = ref('')
const sidebarCollapsed = ref(false)
const topPanelCollapsed = ref(false)
const expandedFolders = ref({})
const previewContent = ref('')
const previewPath = ref('')
const previewLoading = ref(false)
const digestsContent = ref('')
const digestsLoading = ref(false)
const helpNoobContent = ref('')
const helpNoobLoading = ref(false)
const lineageData = ref(null)
const lineageLoading = ref(false)
const duplicateData = ref(null)
const duplicateLoading = ref(false)
const regenerateProgress = ref(null)
const regenerateRunning = ref(false)
const refreshInProgress = ref(false)
const notesExpanded = ref(false)
const helpNoobExpanded = ref(false)

const CONCEPT_TICKER = '🔗'

function filterPapers(papers, query) {
  if (!query) return papers
  const q = query.toLowerCase()
  return papers.filter(p => {
    const title = (p.title || '').toLowerCase()
    const authors = (p.authors || []).join(' ').toLowerCase()
    const affiliations = (p.affiliations || []).join(' ').toLowerCase()
    return title.includes(q) || authors.includes(q) || affiliations.includes(q)
  })
}

const filteredPapers = computed(() => filterPapers(papers.value, searchQuery.value))

function formatAuthors(authors) {
  if (!authors || !authors.length) return ''
  return authors.join(', ')
}

function formatAffiliations(affiliations) {
  if (!affiliations || !affiliations.length) return ''
  return affiliations.join('; ')
}

function renderMarkdown(text) {
  if (!text) return ''
  let html = text

  // YAML frontmatter beautification
  html = html.replace(/^---\n([\s\S]*?)\n---\n/, (match, frontmatter) => {
    const lines = frontmatter.split('\n').map(l => {
      const [key, ...rest] = l.split(':')
      if (rest.length) return `<div style="margin:2px 0"><span style="color:var(--accent)">${key.trim()}:</span> ${rest.join(':').trim()}</div>`
      return `<div>${l}</div>`
    }).join('')
    return `<div style="background:var(--surface2);padding:8px 12px;border-radius:8px;margin-bottom:12px;border:1px solid var(--border);font-size:12px">${lines}</div>`
  })

  // Code blocks (``` ... ```)
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (m, lang, code) => {
    return `<pre style="background:var(--surface2);padding:10px 14px;border-radius:8px;overflow-x:auto;font-size:11.5px;border:1px solid var(--border)"><code>${escapeHtml(code.trim())}</code></pre>`
  })

  // Headers
  html = html.replace(/^#### (.+)$/gm, '<h4 style="font-size:13px;margin:12px 0 6px;color:var(--text)">$1</h4>')
  html = html.replace(/^### (.+)$/gm, '<h3 style="font-size:14px;margin:14px 0 8px;color:var(--text)">$1</h3>')
  html = html.replace(/^## (.+)$/gm, '<h2 style="font-size:16px;margin:16px 0 8px;color:var(--text)">$1</h2>')
  html = html.replace(/^# (.+)$/gm, '<h1 style="font-size:18px;margin:18px 0 10px;color:var(--text)">$1</h1>')

  // Bold and italic
  html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>')

  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>')

  // Links
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')

  // Images
  html = html.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (m, alt, src) => {
    const apiSrc = src.startsWith('http') ? src : `/api/raw?path=${encodeURIComponent(src)}`
    return `<img src="${apiSrc}" alt="${alt}" style="max-width:100%;border-radius:8px;margin:4px 0" />`
  })

  // Unordered lists
  html = html.replace(/^[\-\*] (.+)$/gm, '<li style="margin:2px 0;margin-left:16px;list-style:disc">$1</li>')

  // Ordered lists
  html = html.replace(/^\d+\. (.+)$/gm, '<li style="margin:2px 0;margin-left:16px;list-style:decimal">$1</li>')

  // Line breaks / paragraphs
  html = html.replace(/\n\n/g, '<br/><br/>')
  html = html.replace(/\n/g, '<br/>')

  return html
}

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function getFileGroups(paper) {
  const files = paper.files || []
  const groups = { pdfs: [], notes: [], other: [] }
  for (const f of files) {
    const name = typeof f === 'string' ? f : f.name || f.path || ''
    const lower = name.toLowerCase()
    if (lower.endsWith('.pdf')) groups.pdfs.push(f)
    else if (lower.endsWith('.md') || lower.includes('note')) groups.notes.push(f)
    else groups.other.push(f)
  }
  return groups
}

function getFileName(file) {
  if (typeof file === 'string') {
    const parts = file.split('/')
    return parts[parts.length - 1]
  }
  return file.name || file.path || String(file)
}

function getFilePath(file) {
  if (typeof file === 'string') return file
  return file.path || file.name || String(file)
}

function toggleFolder(key) {
  expandedFolders.value[key] = !expandedFolders.value[key]
}

async function loadPaper(paper) {
  selectedPaper.value = paper
  previewContent.value = ''
  previewPath.value = ''
  digestsContent.value = ''
  helpNoobContent.value = ''
  lineageData.value = null
  duplicateData.value = null
  notesExpanded.value = false
  helpNoobExpanded.value = false

  const arxivId = paper.arxiv_id || paper.id || paper.paper_id
  if (arxivId) {
    // Auto-open 00_notes.md
    const notesFile = (paper.files || []).find(f => {
      const name = getFileName(f)
      return name === '00_notes.md' || name.endsWith('/00_notes.md')
    })
    if (notesFile) {
      await openFile(notesFile)
    }
  }
}

async function openFile(file) {
  const filePath = getFilePath(file)
  previewLoading.value = true
  previewPath.value = filePath
  try {
    const data = await readFile(filePath)
    previewContent.value = data.content || data.text || ''
  } catch (e) {
    previewContent.value = `Error loading file: ${e.message}`
  } finally {
    previewLoading.value = false
  }
}

async function loadDigests(paper) {
  const paperId = paper.arxiv_id || paper.id || paper.paper_id
  if (!paperId) return
  digestsLoading.value = true
  notesExpanded.value = true
  try {
    const data = await getDigests(paperId)
    digestsContent.value = data.content || data.digests || data.text || JSON.stringify(data)
  } catch (e) {
    digestsContent.value = `Error loading digests: ${e.message}`
  } finally {
    digestsLoading.value = false
  }
}

async function loadHelpNoob(paper) {
  const paperId = paper.arxiv_id || paper.id || paper.paper_id
  if (!paperId) return
  helpNoobLoading.value = true
  helpNoobExpanded.value = true
  try {
    const data = await getHelpNoob(paperId)
    helpNoobContent.value = data.content || data.text || JSON.stringify(data)
  } catch (e) {
    helpNoobContent.value = `Error loading help-noob: ${e.message}`
  } finally {
    helpNoobLoading.value = false
  }
}

async function loadLineage(paper) {
  const arxivId = paper.arxiv_id || paper.id
  if (!arxivId) return
  lineageLoading.value = true
  try {
    const data = await fetchLineage(arxivId)
    lineageData.value = data
  } catch (e) {
    lineageData.value = { error: e.message }
  } finally {
    lineageLoading.value = false
  }
}

async function loadDuplicates(paper) {
  const paperId = paper.arxiv_id || paper.id || paper.paper_id
  if (!paperId) return
  duplicateLoading.value = true
  try {
    const data = await getDuplicatePapers(paperId)
    duplicateData.value = data
  } catch (e) {
    duplicateData.value = { error: e.message }
  } finally {
    duplicateLoading.value = false
  }
}

async function refreshSinglePaper(paper) {
  const paperId = paper.arxiv_id || paper.id || paper.paper_id
  if (!paperId) return
  refreshInProgress.value = true
  try {
    await refreshPaper(paperId, app.selectedModel || null)
    app.addLog(`Refreshed paper ${paperId}`, 'DONE')
    await loadBrowse()
  } catch (e) {
    app.addLog(`Refresh failed: ${e.message}`, 'ERROR')
  } finally {
    refreshInProgress.value = false
  }
}

async function regenerateAll() {
  if (regenerateRunning.value) return
  regenerateRunning.value = true
  regenerateProgress.value = { current: 0, total: papers.value.length, message: 'Starting...' }

  for (let i = 0; i < papers.value.length; i++) {
    const paper = papers.value[i]
    const paperId = paper.arxiv_id || paper.id || paper.paper_id
    regenerateProgress.value = {
      current: i + 1,
      total: papers.value.length,
      message: `Refreshing ${getPaperTitle(paper)}...`
    }
    try {
      await refreshPaper(paperId, app.selectedModel || null)
    } catch (e) {
      app.addLog(`Failed to refresh ${paperId}: ${e.message}`, 'WARN')
    }
  }

  regenerateProgress.value = { current: papers.value.length, total: papers.value.length, message: 'Done!' }
  app.addLog('Regenerate all complete', 'DONE')
  await loadBrowse()
  regenerateRunning.value = false
}

function cancelRegenerate() {
  regenerateRunning.value = false
  regenerateProgress.value = null
}

function getPaperTitle(paper) {
  const title = paper.title || 'Untitled'
  return title.length > 80 ? title.substring(0, 77) + '...' : title
}

function hasNotes(paper) {
  return (paper.files || []).some(f => {
    const name = getFileName(f).toLowerCase()
    return name.endsWith('.md') || name.includes('note')
  })
}

function hasLineage(paper) {
  return !!(paper.lineage || paper.citation_count)
}

function hasDuplicates(paper) {
  return !!(paper.duplicate_count || paper.duplicates)
}

async function loadBrowse() {
  try {
    const data = await getBrowse()
    papers.value = data.papers || data
  } catch (e) {
    app.addLog(`Failed to load browse: ${e.message}`, 'ERROR')
  }
}

watch(selectedPaper, (paper) => {
  if (paper) {
    const arxivId = paper.arxiv_id || paper.id || paper.paper_id
    if (arxivId) {
      loadLineage(paper)
    }
  }
})

onMounted(() => {
  loadBrowse()
})
</script>

<template>
  <div class="browse-panel">
    <!-- Left Sidebar: Paper List -->
    <div class="browse-sidebar" :class="{ collapsed: sidebarCollapsed }">
      <div class="sidebar-header">
        <input
          v-if="!sidebarCollapsed"
          v-model="searchQuery"
          type="text"
          placeholder="Search papers..."
          class="search-input"
        />
        <button class="toggle-btn" @click="sidebarCollapsed = !sidebarCollapsed" :title="sidebarCollapsed ? 'Expand' : 'Collapse'">
          {{ sidebarCollapsed ? '▶' : '◀' }}
        </button>
      </div>

      <div v-if="!sidebarCollapsed" class="paper-list">
        <div
          v-for="paper in filteredPapers"
          :key="paper.arxiv_id || paper.id || paper.paper_id"
          :class="['paper-item', { active: selectedPaper && (selectedPaper.arxiv_id || selectedPaper.id) === (paper.arxiv_id || paper.id) }]"
          @click="loadPaper(paper)"
        >
          <div class="paper-item-title">{{ getPaperTitle(paper) }}</div>
          <div class="paper-item-meta">
            <span v-if="paper.authors && paper.authors.length" class="paper-item-authors">
              {{ paper.authors[0] }}{{ paper.authors.length > 1 ? ' et al.' : '' }}
            </span>
          </div>
          <div class="paper-item-badges">
            <span v-if="hasNotes(paper)" class="badge badge-green" title="Has notes">N</span>
            <span v-if="hasLineage(paper)" class="badge badge-cyan" title="Has lineage">L</span>
            <span v-if="hasDuplicates(paper)" class="badge badge-yellow" title="Has duplicates">D</span>
          </div>
          <button
            class="refresh-btn"
            @click.stop="refreshSinglePaper(paper)"
            :disabled="refreshInProgress"
            title="Refresh paper"
          >
            ↻
          </button>
        </div>

        <div v-if="!filteredPapers.length" class="empty-list">
          {{ searchQuery ? 'No matching papers' : 'No papers loaded' }}
        </div>
      </div>
    </div>

    <!-- Toggle button between left/right -->
    <button class="sidebar-toggle" @click="sidebarCollapsed = !sidebarCollapsed">
      {{ sidebarCollapsed ? '▶' : '◀' }}
    </button>

    <!-- Right Area: Paper Detail -->
    <div class="browse-detail">
      <template v-if="selectedPaper">
        <!-- Paper Header -->
        <div class="paper-header">
          <h2 class="paper-title">{{ selectedPaper.title || 'Untitled' }}</h2>
          <div class="paper-meta-row">
            <span v-if="selectedPaper.authors && selectedPaper.authors.length" class="paper-authors">
              {{ formatAuthors(selectedPaper.authors) }}
            </span>
          </div>
          <div class="paper-meta-row">
            <span v-if="selectedPaper.arxiv_id || selectedPaper.id" class="paper-id">
              ID: {{ selectedPaper.arxiv_id || selectedPaper.id }}
            </span>
            <span v-if="selectedPaper.published || selectedPaper.date" class="paper-date">
              Published: {{ selectedPaper.published || selectedPaper.date }}
            </span>
          </div>
          <div v-if="selectedPaper.affiliations && selectedPaper.affiliations.length" class="paper-meta-row">
            <span class="paper-affiliations">{{ formatAffiliations(selectedPaper.affiliations) }}</span>
          </div>
          <div v-if="selectedPaper.concept || selectedPaper.concept_ticker" class="paper-meta-row">
            <span class="concept-badge">{{ CONCEPT_TICKER }} {{ selectedPaper.concept || selectedPaper.concept_ticker }}</span>
          </div>
        </div>

        <!-- Collapsible Top Panel -->
        <div class="top-panel" :class="{ collapsed: topPanelCollapsed }">
          <button class="panel-collapse-btn" @click="topPanelCollapsed = !topPanelCollapsed">
            {{ topPanelCollapsed ? '▼ Details' : '▲ Details' }}
          </button>

          <div v-show="!topPanelCollapsed" class="panel-content">
            <!-- File Groups -->
            <div class="file-groups" v-if="selectedPaper.files && selectedPaper.files.length">
              <div class="file-group">
                <div class="folder-header" @click="toggleFolder('pdfs')">
                  <span class="folder-icon">{{ expandedFolders.pdfs ? '📂' : '📁' }}</span>
                  <span class="folder-label">PDFs</span>
                  <span class="folder-count">{{ getFileGroups(selectedPaper).pdfs.length }}</span>
                </div>
                <div v-if="expandedFolders.pdfs" class="folder-items">
                  <div
                    v-for="(file, i) in getFileGroups(selectedPaper).pdfs"
                    :key="'pdf-' + i"
                    class="file-item"
                    @click="openFile(file)"
                  >
                    {{ getFileName(file) }}
                  </div>
                </div>
              </div>

              <div class="file-group">
                <div class="folder-header" @click="toggleFolder('notes')">
                  <span class="folder-icon">{{ expandedFolders.notes ? '📂' : '📁' }}</span>
                  <span class="folder-label">Notes</span>
                  <span class="folder-count">{{ getFileGroups(selectedPaper).notes.length }}</span>
                </div>
                <div v-if="expandedFolders.notes" class="folder-items">
                  <div
                    v-for="(file, i) in getFileGroups(selectedPaper).notes"
                    :key="'note-' + i"
                    class="file-item"
                    @click="openFile(file)"
                  >
                    {{ getFileName(file) }}
                  </div>
                </div>
              </div>

              <div class="file-group">
                <div class="folder-header" @click="toggleFolder('other')">
                  <span class="folder-icon">{{ expandedFolders.other ? '📂' : '📁' }}</span>
                  <span class="folder-label">Other</span>
                  <span class="folder-count">{{ getFileGroups(selectedPaper).other.length }}</span>
                </div>
                <div v-if="expandedFolders.other" class="folder-items">
                  <div
                    v-for="(file, i) in getFileGroups(selectedPaper).other"
                    :key="'other-' + i"
                    class="file-item"
                    @click="openFile(file)"
                  >
                    {{ getFileName(file) }}
                  </div>
                </div>
              </div>
            </div>

            <!-- Citation Lineage -->
            <div class="lineage-section" v-if="lineageData && !lineageData.error">
              <div class="section-label">Citation Lineage</div>
              <div v-if="lineageLoading" class="loading-text">Loading lineage...</div>
              <div v-else-if="lineageData.citations || lineageData.references" class="lineage-content">
                <div v-if="lineageData.citations && lineageData.citations.length" class="lineage-group">
                  <span class="lineage-label">Citations ({{ lineageData.citations.length }}):</span>
                  <span v-for="(cite, i) in lineageData.citations.slice(0, 10)" :key="'cite-' + i" class="lineage-item">
                    {{ cite.title || cite.id || cite }}{{ i < Math.min(lineageData.citations.length, 10) - 1 ? ', ' : '' }}
                  </span>
                </div>
                <div v-if="lineageData.references && lineageData.references.length" class="lineage-group">
                  <span class="lineage-label">References ({{ lineageData.references.length }}):</span>
                  <span v-for="(ref, i) in lineageData.references.slice(0, 10)" :key="'ref-' + i" class="lineage-item">
                    {{ ref.title || ref.id || ref }}{{ i < Math.min(lineageData.references.length, 10) - 1 ? ', ' : '' }}
                  </span>
                </div>
              </div>
            </div>

            <!-- Digests / Help-Noob -->
            <div class="digests-section">
              <div class="digest-buttons">
                <button class="btn btn-sm" @click="loadDigests(selectedPaper)" :disabled="digestsLoading">
                  {{ digestsLoading ? 'Loading...' : 'Digests' }}
                </button>
                <button class="btn btn-sm btn-outline" @click="loadHelpNoob(selectedPaper)" :disabled="helpNoobLoading">
                  {{ helpNoobLoading ? 'Loading...' : 'Help-Noob' }}
                </button>
              </div>
              <div v-if="notesExpanded && digestsContent" class="digest-content markdown-body">
                <div v-html="renderMarkdown(digestsContent)"></div>
              </div>
              <div v-if="helpNoobExpanded && helpNoobContent" class="digest-content markdown-body">
                <div v-html="renderMarkdown(helpNoobContent)"></div>
              </div>
            </div>
          </div>
        </div>

        <!-- Preview Toolbar -->
        <div class="preview-toolbar" v-if="previewPath">
          <span class="preview-path">{{ previewPath }}</span>
          <button class="btn btn-sm" @click="refreshSinglePaper(selectedPaper)" :disabled="refreshInProgress">
            Recreate Notes
          </button>
        </div>

        <!-- File Preview Area -->
        <div class="preview-area">
          <div v-if="previewLoading" class="preview-loading">Loading...</div>
          <div v-else-if="previewContent" class="markdown-body preview-content" v-html="renderMarkdown(previewContent)"></div>
          <div v-else-if="selectedPaper.files && selectedPaper.files.length" class="preview-hint">
            Select a file from the details panel to preview
          </div>
          <div v-else class="preview-empty">No files to preview</div>
        </div>
      </template>

      <!-- Empty State -->
      <div v-else class="empty-state">
        <div class="empty-icon">📄</div>
        <div class="empty-title">No Paper Selected</div>
        <div class="empty-subtitle">Select a paper from the sidebar to view details</div>
      </div>
    </div>

    <!-- Regenerate All Button -->
    <button
      v-if="papers.length"
      class="regenerate-btn"
      @click="regenerateAll"
      :disabled="regenerateRunning"
    >
      {{ regenerateRunning ? 'Regenerating...' : 'Regenerate All' }}
    </button>

    <!-- Regenerate Progress Overlay -->
    <div v-if="regenerateProgress" class="progress-overlay" @click.self="cancelRegenerate">
      <div class="progress-modal">
        <div class="progress-title">Regenerating All Papers</div>
        <div class="progress-message">{{ regenerateProgress.message }}</div>
        <div class="progress-bar-track">
          <div
            class="progress-bar-fill"
            :style="{ width: (regenerateProgress.total ? (regenerateProgress.current / regenerateProgress.total) * 100 : 0) + '%' }"
          ></div>
        </div>
        <div class="progress-count">{{ regenerateProgress.current }} / {{ regenerateProgress.total }}</div>
        <button class="btn btn-danger btn-sm" @click="cancelRegenerate" style="margin-top:12px">Cancel</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.browse-panel {
  display: flex;
  height: 100%;
  position: relative;
  overflow: hidden;
}

.browse-sidebar {
  width: 25%;
  min-width: 220px;
  max-width: 400px;
  border-right: 1px solid var(--border);
  background: var(--surface);
  display: flex;
  flex-direction: column;
  transition: width 0.2s ease, min-width 0.2s ease;
  overflow: hidden;
}

.browse-sidebar.collapsed {
  width: 0;
  min-width: 0;
  border-right: none;
}

.sidebar-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 10px 6px;
  border-bottom: 1px solid var(--border);
}

.search-input {
  flex: 1;
  min-width: 0;
}

.toggle-btn {
  background: var(--surface2);
  border: 1px solid var(--border);
  color: var(--text2);
  width: 28px;
  height: 28px;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  flex-shrink: 0;
  transition: background 0.15s;
}

.toggle-btn:hover {
  background: var(--border);
  color: var(--text);
}

.sidebar-toggle {
  position: absolute;
  left: 220px;
  top: 50%;
  transform: translateY(-50%);
  z-index: 10;
  background: var(--surface2);
  border: 1px solid var(--border);
  color: var(--text2);
  width: 20px;
  height: 36px;
  border-radius: 0 6px 6px 0;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  transition: left 0.2s ease;
}

.browse-sidebar.collapsed ~ .sidebar-toggle {
  left: 0;
}

.paper-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px;
}

.paper-item {
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
  position: relative;
  margin-bottom: 2px;
}

.paper-item:hover {
  background: var(--surface2);
}

.paper-item.active {
  background: var(--surface2);
  border: 1px solid var(--accent);
}

.paper-item-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  line-height: 1.4;
  margin-bottom: 3px;
  padding-right: 24px;
}

.paper-item-meta {
  font-size: 11px;
  color: var(--text3);
  margin-bottom: 4px;
}

.paper-item-badges {
  display: flex;
  gap: 4px;
}

.badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
}

.badge-green { background: var(--green); color: #080c18; }
.badge-cyan { background: var(--cyan); color: #080c18; }
.badge-yellow { background: var(--yellow); color: #080c18; }

.refresh-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  background: none;
  border: none;
  color: var(--text3);
  cursor: pointer;
  font-size: 14px;
  padding: 2px;
  border-radius: 4px;
  transition: color 0.15s;
}

.refresh-btn:hover { color: var(--accent); }

.empty-list {
  padding: 20px;
  text-align: center;
  color: var(--text3);
  font-size: 12px;
}

.browse-detail {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.paper-header {
  padding: 16px 20px 12px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}

.paper-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 6px;
  line-height: 1.3;
}

.paper-meta-row {
  font-size: 12px;
  color: var(--text2);
  margin-bottom: 3px;
}

.paper-authors { color: var(--text2); }
.paper-id { color: var(--text3); margin-right: 16px; }
.paper-date { color: var(--text3); }
.paper-affiliations { color: var(--text3); font-style: italic; }
.concept-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--surface2);
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 11px;
  color: var(--accent);
}

.top-panel {
  border-bottom: 1px solid var(--border);
}

.panel-collapse-btn {
  width: 100%;
  background: var(--surface2);
  border: none;
  color: var(--text2);
  padding: 6px 16px;
  font-size: 11px;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s;
}

.panel-collapse-btn:hover { background: var(--border); color: var(--text); }

.panel-content {
  padding: 12px 16px;
  max-height: 300px;
  overflow-y: auto;
}

.file-groups {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 10px;
}

.folder-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
  font-size: 12px;
  font-weight: 600;
  color: var(--text2);
}

.folder-header:hover { background: var(--surface2); }

.folder-icon { font-size: 14px; }
.folder-label { flex: 1; }
.folder-count {
  font-size: 10px;
  background: var(--surface2);
  padding: 1px 6px;
  border-radius: 8px;
  color: var(--text3);
}

.folder-items {
  padding-left: 28px;
}

.file-item {
  padding: 3px 8px;
  font-size: 11px;
  color: var(--text3);
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.15s;
}

.file-item:hover {
  background: var(--surface2);
  color: var(--accent);
}

.lineage-section {
  margin-top: 8px;
}

.section-label {
  font-size: 10px;
  font-weight: 600;
  color: var(--text3);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 6px;
}

.loading-text {
  font-size: 11px;
  color: var(--text3);
  padding: 4px 0;
}

.lineage-content {
  font-size: 11px;
  color: var(--text2);
}

.lineage-group {
  margin-bottom: 6px;
}

.lineage-label {
  font-weight: 600;
  color: var(--text3);
  margin-right: 4px;
}

.lineage-item {
  color: var(--text2);
}

.digests-section {
  margin-top: 10px;
}

.digest-buttons {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}

.digest-content {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 14px;
  font-size: 12px;
  line-height: 1.6;
  max-height: 200px;
  overflow-y: auto;
  margin-bottom: 6px;
}

.preview-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 16px;
  background: var(--surface2);
  border-bottom: 1px solid var(--border);
}

.preview-path {
  flex: 1;
  font-size: 11px;
  color: var(--text3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preview-area {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

.preview-loading {
  color: var(--text3);
  font-size: 12px;
  padding: 20px;
  text-align: center;
}

.preview-content {
  font-size: 13px;
  line-height: 1.7;
}

.preview-hint, .preview-empty {
  color: var(--text3);
  font-size: 12px;
  padding: 40px 20px;
  text-align: center;
}

.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--text3);
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 12px;
  opacity: 0.5;
}

.empty-title {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 4px;
}

.empty-subtitle {
  font-size: 12px;
}

.regenerate-btn {
  position: absolute;
  bottom: 16px;
  right: 16px;
  z-index: 5;
}

.progress-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  backdrop-filter: blur(4px);
}

.progress-modal {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 24px;
  min-width: 360px;
  box-shadow: var(--shadow);
}

.progress-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 8px;
}

.progress-message {
  font-size: 12px;
  color: var(--text2);
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
