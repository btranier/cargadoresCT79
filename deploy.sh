#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCH_DIR="$(pwd)"
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

ROOT_DIR=""

add_candidate() {
  local c="$1"
  [ -n "$c" ] || return 0
  if [ -f "$c/docker-compose.yml" ]; then
    ROOT_DIR="$(cd "$c" && pwd)"
    return 1
  fi
  return 0
}

# Resolve root robustly for cases where deploy is launched from parent folders.
if [ -n "${DEPLOY_ROOT:-}" ]; then
  add_candidate "$DEPLOY_ROOT" || true
fi

GIT_ROOT_SCRIPT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
GIT_ROOT_LAUNCH="$(git -C "$LAUNCH_DIR" rev-parse --show-toplevel 2>/dev/null || true)"

for candidate in \
  "$GIT_ROOT_SCRIPT" \
  "$GIT_ROOT_LAUNCH" \
  "$SCRIPT_DIR" \
  "$LAUNCH_DIR" \
  "$SCRIPT_DIR/cargadoresCT79" \
  "$LAUNCH_DIR/cargadoresCT79"
do
  if [ -z "$ROOT_DIR" ]; then
    add_candidate "$candidate" || true
  fi
done

if [ -z "$ROOT_DIR" ]; then
  echo "Error: could not locate project root with docker-compose.yml." >&2
  echo "Hint: run with DEPLOY_ROOT=/path/to/cargadoresCT79 ./deploy ${REF}" >&2
  exit 1
fi

cd "$ROOT_DIR"

COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"
compose() {
  docker compose --project-directory "$ROOT_DIR" -f "$COMPOSE_FILE" "$@"
}

remove_conflicting_named_containers() {
  local names=("saci-pi-backend" "saci-pi-collector" "saci-pi-finalizer" "saci-pi")
  local found=0
  for n in "${names[@]}"; do
    if docker container inspect "$n" >/dev/null 2>&1; then
      if [ "$found" -eq 0 ]; then
        echo "Found existing containers with fixed names from another stack. Removing to avoid name conflicts..."
        found=1
      fi
      docker rm -f "$n" >/dev/null 2>&1 || true
      echo "  removed: $n"
    fi
  done
}

HAS_ORIGIN=0
if git remote get-url origin >/dev/null 2>&1; then
  HAS_ORIGIN=1
fi

echo "[1/10] Using project root: $ROOT_DIR"

if [ "$HAS_ORIGIN" -eq 1 ]; then
  echo "[2/10] Fetching latest refs..."
  git fetch --all --prune
else
  echo "[2/10] Skipping fetch (git remote 'origin' not configured)."
fi

echo "[3/10] Checking out ${REF}..."
git checkout "$REF"

if [ "$HAS_ORIGIN" -eq 1 ]; then
  echo "[4/10] Pulling latest commit from origin/${REF}..."
  git pull --ff-only origin "$REF"
else
  echo "[4/10] Skipping pull (git remote 'origin' not configured)."
fi

echo "[5/10] Validating compose configuration..."
compose config >/dev/null

echo "[6/10] Stopping current project containers..."
compose down --remove-orphans

if [ -f "$ROOT_DIR/Dockerfile" ]; then
  echo "[7/10] Rebuilding images from local Dockerfile..."
  compose build --pull
else
  echo "[7/10] Skipping build: Dockerfile not found in $ROOT_DIR (using registry images only)."
fi

echo "[8/10] Pulling published images (if any)..."
compose pull --ignore-buildable || true

echo "[9/10] Cleaning conflicting fixed-name containers..."
remove_conflicting_named_containers

echo "[10/10] Starting containers and showing status..."
compose up -d
compose ps

echo
printf 'Deploy complete on ref %s\n' "$REF"
printf 'Tip: use "docker compose logs -f collector" to monitor probe runs.\n'
