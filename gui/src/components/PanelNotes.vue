<template>
  <div class="panel-notes">
    <div class="panel-header">
      <h3>Notes</h3>
      <div class="header-actions">
        <button class="btn-sm btn-accent" @click="showAddOverlay = true">+ Add</button>
        <button class="btn-sm" @click="compactGrid">Compact</button>
        <button class="btn-sm btn-danger" @click="clearAll">Clear</button>
      </div>
    </div>

    <div class="canvas-wrapper" ref="canvasWrapper">
      <div
        class="grid-canvas"
        :style="{ width: canvasWidth + 'px', height: canvasHeight + 'px' }"
        @click.self="deselectNote"
      >
        <template v-for="row in gridRows" :key="row">
          <div
            v-for="col in gridCols"
            :key="`${row}-${col}`"
            class="grid-cell"
            :class="{ occupied: getCellNote(row, col) }"
            @click="onCellClick(row, col)"
            @dragover.prevent
            @drop="onCellDrop(row, col, $event)"
          >
            <button
              v-if="!getCellNote(row, col)"
              class="add-cell-btn"
              @click.stop="showAddOverlay = true"
            >
              +
            </button>
            <div
              v-if="getCellNote(row, col)"
              class="note-bubble"
              :class="{
                'note-link': getCellNote(row, col).type === 'link',
                'note-image': getCellNote(row, col).type === 'image',
                dragging: dragState.noteId === getCellNote(row, col).id,
              }"
              :draggable="true"
              @dragstart="onDragStart($event, getCellNote(row, col))"
              @dragend="onDragEnd"
              @click.stop="showDetail(getCellNote(row, col))"
              @touchstart.passive="onTouchStart($event, getCellNote(row, col))"
              @touchmove.prevent="onTouchMove"
              @touchend="onTouchEnd"
            >
              <span class="type-badge" v-if="hoveredNoteId === getCellNote(row, col).id">
                {{ getCellNote(row, col).type === 'link' ? 'Link' : getCellNote(row, col).type === 'image' ? 'Image' : 'Text' }}
              </span>
              <button
                class="delete-btn"
                v-if="hoveredNoteId === getCellNote(row, col).id"
                @click.stop="deleteNote(getCellNote(row, col).id)"
              >
                ×
              </button>
              <div
                class="note-content"
                @mouseenter="hoveredNoteId = getCellNote(row, col).id"
                @mouseleave="hoveredNoteId = null"
              >
                <template v-if="getCellNote(row, col).type === 'image'">
                  <img :src="getCellNote(row, col).imageData" alt="note image" class="note-image-preview" />
                </template>
                <template v-else>
                  <div class="note-text" v-html="formatContent(getCellNote(row, col).content)"></div>
                </template>
                <div class="note-tags" v-if="getCellNote(row, col).concepts?.length">
                  <span class="tag" v-for="c in getCellNote(row, col).concepts.slice(0, 3)" :key="c">{{ c }}</span>
                </div>
              </div>
            </div>
          </div>
        </template>
      </div>
      <div v-if="dragGhost.visible" class="drag-ghost" :style="dragGhostStyle">
        <div class="note-bubble ghost-bubble">
          <div class="note-text">{{ dragGhost.content }}</div>
        </div>
      </div>
    </div>

    <!-- Detail Overlay -->
    <Teleport to="body">
      <div v-if="detailNote" class="modal-overlay" @click.self="detailNote = null">
        <div class="modal-panel detail-modal">
          <div class="modal-header">
            <h3>{{ detailNote.heading || 'Note' }}</h3>
            <button class="close-btn" @click="detailNote = null">×</button>
          </div>
          <div class="modal-body">
            <div class="detail-type-badge" :class="'badge-' + detailNote.type">
              {{ detailNote.type }}
            </div>
            <div v-if="detailNote.type === 'image' && detailNote.imageData" class="detail-image">
              <img :src="detailNote.imageData" alt="note image" />
            </div>
            <div v-if="detailNote.type === 'link'" class="detail-link">
              <a :href="detailNote.url" target="_blank" rel="noopener">{{ detailNote.url }}</a>
            </div>
            <div class="detail-content">{{ detailNote.content }}</div>
            <div v-if="detailNote.concepts?.length" class="detail-section">
              <h4>Concepts</h4>
              <div class="detail-tags">
                <span class="tag" v-for="c in detailNote.concepts" :key="c">{{ c }}</span>
              </div>
            </div>
            <div v-if="detailNote.linkedNodes?.length" class="detail-section">
              <h4>Linked Nodes</h4>
              <div class="linked-nodes">
                <span class="linked-node" v-for="n in detailNote.linkedNodes" :key="n">{{ n }}</span>
              </div>
            </div>
            <div v-if="detailNote.filePath" class="detail-section">
              <h4>File Path</h4>
              <code class="detail-filepath">{{ detailNote.filePath }}</code>
            </div>
            <div class="detail-meta">
              <span>Created: {{ formatTime(detailNote.createdAt) }}</span>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Add Overlay -->
    <Teleport to="body">
      <div v-if="showAddOverlay" class="modal-overlay" @click.self="showAddOverlay = false">
        <div class="modal-panel add-modal">
          <div class="modal-header">
            <h3>Add Note</h3>
            <button class="close-btn" @click="showAddOverlay = false">×</button>
          </div>
          <div class="modal-body">
            <input
              v-model="addForm.heading"
              type="text"
              class="input-field"
              placeholder="Heading (optional)"
            />
            <textarea
              v-model="addForm.content"
              class="textarea-field"
              placeholder="Paste text, URL, or image…"
              rows="8"
              @paste="onPaste"
              ref="addTextarea"
            ></textarea>
            <div v-if="addForm.pastedImage" class="paste-preview">
              <img :src="addForm.pastedImage" alt="pasted" />
              <button class="btn-sm btn-danger" @click="addForm.pastedImage = null">Remove</button>
            </div>
            <div class="modal-actions">
              <button class="btn-accent" @click="addNote" :disabled="adding">
                {{ adding ? 'Analysing…' : 'Add & Analyse' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, nextTick } from 'vue'

const CELL_W = 210
const CELL_H = 110
const GAP = 14

const canvasWrapper = ref(null)
const addTextarea = ref(null)
const notes = ref([])
const showAddOverlay = ref(false)
const detailNote = ref(null)
const hoveredNoteId = ref(null)
const adding = ref(false)
const addForm = reactive({ heading: '', content: '', pastedImage: null })

const canvasWidth = ref(800)
const gridCols = computed(() => Math.max(1, Math.floor((canvasWidth.value + GAP) / (CELL_W + GAP))))
const gridRows = computed(() => {
  const maxRow = notes.value.reduce((m, n) => Math.max(m, n.gridRow || 0), 0)
  return Math.max(3, maxRow + 1)
})
const canvasHeight = computed(() => gridRows.value * (CELL_H + GAP) - GAP)

const dragState = reactive({ noteId: null, startRow: -1, startCol: -1 })
const dragGhost = reactive({ visible: false, x: 0, y: 0, content: '' })

const dragGhostStyle = computed(() => ({
  left: dragGhost.x + 'px',
  top: dragGhost.y + 'px',
}))

function loadNotes() {
  try {
    const raw = localStorage.getItem('hive_notes_bubbles')
    if (raw) notes.value = JSON.parse(raw)
  } catch { notes.value = [] }
}

function saveNotes() {
  localStorage.setItem('hive_notes_bubbles', JSON.stringify(notes.value))
}

function getCellNote(row, col) {
  return notes.value.find((n) => n.gridRow === row && n.gridCol === col)
}

function onCellClick(row, col) {
  const note = getCellNote(row, col)
  if (note) showDetail(note)
}

function onCellDrop(row, col, event) {
  const noteId = event.dataTransfer?.getData('text/plain')
  if (!noteId) return
  moveNote(noteId, row, col)
}

function moveNote(id, row, col) {
  const note = notes.value.find((n) => n.id === id)
  if (!note) return
  if (getCellNote(row, col)) return
  note.gridRow = row
  note.gridCol = col
  saveNotes()
}

function onDragStart(event, note) {
  dragState.noteId = note.id
  event.dataTransfer?.setData('text/plain', note.id)
  event.dataTransfer.effectAllowed = 'move'
  dragGhost.visible = true
  dragGhost.content = note.heading || note.content.slice(0, 40)
}

function onDragEnd() {
  dragState.noteId = null
  dragGhost.visible = false
}

function onTouchStart(event, note) {
  const touch = event.touches[0]
  dragState.noteId = note.id
  dragGhost.visible = true
  dragGhost.x = touch.clientX
  dragGhost.y = touch.clientY
  dragGhost.content = note.heading || note.content.slice(0, 40)
}

function onTouchMove(event) {
  if (!dragState.noteId) return
  const touch = event.touches[0]
  dragGhost.x = touch.clientX - 50
  dragGhost.y = touch.clientY - 25
}

function onTouchEnd(event) {
  if (!dragState.noteId) return
  const touch = event.changedTouches[0]
  const target = document.elementFromPoint(touch.clientX, touch.clientY)
  const cell = target?.closest('.grid-cell')
  if (cell) {
    const [r, c] = (cell.dataset.pos || '').split(',').map(Number)
    if (!isNaN(r) && !isNaN(c)) moveNote(dragState.noteId, r, c)
  }
  dragState.noteId = null
  dragGhost.visible = false
}

function showDetail(note) {
  detailNote.value = { ...note }
}

function deleteNote(id) {
  notes.value = notes.value.filter((n) => n.id !== id)
  saveNotes()
}

function clearAll() {
  if (!confirm('Clear all notes?')) return
  notes.value = []
  saveNotes()
}

function compactGrid() {
  const sorted = [...notes.value].sort((a, b) => (a.createdAt || 0) - (b.createdAt || 0))
  const cols = gridCols.value
  sorted.forEach((note, i) => {
    note.gridRow = Math.floor(i / cols) + 1
    note.gridCol = (i % cols) + 1
  })
  notes.value = sorted
  saveNotes()
}

function detectType(content, imageData) {
  if (imageData) return 'image'
  const urlMatch = content.match(/^https?:\/\/\S+$/i)
  if (urlMatch) return 'link'
  return 'text'
}

async function addNote() {
  if (!addForm.content.trim() && !addForm.pastedImage) return
  adding.value = true
  try {
    let content = addForm.content.trim()
    let type = 'text'
    let imageData = null
    let url = null

    if (addForm.pastedImage) {
      imageData = addForm.pastedImage
      type = 'image'
      content = addForm.heading || 'Pasted image'
    } else {
      type = detectType(content)
      if (type === 'link') url = content
    }

    let concepts = []
    let linkedNodes = []
    if (type === 'text' && content) {
      try {
        const resp = await fetch('/api/notes/analyze', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: content, heading: addForm.heading }),
        })
        if (resp.ok) {
          const data = await resp.json()
          concepts = data.concepts || []
          linkedNodes = data.linkedNodes || []
        }
      } catch { /* optional API */ }
    }

    const note = {
      id: 'note_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8),
      heading: addForm.heading,
      content,
      type,
      url,
      imageData,
      concepts,
      linkedNodes,
      filePath: '',
      createdAt: Date.now(),
      gridRow: findEmptyRow(),
      gridCol: findEmptyCol(),
    }
    notes.value.push(note)
    saveNotes()
    addForm.heading = ''
    addForm.content = ''
    addForm.pastedImage = null
    showAddOverlay.value = false
  } finally {
    adding.value = false
  }
}

