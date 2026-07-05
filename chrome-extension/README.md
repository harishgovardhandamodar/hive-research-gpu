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

## Building & Packaging

### Development (no build — load unpacked)

The extension is written in vanilla JavaScript with no build step. All files are used directly.

```bash
# From the project root, the extension is at:
chrome-extension/
├── manifest.json
├── background.js
├── popup.html / popup.js
├── options.html / options.js
└── icons/
```

To load during development:
1. Open Chrome → `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select the `chrome-extension/` directory

### Packaging for distribution (ZIP)

To create a distributable `.zip` for the Chrome Web Store or sideloading:

```bash
# From the project root
cd chrome-extension
zip -r ../hive-research-extension.zip . \
  -x "*.git*" \
  -x "*.DS_Store" \
  -x "*README.md"
cd ..
```

This creates `hive-research-extension.zip` in the project root.

### Automate with a build script

A `Makefile` target or script can be added to `pyproject.toml`:

```bash
# Or using the convenience script:
python3 -c "
import shutil, zipfile, pathlib
src = pathlib.Path('chrome-extension')
dst = pathlib.Path('dist/hive-research-extension.zip')
dst.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zf:
    for f in src.rglob('*'):
        if f.is_file() and not f.name.startswith('.'):
            zf.write(f, arcname=f.relative_to(src.parent))
print(f'Extension package: {dst}')
"
```

### Sideloading the packaged extension

1. Go to `chrome://extensions`
2. Enable **Developer mode**
3. Drag and drop the `.zip` file onto the extensions page
4. Chrome will unpack and install it automatically

### Chrome Web Store submission (optional)

To publish on the Chrome Web Store:
1. Create a developer account at https://chrome.google.com/webstore/devconsole
2. Pay the one-time registration fee ($5)
3. Upload the `hive-research-extension.zip`
4. Fill in store listing details (description, screenshots, icons)
5. Submit for review

## Project Files

| File | Purpose |
|------|---------|
| `manifest.json` | Extension manifest (Manifest V3, permissions, icons) |
| `background.js` | Service worker: context menus, API calls, notifications |
| `popup.html` / `popup.js` | Toolbar popup UI |
| `options.html` / `options.js` | Settings page with server config + test connection |
| `icons/` | Extension icons (16, 32, 48, 128px + SVG) |
| `README.md` | This file |
