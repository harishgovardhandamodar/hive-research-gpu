// Hive Research — Background Service Worker
// Handles context menus, API calls, and notifications.

const STORAGE_KEY = 'hive_server_config';

function getDefaultConfig() {
  return {
    serverUrl: 'http://localhost:7777',
    authToken: '',
  };
}

async function getConfig() {
  const result = await chrome.storage.sync.get(STORAGE_KEY);
  return result[STORAGE_KEY] || getDefaultConfig();
}

// ── API ──

async function hiveApi(method, path, data) {
  const config = await getConfig();
  const url = `${config.serverUrl.replace(/\/+$/, '')}${path}`;
  const headers = { 'Content-Type': 'application/json' };
  if (config.authToken) {
    headers['Authorization'] = `Bearer ${config.authToken}`;
  }
  const opts = { method, headers };
  if (data) opts.body = JSON.stringify(data);
  const r = await fetch(url, opts);
  if (!r.ok) {
    const err = await r.text().catch(() => r.statusText);
    throw new Error(`HTTP ${r.status}: ${err}`);
  }
  return r.json();
}

async function ingestUrl(url, title) {
  return hiveApi('POST', '/api/web/add', { url });
}

// ── Health Check ──

async function checkServerHealth() {
  try {
    const stats = await hiveApi('GET', '/api/stats');
    return { ok: true, stats };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

// ── Context Menu ──

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: 'hive-ingest-page',
    title: 'Send to Hive Research',
    contexts: ['page', 'link'],
  });
  chrome.contextMenus.create({
    id: 'hive-ingest-link',
    title: 'Send Link to Hive Research',
    contexts: ['link'],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const url = info.linkUrl || info.pageUrl || (tab ? tab.url : '');
  const title = tab ? tab.title : '';

  if (!url) return;

  try {
    showNotification('Sending to Hive...', 'Sending page to Hive Research for ingestion.');
    const result = await ingestUrl(url, title);
    const status = result.status || 'unknown';
    if (status === 'added') {
      showNotification('Saved to Hive!', `Page "${title || url}" has been ingested.`);
    } else if (status === 'exists') {
      showNotification('Already in Hive', `"${title || url}" was already in your knowledge base.`);
    } else {
      showNotification('Hive: ' + status, JSON.stringify(result));
    }
  } catch (e) {
    showNotification('Hive Error', `Failed to send to Hive: ${e.message}`);
  }
});

// ── Notifications ──

function showNotification(title, message) {
  chrome.notifications.create({
    type: 'basic',
    iconUrl: 'icons/icon48.png',
    title: title,
    message: message,
    priority: 1,
  });
}

// ── Message Handler (for popup) ──

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'ingest') {
    ingestUrl(request.url, request.title)
      .then(result => sendResponse({ ok: true, result }))
      .catch(err => sendResponse({ ok: false, error: err.message }));
    return true; // keep channel open for async response
  }

  if (request.action === 'health') {
    checkServerHealth()
      .then(result => sendResponse(result))
      .catch(err => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (request.action === 'getConfig') {
    getConfig().then(cfg => sendResponse(cfg));
    return true;
  }
});