function findEmptyRow() {
  for (let r = 1; r <= 50; r++) {
    for (let c = 1; c <= gridCols.value; c++) {
      if (!getCellNote(r, c)) return r
    }
  }
  return gridRows.value + 1
}

function findEmptyCol() {
  for (let c = 1; c <= gridCols.value; c++) {
    if (!getCellNote(1, c)) return c
  }
  return 1
}

function onPaste(event) {
  const items = event.clipboardData?.items
  if (!items) return
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      const file = item.getAsFile()
      const reader = new FileReader()
      reader.onload = (e) => {
        addForm.pastedImage = e.target.result
      }
      reader.readAsDataURL(file)
      event.preventDefault()
      return
    }
  }
}

function formatContent(text) {
  if (!text) return ''
  let escaped = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  escaped = escaped.replace(
    /(https?:\/\/\S+)/g,
    '<a href="$1" target="_blank" rel="noopener" class="note-link-url">$1</a>'
  )
  return escaped.replace(/\n/g, '<br>')
}

function formatTime(ts) {
  if (!ts) return '—'
  return new Date(ts).toLocaleString()
}

function deselectNote() {
  detailNote.value = null
}

let resizeObserver
onMounted(() => {
  loadNotes()
  if (canvasWrapper.value) {
    canvasWidth.value = canvasWrapper.value.clientWidth
    resizeObserver = new ResizeObserver((entries) => {
      canvasWidth.value = entries[0]?.contentRect?.width || 800
    })
    resizeObserver.observe(canvasWrapper.value)
  }
})

