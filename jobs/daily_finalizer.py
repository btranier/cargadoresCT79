#!/usr/bin/env python3
import os, time, csv, json
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

OUTDIR = os.environ.get("PROBE_OUTDIR", "/app/logs")
INGEST_BULK_URL = os.environ.get("INGEST_BULK_URL", "http://backend:10000/api/ingest/bulk_day")
SOURCE = os.environ.get("SOURCE_ID", "pi")
FINALIZE_HOUR = int(os.environ.get("FINALIZE_HOUR", "23"))
FINALIZE_MIN = int(os.environ.get("FINALIZE_MIN", "50"))

def day_str(dt): return dt.strftime("%Y%m%d")
def readings_csv_path(dt): return os.path.join(OUTDIR, f"readings_{day_str(dt)}.csv")

def post_json(url, payload, timeout=30):
    data=json.dumps(payload).encode("utf-8")
    req=Request(url, data=data, headers={"Content-Type":"application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8","ignore")
    except HTTPError as e:
        return e.code, e.read().decode("utf-8","ignore")
    except URLError as e:
        return 0, str(e)

def read_all_rows(path):
    if not os.path.exists(path): return []
    with open(path,"r",encoding="utf-8") as f:
        return list(csv.DictReader(f))

def sleep_until_target():
    now=datetime.now()
    target=now.replace(hour=FINALIZE_HOUR, minute=FINALIZE_MIN, second=0, microsecond=0)
    if target<=now: target += timedelta(days=1)
    time.sleep(max(1.0,(target-now).total_seconds()))

def main():
    os.makedirs(OUTDIR, exist_ok=True)
    while True:
        sleep_until_target()
        now=datetime.now()
        path=readings_csv_path(now)
        rows=read_all_rows(path)
        payload={"date_local": now.strftime("%Y-%m-%d"), "source": SOURCE, "csv_file": os.path.basename(path), "rows": rows}
        status, resp = post_json(INGEST_BULK_URL, payload)
        logf=os.path.join(OUTDIR, f"probe_{day_str(now)}.log")
        with open(logf,"a",encoding="utf-8") as lf:
            lf.write(f"\n[finalize] {now.isoformat()} status={status} resp={resp[:500]}\n")

if __name__=="__main__":
    main()
