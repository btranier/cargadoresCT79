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

echo "[1/9] Using project root: $ROOT_DIR"

echo "[2/9] Fetching latest refs..."
git fetch --all --prune

echo "[3/9] Checking out ${REF}..."
git checkout "$REF"

echo "[4/9] Pulling latest commit from origin/${REF}..."
git pull --ff-only origin "$REF"

COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"
echo "[1/8] Using project root: $ROOT_DIR"

echo "[2/8] Fetching latest refs..."
git fetch --all --prune

echo "[3/8] Checking out ${REF}..."
git checkout "$REF"

echo "[4/8] Pulling latest commit from origin/${REF}..."
git pull --ff-only origin "$REF"

COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"
DOCKERFILE_PATH="$ROOT_DIR/Dockerfile"

if [ ! -f "$COMPOSE_FILE" ]; then
  echo "Error: docker compose file not found at $COMPOSE_FILE" >&2
  exit 1
fi

if [ ! -f "$DOCKERFILE_PATH" ]; then
  echo "Error: Dockerfile not found at $DOCKERFILE_PATH" >&2
  exit 1
fi

compose() {
  docker compose --project-directory "$ROOT_DIR" -f "$COMPOSE_FILE" "$@"
}

echo "[5/9] Validating compose configuration..."
compose config >/dev/null

echo "[6/9] Stopping current project containers..."
compose down --remove-orphans

echo "[7/9] Rebuilding images (when Dockerfile/build context is available)..."
BUILD_LOG="$(mktemp)"
if compose build --pull >"$BUILD_LOG" 2>&1; then
  cat "$BUILD_LOG"
  echo "Build step completed successfully."
else
  cat "$BUILD_LOG"
  if grep -Eqi "failed to read dockerfile|dockerfile: no such file or directory|open .*Dockerfile: no such file or directory" "$BUILD_LOG"; then
    echo "Warning: Dockerfile not found for one or more build services."
    echo "Continuing with image pull + startup (this preserves legacy setups without local Dockerfile)."
  else
    echo "Error: docker compose build failed." >&2
    rm -f "$BUILD_LOG"
    exit 1
  fi
fi
rm -f "$BUILD_LOG"

echo "[8/9] Pulling published images (if any)..."
compose pull --ignore-buildable || true

echo "[9/9] Starting containers and showing status..."
compose up -d
compose ps

echo
printf 'Deploy complete on ref %s\n' "$REF"
printf 'Tip: use "docker compose logs -f collector" to monitor probe runs.\n'
