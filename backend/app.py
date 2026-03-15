import glob
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from calendar import monthrange
from sqlalchemy import select, and_, or_, text
from typing import Optional
import os, json
from collections import defaultdict
from html import escape

from .db import SessionLocal, init_db, engine, Gateway, Meter, Reading

STATIC_DIR = "frontend"
INDEX_FILE = os.path.join(STATIC_DIR, "index.html")

app = FastAPI(title="SACI PI Stack v1.4.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"]
)

@app.on_event("startup")
def startup():
    init_db()
    _ensure_ingest_tables()

@app.get("/health")
def health():
    state = {"last_poll_utc": None, "inserted": None}
    try:
        with open("./data/poller_state.json","r",encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        pass
    return {"ok": True, "time": datetime.utcnow().isoformat(), "poller": state}

class MeterEditable(BaseModel):
    slot_code: Optional[str] = None
    description: Optional[str] = None
    phase: Optional[str] = None
    status: Optional[str] = None
    multiplier: Optional[float] = None
    owner_name: Optional[str] = None
    parking_slot: Optional[str] = None
    is_active: Optional[bool] = None

@app.get("/api/config/gateways")
def list_gateways():
    with SessionLocal() as db:
        return [
            {"id":g.id,"label":g.label,"host":g.host,"port":g.port}
            for g in db.execute(select(Gateway)).scalars().all()
        ]

@app.get("/api/config/gateways/{gid}/meters")
def list_meters_by_gateway(gid: int):
    with SessionLocal() as db:
        rows = db.execute(select(Meter).where(Meter.gateway_id==gid).order_by(Meter.unit_id)).scalars().all()
        return [
            {"id":m.id,"gateway_id":m.gateway_id,"unit_id":m.unit_id,"deviceID":(m.device_id or m.device_uid),"slot_code":m.slot_code,
             "description":m.description,"phase":m.phase,"status":m.status,"multiplier":m.multiplier,
             "owner_name":m.owner_name,"parking_slot":m.parking_slot,"is_active":bool(m.is_active)}
            for m in rows
        ]



@app.get("/api/config/meters")
def list_all_meters():
    with SessionLocal() as db:
        rows = db.execute(select(Meter).order_by(Meter.id)).scalars().all()
        return [
            {"id":m.id,"gateway_id":m.gateway_id,"unit_id":m.unit_id,"deviceID":(m.device_id or m.device_uid),"slot_code":m.slot_code,
             "description":m.description,"phase":m.phase,"status":m.status,"multiplier":m.multiplier,
             "owner_name":m.owner_name,"parking_slot":m.parking_slot,"is_active":bool(m.is_active)}
            for m in rows
        ]

@app.patch("/api/config/meters/{mid}")
def edit_meter(mid: int, m: MeterEditable):
    with SessionLocal() as db:
        row = db.get(Meter, mid)
        if not row: raise HTTPException(404, "Medidor no encontrado")
        data = m.dict(exclude_unset=True)
        for k in ("slot_code","description","phase","status","multiplier","owner_name","parking_slot"):
            if k in data: setattr(row, k, data[k])
        if "is_active" in data:
            row.is_active = 1 if data["is_active"] else 0
        db.commit(); db.refresh(row)
        return {"ok": True}

class QueryBody(BaseModel):
    start: str
    end: str
    granularity: str = "15min"
    only_active: bool = True


class DashboardQueryBody(BaseModel):
    start: str
    end: str


def _easter_sunday(year: int):
    # Meeus/Jones/Butcher Gregorian algorithm.
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    from datetime import date
    return date(year, month, day)


def _is_30td_national_holiday(local_ts: datetime) -> bool:
    from datetime import date, timedelta

    y = local_ts.year
    d = local_ts.date()
    easter = _easter_sunday(y)
    good_friday = easter - timedelta(days=2)

    national = {
        date(y, 1, 1),   # Año nuevo
        date(y, 1, 6),   # Epifanía
        good_friday,     # Viernes Santo
        date(y, 5, 1),   # Día del trabajador
        date(y, 8, 15),  # Asunción
        date(y, 10, 12), # Fiesta nacional
        date(y, 11, 1),  # Todos los Santos
        date(y, 12, 6),  # Constitución
        date(y, 12, 8),  # Inmaculada
        date(y, 12, 25), # Navidad
    }
    return d in national


def _tariff_period_for_spain(local_ts: datetime) -> str:
    # 3.0TD: Saturdays, Sundays and non-substitutable national holidays => P6 all day.
    if local_ts.weekday() >= 5 or _is_30td_national_holiday(local_ts):
        return "P6"

    seasonal_by_hour = {
        1: ["P6"] * 8 + ["P2"] * 2 + ["P1"] * 4 + ["P2"] * 4 + ["P1"] * 4 + ["P2"] * 2,
        2: ["P6"] * 8 + ["P2"] * 2 + ["P1"] * 4 + ["P2"] * 4 + ["P1"] * 4 + ["P2"] * 2,
        7: ["P6"] * 8 + ["P2"] * 2 + ["P1"] * 4 + ["P2"] * 4 + ["P1"] * 4 + ["P2"] * 2,
        12: ["P6"] * 8 + ["P2"] * 2 + ["P1"] * 4 + ["P2"] * 4 + ["P1"] * 4 + ["P2"] * 2,
        3: ["P6"] * 8 + ["P3"] * 2 + ["P2"] * 4 + ["P3"] * 4 + ["P2"] * 4 + ["P3"] * 2,
        11: ["P6"] * 8 + ["P3"] * 2 + ["P2"] * 4 + ["P3"] * 4 + ["P2"] * 4 + ["P3"] * 2,
        6: ["P6"] * 8 + ["P4"] * 2 + ["P3"] * 4 + ["P4"] * 4 + ["P3"] * 4 + ["P4"] * 2,
        8: ["P6"] * 8 + ["P4"] * 2 + ["P3"] * 4 + ["P4"] * 4 + ["P3"] * 4 + ["P4"] * 2,
        9: ["P6"] * 8 + ["P4"] * 2 + ["P3"] * 4 + ["P4"] * 4 + ["P3"] * 4 + ["P4"] * 2,
        4: ["P6"] * 8 + ["P5"] * 2 + ["P4"] * 4 + ["P5"] * 4 + ["P4"] * 4 + ["P5"] * 2,
        5: ["P6"] * 8 + ["P5"] * 2 + ["P4"] * 4 + ["P5"] * 4 + ["P4"] * 4 + ["P5"] * 2,
        10: ["P6"] * 8 + ["P5"] * 2 + ["P4"] * 4 + ["P5"] * 4 + ["P4"] * 4 + ["P5"] * 2,
    }
    return seasonal_by_hour[local_ts.month][local_ts.hour]


def _month_bounds_utc(year: int, month: int):
    tz = ZoneInfo("Europe/Madrid")
    start_local = datetime(year, month, 1, 0, 0, 0, tzinfo=tz)
    if month == 12:
        end_local = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=tz)
    else:
        end_local = datetime(year, month + 1, 1, 0, 0, 0, tzinfo=tz)
    start_utc = start_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    end_utc = end_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    return start_utc, end_utc


