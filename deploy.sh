#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

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

echo "[1/7] Fetching latest refs..."
git fetch --all --prune

echo "[2/7] Checking out ${REF}..."
git checkout "$REF"

echo "[3/7] Pulling latest commit from origin/${REF}..."
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

echo "[4/8] Validating compose configuration..."
compose config >/dev/null

echo "[5/8] Stopping current project containers..."
compose down --remove-orphans

echo "[6/8] Rebuilding images..."
compose build --pull

echo "[7/8] Starting containers..."
compose up -d

echo "[8/8] Current container status:"
compose ps

echo
printf 'Deploy complete on ref %s\n' "$REF"
printf 'Tip: use "docker compose logs -f collector" to monitor probe runs.\n'
