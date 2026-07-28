<script setup>
import { onMounted, computed, ref, watch } from 'vue'
import { useAppStore } from './stores/app.js'
import { useGraphStore } from './stores/graph.js'
import { usePoolStore } from './stores/pool.js'

import PanelGraph from './components/PanelGraph.vue'
import PanelImport from './components/PanelImport.vue'
import PanelBrowse from './components/PanelBrowse.vue'
import PanelPool from './components/PanelPool.vue'
import PanelSimilarity from './components/PanelSimilarity.vue'
import PanelAnalytics from './components/PanelAnalytics.vue'
import PanelChat from './components/PanelChat.vue'
import PanelNotes from './components/PanelNotes.vue'
import PanelHelp from './components/PanelHelp.vue'
import PanelAbout from './components/PanelAbout.vue'

const app = useAppStore()
const graph = useGraphStore()
const pool = usePoolStore()

const panels = [
  { id: 'pool', label: 'Pool', icon: '◆' },
  { id: 'graph', label: 'Graph', icon: '◇' },
  { id: 'import', label: 'Import', icon: '✚' },
  { id: 'browse', label: 'Browse', icon: '☰' },
  { id: 'similarity', label: 'Similarity', icon: '≈' },
  { id: 'analytics', label: 'Analytics', icon: '◈' },
  { id: 'chat', label: 'Chat', icon: '💬' },
  { id: 'notes', label: 'Notes', icon: '📝' },
]

const bottomPanels = [
  { id: 'help', label: 'Help', icon: '❓' },
  { id: 'about', label: 'About', icon: 'ℹ' },
]

const userMenuVisible = ref(false)
const loginUserVal = ref('')
const loginPassVal = ref('')
const loginError = ref('')

const filteredLogs = computed(() => {
  return app.serverLogs.filter(l => {
    const level = logLevel(l.level)
    return app.logFilters[level] || level === 'INPROGRESS'
  })
})

function logLevel(cls) {
  if (!cls) return 'INFO'
  const c = cls.toUpperCase()
  if (c === 'ERROR') return 'ERROR'
  if (c === 'WARN' || c === 'WARNING') return 'WARN'
  if (c === 'DONE') return 'DONE'
  if (c === 'INPROGRESS') return 'INPROGRESS'
  return 'INFO'
}

function toggleUserMenu() {
  userMenuVisible.value = !userMenuVisible.value
  if (userMenuVisible.value) app.checkSession()
}

async function doLogin() {
  const u = loginUserVal.value.trim()
  const p = loginPassVal.value.trim()
  if (!u || !p) { loginError.value = 'Enter username and password'; return }
  loginError.value = ''
  try {
    await app.loginUser(u, p)
    userMenuVisible.value = false
    app.addLog('Logged in as: ' + app.user?.username, 'DONE')
  } catch (e) {
    loginError.value = e.message || 'Connection error'
  }
}

async function doRegister() {
  const u = loginUserVal.value.trim()
  const p = loginPassVal.value.trim()
  if (!u || !p) { loginError.value = 'Enter username and password'; return }
  loginError.value = ''
  try {
    await app.registerUser(u, p)
    userMenuVisible.value = false
    app.addLog('Registered and logged in as: ' + app.user?.username, 'DONE')
  } catch (e) {
    loginError.value = e.message || 'Connection error'
  }
}

function doLogout() {
  app.logoutUser()
  userMenuVisible.value = false
  app.addLog('Logged out', 'INFO')
}

onMounted(() => {
  app.checkSession()
  app.fetchStats()
  app.fetchGpuStatus()
  app.fetchOllamaStatus()
  graph.fetchGraph()
  app.fetchLogs()
  pool.fetchPool()
  setInterval(() => app.fetchLogs(), 2000)
  setInterval(() => app.fetchIngestionQueue(), 2000)
})
</script>