def _build_monthly_invoice(db, meter: Meter, year: int, month: int):
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="month must be between 1 and 12")

    start_utc, end_utc = _month_bounds_utc(year, month)
    tz_madrid = ZoneInfo("Europe/Madrid")
    multiplier = 1.0 if meter.multiplier is None else float(meter.multiplier)

    previous_end = db.execute(
        select(Reading)
        .where(and_(Reading.meter_id == meter.id, Reading.ts_utc < start_utc, Reading.kwh_import != None))
        .order_by(Reading.ts_utc.desc())
        .limit(1)
    ).scalars().first()
    current_end = db.execute(
        select(Reading)
        .where(and_(Reading.meter_id == meter.id, Reading.ts_utc < end_utc, Reading.kwh_import != None))
        .order_by(Reading.ts_utc.desc())
        .limit(1)
    ).scalars().first()

    rows = db.execute(
        select(Reading)
        .where(and_(Reading.meter_id == meter.id, Reading.ts_utc >= start_utc - timedelta(days=1), Reading.ts_utc < end_utc))
        .order_by(Reading.ts_utc)
    ).scalars().all()

    periods = ["P1", "P2", "P3", "P4", "P5", "P6"]
    energy_by_period = {p: 0.0 for p in periods}
    max_power_by_period = {p: 0.0 for p in periods}
    daily = defaultdict(lambda: {p: 0.0 for p in periods})

    prev_kwh = previous_end.kwh_import if previous_end else None
    for r in rows:
        ts_local = r.ts_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz_madrid)
        if not (start_utc <= r.ts_utc < end_utc):
            if r.kwh_import is not None:
                prev_kwh = r.kwh_import
            continue

        period = _tariff_period_for_spain(ts_local)
        if r.power_kw is not None:
            max_power_by_period[period] = max(max_power_by_period[period], float(r.power_kw) * multiplier)

        if r.kwh_import is not None and prev_kwh is not None and float(r.kwh_import) >= float(prev_kwh):
            delta = (float(r.kwh_import) - float(prev_kwh)) * multiplier
            energy_by_period[period] += delta
            day_key = ts_local.strftime("%Y-%m-%d")
            daily[day_key][period] += delta
        if r.kwh_import is not None:
            prev_kwh = r.kwh_import

    days = []
    _, last_day = monthrange(year, month)
    for d in range(1, last_day + 1):
        day_key = f"{year:04d}-{month:02d}-{d:02d}"
        entry = {"date": day_key, "periods": {p: round(daily[day_key].get(p, 0.0), 3) for p in periods}}
        entry["total_kwh"] = round(sum(entry["periods"].values()), 3)
        days.append(entry)

    return {
        "meter": {
            "id": meter.id,
            "slot_code": meter.slot_code,
            "owner_name": meter.owner_name,
            "parking_slot": meter.parking_slot,
            "deviceID": meter.device_id or meter.device_uid,
            "multiplier": multiplier,
        },
        "year": year,
        "month": month,
        "timezone": "Europe/Madrid",
        "periods": periods,
        "previous_month_end_reading_kwh": round(float(previous_end.kwh_import), 3) if previous_end and previous_end.kwh_import is not None else None,
        "current_month_end_reading_kwh": round(float(current_end.kwh_import), 3) if current_end and current_end.kwh_import is not None else None,
        "energy_by_period_kwh": {p: round(energy_by_period[p], 3) for p in periods},
        "max_power_by_period_kw": {p: round(max_power_by_period[p], 3) for p in periods},
        "total_energy_kwh": round(sum(energy_by_period.values()), 3),
        "daily_breakdown": days,
    }


