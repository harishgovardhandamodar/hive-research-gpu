#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN=python3
else
  PYTHON_BIN=python
fi

if "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import socket
s = socket.socket()
s.settimeout(1)
try:
    s.connect(("127.0.0.1", 8081))
except OSError:
    raise SystemExit(1)
finally:
    s.close()
PY
then
  echo "hive-server already running on port 8081; skipping compose build/start for hive-server"
  docker compose up -d hive-research-gpu
else
  echo "hive-server not detected on port 8081; starting hive-server and hive-research-gpu"
  docker compose --profile server up -d --build
fi