onUnmounted(() => {
  resizeObserver?.disconnect()
})
</script>

<style scoped>
.panel-notes {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg);
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}

.panel-header h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}

.header-actions {
  display: flex;
  gap: 6px;
}

.btn-sm {
  padding: 4px 10px;
  font-size: 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
  transition: background 0.15s;
}

.btn-sm:hover {
  background: color-mix(in srgb, var(--surface) 80%, var(--text) 20%);
}

.btn-accent {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}

.btn-accent:hover {
  opacity: 0.9;
}

.btn-danger {
  color: #e55;
  border-color: #e553;
}

.canvas-wrapper {
  flex: 1;
  overflow: auto;
  padding: 12px 16px;
  position: relative;
}

.grid-canvas {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  gap: 14px;
}

.grid-cell {
  width: 210px;
  height: 110px;
  border: 1px dashed var(--border);
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  transition: border-color 0.15s;
}

.grid-cell:hover {
  border-color: var(--accent);
}

.grid-cell.occupied {
  border-style: solid;
  border-color: transparent;
}

.add-cell-btn {
  opacity: 0;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  font-size: 18px;
  cursor: pointer;
  transition: opacity 0.15s;
}

.grid-cell:hover .add-cell-btn {
  opacity: 0.6;
}

.add-cell-btn:hover {
  opacity: 1 !important;
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}