<template>
  <div class="app" :class="{ light: !app.isDark }">
    <!-- Header -->
    <div class="header glass">
      <div class="logo">🔍</div>
      <h1>Lonewolf Research</h1>
      <div class="stats">
        <div class="s"><div class="dot p"></div><strong>{{ app.stats.papers || 0 }}</strong> papers</div>
        <div class="s"><div class="dot c"></div><strong>{{ app.stats.concepts || 0 }}</strong> concepts</div>
        <div class="s"><div class="dot e"></div><strong>{{ app.stats.relations || 0 }}</strong> edges</div>
      </div>
      <select class="model-select" :value="app.selectedModel" @change="app.setModel($event.target.value)" title="Active model for LLM calls">
        <option value="">Default (large: qwen3.6:35b)</option>
        <option value="fast">Fast (llama3.2:3b)</option>
      </select>
      <div id="gpuStatus" class="gpu-btn" @click="app.fetchGpuStatus()" :title="app.gpuTitle">🖥 GPU</div>
      <div class="theme-toggle" @click="app.toggleTheme()">{{ app.isDark ? '☾' : '☀' }}</div>
      <div class="user-btn" @click="toggleUserMenu()" title="User / Login">👤 <span>{{ app.user ? app.user.username : 'Login' }}</span></div>
    </div>

    <!-- User Menu Dropdown -->
    <div v-if="userMenuVisible" class="user-menu">
      <div v-if="!app.user">
        <input v-model="loginUserVal" placeholder="Username" style="margin-bottom:4px;padding:6px 8px;font-size:12px">
        <input v-model="loginPassVal" type="password" placeholder="Password" style="margin-bottom:6px;padding:6px 8px;font-size:12px" @keydown.enter="doLogin">
        <div style="display:flex;gap:4px">
          <button class="btn btn-sm" @click="doLogin" style="flex:1;font-size:10px">Login</button>
          <button class="btn btn-sm btn-outline" @click="doRegister" style="flex:1;font-size:10px">Register</button>
        </div>
        <div v-if="loginError" style="color:var(--red);font-size:10px;margin-top:4px">{{ loginError }}</div>
      </div>
      <div v-else>
        <div style="font-size:12px;font-weight:600;margin-bottom:6px">👤 {{ app.user.username }}</div>
        <div style="font-size:10px;color:var(--text3);margin-bottom:8px">Session active</div>
        <button class="btn btn-sm btn-outline" @click="doLogout" style="font-size:10px;width:100%">🚪 Logout</button>
      </div>
    </div>

    <!-- Body -->
    <div class="body">
      <!-- Sidebar -->
      <div class="sidebar">
        <div
          v-for="panel in panels"
          :key="panel.id"
          class="nav-item"
          :class="{ active: app.activePanel === panel.id }"
          @click="app.switchPanel(panel.id)"
        >
          {{ panel.icon }}
          <span class="tip">{{ panel.label }}</span>
        </div>
        <div class="spacer"></div>
        <div
          v-for="panel in bottomPanels"
          :key="panel.id"
          class="nav-item"
          :class="{ active: app.activePanel === panel.id }"
          @click="app.switchPanel(panel.id)"
        >
          {{ panel.icon }}
          <span class="tip">{{ panel.label }}</span>
        </div>
      </div>

      <!-- Main -->
      <div class="main">
        <div class="main-top">
          <PanelPool v-if="app.activePanel === 'pool'" />
          <PanelGraph v-if="app.activePanel === 'graph'" />
          <PanelImport v-if="app.activePanel === 'import'" />
          <PanelBrowse v-if="app.activePanel === 'browse'" />
          <PanelSimilarity v-if="app.activePanel === 'similarity'" />
          <PanelAnalytics v-if="app.activePanel === 'analytics'" />
          <PanelChat v-if="app.activePanel === 'chat'" />
          <PanelNotes v-if="app.activePanel === 'notes'" />
          <PanelHelp v-if="app.activePanel === 'help'" />
          <PanelAbout v-if="app.activePanel === 'about'" />
        </div>

        <!-- Ingestion Bar -->
        <div v-if="app.ingestionBarVisible && app.ingestionJobs.length" class="ingestion-bar">
          <span style="color:var(--text2);font-weight:500">⚙ Ingestion Queue</span>
          <span style="color:var(--text3)">{{ app.activeIngestionCount }} active</span>
          <span style="display:flex;gap:4px;flex-wrap:wrap;flex:1">
            <span v-for="job in app.displayIngestionJobs" :key="job.paper_id" class="ingestion-item" :style="{color: job.status==='error'?'var(--red)':job.status==='done'?'var(--green)':job.status==='queued'?'var(--text3)':'var(--accent)'}">
              {{ job.status==='error'?'✖':job.status==='done'?'✔':job.status==='queued'?'○':'●' }} {{ job.paper_id }} <span style="color:var(--text3)">{{ job.status }}</span>
            </span>
          </span>
          <span @click="app.clearIngestionQueue()" style="cursor:pointer;color:var(--text3);margin-left:auto" title="Clear finished jobs">✖</span>
        </div>

        <!-- Log Bar -->
        <div class="log-bar" :class="{ collapsed: app.logBarCollapsed }">
          <div class="log-bar-header" @click="app.toggleLogBar()">
            <div class="ll" style="cursor:pointer">☰ Activity Log <span class="count">{{ filteredLogs.length }}</span></div>
            <div style="display:flex;gap:8px;align-items:center;font-size:10px;cursor:default" @click.stop>
              <label v-for="level in ['INFO','DONE','WARN','ERROR']" :key="level" style="cursor:pointer;display:flex;align-items:center;gap:2px" :style="{color: level==='INFO'?'var(--accent)':level==='DONE'?'var(--green)':level==='WARN'?'var(--yellow)':'var(--red)'}">
                <input type="checkbox" v-model="app.logFilters[level]" style="width:auto;margin:0"> {{ level === 'INFO' ? 'Info' : level === 'DONE' ? 'Done' : level === 'WARN' ? 'Warn' : 'Error' }}
              </label>
              <span @click="app.toggleLogBar()" style="cursor:pointer;margin-left:4px">{{ app.logBarCollapsed ? '▼' : '▲' }}</span>
            </div>
          </div>
          <div class="log-bar-content" ref="logContent">
            <div v-for="(log, i) in filteredLogs" :key="i" class="l" :class="logLevel(log.level)">{{ log.formatted || log.msg || log.message }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
}
.header {
  background: var(--glass-bg);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
  padding: 0 20px;
  display: flex;
  align-items: center;
  gap: 16px;
  flex-shrink: 0;
  height: var(--header-h);
  z-index: 100;
}
.header .logo {
  width: 28px; height: 28px;
  background: linear-gradient(135deg, var(--accent), var(--accent2));
  border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px; color: #080c18; font-weight: 800;
  flex-shrink: 0;
  box-shadow: 0 2px 8px rgba(96,165,250,.3);
}
.header h1 {
  font-size: 15px; font-weight: 700; letter-spacing: -0.3px; white-space: nowrap;
  background: linear-gradient(135deg, var(--text), var(--text2));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}