@app.get("/api/invoices/monthly/{meter_id}")
def monthly_invoice_data(meter_id: int, year: int, month: int):
    with SessionLocal() as db:
        meter = db.get(Meter, meter_id)
        if not meter:
            raise HTTPException(status_code=404, detail="Meter not found")
        if not bool(meter.is_active):
            raise HTTPException(status_code=400, detail="Meter is inactive")
        return _build_monthly_invoice(db, meter, year, month)


@app.get("/api/invoices/monthly/{meter_id}/print", response_class=HTMLResponse)
def monthly_invoice_printable(meter_id: int, year: int, month: int):
    with SessionLocal() as db:
        meter = db.get(Meter, meter_id)
        if not meter:
            raise HTTPException(status_code=404, detail="Meter not found")
        if not bool(meter.is_active):
            raise HTTPException(status_code=400, detail="Meter is inactive")
        invoice = _build_monthly_invoice(db, meter, year, month)

    periods = invoice["periods"]
    max_daily = max((row["total_kwh"] for row in invoice["daily_breakdown"]), default=0.0)
    bars = []
    for i, day in enumerate(invoice["daily_breakdown"]):
        x = 30 + i * 14
        y = 180
        for p in periods:
            v = day["periods"][p]
            h = 0 if max_daily <= 0 else (v / max_daily) * 130
            y -= h
            color = {"P1": "#ff6b6b", "P2": "#f7a35c", "P3": "#ffd166", "P4": "#06d6a0", "P5": "#4cc9f0", "P6": "#9b5de5"}[p]
            bars.append(f'<rect x="{x}" y="{y:.2f}" width="10" height="{h:.2f}" fill="{color}"></rect>')

    rows = []
    for day in invoice["daily_breakdown"]:
        tds = "".join(f"<td>{day['periods'][p]:.3f}</td>" for p in periods)
        rows.append(f"<tr><td>{escape(day['date'])}</td>{tds}<td>{day['total_kwh']:.3f}</td></tr>")

    period_rows = "".join(
        f"<tr><td>{p}</td><td>{invoice['energy_by_period_kwh'][p]:.3f}</td><td>{invoice['max_power_by_period_kw'][p]:.3f}</td></tr>"
        for p in periods
    )
    meter_label = invoice["meter"]["slot_code"] or f"Meter {invoice['meter']['id']}"
    return f"""
<!doctype html><html><head><meta charset='utf-8'><title>Invoice {escape(meter_label)}</title>
<style>
body{{font-family:Arial,sans-serif;margin:24px;color:#111}} h1{{margin:0 0 6px}} table{{border-collapse:collapse;width:100%;margin-top:10px}} th,td{{border:1px solid #ccc;padding:6px;font-size:12px;text-align:right}} th:first-child,td:first-child{{text-align:left}}
.muted{{color:#666;font-size:12px}} @media print{{.no-print{{display:none}}}}
</style></head><body>
<button class='no-print' onclick='window.print()'>Print / Save PDF</button>
<h1>Monthly invoice — {escape(meter_label)}</h1>
<div class='muted'>Owner: {escape(invoice['meter']['owner_name'] or '-')} · Parking: {escape(invoice['meter']['parking_slot'] or '-')} · Month: {invoice['year']}-{invoice['month']:02d} ({invoice['timezone']})</div>
<p><b>Reading previous month end:</b> {invoice['previous_month_end_reading_kwh']} kWh<br>
<b>Reading invoiced month end:</b> {invoice['current_month_end_reading_kwh']} kWh<br>
<b>Total energy:</b> {invoice['total_energy_kwh']:.3f} kWh</p>
<h3>Delivery periods summary</h3>
<table><thead><tr><th>Period</th><th>Energy (kWh)</th><th>Max power (kW)</th></tr></thead><tbody>{period_rows}</tbody></table>
<h3>Appendix A — Daily table by period</h3>
<table><thead><tr><th>Date</th>{''.join(f'<th>{p}</th>' for p in periods)}<th>Total</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<h3>Appendix B — Daily stacked graph</h3>
<svg width='{max(520, len(invoice['daily_breakdown']) * 14 + 40)}' height='220' viewBox='0 0 {max(520, len(invoice['daily_breakdown']) * 14 + 40)} 220' xmlns='http://www.w3.org/2000/svg'>
<line x1='24' y1='180' x2='{max(520, len(invoice['daily_breakdown']) * 14 + 20)}' y2='180' stroke='#333'/>
{''.join(bars)}
</svg>
</body></html>
"""

