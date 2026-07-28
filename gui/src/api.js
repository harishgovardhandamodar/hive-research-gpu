async function api(path, method = 'GET', body = null) {
  const headers = { 'Content-Type': 'application/json' }
  const token = localStorage.getItem('session_token')
  if (token) headers['X-Session-Token'] = token

  const opts = { method, headers }
  if (body && method !== 'GET') opts.body = JSON.stringify(body)

  const res = await fetch(`/api${path}`, opts)
  const data = await res.json()
  if (!res.ok) throw new Error(data.error || `API error ${res.status}`)
  return data
}

export function getGraph() { return api('/graph') }
export function getStats() { return api('/stats') }
export function getPapers() { return api('/papers') }
export function getPaperSearch(q) { return api(`/papers/search?q=${encodeURIComponent(q)}`) }
export function getConcepts() { return api('/concepts') }
export function getBrowse() { return api('/browse') }
export function readFile(path) { return api(`/read?path=${encodeURIComponent(path)}`) }
export function getDigests(paperId, types = '', refresh = false) {
  return api(`/digests/${paperId}?types=${encodeURIComponent(types)}&refresh=${refresh}`)
}
export function getHelpNoob(paperId, refresh = false) {
  return api(`/help-noob/${paperId}?refresh=${refresh}`)
}
export function addPaper(id, model = null) {
  return api('/add', 'POST', { id, model })
}
export function searchArxiv(query) {
  return api('/search', 'POST', { query })
}
export function importSearch(query, model = null) {
  return api('/import', 'POST', { query, model })
}
export function queryRag(question) {
  return api('/query', 'POST', { question })
}
export function refreshPapers(model = null, force = false) {
  return api('/refresh', 'POST', { model, force })
}
export function refreshPaper(paperId, model = null) {
  return api('/papers/refresh', 'POST', { paper_id: paperId, model })
}
export function getRefreshStatus() { return api('/refresh/status') }
export function detailGraph() { return api('/graph/detail', 'POST') }
export function generateDefinitions() { return api('/definitions', 'POST') }
export function fetchLineage(arxivId) { return api('/lineage', 'POST', { arxiv_id: arxivId }) }
export function getSimilarity(paperIds, algorithm = 'combined') {
  return api('/similarity', 'POST', { paper_ids: paperIds, algorithm })
}
export function ingestWeb(url, model = null) {
  return api('/web/add', 'POST', { url, model })
}
export function getWebList() { return api('/web/list') }
export function getOverlaps() { return api('/overlaps') }
export function getMetagraph() { return api('/metagraph') }
export function getPoolPapers() { return api('/pool/papers') }
export function getPool() { return api('/pool') }
export function getPoolGraph() { return api('/pool/graph') }
export function getPoolTopics() { return api('/pool/topics') }
export function getPoolInsights() { return api('/pool/insights') }
export function addPoolTopic(name, query) {
  return api('/pool/topics/add', 'POST', { name, query })
}
export function removePoolTopic(name) {
  return api('/pool/topics/remove', 'POST', { name })
}
export function importPoolPaper(arxivId) {
  return api('/pool/import', 'POST', { arxiv_id: arxivId })
}
export function importPoolBatch(arxivIds) {
  return api('/pool/import_batch', 'POST', { arxiv_ids: arxivIds })
}
export function queryPool(query) {
  return api('/pool/query', 'POST', { query })
}
export function getOllamaStatus() { return api('/ollama') }
export function getGpuStatus() { return api('/gpu') }
export function getLogs(n = 100) { return api(`/logs?n=${n}`) }
export function getIngestionQueue() { return api('/ingestion/queue') }
export function clearIngestionQueue() { return api('/ingestion/clear', 'POST') }
export function analyzeNote(content, heading) {
  return api('/notes/analyze', 'POST', { content, heading })
}
export function getDuplicatePapers(paperId = '', threshold = 0.85) {
  return api(`/papers/duplicates?paper_id=${encodeURIComponent(paperId)}&threshold=${threshold}`)
}
export function getExportBibtex() { return api('/export/bibtex') }
export function getExportJson() { return api('/export/json') }
export function getExportCsv() { return api('/export/csv') }
export function getCollections() { return api('/collections') }
export function getFavorites() { return api('/favorites') }
export function login(username, password) {
  return api('/user/login', 'POST', { username, password })
}
export function register(username, password) {
  return api('/user/register', 'POST', { username, password })
}
export function logout(token) {
  return api('/user/logout', 'POST', { token })
}
export function getUserMe(token) {
  return api('/user/me', 'POST', { token })
}
export function getUserStatus() { return api('/user/status') }

export { api }
