#!/usr/bin/env sh
set -eu
ROOT="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$ROOT/logs" "$ROOT/data"
exec uvicorn backend.app:app --host 0.0.0.0 --port "${PORT:-10000}"
