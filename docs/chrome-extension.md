# Chrome Extension

A browser extension for one-click web page ingestion into Hive Research.

## Installation

1. Open Chrome and go to `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select the `chrome-extension/` directory

## Building for Distribution

```bash
cd chrome-extension
python3 build.py
# Creates dist/hive-research-extension.zip
```

## Usage

### Toolbar Icon
1. Navigate to any web page
2. Click the Hive toolbar icon
3. Review the page info
4. Click **Send to Hive Research**

### Right-Click Menu
1. Right-click on a page or link
2. Select **Send to Hive Research**
3. A desktop notification shows the result

## Configuration

1. Click the extension icon → **⚙ Settings**
2. Enter your Hive server URL (default: `http://localhost:7777`)
3. Optionally enter an auth token
4. Click **Test Connection** to verify
5. Click **Save**

## Architecture

```
┌─────────────────────┐     ┌──────────────────────┐
│  Chrome Extension   │     │  Hive Research Server │
│                     │     │                      │
│  popup.js ──────────┼────>│  POST /api/web/add   │
│  background.js ─────┼────>│  { url }             │
│                     │     │                      │
│  options.js ────────┼────>│  GET /api/stats      │
└─────────────────────┘     └──────────────────────┘
```
