#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./import_readings.sh [csv_path]
# Example:
#   ./import_readings.sh readings_20260201.csv

CSV_PATH="${1:-readings_20260201.csv}"
DB_PATH="${DB_PATH:-./data/saci.db}"

if [[ ! -f "$CSV_PATH" ]]; then
  echo "❌ CSV file not found: $CSV_PATH"
  exit 1
fi

export DATABASE_URL="sqlite:///$DB_PATH"
export PYTHONPATH="${PYTHONPATH:-.}"

echo "➡️  Importing '$CSV_PATH' into '$DB_PATH'..."
python -m backend.import_readings_csv "$CSV_PATH"

echo "✅ Done. Quick DB check:"
python - <<'PY'
import os, sqlite3
from pathlib import Path
url = os.getenv("DATABASE_URL")
db = Path(url.replace("sqlite:///", "", 1))
con = sqlite3.connect(db)
cur = con.cursor()
for q, label in [
    ("select count(*) from gateways", "gateways"),
    ("select count(*) from readings", "readings"),
    ("select count(*) from readings where ok=1", "readings_ok"),
]:
    print(f"{label}={cur.execute(q).fetchone()[0]}")
con.close()
PY
