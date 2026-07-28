<template>
  <div class="panel-about">
    <div class="panel-header">
      <h3>About</h3>
    </div>

    <div class="about-content">
      <!-- Stats Grid -->
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-value gradient-text">{{ stats.papers }}</div>
          <div class="stat-label">Papers</div>
        </div>
        <div class="stat-card">
          <div class="stat-value gradient-text">{{ stats.concepts }}</div>
          <div class="stat-label">Concepts</div>
        </div>
        <div class="stat-card">
          <div class="stat-value gradient-text">{{ stats.relations }}</div>
          <div class="stat-label">Relations</div>
        </div>
        <div class="stat-card">
          <div class="stat-value gradient-text">{{ stats.ragChunks }}</div>
          <div class="stat-label">RAG Chunks</div>
        </div>
      </div>

      <!-- System Card -->
      <div class="info-card">
        <h4>System</h4>
        <div class="info-rows">
          <div class="info-row">
            <span class="info-key">Platform</span>
            <span class="info-val">{{ system.platform || '—' }}</span>
          </div>
          <div class="info-row">
            <span class="info-key">Processor</span>
            <span class="info-val">{{ system.processor || '—' }}</span>
          </div>
          <div class="info-row">
            <span class="info-key">Python</span>
            <span class="info-val">{{ system.python || '—' }}</span>
          </div>
        </div>
      </div>

      <!-- Ollama Card -->
      <div class="info-card">
        <h4>Ollama</h4>
        <div class="info-rows">
          <div class="info-row">
            <span class="info-key">Status</span>
            <span class="info-val">
              <span class="status-dot" :class="ollama.connected ? 'status-ok' : 'status-off'"></span>
              {{ ollama.connected ? 'Connected' : 'Disconnected' }}
            </span>
          </div>
          <div class="info-row" v-if="ollama.model">
            <span class="info-key">Model</span>
            <span class="info-val">{{ ollama.model }}</span>
          </div>
          <div class="info-row" v-if="ollama.fastModel">
            <span class="info-key">Fast Model</span>
            <span class="info-val">{{ ollama.fastModel }}</span>
          </div>
          <div class="info-row" v-if="ollama.embedModel">
            <span class="info-key">Embed Model</span>
            <span class="info-val">{{ ollama.embedModel }}</span>
          </div>
        </div>
      </div>

      <!-- GPU Card -->
      <div class="info-card" v-if="gpu.backend">
        <h4>GPU</h4>
        <div class="info-rows">
          <div class="info-row">
            <span class="info-key">Backend</span>
            <span class="info-val">
              <span class="backend-badge" :class="gpu.backend === 'CUDA' ? 'backend-cuda' : 'backend-cpu'">
                {{ gpu.backend }}
              </span>
            </span>
          </div>
          <div class="info-row">
            <span class="info-key">Devices</span>
            <span class="info-val">{{ gpu.devices?.length || 0 }}</span>
          </div>
        </div>
        <div v-if="gpu.devices?.length" class="gpu-devices">
          <div class="gpu-device" v-for="(device, i) in gpu.devices" :key="i">
            <div class="gpu-device-header">
              <span class="gpu-device-name">{{ device.name || `GPU ${i}` }}</span>
            </div>
            <div class="gpu-metrics">
              <div class="gpu-metric" v-if="device.memoryTotal">
                <span class="metric-label">Memory</span>
                <div class="metric-bar-wrapper">
                  <div
                    class="metric-bar"
                    :style="{ width: device.memoryUsed && device.memoryTotal ? (device.memoryUsed / device.memoryTotal * 100) + '%' : '0%' }"
                  ></div>
                </div>
                <span class="metric-value">
                  {{ formatMB(device.memoryUsed) }} / {{ formatMB(device.memoryTotal) }}
                </span>
              </div>
              <div class="gpu-metric" v-if="device.utilization != null">
                <span class="metric-label">Util</span>
                <div class="metric-bar-wrapper">
                  <div class="metric-bar util-bar" :style="{ width: device.utilization + '%' }"></div>
                </div>
                <span class="metric-value">{{ device.utilization }}%</span>
              </div>
              <div class="gpu-metric" v-if="device.temperature != null">
                <span class="metric-label">Temp</span>
                <span class="metric-value" :class="tempClass(device.temperature)">
                  {{ device.temperature }}°C
                </span>
              </div>
              <div class="gpu-metric" v-if="device.power != null">
                <span class="metric-label">Power</span>
                <span class="metric-value">{{ device.power }}W</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useAppStore } from '../stores/app.js'
