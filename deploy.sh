#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REF="${1:-main}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: docker is not installed or not in PATH." >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Error: docker compose plugin is not available." >&2
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "Error: git is not installed or not in PATH." >&2
  exit 1
fi

# Resolve project root robustly across environments.
# Priority:
#   1) DEPLOY_ROOT env override
#   2) git toplevel from script directory
#   3) script directory itself
#   4) a nested ./cargadoresCT79 folder
ROOT_DIR=""
if [ -n "${DEPLOY_ROOT:-}" ] && [ -f "${DEPLOY_ROOT}/docker-compose.yml" ]; then
  ROOT_DIR="$(cd "${DEPLOY_ROOT}" && pwd)"
else
  GIT_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
  for candidate in "$GIT_ROOT" "$SCRIPT_DIR" "$SCRIPT_DIR/cargadoresCT79"; do
    if [ -n "$candidate" ] && [ -f "$candidate/docker-compose.yml" ]; then
      ROOT_DIR="$(cd "$candidate" && pwd)"
      break
    fi
  done
fi

if [ -z "$ROOT_DIR" ]; then
  echo "Error: could not locate project root with docker-compose.yml." >&2
  echo "Hint: run with DEPLOY_ROOT=/path/to/repo ./deploy ${REF}" >&2
  exit 1
fi

cd "$ROOT_DIR"

echo "[1/8] Using project root: $ROOT_DIR"

echo "[2/8] Fetching latest refs..."
git fetch --all --prune

echo "[3/8] Checking out ${REF}..."
git checkout "$REF"

echo "[4/8] Pulling latest commit from origin/${REF}..."
git pull --ff-only origin "$REF"

COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"

compose() {
  docker compose --project-directory "$ROOT_DIR" -f "$COMPOSE_FILE" "$@"
}

echo "[5/8] Validating compose configuration..."
compose config >/dev/null

echo "[6/8] Stopping current project containers..."
compose down --remove-orphans

echo "[7/8] Rebuilding images..."
compose build --pull

echo "[8/8] Starting containers and showing status..."
compose up -d
compose ps

echo
printf 'Deploy complete on ref %s\n' "$REF"
printf 'Tip: use "docker compose logs -f collector" to monitor probe runs.\n'
