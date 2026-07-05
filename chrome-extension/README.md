# Hive Research — Chrome Extension

Ingest web pages into your Hive Research knowledge base with one click.

## Features

- **One-click ingest** — Click the toolbar icon, then "Send to Hive Research"
- **Right-click menu** — Right-click any page or link → "Send to Hive Research"
- **Status indicator** — Shows server connection status (green/red dot)
- **Settings page** — Configure server URL and optional auth token
- **Notifications** — Desktop notifications for success/failure

## Installation

1. Open Chrome and go to `chrome://extensions`
2. Enable **Developer mode** (toggle in top-right)
3. Click **Load unpacked**
4. Select the `chrome-extension/` directory in this project

## Configuration

1. Click the extension toolbar icon
2. Click **⚙ Settings** at the bottom
3. Enter your Hive server URL (default: `http://localhost:7777`)
4. If your server uses auth, enter your `HIVE_AUTH_TOKEN`
5. Click **Test Connection** to verify
6. Click **Save**

## Usage

### Toolbar icon
1. Navigate to any web page
2. Click the 🐝 Hive toolbar icon
3. Review the page info
4. Click **Send to Hive Research**

### Right-click
1. Right-click on a page or link
2. Select **Send to Hive Research**
3. A desktop notification shows the result

## Architecture

```
┌─────────────────────┐     ┌──────────────────────┐
│  Chrome Extension   │     │  Hive Research Server │
│                     │     │                      │
│  popup.js ──────────┼────>│  POST /api/web/add   │
│  background.js ─────┼────>│  { url, title }      │
│                     │     │                      │
│  options.js ────────┼────>│  GET /api/stats      │
└─────────────────────┘     └──────────────────────┘
```

## Development

The extension is written in vanilla JavaScript (no build step). Files:

| File | Purpose |
|------|---------|
| `manifest.json` | Extension manifest (Manifest V3) |
| `background.js` | Service worker: context menus, API calls, notifications |
| `popup.html` / `popup.js` | Toolbar popup UI |
| `options.html` / `options.js` | Settings page |
| `icons/` | Extension icons (16, 32, 48, 128px) |