@app.get("/api/readings/latest")
@app.get("/readings/latest")
def readings_latest(limit: int = 200):
    with SessionLocal() as db:
        rows = db.execute(
            select(Reading, Meter.slot_code, Meter.owner_name, Meter.parking_slot, Meter.is_active, Meter.device_id, Meter.device_uid, Reading.gateway_id, Reading.unit_id)
            .join(Meter, and_(Meter.gateway_id==Reading.gateway_id, Meter.unit_id==Reading.unit_id), isouter=True)
            .order_by(Reading.ts_utc.desc())
            .limit(limit)
        ).all()
        out=[]
        for r, slot, owner_name, parking_slot, is_active, device_id, device_uid, gwid, unitid in rows:
            out.append({
                "ts_utc": r.ts_utc.isoformat() if r.ts_utc else None,
                "gateway_id": gwid, "unit_id": unitid, "meter_id": r.meter_id,
                "deviceID": device_id or device_uid,
                "slot_code": slot,
                "owner_name": owner_name, "parking_slot": parking_slot, "is_active": bool(is_active) if is_active is not None else None,
                "volt_v": r.volt_v, "current_a": r.current_a, "power_kw": r.power_kw,
                "freq_hz": r.freq_hz, "pf": r.pf, "kwh_import": r.kwh_import
            })
        return out