.note-bubble {
  width: 100%;
  height: 100%;
  padding: 10px;
  border-radius: 10px;
  background: var(--surface);
  border: 1px solid var(--border);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  position: relative;
  transition: box-shadow 0.15s, transform 0.15s;
  overflow: hidden;
}

.note-bubble:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
  transform: translateY(-1px);
}

.note-bubble.note-link {
  border-left: 3px solid #5b9bf5;
}

.note-bubble.note-image {
  padding: 0;
}

.note-bubble.dragging {
  opacity: 0.4;
}

.type-badge {
  position: absolute;
  top: 6px;
  right: 6px;
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  background: color-mix(in srgb, var(--accent) 20%, transparent);
  color: var(--accent);
  font-weight: 600;
  text-transform: uppercase;
  pointer-events: none;
  z-index: 2;
}

.delete-btn {
  position: absolute;
  top: 6px;
  left: 6px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  border: none;
  background: #e55;
  color: #fff;
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2;
  opacity: 0;
  transition: opacity 0.15s;
}

.note-bubble:hover .delete-btn {
  opacity: 1;
}

.note-content {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.note-text {
  font-size: 12px;
  color: var(--text);
  line-height: 1.4;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  word-break: break-word;
}

.note-text :deep(.note-link-url) {
  color: #5b9bf5;
  word-break: break-all;
  font-size: 11px;
}

.note-image-preview {
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: 8px;
}

.note-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
}

.tag {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  background: color-mix(in srgb, var(--accent) 15%, transparent);
  color: var(--accent);
  white-space: nowrap;
}

.drag-ghost {
  position: fixed;
  pointer-events: none;
  z-index: 9999;
  opacity: 0.85;
}

.ghost-bubble {
  width: 160px;
  height: 60px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
}

/* Modals */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-panel {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  width: 90%;
  max-width: 520px;
  max-height: 80vh;
  overflow-y: auto;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
}

.modal-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text);
}

.close-btn {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: none;
  background: var(--surface);
  color: var(--text);
  font-size: 18px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.modal-body {
  padding: 20px;
}

.input-field {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
  font-size: 14px;
  margin-bottom: 12px;
  box-sizing: border-box;
}

.input-field:focus {
  outline: none;
  border-color: var(--accent);
}

.textarea-field {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
  font-size: 13px;
  resize: vertical;
  font-family: inherit;
  box-sizing: border-box;
}

.textarea-field:focus {
  outline: none;
  border-color: var(--accent);
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

.modal-actions .btn-accent {
  padding: 8px 20px;
  border-radius: 8px;
  border: none;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.modal-actions .btn-accent:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.paste-preview {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
}

.paste-preview img {
  max-height: 80px;
  border-radius: 8px;
  border: 1px solid var(--border);
}

.detail-type-badge {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 4px;
  text-transform: uppercase;
  margin-bottom: 12px;
}

.badge-text {
  background: color-mix(in srgb, var(--accent) 15%, transparent);
  color: var(--accent);
}

.badge-link {
  background: color-mix(in srgb, #5b9bf5 20%, transparent);
  color: #5b9bf5;
}

.badge-image {
  background: color-mix(in srgb, #a78bfa 20%, transparent);
  color: #a78bfa;
}

.detail-image {
  margin: 12px 0;
}

.detail-image img {
  max-width: 100%;
  border-radius: 8px;
  border: 1px solid var(--border);
}

.detail-link {
  margin: 8px 0;
}

.detail-link a {
  color: #5b9bf5;
  word-break: break-all;
}

.detail-content {
  font-size: 14px;
  color: var(--text);
  line-height: 1.6;
  white-space: pre-wrap;
  margin-bottom: 16px;
}

.detail-section {
  margin-bottom: 14px;
}

.detail-section h4 {
  margin: 0 0 6px;
  font-size: 12px;
  font-weight: 600;
  color: color-mix(in srgb, var(--text) 60%, transparent);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.detail-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.linked-nodes {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.linked-node {
  font-size: 12px;
  padding: 3px 8px;
  border-radius: 4px;
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text);
}

.detail-filepath {
  font-size: 12px;
  padding: 4px 8px;
  background: var(--surface);
  border-radius: 4px;
  color: var(--text);
  word-break: break-all;
}

.detail-meta {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
  font-size: 12px;
  color: color-mix(in srgb, var(--text) 50%, transparent);
}
</style>