.header .stats { display: flex; gap: 10px; margin-left: auto; font-size: 11px; }
.header .stats .s {
  display: flex; align-items: center; gap: 5px;
  background: var(--bg); padding: 3px 12px; border-radius: 8px; border: 1px solid var(--border);
  transition: border-color 0.15s;
}
.header .stats .s:hover { border-color: var(--text3); }
.header .stats .s .dot { width: 6px; height: 6px; border-radius: 50%; }
.header .stats .s strong { font-size: 12px; min-width: 12px; text-align: center; }
.dot.p { background: var(--accent); box-shadow: 0 0 6px rgba(96,165,250,.5); }
.dot.c { background: var(--purple); box-shadow: 0 0 6px rgba(192,132,252,.5); }
.dot.e { background: var(--yellow); box-shadow: 0 0 6px rgba(251,191,36,.5); }

.model-select {
  font-size: 10px; padding: 2px 6px; border-radius: 4px;
  border: 1px solid var(--border); background: var(--surface);
  color: var(--text); width: 155px;
}
.gpu-btn {
  display: flex; align-items: center; gap: 5px;
  font-size: 10px; color: var(--text3);
  padding: 3px 10px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--bg); cursor: pointer; flex-shrink: 0; transition: border-color 0.15s;
}
.gpu-btn:hover { border-color: var(--text3); }
.theme-toggle {
  cursor: pointer; font-size: 15px; color: var(--text3);
  padding: 3px 8px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--bg); line-height: 1; transition: all 0.15s;
}
.theme-toggle:hover { border-color: var(--text2); color: var(--text2); }
.user-btn {
  cursor: pointer; font-size: 13px; color: var(--text3);
  padding: 3px 8px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--bg); line-height: 1; transition: all 0.15s; white-space: nowrap;
}
.user-btn:hover { border-color: var(--text2); color: var(--text2); }

