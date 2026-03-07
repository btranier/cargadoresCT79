#!/usr/bin/env python3
import argparse
import csv
import os
import sqlite3
from pathlib import Path


def _to_float(value):
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _to_ok(value):
    return 0 if str(value).strip().lower() in {"false", "0", "no"} else 1


def _sqlite_path() -> Path:
    url = os.getenv("DATABASE_URL", "sqlite:///./data/saci.db")
    if not url.startswith("sqlite:///"):
        raise RuntimeError("This importer supports only sqlite DATABASE_URL")
    return Path(url.replace("sqlite:///", "", 1))


def import_csv(csv_path: Path):
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    db_path = _sqlite_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA busy_timeout=10000")

    con.execute("""
    CREATE TABLE IF NOT EXISTS gateways (
      id INTEGER PRIMARY KEY,
      label TEXT NOT NULL,
      host TEXT NOT NULL,
      port INTEGER NOT NULL,
      UNIQUE(host, port)
    )
    """)
    con.execute("""
    CREATE TABLE IF NOT EXISTS meters (
      id INTEGER PRIMARY KEY,
      gateway_id INTEGER,
      unit_id INTEGER
    )
    """)
    con.execute("""
    CREATE TABLE IF NOT EXISTS readings (
      id INTEGER PRIMARY KEY,
      ts_utc DATETIME,
      gateway_id INTEGER,
      unit_id INTEGER,
      meter_id INTEGER,
      volt_v FLOAT,
      current_a FLOAT,
      power_kw FLOAT,
      freq_hz FLOAT,
      pf FLOAT,
      kwh_import FLOAT,
      ok INTEGER DEFAULT 1,
      error TEXT
    )
    """)
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS uix_readings_ts_gw_unit ON readings(ts_utc, gateway_id, unit_id)")

    inserted = duplicates = skipped = 0
    gateway_cache = {}

    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = csv.DictReader(f)
        for row in rows:
            ts = (row.get("timestamp_utc") or "").strip()
            gw = (row.get("gateway") or "").strip()
            unit = (row.get("unit") or row.get("unit_id") or "").strip()
            if not ts or not gw or not unit:
                skipped += 1
                continue

            try:
                unit_i = int(unit)
                if unit_i <= 0:
                    skipped += 1
                    continue
                host, port_raw = gw.split(":")
                port = int(port_raw)
            except Exception:
                skipped += 1
                continue

            gw_key = (host, port)
            gw_id = gateway_cache.get(gw_key)
            if gw_id is None:
                existing = con.execute("SELECT id FROM gateways WHERE host=? AND port=? ORDER BY id ASC LIMIT 1", (host, port)).fetchone()
                if existing:
                    gw_id = existing[0]
                else:
                    cur = con.execute(
                        "INSERT INTO gateways(label, host, port) VALUES (?, ?, ?)",
                        (f"{host}:{port}", host, port),
                    )
                    gw_id = cur.lastrowid
                gateway_cache[gw_key] = gw_id

            meter_row = con.execute(
                "SELECT id FROM meters WHERE gateway_id=? AND unit_id=?",
                (gw_id, unit_i),
            ).fetchone()
            meter_id = meter_row[0] if meter_row else None

            cur = con.execute(
                """
                INSERT OR IGNORE INTO readings
                (ts_utc, gateway_id, unit_id, meter_id, volt_v, current_a, power_kw, freq_hz, pf, kwh_import, ok, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts.replace("Z", "").replace("T", " ").replace("+00:00", ""),
                    gw_id,
                    unit_i,
                    meter_id,
                    _to_float(row.get("volt_v")),
                    _to_float(row.get("current_a")),
                    _to_float(row.get("power_kw") or row.get("pow_kw")),
                    _to_float(row.get("freq_hz")),
                    _to_float(row.get("pf")),
                    _to_float(row.get("kwh_import")),
                    _to_ok(row.get("ok")),
                    (row.get("error") or "").strip() or None,
                ),
            )
            if cur.rowcount == 1:
                inserted += 1
            else:
                duplicates += 1

    con.commit()
    con.close()
    return inserted, duplicates, skipped, db_path


def main():
    parser = argparse.ArgumentParser(description="Import collector readings CSV into sqlite DB.")
    parser.add_argument("csv_path", help="Path to readings_YYYYMMDD.csv")
    args = parser.parse_args()

    inserted, duplicates, skipped, db_path = import_csv(Path(args.csv_path))
    print(f"db={db_path} inserted={inserted} duplicates={duplicates} skipped={skipped}")


if __name__ == "__main__":
    main()