import { useGraphStore } from '../stores/graph.js'

const appStore = useAppStore()
const graphStore = useGraphStore()

const stats = reactive({ papers: 0, concepts: 0, relations: 0, ragChunks: 0 })
const system = reactive({ platform: '', processor: '', python: '' })
const ollama = reactive({ connected: false, model: '', fastModel: '', embedModel: '' })
const gpu = reactive({ backend: '', devices: [] })

function formatMB(mb) {
  if (!mb) return '—'
  if (mb >= 1024) return (mb / 1024).toFixed(1) + ' GB'
  return mb + ' MB'
}

function tempClass(temp) {
  if (temp >= 85) return 'temp-hot'
  if (temp >= 70) return 'temp-warm'
  return ''
}

async function fetchAbout() {
  try {
    const resp = await fetch('/api/stats')
    if (resp.ok) {
      const data = await resp.json()
      stats.papers = data.papers ?? data.total_papers ?? 0
      stats.concepts = data.concepts ?? data.total_concepts ?? 0
      stats.relations = data.relations ?? data.total_relations ?? 0
      stats.ragChunks = data.ragChunks ?? data.total_chunks ?? 0
      if (data.system) {
        system.platform = data.system.platform || ''
        system.processor = data.system.processor || ''
        system.python = data.system.python || ''
      }
    }
  } catch { /* fallback */ }

  try {
    const resp = await fetch('/api/ollama/status')
    if (resp.ok) {
      const data = await resp.json()
      ollama.connected = data.connected ?? false
      ollama.model = data.model || ''
      ollama.fastModel = data.fastModel || ''
      ollama.embedModel = data.embedModel || ''
    }
  } catch { /* optional */ }

  try {
    const resp = await fetch('/api/gpu/status')
    if (resp.ok) {
      const data = await resp.json()
      gpu.backend = data.backend || ''
      gpu.devices = data.devices || []
    }
  } catch { /* optional */ }

  if (!system.platform) {
    system.platform = navigator.platform || 'Unknown'
  }
}

onMounted(fetchAbout)
</script>

<style scoped>
.panel-about {
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

.about-content {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow-y: auto;
  flex: 1;
}

.stats-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.stat-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 18px 14px;
  text-align: center;
}

.stat-value {
  font-size: 28px;
  font-weight: 800;
  line-height: 1.1;
}

.gradient-text {
  background: linear-gradient(135deg, #a78bfa, #5b9bf5, #34d399);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.stat-label {
  margin-top: 4px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: color-mix(in srgb, var(--text) 55%, transparent);
}

.info-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px;
}

.info-card h4 {
  margin: 0 0 12px;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text);
}

.info-rows {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.info-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.info-key {
  font-size: 12px;
  color: color-mix(in srgb, var(--text) 55%, transparent);
}

.info-val {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  display: flex;
  align-items: center;
  gap: 6px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.status-ok {
  background: #34d399;
  box-shadow: 0 0 6px #34d39966;
}

.status-off {
  background: #f87171;
  box-shadow: 0 0 6px #f8717166;
}

.backend-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 4px;
  text-transform: uppercase;
}

.backend-cuda {
  background: color-mix(in srgb, #34d399 20%, transparent);
  color: #34d399;
}

.backend-cpu {
  background: color-mix(in srgb, #fbbf24 20%, transparent);
  color: #fbbf24;
}

.gpu-devices {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.gpu-device {
  background: color-mix(in srgb, var(--bg) 60%, var(--surface));
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
}

.gpu-device-header {
  margin-bottom: 8px;
}

.gpu-device-name {
  font-size: 12px;
  font-weight: 700;
  color: var(--text);
}

.gpu-metrics {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.gpu-metric {
  display: flex;
  align-items: center;
  gap: 8px;
}

.metric-label {
  font-size: 10px;
  color: color-mix(in srgb, var(--text) 50%, transparent);
  min-width: 32px;
}

.metric-bar-wrapper {
  flex: 1;
  height: 6px;
  background: color-mix(in srgb, var(--text) 10%, transparent);
  border-radius: 3px;
  overflow: hidden;
}

.metric-bar {
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(90deg, #5b9bf5, #a78bfa);
  transition: width 0.5s ease;
}

.metric-bar.util-bar {
  background: linear-gradient(90deg, #34d399, #5b9bf5);
}

.metric-value {
  font-size: 10px;
  font-weight: 600;
  color: var(--text);
  min-width: 60px;
  text-align: right;
}

.temp-hot {
  color: #f87171;
}

.temp-warm {
  color: #fbbf24;
}
</style>
