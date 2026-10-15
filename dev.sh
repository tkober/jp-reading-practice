#!/usr/bin/env bash
# Start backend and frontend together for local development. Ports are
# overridable via env so parallel Claude sessions working on this repo in
# separate worktrees can each pick a free one.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

backend_port="${BACKEND_PORT:-8000}"
frontend_port="${FRONTEND_PORT:-4200}"

if [ ! -f "$root/backend/.env" ]; then
  echo "backend/.env is missing. Copy backend/.env.example and point DB_URL somewhere." >&2
  exit 1
fi

# The CLI would otherwise open an interactive analytics prompt on first run,
# which cannot be answered when both servers share this terminal.
export NG_CLI_ANALYTICS=false

cleanup() {
  # Kill the whole process group so uvicorn's reloader dies with us.
  kill 0 2>/dev/null || true
}
trap cleanup EXIT INT TERM

(cd "$root/backend" && uv run uvicorn app.main:app --reload --port "$backend_port") &
(
  cd "$root/frontend"
  if [ "$backend_port" != "8000" ]; then
    # proxy.conf.json is committed and points at :8000; a non-default
    # backend port needs its own proxy config instead of editing that file.
    proxy_conf=$(mktemp)
    sed "s/localhost:8000/localhost:$backend_port/" proxy.conf.json > "$proxy_conf"
    npx ng serve --port "$frontend_port" --proxy-config "$proxy_conf"
  else
    npx ng serve --port "$frontend_port"
  fi
) &

echo ""
echo "  App:      http://localhost:$frontend_port   <- open this one"
echo "  API docs: http://localhost:$backend_port/docs"
echo ""

wait
