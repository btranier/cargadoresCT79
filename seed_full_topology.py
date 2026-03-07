#!/usr/bin/env python3
import csv, argparse
from sqlalchemy import delete, select
from backend.db import SessionLocal, init_db, Gateway, Meter, Reading

def upsert_gateway(db, host, port, label=None):
    g = db.execute(select(Gateway).where(Gateway.host==host, Gateway.port==port)).scalars().first()
    if g:
        if label and g.label != label:
            g.label = label; db.commit()
        return g
    g = Gateway(label=label or f"{host}:{port}", host=host, port=int(port))
    db.add(g); db.commit(); db.refresh(g); return g

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--clear-readings", action="store_true")
    args = ap.parse_args()

    init_db()
    hosts = [
        ("192.168.1.100", 502, "gw1"),
        ("192.168.1.101", 502, "gw2"),
        ("192.168.1.102", 502, "gw3"),
        ("192.168.1.103", 502, "gw4"),
    ]
    with SessionLocal() as db:
        if args.clear_readings:
            db.execute(delete(Reading))
        db.execute(delete(Meter))
        db.execute(delete(Gateway))
        db.commit()

        gw_id_by_host = {}
        for h,p,label in hosts:
            gw = upsert_gateway(db, h, p, label)
            gw_id_by_host[(h,p)] = gw.id

        # Pre-create 32 per gateway
        for (h,p), gid in gw_id_by_host.items():
            for unit in range(1,33):
                m = Meter(gateway_id=gid, unit_id=unit, status="Desactivado", multiplier=1.0)
                db.add(m)
        db.commit()

        # Activate and label from CSV
        with open(args.csv_path, newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                host = row["gateway_host"].strip()
                port = int(row.get("gateway_port","502") or "502")
                unit = int(row["unit_id"])
                slot = (row.get("slot_code") or "").strip() or None
                desc = (row.get("description") or "").strip() or None
                phase = (row.get("phase") or "").strip() or None
                status = (row.get("status") or "Activo").strip() or "Activo"
                gid = gw_id_by_host.get((host,port))
                if gid is None: 
                    continue
                m = db.execute(select(Meter).where(Meter.gateway_id==gid, Meter.unit_id==unit)).scalars().first()
                if not m:
                    m = Meter(gateway_id=gid, unit_id=unit)
                    db.add(m); db.commit(); db.refresh(m)
                m.slot_code = slot
                m.description = desc
                m.phase = phase
                m.status = status
                db.commit()
        print("Reseed complete.")

if __name__ == "__main__":
    main()
