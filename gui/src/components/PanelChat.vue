<script setup>
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { useAppStore } from '../stores/app.js'
import { queryRag } from '../api.js'

const app = useAppStore()

const messages = ref([
  {
    role: 'assistant',
    content: 'Welcome to Hive Research RAG. Ask me anything about your paper collection.',
    sources: [],
    time: new Date()
  }
])

const userInput = ref('')
const loading = ref(false)
const messagesContainer = ref(null)

function scrollToBottom() {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

function formatTime(date) {
  return new Date(date).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function sourceLabel(s) {
  const id = s.id || s.paper_id || s.arxiv_id || ''
  const title = s.title || ''
  if (title && id) return `${id} — ${title}`
  return title || id || 'Unknown source'
}

async function sendMessage() {
  const text = userInput.value.trim()
  if (!text || loading.value) return

  messages.value.push({
    role: 'user',
    content: text,
    sources: [],
    time: new Date()
  })

  userInput.value = ''
  loading.value = true
  scrollToBottom()

  try {
    const data = await queryRag(text)
    messages.value.push({
      role: 'assistant',
      content: data.answer || data.response || data.result || 'No answer returned.',
      sources: data.sources || data.citations || data.references || [],
      time: new Date()
    })
  } catch (e) {
    console.error('RAG query failed:', e)
    messages.value.push({
      role: 'assistant',
      content: `Error: ${e.message}`,
      sources: [],
      time: new Date()
    })
  } finally {
    loading.value = false
    scrollToBottom()
  }
}

function onKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
}

onMounted(() => {
  scrollToBottom()
})

watch(messages, () => {
  scrollToBottom()
}, { deep: true })
</script>

<template>
  <div class="chat-panel">
    <div ref="messagesContainer" class="messages-area">
      <div
        v-for="(msg, idx) in messages"
        :key="idx"
        :class="['message', msg.role]"
      >
        <div class="message-bubble">
          <div class="message-content">{{ msg.content }}</div>
          <div class="message-time">{{ formatTime(msg.time) }}</div>
        </div>
      </div>

      <div v-if="loading" class="message assistant">
        <div class="message-bubble typing-indicator">
          <span class="dot"></span>
          <span class="dot"></span>
          <span class="dot"></span>
        </div>
      </div>
    </div>

    <div v-if="messages.length > 1 && messages[messages.length - 1]?.sources?.length" class="sources-bar">
      <div class="sources-header">Sources</div>
      <div class="sources-list">
        <span
          v-for="(s, i) in messages[messages.length - 1].sources"
          :key="i"
          class="source-chip"
          :title="JSON.stringify(s)"
        >{{ sourceLabel(s) }}</span>
      </div>
    </div>

    <div class="input-bar">
      <input
        v-model="userInput"
        type="text"
        placeholder="Ask about your papers..."
        class="chat-input"
        :disabled="loading"
        @keydown="onKeydown"
      />
      <button class="btn send-btn" :disabled="!userInput.trim() || loading" @click="sendMessage">
        Ask
      </button>
    </div>
  </div>
</template>

<style scoped>
.chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.messages-area {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.message {
  display: flex;
  max-width: 80%;
}

.message.user {
  align-self: flex-end;
}

.message.assistant {
  align-self: flex-start;
}

.message-bubble {
  padding: 10px 14px;
  border-radius: var(--radius);
  font-size: 13px;
  line-height: 1.55;
  word-break: break-word;
}

.message.user .message-bubble {
  background: linear-gradient(135deg, var(--accent), var(--accent2));
  color: #080c18;
  border-bottom-right-radius: 4px;
}

.message.assistant .message-bubble {
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text);
  border-bottom-left-radius: 4px;
}

.message-content {
  white-space: pre-wrap;
}

.message-time {
  margin-top: 4px;
  font-size: 10px;
  opacity: 0.5;
}

.typing-indicator {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 12px 18px;
}

.typing-indicator .dot {
  width: 6px;
  height: 6px;
  background: var(--text3);
  border-radius: 50%;
  animation: bounce 1.4s infinite ease-in-out;
}

.typing-indicator .dot:nth-child(1) { animation-delay: 0s; }
.typing-indicator .dot:nth-child(2) { animation-delay: 0.2s; }
.typing-indicator .dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes bounce {
  0%, 80%, 100% { transform: translateY(0); opacity: 0.4; }
  40% { transform: translateY(-6px); opacity: 1; }
}

.sources-bar {
  flex-shrink: 0;
  padding: 8px 16px;
  border-top: 1px solid var(--border);
  background: var(--surface);
}

.sources-header {
  font-size: 10px;
  font-weight: 600;
  color: var(--text3);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 6px;
}

.sources-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.source-chip {
  display: inline-block;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 2px 10px;
  font-size: 10px;
  color: var(--text2);
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: default;
}

.source-chip:hover {
  border-color: var(--accent);
  color: var(--text);
}

.input-bar {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--border);
  background: var(--surface);
  flex-shrink: 0;
}

.chat-input {
  flex: 1;
  min-width: 0;
}

.send-btn {
  flex-shrink: 0;
  padding: 8px 20px;
}
</style>
