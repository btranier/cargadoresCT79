import os, csv, datetime as dt
from sqlalchemy import select
from .db import SessionLocal, init_db, Gateway, Meter, Reading

IMPORT_DIR = os.getenv("IMPORT_DIR", "./data/import_bootstrap")

def parse_ts(s: str):
    if not s: return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None

def ensure_maps(db):
    gmap = {(g.host, g.port): g.id for g in db.execute(select(Gateway)).scalars()}
    mmap = {}
    for gid in gmap.values():
        rows = db.execute(select(Meter).where(Meter.gateway_id == gid)).scalars().all()
        for m in rows:
            mmap[(gid, m.unit_id)] = m.id
    return gmap, mmap

def import_csv(path: str):
    with SessionLocal() as db, open(path, newline="", encoding="utf-8") as f:
        gmap, mmap = ensure_maps(db)
        r = csv.DictReader(f)
        added = 0
        for row in r:
            ts = parse_ts(row.get("ts_utc", ""))
            host = (row.get("gateway_host") or "").strip()
            port = int(row.get("gateway_port") or "502")
            unit = int(row.get("unit_id") or "0")
            if not ts or not host or not unit:
                continue
            gid = gmap.get((host, port))
            if not gid:
                continue
            exists = db.execute(
                select(Reading.id).where(
                    Reading.ts_utc == ts,
                    Reading.gateway_id == gid,
                    Reading.unit_id == unit,
                )
            ).first()
            if exists:
                continue
            m_id = mmap.get((gid, unit))
            rd = Reading(
                ts_utc=ts,
                gateway_id=gid,
                unit_id=unit,
                meter_id=m_id,
                volt_v=float(row.get("volt_v") or 0) if row.get("volt_v") else None,
                current_a=float(row.get("current_a") or 0) if row.get("current_a") else None,
                power_kw=float(row.get("power_kw") or 0) if row.get("power_kw") else None,
                freq_hz=float(row.get("freq_hz") or 0) if row.get("freq_hz") else None,
                pf=float(row.get("pf") or 0) if row.get("pf") else None,
                kwh_import=float(row.get("kwh_import") or 0) if row.get("kwh_import") else None,
            )
            db.add(rd); added += 1
        db.commit()
    print(f"[import] {path}: inserted {added} rows")

def run():
    init_db()
    if not os.path.isdir(IMPORT_DIR):
        print(f"[import] No dir {IMPORT_DIR}. Skipping.")
        return
    for name in sorted(os.listdir(IMPORT_DIR)):
        if name.lower().endswith(".csv"):
            import_csv(os.path.join(IMPORT_DIR, name))

if __name__ == "__main__":
    run()
