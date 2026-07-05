// Hive Research — Popup Script

const $ = id => document.getElementById(id);

let currentTab = null;

// ── Load tab info ──

async function loadTabInfo() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tabs || !tabs.length) {
    $('pageTitle').textContent = 'No active tab';
    return;
  }
  currentTab = tabs[0];
  $('pageTitle').textContent = currentTab.title || '(untitled)';
  $('pageUrl').textContent = currentTab.url || '—';
}

// ── Health check ──

async function checkHealth() {
  const dot = $('statusDot');
  dot.className = 'status loading';

  try {
    const resp = await chrome.runtime.sendMessage({ action: 'health' });
    if (resp && resp.ok) {
      dot.className = 'status online';
      $('serverDisplay').textContent = 'connected';
      $('ingestBtn').disabled = false;
    } else {
      dot.className = 'status offline';
      $('serverDisplay').textContent = 'disconnected';
      $('ingestBtn').disabled = true;
    }
  } catch (e) {
    dot.className = 'status offline';
    $('serverDisplay').textContent = 'error';
    $('ingestBtn').disabled = true;
  }

  // Show server URL
  try {
    const cfg = await chrome.runtime.sendMessage({ action: 'getConfig' });
    if (cfg && cfg.serverUrl) {
      $('serverLink').querySelector('span').textContent = cfg.serverUrl.replace(/^https?:\/\//, '');
    }
  } catch (_) {}
}

// ── Ingest ──

async function ingest() {
  if (!currentTab || !currentTab.url) return;

  const btn = $('ingestBtn');
  const result = $('result');
  btn.disabled = true;
  btn.textContent = 'Sending...';
  result.className = 'result';
  result.style.display = 'none';

  try {
    const resp = await chrome.runtime.sendMessage({
      action: 'ingest',
      url: currentTab.url,
      title: currentTab.title || '',
    });

    if (resp && resp.ok) {
      const status = resp.result.status || 'done';
      if (status === 'added') {
        result.className = 'result success';
        result.innerHTML = `<div class="label">✓ Saved to Hive</div>
          <div class="detail">Page has been ingested and added to your knowledge graph.</div>`;
      } else if (status === 'exists') {
        result.className = 'result success';
        result.innerHTML = `<div class="label">Already in Hive</div>
          <div class="detail">This page was already in your knowledge base.</div>`;
      } else {
        result.className = 'result success';
        result.innerHTML = `<div class="label">✓ ${status}</div>
          <div class="detail">${JSON.stringify(resp.result)}</div>`;
      }
      btn.className = 'btn btn-success';
      btn.textContent = '✓ Sent';
    } else {
      throw new Error((resp && resp.error) || 'Unknown error');
    }
  } catch (e) {
    result.className = 'result error';
    result.innerHTML = `<div class="label">✗ Failed</div>
      <div class="detail">${e.message}</div>`;
    btn.className = 'btn btn-error';
    btn.textContent = 'Retry';
    btn.disabled = false;
  }
}

// ── Events ──

document.addEventListener('DOMContentLoaded', () => {
  loadTabInfo();
  checkHealth();

  $('ingestBtn').addEventListener('click', ingest);

  $('optionsLink').addEventListener('click', (e) => {
    e.preventDefault();
    chrome.runtime.openOptionsPage();
  });
});