@app.post("/api/readings/query")
@app.post("/readings/query")
def readings_query(body: QueryBody):
    start = datetime.fromisoformat(body.start.replace("Z","+00:00")).replace(tzinfo=None)
    end = datetime.fromisoformat(body.end.replace("Z","+00:00")).replace(tzinfo=None)

    with SessionLocal() as db:
        rows = db.execute(
            select(Reading, Meter.slot_code, Meter.multiplier, Meter.is_active)
            .join(Meter, and_(Meter.gateway_id==Reading.gateway_id, Meter.unit_id==Reading.unit_id), isouter=True)
            .where(and_(Reading.ts_utc >= start, Reading.ts_utc <= end, or_(Meter.status == None, Meter.status == "Activo")))
            .order_by(Reading.gateway_id, Reading.unit_id, Reading.ts_utc)
        ).all()

        def bucketize(ts, gran):
            if gran == "day":
                return ts.replace(hour=0, minute=0, second=0, microsecond=0)
            if gran == "15min":
                return ts.replace(minute=(ts.minute // 15) * 15, second=0, microsecond=0)
            return ts.replace(minute=0, second=0, microsecond=0)

        series = {}
        label_counts = {}
        meter_labels = {}
        for r, slot, multiplier, is_active in rows:
            if body.only_active and is_active is not None and int(is_active) == 0:
                continue
            meter_key = (r.meter_id or 0, r.gateway_id, r.unit_id)
            if meter_key not in meter_labels:
                base_label = slot or f"G{r.gateway_id}-U{r.unit_id}"
                seen = label_counts.get(base_label, 0)
                label_counts[base_label] = seen + 1
                meter_labels[meter_key] = base_label if seen == 0 else f"{base_label} ({seen+1})"
            label = meter_labels[meter_key]

            prev = series.get(("__prev", meter_key))
            if prev is not None and r.kwh_import is not None and r.kwh_import >= prev:
                delta = r.kwh_import - prev
                mul = 1.0 if multiplier is None else float(multiplier)
                b = bucketize(r.ts_utc, body.granularity)
                series[(b, label)] = series.get((b,label), 0.0) + (delta * mul)
            series[("__prev", meter_key)] = r.kwh_import

        buckets = sorted({b for (b,_) in series.keys() if not (isinstance(b, str) and b=="__prev")})
        slots = sorted({s for (b,s) in series.keys() if not (isinstance(b, str) and b=="__prev")})
        out = {"buckets":[b.isoformat() for b in buckets], "slots": slots, "matrix":[]}
        for b in buckets:
            out["matrix"].append([ round(series.get((b,s),0.0),3) for s in slots ])
        return out


@app.post("/api/dashboard/analytics")
def dashboard_analytics(body: DashboardQueryBody):
    start = datetime.fromisoformat(body.start.replace("Z", "+00:00")).replace(tzinfo=None)
    end = datetime.fromisoformat(body.end.replace("Z", "+00:00")).replace(tzinfo=None)
    if start >= end:
        raise HTTPException(status_code=400, detail="start must be before end")

    def b15(ts: datetime):
        return ts.replace(minute=(ts.minute // 15) * 15, second=0, microsecond=0)

    def bhour(ts: datetime):
        return ts.replace(minute=0, second=0, microsecond=0)

    with SessionLocal() as db:
        meters = db.execute(select(Meter).order_by(Meter.id)).scalars().all()
        gateways = db.execute(select(Gateway).order_by(Gateway.id)).scalars().all()
        gw_by_id = {g.id: g for g in gateways}

        meter_map = {}
        for m in meters:
            if m.gateway_id is None or m.unit_id is None:
                continue
            meter_map[(int(m.gateway_id), int(m.unit_id))] = m

        rows = db.execute(
            select(Reading)
            .where(and_(Reading.ts_utc >= start, Reading.ts_utc < end))
            .order_by(Reading.ts_utc)
        ).scalars().all()

    kw_per_15 = defaultdict(float)
    active_meters_per_15 = defaultdict(set)
    meter_hour_bounds = {}
    unmapped = defaultdict(int)

    for r in rows:
        if r.gateway_id is None or r.unit_id is None:
            continue

        key = (int(r.gateway_id), int(r.unit_id))
        meter = meter_map.get(key)

        if meter is None:
            if r.kwh_import is not None and float(r.kwh_import) > 2:
                unmapped[key] += 1
            continue

        if r.power_kw is not None:
            p = float(r.power_kw)
            bucket_15 = b15(r.ts_utc)
            kw_per_15[bucket_15] += p
            if p > 0.5:
                active_meters_per_15[bucket_15].add(key)

        if r.kwh_import is None:
            continue
        ts_m = r.ts_utc.replace(second=0, microsecond=0)
        if ts_m.minute < 2:
            continue
        hour = bhour(ts_m)
        mhk = (key, hour)
        kwh = float(r.kwh_import)
        prev = meter_hour_bounds.get(mhk)
        if prev is None:
            meter_hour_bounds[mhk] = {
                "first_ts": ts_m,
                "first_kwh": kwh,
                "last_ts": ts_m,
                "last_kwh": kwh,
            }
        else:
            if ts_m <= prev["first_ts"]:
                prev["first_ts"] = ts_m
                prev["first_kwh"] = kwh
            if ts_m >= prev["last_ts"]:
                prev["last_ts"] = ts_m
                prev["last_kwh"] = kwh

    hour_slot_kwh = defaultdict(float)
    total_slot_kwh = defaultdict(float)
    for (key, hour), bound in meter_hour_bounds.items():
        delta = bound["last_kwh"] - bound["first_kwh"]
        if delta < 0:
            continue
        meter = meter_map.get(key)
        if meter is None:
            continue
        mult = 1.0 if meter.multiplier is None else float(meter.multiplier)
        delta = delta * mult
        slot = meter.slot_code or f"G{key[0]}-U{key[1]}"
        hour_slot_kwh[(hour, slot)] += delta
        total_slot_kwh[slot] += delta

    timeline_hours = []
    h = bhour(start)
    while h < end:
        timeline_hours.append(h)
        h = h + timedelta(hours=1)

    slots = [s for s, _ in sorted(total_slot_kwh.items(), key=lambda x: x[1], reverse=True)]
    matrix = []
    for hour in timeline_hours:
        matrix.append([round(hour_slot_kwh.get((hour, s), 0.0), 3) for s in slots])

    max_kw = max(kw_per_15.values()) if kw_per_15 else 0.0
    max_active_meters = max((len(v) for v in active_meters_per_15.values()), default=0)
    total_kwh = sum(total_slot_kwh.values())

    unmapped_list = []
    for (gid, unit_id), count in sorted(unmapped.items(), key=lambda x: x[1], reverse=True):
        gw = gw_by_id.get(gid)
        gw_label = f"{gw.host}:{gw.port}" if gw else f"gateway_id={gid}"
        unmapped_list.append({"gateway": gw_label, "unit_id": unit_id, "readings": count})

    return {
        "buckets": [x.isoformat() for x in timeline_hours],
        "slots": slots,
        "matrix": matrix,
        "kpis": {
            "total_kwh": round(total_kwh, 3),
            "max_kw": round(max_kw, 3),
            "max_active_meters": int(max_active_meters),
        },
        "config": {
            "gateways": len(gateways),
            "meters": len(meter_map),
            "unmapped_meters": len(unmapped_list),
            "unmapped_list": unmapped_list,
        },
    }

@app.get("/api/admin/poller_state")
def poller_state():
    path = "./data/poller_state.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            import json; return json.load(f)
    except Exception:
        return {"last_poll_utc": None, "inserted": None}

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/", response_class=HTMLResponse)
def serve_index():
    return FileResponse(INDEX_FILE)


# --- Bootstrap config + ingest + admin endpoints (v7) ---
BOOTSTRAP_CONFIG_FILE = os.environ.get("BOOTSTRAP_CONFIG_FILE", "./data/active_mapping.csv")
AUTO_BOOTSTRAP_CONFIG = str(os.environ.get("AUTO_BOOTSTRAP_CONFIG", "0")).strip().lower() in ("1", "true", "yes", "on")

def _bootstrap_config_from_flat_file(path: str, replace: bool = False):
    if not os.path.exists(path):
        return {"loaded": 0, "reason": "file_not_found"}
    return {
        "loaded": 0,
        "reason": "disabled",
        "message": "Automated meter imports are disabled. Manage meters manually.",
    }
@app.on_event("startup")
def _startup_bootstrap_config():
    if not AUTO_BOOTSTRAP_CONFIG:
        return
    try:
        _bootstrap_config_from_flat_file(BOOTSTRAP_CONFIG_FILE)
    except Exception:
        pass

def _ensure_ingest_tables():
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(readings)")).fetchall()]
        if "ok" not in cols:
            conn.execute(text("ALTER TABLE readings ADD COLUMN ok INTEGER DEFAULT 1"))
        if "error" not in cols:
            conn.execute(text("ALTER TABLE readings ADD COLUMN error TEXT"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uix_readings_ts_gw_unit ON readings(ts_utc, gateway_id, unit_id)"))
        meter_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(meters)")).fetchall()]
        if "owner_name" not in meter_cols:
            conn.execute(text("ALTER TABLE meters ADD COLUMN owner_name TEXT"))
        if "parking_slot" not in meter_cols:
            conn.execute(text("ALTER TABLE meters ADD COLUMN parking_slot TEXT"))
        if "is_active" not in meter_cols:
            conn.execute(text("ALTER TABLE meters ADD COLUMN is_active INTEGER DEFAULT 1"))
        if "device_uid" not in meter_cols:
            conn.execute(text("ALTER TABLE meters ADD COLUMN device_uid TEXT"))
        if "deviceID" not in meter_cols:
            conn.execute(text("ALTER TABLE meters ADD COLUMN \"deviceID\" TEXT"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uix_meters_deviceID ON meters(\"deviceID\")"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uix_meters_device_uid ON meters(device_uid)"))

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS exec_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_start_utc TEXT UNIQUE,
            run_end_utc TEXT,
            exit_code INTEGER,
            source TEXT,
            csv_file TEXT,
            log_file TEXT,
            gateway_failures_json TEXT,
            readings_count INTEGER,
            inserted_count INTEGER,
            duplicate_count INTEGER,
            log_text TEXT
        )
        """))

def _get_or_create_gateway(db, host: str, port: int):
    gw = db.query(Gateway).filter(Gateway.host==host, Gateway.port==port).first()
    if gw: return gw
    gw = Gateway(label=f"{host}:{port}", host=host, port=port)
    db.add(gw)
    db.flush()
    return gw

def _get_meter_id(db, gateway_id: int, unit_id: int):
    m = db.query(Meter).filter(Meter.gateway_id==gateway_id, Meter.unit_id==unit_id).first()
    return m.id if m else None


def _get_meter_by_uid(db, device_uid: str):
    device_uid = (device_uid or "").strip()
    if not device_uid:
        return None
    m = db.query(Meter).filter((Meter.device_id==device_uid) | (Meter.device_uid==device_uid)).first()
    return m


@app.post("/api/ingest/run")
async def ingest_run(payload: dict):
    readings = payload.get("readings") or []
    gw_failures = payload.get("gateway_failures") or []
    run_start = payload.get("run_start_utc")
    run_end = payload.get("run_end_utc")
    exit_code = payload.get("exit_code")
    source = payload.get("source")
    csv_file = payload.get("csv_file")
    log_file = payload.get("log_file")
    log_text = payload.get("log_text") or ""

    inserted = 0
    duplicates = 0

    with SessionLocal() as db:
        for r in readings:
                try:
                    ts = r.get("timestamp_utc")
                    gw = r.get("gateway")
                    unit = r.get("unit")
                    device_uid = r.get("deviceID") or r.get("device_uid") or r.get("meter_uid") or r.get("uid")

                    # Must have timestamp + gateway. device_uid preferred, unit optional unless device_uid missing.
                    if not ts or not gw:
                        continue
                    host, port = gw.split(":")
                    gw_row = _get_or_create_gateway(db, host, int(port))

                    unit_i = None
                    try:
                        unit_i = int(unit) if unit is not None else None
                    except Exception:
                        unit_i = None

                    meter_id = None
                    if device_uid:
                        m = _get_meter_by_uid(db, str(device_uid))
                        meter_id = m.id if m else None
                    else:
                        # legacy fallback
                        if unit_i is None or unit_i <= 0:
                            continue
                        m = db.query(Meter).filter(Meter.gateway_id==gw_row.id, Meter.unit_id==unit_i).first()
                        meter_id = m.id if m else None

                    db.execute(text("""
                        INSERT OR IGNORE INTO readings
                        (ts_utc, gateway_id, unit_id, meter_id, volt_v, current_a, power_kw, freq_hz, pf, kwh_import, ok, error)
                        VALUES
                        (:ts_utc, :gateway_id, :unit_id, :meter_id, :volt_v, :current_a, :power_kw, :freq_hz, :pf, :kwh_import, :ok, :error)
                    """), {
                        "ts_utc": ts.replace("Z","").replace("T"," ").replace("+00:00",""),
                        "gateway_id": gw_row.id,
                        "unit_id": unit_i,
                        "meter_id": meter_id,
                        "volt_v": r.get("volt_v"),
                        "current_a": r.get("current_a"),
                        "power_kw": r.get("power_kw") or r.get("pow_kw"),
                        "freq_hz": r.get("freq_hz"),
                        "pf": r.get("pf"),
                        "kwh_import": r.get("kwh_import"),
                        "ok": 1 if (str(r.get("ok")).lower() in ("1","true","yes","ok")) else 0,
                        "error": r.get("error"),
                    })
                    changed = db.execute(text("SELECT changes()")).scalar() or 0
                    if changed == 1:
                        inserted += 1
                    else:
                        duplicates += 1
                except Exception:
                    # never break the run for a single bad row
                    continue

        # exec_logs insert (always)
        try:
            db.execute(text("""
                INSERT OR IGNORE INTO exec_logs
                (run_start_utc, run_end_utc, exit_code, source, csv_file, log_file, gateway_failures_json,
                 readings_count, inserted_count, duplicate_count, log_text)
                VALUES
                (:run_start_utc, :run_end_utc, :exit_code, :source, :csv_file, :log_file, :gateway_failures_json,
                 :readings_count, :inserted_count, :duplicate_count, :log_text)
            """), {
                "run_start_utc": run_start,
                "run_end_utc": run_end,
                "exit_code": exit_code,
                "source": source,
                "csv_file": csv_file,
                "log_file": log_file,
                "gateway_failures_json": json.dumps(gw_failures),
                "readings_count": len(readings),
                "inserted_count": inserted,
                "duplicate_count": duplicates,
                "log_text": log_text,
            })
        except Exception:
            pass
        db.commit()

    return {"ok": True, "inserted": inserted, "duplicates": duplicates}
@app.post("/api/ingest/bulk_day")
async def ingest_bulk_day(payload: dict):
    _ensure_ingest_tables()
    rows = payload.get("rows") or []
    inserted = 0
    duplicates = 0
    with SessionLocal() as db:
        with engine.begin() as conn:
            for r in rows:
                try:
                    ts = r.get("timestamp_utc")
                    gw = r.get("gateway")
                    unit = r.get("unit") or r.get("unit_id")
                    if not ts or not gw or not unit or int(unit) <= 0:
                        continue
                    host, port = gw.split(":")
                    gw_row = _get_or_create_gateway(db, host, int(port))
                    meter_id = _get_meter_id(db, gw_row.id, int(unit))
                    conn.execute(text("""
                        INSERT OR IGNORE INTO readings
                        (ts_utc, gateway_id, unit_id, meter_id, volt_v, current_a, power_kw, freq_hz, pf, kwh_import, ok, error)
                        VALUES
                        (:ts_utc, :gateway_id, :unit_id, :meter_id, :volt_v, :current_a, :power_kw, :freq_hz, :pf, :kwh_import, :ok, :error)
                    """), {
                        "ts_utc": ts.replace("Z","").replace("T"," ").replace("+00:00",""),
                        "gateway_id": gw_row.id,
                        "unit_id": int(unit),
                        "meter_id": meter_id,
                        "volt_v": r.get("volt_v"),
                        "current_a": r.get("current_a"),
                        "power_kw": r.get("power_kw"),
                        "freq_hz": r.get("freq_hz"),
                        "pf": r.get("pf"),
                        "kwh_import": r.get("kwh_import"),
                        "ok": 0 if (str(r.get("ok","")).lower() in ("false","0","no")) else 1,
                        "error": r.get("error"),
                    })
                    ch = conn.execute(text("SELECT changes()")).scalar() or 0
                    if ch == 1: inserted += 1
                    else: duplicates += 1
                except Exception:
                    continue
    return {"inserted": inserted, "ignored_duplicates": duplicates, "rows_seen": len(rows)}

@app.get("/api/admin/gateway_status")
def admin_gateway_status():
    with engine.begin() as conn:
        last = conn.execute(text(
            "SELECT run_start_utc, exit_code, gateway_failures_json FROM exec_logs "
            "ORDER BY run_start_utc DESC LIMIT 1"
        )).mappings().first()
    failures = []
    exit_code = 0
    run_start = None
    if last:
        run_start = last.get("run_start_utc")
        exit_code = last.get("exit_code") or 0
        try: failures = json.loads(last.get("gateway_failures_json") or "[]")
        except: failures = []
    failed_set = set()
    for f in failures or []:
        g = f.get("gateway")
        if g: failed_set.add(g)
    with SessionLocal() as db:
        gws = db.query(Gateway).order_by(Gateway.id).all()
        out=[]
        for g in gws:
            key=f"{g.host}:{g.port}"
            ok = (exit_code == 0) and (key not in failed_set)
            out.append({"gateway_id": g.id, "label": g.label, "host": g.host, "port": g.port, "gateway": key, "ok": bool(ok), "last_run_start_utc": run_start})
        return out

@app.get("/api/admin/log_files")
@app.get("/admin/log_files")
def admin_log_files():
    file_entries = []
    files = sorted(glob.glob("/app/logs/*.log"))
    if not files:
        files = sorted(glob.glob("./logs/*.log"))
    for p in files:
        file_entries.append({"name": os.path.basename(p), "path": p, "source": "file"})

    # Also expose run logs stored in DB (for environments where log files are not persisted)
    with engine.begin() as conn:
        db_rows = conn.execute(text(
            "SELECT log_file, run_start_utc FROM exec_logs "
            "WHERE log_file IS NOT NULL AND TRIM(log_file) <> '' "
            "ORDER BY run_start_utc DESC LIMIT 400"
        )).mappings().all()
    seen = {entry["name"] for entry in file_entries}
    for row in db_rows:
        base = os.path.basename(row.get("log_file") or "")
        if not base or base in seen:
            continue
        seen.add(base)
        file_entries.append({"name": base, "path": row.get("log_file"), "source": "db"})

    return file_entries[-200:]

@app.get("/api/admin/log_file")
@app.get("/admin/log_file")
def admin_log_file(name: str, tail: int = 400):
    safe = os.path.basename(name)
    path = os.path.join("/app/logs", safe)
    if not os.path.exists(path):
        path = os.path.join("./logs", safe)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        return {"ok": True, "name": safe, "lines": lines[-int(tail):], "source": "file"}

    # Fallback to DB-stored execution log text by matching basename(log_file)
    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT run_start_utc, log_text FROM exec_logs "
            "WHERE log_file IS NOT NULL AND TRIM(log_file) <> '' "
            "AND (log_file = :safe OR log_file LIKE :suffix) "
            "ORDER BY run_start_utc DESC LIMIT 1"
        ), {"safe": safe, "suffix": f"%/{safe}"}).mappings().first()
    if row and (row.get("log_text") is not None):
        text_content = row.get("log_text") or ""
        lines = text_content.splitlines(keepends=True)
        return {"ok": True, "name": safe, "lines": lines[-int(tail):], "source": "db"}

    return {"ok": False, "error": "not_found"}

@app.get("/api/admin/config_summary")
def admin_config_summary():
    with SessionLocal() as db:
        gw_count = db.query(Gateway).count()
        meter_count = db.query(Meter).count()
        per_gw = db.execute(select(Gateway.id, Gateway.label, Gateway.host, Gateway.port)).all()
        per=[]
        for gid,label,host,port in per_gw:
            c = db.query(Meter).filter(Meter.gateway_id==gid).count()
            per.append({"gateway_id": gid, "label": label, "host": host, "port": port, "meters": c})
        return {"gateways": gw_count, "meters": meter_count, "per_gateway": per}

@app.post("/api/admin/import_config")
async def admin_import_config(payload: dict, replace: int = 0):
    path = BOOTSTRAP_CONFIG_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if "csv_text" in payload and payload["csv_text"]:
        with open(path, "w", encoding="utf-8") as f:
            f.write(payload["csv_text"])
    else:
        return {"ok": False, "error": "missing csv_text"}
    res = _bootstrap_config_from_flat_file(path, replace=bool(replace))
    return {"ok": True, "result": res, "file": path}

@app.post("/api/admin/import_default_config")
@app.post("/admin/import_default_config")
async def admin_import_default_config(replace: int = 0):
    candidates = [
        BOOTSTRAP_CONFIG_FILE,
        "./data/Active-Mapping.csv",
        "./data/active_mapping.csv",
        "/app/data/Active-Mapping.csv",
        "/app/data/active_mapping.csv",
        "/workspace/cargadoresCT79/data/Active-Mapping.csv",
    ]
    path = next((c for c in candidates if c and os.path.exists(c)), None)
    if not path:
        return {"ok": False, "error": "file_not_found", "candidates": candidates}
    res = _bootstrap_config_from_flat_file(path, replace=bool(replace))
    return {"ok": True, "result": res, "file": path}



# --- Admin exec logs ---
@app.get("/api/admin/exec_logs")
@app.get("/admin/exec_logs")
def admin_exec_logs(limit: int = 200):
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT run_start_utc, run_end_utc, exit_code, source, csv_file, log_file, "
            "gateway_failures_json, readings_count, inserted_count, duplicate_count "
            "FROM exec_logs ORDER BY run_start_utc DESC LIMIT :limit"
        ), {"limit": int(limit)}).mappings().all()
    out = []
    for r in rows:
        try:
            gf = json.loads(r.get("gateway_failures_json") or "[]")
        except Exception:
            gf = []
        out.append({
            "run_start_utc": r.get("run_start_utc"),
            "run_end_utc": r.get("run_end_utc"),
            "exit_code": r.get("exit_code"),
            "source": r.get("source"),
            "csv_file": r.get("csv_file"),
            "log_file": r.get("log_file"),
            "gateway_failures": gf,
            "readings_count": r.get("readings_count"),
            "inserted_count": r.get("inserted_count"),
            "duplicate_count": r.get("duplicate_count"),
        })
    return out


@app.get("/{full_path:path}", response_class=HTMLResponse)
def spa_fallback(full_path: str):
    if full_path.startswith("api/") or full_path.startswith("admin/") or full_path.startswith("readings/") or full_path == "health":
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not Found")
    candidate = os.path.join(STATIC_DIR, full_path)
    if os.path.isfile(candidate):
        return FileResponse(candidate)
    return FileResponse(INDEX_FILE)
