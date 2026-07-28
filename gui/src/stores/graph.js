import { defineStore } from 'pinia'
import * as api from '../api.js'

const defaultStyle = {
  paperColor: '#60a5fa',
  lineageColor: '#2dd4bf',
  webColor: '#fb923c',
  conceptColor: '#c084fc',
  edgeColor: '#1e3a5f',
  citeColor: '#34d399',
  paperSize: 14,
  conceptSize: 7
}

function loadStyle() {
  try {
    const saved = JSON.parse(localStorage.getItem('graph_style'))
    return saved ? { ...defaultStyle, ...saved } : { ...defaultStyle }
  } catch {
    return { ...defaultStyle }
  }
}

export const useGraphStore = defineStore('graph', {
  state: () => ({
    data: { nodes: [], links: [] },
    simulation: null,
    graphStyle: loadStyle()
  }),

  actions: {
    async fetchGraph() {
      try {
        const resp = await api.getGraph()
        this.data = resp
      } catch (e) {
        console.error('Failed to fetch graph:', e)
      }
    },

    updateGraphStyle(style) {
      this.graphStyle = { ...this.graphStyle, ...style }
      localStorage.setItem('graph_style', JSON.stringify(this.graphStyle))
    },

    resetGraphStyle() {
      this.graphStyle = { ...defaultStyle }
      localStorage.setItem('graph_style', JSON.stringify(this.graphStyle))
    }
  }
})
