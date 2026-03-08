#!/usr/bin/env bash
set -euo pipefail

REF="${1:-main}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCH_DIR="$(pwd)"

require_cmd() {
  local cmd="$1"
  local hint="$2"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Error: ${hint}" >&2
    exit 1
  fi
}

require_cmd docker "docker is not installed or not in PATH."
require_cmd git "git is not installed or not in PATH."

if ! docker compose version >/dev/null 2>&1; then
  echo "Error: docker compose plugin is not available." >&2
  exit 1
fi

resolve_root_dir() {
  local -a candidates=()
  local git_script_root git_launch_root

  if [ -n "${DEPLOY_ROOT:-}" ]; then
    candidates+=("$DEPLOY_ROOT")
  fi

  git_script_root="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
  git_launch_root="$(git -C "$LAUNCH_DIR" rev-parse --show-toplevel 2>/dev/null || true)"

  candidates+=(
    "$git_script_root"
    "$git_launch_root"
    "$SCRIPT_DIR"
    "$LAUNCH_DIR"
    "$SCRIPT_DIR/cargadoresCT79"
    "$LAUNCH_DIR/cargadoresCT79"
  )

  local c
  for c in "${candidates[@]}"; do
    [ -n "$c" ] || continue
    if [ -f "$c/docker-compose.yml" ]; then
      cd "$c" && pwd
      return 0
    fi
  done

  return 1
}

ROOT_DIR="$(resolve_root_dir || true)"
if [ -z "$ROOT_DIR" ]; then
  echo "Error: could not locate project root with docker-compose.yml." >&2
  echo "Hint: DEPLOY_ROOT=/path/to/cargadoresCT79 ./deploy ${REF}" >&2
  exit 1
fi

cd "$ROOT_DIR"
COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"

compose() {
  docker compose --project-directory "$ROOT_DIR" -f "$COMPOSE_FILE" "$@"
}

has_origin_remote() {
  git remote get-url origin >/dev/null 2>&1
}

cleanup_fixed_name_containers() {
  local -a names=("saci-pi-backend" "saci-pi-collector" "saci-pi-finalizer" "saci-pi")
  local removed_any=0
  local n
  for n in "${names[@]}"; do
    if docker container inspect "$n" >/dev/null 2>&1; then
      docker rm -f "$n" >/dev/null 2>&1 || true
      if [ "$removed_any" -eq 0 ]; then
        echo "Removed stale fixed-name containers to avoid Docker name conflicts:"
        removed_any=1
      fi
      echo "  - $n"
    fi
  done
}

echo "[1/10] Using project root: $ROOT_DIR"

if has_origin_remote; then
  echo "[2/10] Fetching latest refs..."
  git fetch --all --prune
else
  echo "[2/10] Skipping fetch (git remote 'origin' not configured)."
fi

echo "[3/10] Checking out ${REF}..."
git checkout "$REF"

if has_origin_remote; then
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
  echo "[7/10] Skipping build: no Dockerfile in $ROOT_DIR (using image pull only)."
fi

echo "[8/10] Pulling published images (if any)..."
compose pull --ignore-buildable || true

echo "[9/10] Cleaning conflicting fixed-name containers..."
cleanup_fixed_name_containers

echo "[10/10] Starting containers and showing status..."
compose up -d
compose ps

echo
printf 'Deploy complete on ref %s\n' "$REF"
printf 'Tip: use "docker compose logs -f collector" to monitor probe runs.\n'
