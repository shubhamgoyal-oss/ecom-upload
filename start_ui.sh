#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m pip install --user -r requirements.txt >/tmp/fb_ui_pip.log 2>&1 || true
nohup python3 -c "from app import app; app.run(host='0.0.0.0', port=5050, debug=False, use_reloader=False)" >/tmp/fb_ui.log 2>&1 &
echo $! >/tmp/fb_ui.pid
sleep 1
if curl -sSf http://127.0.0.1:5050/ >/dev/null; then
  echo "FB UI started: http://127.0.0.1:5050"
else
  echo "FB UI failed to start. Check /tmp/fb_ui.log"
  exit 1
fi
