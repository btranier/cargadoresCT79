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

echo "[4/7] Stopping current project containers..."
docker compose down --remove-orphans

echo "[5/7] Rebuilding images..."
docker compose build --pull

echo "[6/7] Starting containers..."
docker compose up -d

echo "[7/7] Current container status:"
docker compose ps

echo
printf 'Deploy complete on ref %s\n' "$REF"
printf 'Tip: use "docker compose logs -f collector" to monitor probe runs.\n'
