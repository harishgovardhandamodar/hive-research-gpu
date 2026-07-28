import { defineStore } from 'pinia'
import * as api from '../api.js'

export const useAppStore = defineStore('app', {
  state: () => ({
    activePanel: 'graph',
    isDark: JSON.parse(localStorage.getItem('theme_dark') ?? 'true'),
    stats: { papers: 0, concepts: 0, relations: 0, rag: { chunks: 0 } },
    user: null,
    logs: [],
    logLastId: 0,
    logFilters: JSON.parse(localStorage.getItem('log_filters') ?? '{"INFO":true,"DONE":true,"WARN":true,"ERROR":true}'),
    gpuStatus: null,
    ollamaStatus: null,
    selectedModel: localStorage.getItem('selected_model') ?? '',
    ingestionJobs: [],
    logBarCollapsed: false,
    ingestionBarVisible: false
  }),

  getters: {
    themeClass: (state) => (state.isDark ? '' : 'light'),
    gpuTitle(state) {
      if (!state.gpuStatus) return 'No GPU info'
      if (state.gpuStatus.nvidia && state.gpuStatus.devices) {
        return state.gpuStatus.devices.map(d =>
          `GPU ${d.index}: ${d.name||'RTX 5080'} ${d.utilization_percent}% ${d.memory_used_mb}MB`
        ).join(' | ')
      }
      return 'No GPU acceleration'
    },
    activeIngestionCount(state) {
      return state.ingestionJobs.filter(j => j.status !== 'done' && j.status !== 'error').length
    },
    displayIngestionJobs(state) {
      const active = state.ingestionJobs.filter(j => j.status !== 'done' && j.status !== 'error').slice(-5)
      const done = state.ingestionJobs.filter(j => j.status === 'done' || j.status === 'error').slice(-3)
      return [...active, ...done]
    },
    serverLogs(state) { return state.logs }
  },

  actions: {
    switchPanel(name) {
      this.activePanel = name
    },

    toggleTheme() {
      this.isDark = !this.isDark
      localStorage.setItem('theme_dark', JSON.stringify(this.isDark))
    },

    async fetchStats() {
      try {
        const data = await api.getStats()
        this.stats = data
      } catch (e) {
        console.error('Failed to fetch stats:', e)
      }
    },

    async fetchGpuStatus() {
      try {
        this.gpuStatus = await api.getGpuStatus()
      } catch (e) {
        console.error('Failed to fetch GPU status:', e)
      }
    },

    async fetchOllamaStatus() {
      try {
        this.ollamaStatus = await api.getOllamaStatus()
      } catch (e) {
        console.error('Failed to fetch Ollama status:', e)
      }
    },

    async fetchLogs() {
      try {
        const data = await api.getLogs(200)
        const entries = Array.isArray(data) ? data : (data.logs || [])
        entries.forEach(l => {
          if (l._id && l._id <= this.logLastId) return
          if (l._id) this.logLastId = l._id
          this.logs.push({
            level: l.level || 'INFO',
            formatted: l.formatted || l.message || '',
            msg: l.msg || l.formatted || '',
            _id: l._id || this.logLastId++,
            time: new Date().toISOString()
          })
        })
        if (this.logs.length > 500) this.logs = this.logs.slice(-500)
      } catch (e) {
        console.error('Failed to fetch logs:', e)
      }
    },

    addLog(msg, level = 'INFO') {
      this.logs.push({ msg, level, time: new Date().toISOString(), _id: this.logLastId++ })
      if (this.logs.length > 500) this.logs = this.logs.slice(-500)
    },

    async fetchIngestionQueue() {
      try {
        const data = await api.getIngestionQueue()
        this.ingestionJobs = Array.isArray(data) ? data : (data.jobs || [])
        this.ingestionBarVisible = this.ingestionJobs.length > 0
      } catch (e) {
        console.error('Failed to fetch ingestion queue:', e)
      }
    },

    async loginUser(username, password) {
      try {
        const data = await api.login(username, password)
        if (data.token) {
          localStorage.setItem('session_token', data.token)
          this.user = data.user || { username }
          this.addLog(`Logged in as ${username}`, 'DONE')
        }
        return data
      } catch (e) {
        this.addLog(`Login failed: ${e.message}`, 'ERROR')
        throw e
      }
    },

    async registerUser(username, password) {
      try {
        const data = await api.register(username, password)
        if (data.token) {
          localStorage.setItem('session_token', data.token)
          this.user = data.user || { username }
          this.addLog(`Registered as ${username}`, 'DONE')
        }
        return data
      } catch (e) {
        this.addLog(`Registration failed: ${e.message}`, 'ERROR')
        throw e
      }
    },

    async logoutUser() {
      try {
        const token = localStorage.getItem('session_token')
        if (token) await api.logout(token)
      } catch (e) { /* ignore */ }
      localStorage.removeItem('session_token')
      this.user = null
      this.addLog('Logged out', 'DONE')
    },

    async checkSession() {
      try {
        const token = localStorage.getItem('session_token')
        if (!token) return
        const data = await api.getUserMe(token)
        if (data.user) this.user = data.user
        else localStorage.removeItem('session_token')
      } catch {
        localStorage.removeItem('session_token')
        this.user = null
      }
    },

    setModel(model) {
      this.selectedModel = model
      localStorage.setItem('selected_model', model)
    },

    toggleLogBar() {
      this.logBarCollapsed = !this.logBarCollapsed
    },

    async clearIngestionQueue() {
      try {
        await api.clearIngestionQueue()
        this.ingestionJobs = []
      } catch (e) {
        console.error('Failed to clear ingestion queue:', e)
      }
    }
  }
})
