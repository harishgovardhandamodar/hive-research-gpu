import { defineStore } from 'pinia'
import * as api from '../api.js'

export const usePoolStore = defineStore('pool', {
  state: () => ({
    papers: [],
    poolData: {},
    topics: [],
    insights: null,
    graphData: null
  }),

  actions: {
    async fetchPool() {
      try {
        const data = await api.getPool()
        this.poolData = data
        if (data.papers) this.papers = data.papers
      } catch (e) {
        console.error('Failed to fetch pool:', e)
      }
    },

    async fetchPoolPapers() {
      try {
        const data = await api.getPoolPapers()
        this.papers = data.papers || data
      } catch (e) {
        console.error('Failed to fetch pool papers:', e)
      }
    },

    async fetchPoolTopics() {
      try {
        const data = await api.getPoolTopics()
        this.topics = data.topics || data
      } catch (e) {
        console.error('Failed to fetch pool topics:', e)
      }
    },

    async fetchPoolInsights() {
      try {
        this.insights = await api.getPoolInsights()
      } catch (e) {
        console.error('Failed to fetch pool insights:', e)
      }
    },

    async fetchPoolGraph() {
      try {
        this.graphData = await api.getPoolGraph()
      } catch (e) {
        console.error('Failed to fetch pool graph:', e)
      }
    }
  }
})