.user-menu {
  position: fixed; top: 48px; right: 12px; z-index: 9999;
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 12px; min-width: 200px; box-shadow: var(--shadow);
  animation: panelIn 0.15s;
}

.body { display: flex; flex: 1; overflow: hidden; position: relative; }
.sidebar {
  width: var(--sidebar-w); min-width: var(--sidebar-w);
  background: var(--glass-bg2); backdrop-filter: blur(12px);
  border-right: 1px solid var(--border);
  display: flex; flex-direction: column; align-items: center;
  padding: 10px 0; gap: 3px; flex-shrink: 0; z-index: 10;
}
.sidebar .nav-item {
  width: 38px; height: 38px; display: flex; align-items: center; justify-content: center;
  border-radius: 10px; cursor: pointer; color: var(--text3); font-size: 17px;
  transition: all 0.2s cubic-bezier(0.4,0,0.2,1); position: relative;
}
.sidebar .nav-item:hover { color: var(--text2); background: var(--surface2); transform: scale(1.05); }
.sidebar .nav-item:active { transform: scale(0.95); }
.sidebar .nav-item.active {
  color: var(--accent); background: rgba(96,165,250,.12);
  box-shadow: inset 0 0 0 1px rgba(96,165,250,.2);
}
.sidebar .nav-item .tip {
  position: absolute; left: 58px; top: 50%; transform: translateY(-50%);
  background: var(--surface2); color: var(--text); padding: 5px 12px; border-radius: 6px;
  font-size: 11px; white-space: nowrap; opacity: 0; pointer-events: none;
  transition: all 0.2s cubic-bezier(0.4,0,0.2,1); z-index: 100;
  border: 1px solid var(--border); box-shadow: var(--shadow);
}
.sidebar .nav-item:hover .tip { opacity: 1; left: 62px; }
.sidebar .spacer { flex: 1; }

.main { flex: 1; display: flex; flex-direction: column; overflow: hidden; padding: 0; }
.main-top { flex: 1; display: flex; flex-direction: column; overflow: hidden; }

.ingestion-bar {
  display: flex; flex-shrink: 0; background: var(--surface);
  border-bottom: 1px solid var(--border); padding: 4px 12px;
  font-size: 10px; gap: 6px; flex-wrap: wrap; align-items: center;
}
.ingestion-item {
  display: inline-flex; align-items: center; gap: 2px;
  padding: 1px 5px; border-radius: 3px; background: var(--bg);
  font-size: 9px; white-space: nowrap;
}

.log-bar {
  background: var(--glass-bg); backdrop-filter: blur(12px);
  border-top: 1px solid var(--border); flex-shrink: 0;
  display: flex; flex-direction: column; max-height: 40vh;
  transition: max-height 0.3s cubic-bezier(0.4,0,0.2,1);
}
.log-bar.collapsed { max-height: 32px; }
.log-bar-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 5px 16px; cursor: pointer; user-select: none;
  font-size: 11px; color: var(--text3); border-bottom: 1px solid var(--border);
  flex-shrink: 0; transition: background 0.15s;
}
.log-bar-header:hover { background: var(--surface2); }
.log-bar-header .ll { display: flex; align-items: center; gap: 8px; }
.log-bar-header .ll .count {
  background: var(--bg); padding: 1px 6px; border-radius: 6px;
  font-size: 10px; min-width: 18px; text-align: center;
}
.log-bar-content {
  flex: 1; overflow-y: auto; padding: 6px 16px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 10.5px; line-height: 1.7; min-height: 0;
}
.log-bar-content .l { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.log-bar-content .l.ERROR { color: var(--red); }
.log-bar-content .l.WARN, .log-bar-content .l.WARNING { color: var(--yellow); }
.log-bar-content .l.INFO { color: var(--text2); }
.log-bar-content .l.DEBUG { color: var(--text3); }
.log-bar-content .l.DONE { color: var(--green); }
.log-bar-content .l.INPROGRESS { color: var(--accent); animation: pulse 1.5s ease-in-out infinite; }

@keyframes panelIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
</style>
