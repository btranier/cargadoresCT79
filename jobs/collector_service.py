#!/usr/bin/env python3
import os, subprocess, time, csv, json
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

ROOT = os.environ.get("ROOT_DIR", "/app")
OUTDIR = os.environ.get("PROBE_OUTDIR", os.path.join(ROOT, "logs"))
SCRIPT = os.environ.get("PROBE_SCRIPT", os.path.join(ROOT, "Cargadores.py"))
INTERVAL_SEC = int(os.environ.get("PROBE_INTERVAL_SEC", "900"))
INGEST_URL = os.environ.get("INGEST_URL", "http://backend:10000/api/ingest/run")
SOURCE = os.environ.get("SOURCE_ID", "pi")

def utcnow():
    return datetime.now(timezone.utc)

def day_str(dt): return dt.strftime("%Y%m%d")
def ensure_dir(p): os.makedirs(p, exist_ok=True)

def readings_csv_path(dt): return os.path.join(OUTDIR, f"readings_{day_str(dt)}.csv")
def log_path(dt): return os.path.join(OUTDIR, f"probe_{day_str(dt)}.log")

def count_rows(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return max(0, sum(1 for _ in f) - 1)
    except Exception:
        return 0

def read_new_rows(path, start_row_exclusive):
    if not os.path.exists(path): return []
    out=[]
    with open(path, "r", encoding="utf-8") as f:
        r=csv.DictReader(f); i=0
        for row in r:
            i+=1
            if i<=start_row_exclusive: continue
            def to_float(x):
                try: return float(x) if x not in (None,"","None") else None
                except: return None
            def to_int(x):
                try: return int(x) if x not in (None,"","None") else None
                except: return None
            out.append({
                "timestamp_utc": row.get("timestamp_utc"),
                "gateway": row.get("gateway"),
                "unit": to_int(row.get("unit")),
                "device_uid": (row.get("device_uid") or "").strip() or None,
                "ok": (str(row.get("ok","")).lower() in ("true","1","yes","y")),
                "volt_v": to_float(row.get("volt_v")),
                "current_a": to_float(row.get("current_a")),
                "power_kw": to_float(row.get("power_kw")),
                "freq_hz": to_float(row.get("freq_hz")),
                "pf": to_float(row.get("pf")),
                "kwh_import": to_float(row.get("kwh_import")),
                "error": row.get("error") or None,
            })
    return out

def append_marker(lf, start): lf.write(f"\n=== RUN {start.isoformat()} ===\n")

def extract_last_run_log(logfile, marker):
    try:
        with open(logfile, "r", encoding="utf-8") as f: txt=f.read()
        idx=txt.rfind(marker)
        return txt[idx:] if idx>=0 else ""
    except Exception:
        return ""

def post_json(url, payload, timeout=15):
    data=json.dumps(payload).encode("utf-8")
    req=Request(url, data=data, headers={"Content-Type":"application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8","ignore")
    except HTTPError as e:
        return e.code, e.read().decode("utf-8","ignore")
    except URLError as e:
        return 0, str(e)

def sleep_to_next_slot(interval):
    now=time.time()
    next_t=((now//interval)+1)*interval
    time.sleep(max(0.0, next_t-now))

def main():
    ensure_dir(OUTDIR)
    while True:
        start=utcnow()
        csv_path=readings_csv_path(start)
        logfile=log_path(start)
        marker=f"=== RUN {start.isoformat()} ==="
        before_rows=count_rows(csv_path)
        try:
            with open(logfile,"a",encoding="utf-8") as lf:
                append_marker(lf,start)
                p=subprocess.run(["python", SCRIPT, "--outdir", OUTDIR],
                                 cwd=ROOT, stdout=lf, stderr=subprocess.STDOUT, env=os.environ.copy())
            end=utcnow()
            new_rows=read_new_rows(csv_path, before_rows)
            run_log_text=extract_last_run_log(logfile, marker)

            gw_failures=[]
            for r in new_rows:
                if (r.get("ok") is False) and r.get("gateway") and r.get("unit"):
                    gw_failures.append({"gateway": r.get("gateway"), "unit": r.get("unit"), "error": r.get("error")})

            synthetic=[]
            try:
                if int(p.returncode)!=0 and len(new_rows)==0:
                    req=Request("http://backend:10000/api/config/gateways", headers={"Accept":"application/json"})
                    with urlopen(req, timeout=10) as resp:
                        gws=json.loads(resp.read().decode("utf-8","ignore") or "[]")
                    ts0=start.isoformat().replace("+00:00","Z")
                    for g in (gws or []):
                        host=g.get("host"); port=g.get("port")
                        if host and port:
                            synthetic.append({
                                "timestamp_utc": ts0,
                                "gateway": f"{host}:{port}",
                                "unit": 1,
                                "ok": False,
                                "volt_v": None, "current_a": None, "power_kw": None, "freq_hz": None, "pf": None, "kwh_import": None,
                                "error": "collector_timeout_or_error"
                            })
            except Exception:
                synthetic=[]

            all_rows=new_rows+synthetic
            if synthetic:
                gw_failures += [{"gateway": r.get("gateway"), "unit": r.get("unit"), "error": r.get("error")} for r in synthetic]

            payload={
                "run_start_utc": start.isoformat().replace("+00:00","Z"),
                "run_end_utc": end.isoformat().replace("+00:00","Z"),
                "exit_code": int(p.returncode),
                "source": SOURCE,
                "csv_file": os.path.basename(csv_path),
                "log_file": os.path.basename(logfile),
                "readings": all_rows,
                "gateway_failures": gw_failures,
                "log_text": run_log_text,
            }
            status, resp = post_json(INGEST_URL, payload)
            with open(logfile,"a",encoding="utf-8") as lf:
                lf.write(f"\n[ingest] status={status} resp={resp[:500]}\n")
        except Exception as e:
            with open(logfile,"a",encoding="utf-8") as lf:
                lf.write(f"\n[collector] ERROR: {repr(e)}\n")
        finally:
            sleep_to_next_slot(INTERVAL_SEC)

if __name__=="__main__":
    main()
