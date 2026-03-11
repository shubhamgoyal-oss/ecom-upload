#!/usr/bin/env bash
set -euo pipefail
if [ -f /tmp/fb_ui.pid ]; then
  PID=$(cat /tmp/fb_ui.pid || true)
  if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
    kill "$PID" || true
  fi
  rm -f /tmp/fb_ui.pid
fi
pkill -f "from app import app; app.run(host='0.0.0.0', port=5050" >/dev/null 2>&1 || true
echo "FB UI stopped"
