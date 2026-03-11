#!/usr/bin/env bash
set -euo pipefail
if lsof -nP -iTCP:5050 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "UP"
  lsof -nP -iTCP:5050 -sTCP:LISTEN
  curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:5050/
else
  echo "DOWN"
fi
