#!/usr/bin/env python3
import argparse
import csv
import os
import sqlite3
from pathlib import Path

DEFAULT_MAPPING_CSV = "data/active_mapping.csv"
METERS_PER_GATEWAY = 32


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




def _ensure_column(con: sqlite3.Connection, table: str, column: str, ddl: str):
    cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

def _ensure_schema(con: sqlite3.Connection):
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
      unit_id INTEGER,
      device_uid TEXT,
      slot_code TEXT,
      description TEXT,
      phase TEXT,
      status TEXT DEFAULT 'Desactivado',
      multiplier FLOAT DEFAULT 1.0,
      owner_name TEXT,
      parking_slot TEXT,
      is_active INTEGER DEFAULT 0,
      UNIQUE(device_uid)
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
    _ensure_column(con, "meters", "device_uid", "device_uid TEXT")
    _ensure_column(con, "meters", "slot_code", "slot_code TEXT")
    _ensure_column(con, "meters", "description", "description TEXT")
    _ensure_column(con, "meters", "phase", "phase TEXT")
    _ensure_column(con, "meters", "status", "status TEXT DEFAULT 'Desactivado'")
    _ensure_column(con, "meters", "multiplier", "multiplier FLOAT DEFAULT 1.0")
    _ensure_column(con, "meters", "owner_name", "owner_name TEXT")
    _ensure_column(con, "meters", "parking_slot", "parking_slot TEXT")
    _ensure_column(con, "meters", "is_active", "is_active INTEGER DEFAULT 0")

    _ensure_column(con, "readings", "ok", "ok INTEGER DEFAULT 1")
    _ensure_column(con, "readings", "error", "error TEXT")

    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS uix_gateways_host_port ON gateways(host, port)")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS uix_meters_gateway_unit ON meters(gateway_id, unit_id)")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS uix_readings_ts_gw_unit ON readings(ts_utc, gateway_id, unit_id)")


def _collect_gateways_from_readings(csv_path: Path):
    gateways = set()
    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            gw = (row.get("gateway") or "").strip()
            if not gw or ":" not in gw:
                continue
            host, port_raw = gw.split(":", 1)
            try:
                gateways.add((host.strip(), int(port_raw)))
            except ValueError:
                continue
    return gateways


def _collect_gateways_from_mapping(mapping_csv: Path):
    gateways = set()
    if not mapping_csv.exists():
        return gateways
    with mapping_csv.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            host = (row.get("gateway_host") or "").strip()
            port_raw = (row.get("gateway_port") or "502").strip()
            if not host:
                continue
            try:
                gateways.add((host, int(port_raw)))
            except ValueError:
                continue
    return gateways


def _get_or_create_gateway(con: sqlite3.Connection, host: str, port: int):
    row = con.execute("SELECT id FROM gateways WHERE host=? AND port=?", (host, port)).fetchone()
    if row:
        return row[0]
    cur = con.execute(
        "INSERT INTO gateways(label, host, port) VALUES (?, ?, ?)",
        (f"{host}:{port}", host, port),
    )
    return cur.lastrowid


def _seed_meters_for_gateway(con: sqlite3.Connection, gateway_id: int):
    created = 0
    for unit_id in range(1, METERS_PER_GATEWAY + 1):
        cur = con.execute(
            """
            INSERT OR IGNORE INTO meters(gateway_id, unit_id, status, multiplier, is_active)
            VALUES (?, ?, 'Desactivado', 1.0, 0)
            """,
            (gateway_id, unit_id),
        )
        if cur.rowcount == 1:
            created += 1
    return created


def _apply_active_mapping(con: sqlite3.Connection, mapping_csv: Path, gateway_ids: dict):
    if not mapping_csv.exists():
        return 0

    updated = 0
    with mapping_csv.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            host = (row.get("gateway_host") or "").strip()
            port_raw = (row.get("gateway_port") or "502").strip()
            unit_raw = (row.get("unit_id") or "").strip()
            if not host or not unit_raw:
                continue
            try:
                port = int(port_raw)
                unit_id = int(unit_raw)
            except ValueError:
                continue
            gw_id = gateway_ids.get((host, port))
            if gw_id is None:
                continue

            slot_code = (row.get("slot_code") or "").strip() or None
            description = (row.get("description") or "").strip() or None
            phase = (row.get("phase") or "").strip() or None
            status = (row.get("status") or "Activo").strip() or "Activo"

            cur = con.execute(
                """
                UPDATE meters
                SET slot_code=?, description=?, phase=?, status=?, is_active=1
                WHERE gateway_id=? AND unit_id=?
                """,
                (slot_code, description, phase, status, gw_id, unit_id),
            )
            if cur.rowcount == 1:
                updated += 1
    return updated


def import_csv(csv_path: Path, mapping_csv: Path):
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    db_path = _sqlite_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA busy_timeout=10000")

    _ensure_schema(con)

    gateways = _collect_gateways_from_readings(csv_path) | _collect_gateways_from_mapping(mapping_csv)
    gateway_ids = {}
    seeded_meters = 0
    for host, port in sorted(gateways):
        gw_id = _get_or_create_gateway(con, host, port)
        gateway_ids[(host, port)] = gw_id
        seeded_meters += _seed_meters_for_gateway(con, gw_id)

    mapped_active = _apply_active_mapping(con, mapping_csv, gateway_ids)

    inserted = duplicates = skipped = 0
    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = csv.DictReader(f)
        for row in rows:
            ts = (row.get("timestamp_utc") or "").strip()
            gw = (row.get("gateway") or "").strip()
            unit_raw = (row.get("unit") or row.get("unit_id") or "").strip()
            if not ts or not gw or not unit_raw:
                skipped += 1
                continue

            try:
                host, port_raw = gw.split(":", 1)
                port = int(port_raw)
                unit_i = int(unit_raw)
                if unit_i <= 0:
                    raise ValueError("unit must be > 0")
            except Exception:
                skipped += 1
                continue

            gw_id = gateway_ids.get((host, port))
            if gw_id is None:
                gw_id = _get_or_create_gateway(con, host, port)
                gateway_ids[(host, port)] = gw_id
                seeded_meters += _seed_meters_for_gateway(con, gw_id)

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
    return {
        "db": db_path,
        "inserted": inserted,
        "duplicates": duplicates,
        "skipped": skipped,
        "seeded_meters": seeded_meters,
        "mapped_active": mapped_active,
        "gateways": len(gateway_ids),
    }


def main():
    parser = argparse.ArgumentParser(description="Import collector readings CSV into sqlite DB.")
    parser.add_argument("csv_path", help="Path to readings_YYYYMMDD.csv")
    parser.add_argument(
        "--mapping-csv",
        default=DEFAULT_MAPPING_CSV,
        help=f"CSV with active meters mapping (default: {DEFAULT_MAPPING_CSV})",
    )
    args = parser.parse_args()

    stats = import_csv(Path(args.csv_path), Path(args.mapping_csv))
    print(
        "db={db} gateways={gateways} seeded_meters={seeded_meters} mapped_active={mapped_active} "
        "inserted={inserted} duplicates={duplicates} skipped={skipped}".format(**stats)
    )


if __name__ == "__main__":
    main()
