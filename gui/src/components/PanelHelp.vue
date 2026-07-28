<template>
  <div class="panel-help">
    <div class="panel-header">
      <h3>Help</h3>
    </div>

    <div class="cards-container">
      <!-- Quick Start -->
      <div class="help-card">
        <h4>Quick Start</h4>
        <ol class="step-list">
          <li>
            <span class="step-num">1</span>
            <div>
              <strong>Import</strong> — Add papers via CLI or GUI import panel
            </div>
          </li>
          <li>
            <span class="step-num">2</span>
            <div>
              <strong>Pipeline</strong> — Run the extraction pipeline to extract concepts and relations
            </div>
          </li>
          <li>
            <span class="step-num">3</span>
            <div>
              <strong>Graph</strong> — Explore the knowledge graph interactively
            </div>
          </li>
          <li>
            <span class="step-num">4</span>
            <div>
              <strong>Chat</strong> — Ask questions and get RAG-powered answers
            </div>
          </li>
        </ol>
      </div>

      <!-- CLI Reference -->
      <div class="help-card">
        <h4>CLI Quick Reference</h4>
        <div class="cli-list">
          <div class="cli-item">
            <code class="cli-cmd">hive serve</code>
            <span class="cli-desc">Start the GUI server</span>
          </div>
          <div class="cli-item">
            <code class="cli-cmd">hive add &lt;file&gt;</code>
            <span class="cli-desc">Add a paper to the database</span>
          </div>
          <div class="cli-item">
            <code class="cli-cmd">hive import &lt;dir&gt;</code>
            <span class="cli-desc">Import all papers from a directory</span>
          </div>
          <div class="cli-item">
            <code class="cli-cmd">hive query &lt;text&gt;</code>
            <span class="cli-desc">Query the knowledge base</span>
          </div>
          <div class="cli-item">
            <code class="cli-cmd">hive stats</code>
            <span class="cli-desc">Show database statistics</span>
          </div>
          <div class="cli-item">
            <code class="cli-cmd">hive export</code>
            <span class="cli-desc">Export the knowledge graph</span>
          </div>
        </div>
      </div>

      <!-- API Endpoints -->
      <div class="help-card">
        <h4>API Endpoints</h4>
        <div class="api-list">
          <div class="api-item" v-for="ep in endpoints" :key="ep.path">
            <span class="api-method" :class="'method-' + ep.method.toLowerCase()">
              {{ ep.method }}
            </span>
            <code class="api-path">{{ ep.path }}</code>
            <span class="api-desc">{{ ep.desc }}</span>
          </div>
        </div>
      </div>

      <!-- Python Client -->
      <div class="help-card">
        <h4>Python Client</h4>
        <pre class="code-block"><code>from hive_client import HiveClient

client = HiveClient("http://localhost:8503")

# Query
results = client.query("transformer attention mechanisms")

# Add paper
client.add_paper("path/to/paper.pdf")

# Get stats
stats = client.stats()
print(stats)</code></pre>
      </div>

      <!-- Full Docs -->
      <div class="help-card docs-card">
        <h4>Full Documentation</h4>
        <p>Comprehensive documentation, examples, and API reference.</p>
        <a class="docs-link" href="/hive" target="_blank" rel="noopener">
          Open Documentation →
        </a>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive } from 'vue'

const endpoints = reactive([
  { method: 'GET', path: '/api/stats', desc: 'Database statistics' },
  { method: 'GET', path: '/api/graph', desc: 'Knowledge graph data' },
  { method: 'GET', path: '/api/papers', desc: 'List all papers' },
  { method: 'POST', path: '/api/query', desc: 'RAG query' },
  { method: 'POST', path: '/api/chat', desc: 'Chat conversation' },
  { method: 'POST', path: '/api/notes/analyze', desc: 'Analyse note concepts' },
  { method: 'GET', path: '/api/ollama/status', desc: 'Ollama connection status' },
  { method: 'GET', path: '/api/gpu/status', desc: 'GPU device information' },
])
</script>

<style scoped>
.panel-help {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg);
}

.panel-header {
  display: flex;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}

.panel-header h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}

.cards-container {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow-y: auto;
  flex: 1;
}

.help-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px;
}

.help-card h4 {
  margin: 0 0 12px;
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.step-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.step-list li {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  font-size: 13px;
  color: var(--text);
  line-height: 1.5;
}

.step-num {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  min-width: 22px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--accent) 15%, transparent);
  color: var(--accent);
  font-size: 11px;
  font-weight: 700;
}

.cli-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.cli-item {
  display: flex;
  align-items: center;
  gap: 10px;
}

.cli-cmd {
  font-size: 12px;
  padding: 3px 8px;
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  color: var(--accent);
  border-radius: 4px;
  white-space: nowrap;
  font-weight: 600;
}

.cli-desc {
  font-size: 12px;
  color: color-mix(in srgb, var(--text) 70%, transparent);
}

.api-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.api-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.api-method {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 3px;
  min-width: 38px;
  text-align: center;
  text-transform: uppercase;
}

.method-get {
  background: color-mix(in srgb, #34d399 20%, transparent);
  color: #34d399;
}

.method-post {
  background: color-mix(in srgb, #5b9bf5 20%, transparent);
  color: #5b9bf5;
}

.method-put {
  background: color-mix(in srgb, #fbbf24 20%, transparent);
  color: #fbbf24;
}

.method-delete {
  background: color-mix(in srgb, #f87171 20%, transparent);
  color: #f87171;
}

.api-path {
  font-size: 12px;
  color: var(--text);
  background: none;
}

.api-desc {
  font-size: 11px;
  color: color-mix(in srgb, var(--text) 55%, transparent);
}

.code-block {
  margin: 0;
  padding: 14px;
  background: color-mix(in srgb, var(--bg) 80%, var(--surface));
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text);
  overflow-x: auto;
  font-family: 'SF Mono', 'Fira Code', monospace;
}

.docs-card {
  text-align: center;
}

.docs-card p {
  font-size: 13px;
  color: color-mix(in srgb, var(--text) 65%, transparent);
  margin: 0 0 12px;
}

.docs-link {
  display: inline-block;
  padding: 8px 20px;
  border-radius: 8px;
  background: var(--accent);
  color: #fff;
  text-decoration: none;
  font-size: 13px;
  font-weight: 600;
  transition: opacity 0.15s;
}

.docs-link:hover {
  opacity: 0.85;
}
</style>
