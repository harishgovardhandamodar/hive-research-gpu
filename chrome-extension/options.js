// Hive Research — Options/Settings Page

const STORAGE_KEY = 'hive_server_config';

const $ = id => document.getElementById(id);

// ── Load ──

async function loadSettings() {
  const result = await chrome.storage.sync.get(STORAGE_KEY);
  const config = result[STORAGE_KEY] || getDefaultConfig();
  $('serverUrl').value = config.serverUrl || 'http://localhost:7777';
  $('authToken').value = config.authToken || '';
}

function getDefaultConfig() {
  return { serverUrl: 'http://localhost:7777', authToken: '' };
}

// ── Save ──

async function saveSettings() {
  const config = {
    serverUrl: $('serverUrl').value.trim().replace(/\/+$/, ''),
    authToken: $('authToken').value.trim(),
  };

  if (!config.serverUrl) {
    showStatus('Server URL is required.', 'error');
    return;
  }

  await chrome.storage.sync.set({ [STORAGE_KEY]: config });
  showStatus('Settings saved.', 'saved');
}

function showStatus(msg, type) {
  const el = $('saveStatus');
  el.textContent = msg;
  el.className = 'status ' + type;
  setTimeout(() => { if (el.className === 'status ' + type) el.className = 'status'; }, 3000);
}

// ── Test Connection ──

async function testConnection() {
  const config = {
    serverUrl: $('serverUrl').value.trim().replace(/\/+$/, ''),
    authToken: $('authToken').value.trim(),
  };

  $('connStatus').textContent = 'Testing...';
  $('connStatus').className = '';

  try {
    const url = `${config.serverUrl}/api/stats`;
    const headers = { 'Content-Type': 'application/json' };
    if (config.authToken) headers['Authorization'] = `Bearer ${config.authToken}`;

    const r = await fetch(url, { headers });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);

    const stats = await r.json();
    $('connStatus').textContent = '✓ Connected';
    $('connStatus').className = 'ok';
    $('statPapers').textContent = stats.papers || 0;
    $('statConcepts').textContent = stats.concepts || 0;
    $('statEdges').textContent = stats.relations || 0;
    $('statChunks').textContent = (stats.rag && stats.rag.chunks) || 0;

    showStatus('Connection successful!', 'saved');
  } catch (e) {
    $('connStatus').textContent = '✗ Connection failed: ' + e.message;
    $('connStatus').className = 'err';
    $('statPapers').textContent = '—';
    $('statConcepts').textContent = '—';
    $('statEdges').textContent = '—';
    $('statChunks').textContent = '—';
    showStatus('Connection failed.', 'error');
  }
}

// ── Events ──

document.addEventListener('DOMContentLoaded', () => {
  loadSettings();

  $('saveBtn').addEventListener('click', saveSettings);
  $('testBtn').addEventListener('click', testConnection);
});
