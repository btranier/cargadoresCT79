import os, json, logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from typing import List, Tuple, Optional

from pymodbus.client import ModbusTcpClient
from sqlalchemy import select
from .db import SessionLocal, init_db, Gateway, Meter, Reading

LOG_DIR = os.getenv("LOG_DIR", "./logs")
os.makedirs(LOG_DIR, exist_ok=True)
logger = logging.getLogger("saci.poller")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    fh = RotatingFileHandler(os.path.join(LOG_DIR, "poller.log"), maxBytes=1_000_000, backupCount=3)
    sh = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    fh.setFormatter(fmt); sh.setFormatter(fmt)
    logger.addHandler(fh); logger.addHandler(sh)

def parse_gateways(env: str) -> List[Tuple[str,int]]:
    out=[]
    for part in env.split(","):
        part = part.strip()
        if not part: continue
        if ":" in part:
            h,p = part.split(":",1); out.append((h.strip(), int(p.strip())))
        else:
            out.append((part, 502))
    return out

def parse_units(env: str) -> List[int]:
    env=(env or "").strip()
    if not env: return list(range(1,33))
    if "-" in env:
        a,b = env.split("-",1); return list(range(int(a), int(b)+1))
    return [int(x) for x in env.split(",") if x.strip()]

def get_env_int(name, default=None):
    v=os.getenv(name, "")
    if v=="": return default
    try: return int(v)
    except: return default

REGS = {
    "volt_v":  {"ADDR": get_env_int("REG_VOLT_ADDR"),  "COUNT": get_env_int("REG_VOLT_COUNT",2),  "TYPE": os.getenv("REG_VOLT_TYPE","float32_be")},
    "current_a":{"ADDR": get_env_int("REG_CURR_ADDR"), "COUNT": get_env_int("REG_CURR_COUNT",2), "TYPE": os.getenv("REG_CURR_TYPE","float32_be")},
    "power_kw":{"ADDR": get_env_int("REG_PWR_ADDR"),   "COUNT": get_env_int("REG_PWR_COUNT",2),  "TYPE": os.getenv("REG_PWR_TYPE","float32_be")},
    "freq_hz": {"ADDR": get_env_int("REG_FREQ_ADDR"),  "COUNT": get_env_int("REG_FREQ_COUNT",1), "TYPE": os.getenv("REG_FREQ_TYPE","u16")},
    "pf":      {"ADDR": get_env_int("REG_PF_ADDR"),    "COUNT": get_env_int("REG_PF_COUNT",1),   "TYPE": os.getenv("REG_PF_TYPE","u16_scale_0p001")},
    "kwh_import":{"ADDR": get_env_int("REG_KWH_ADDR"), "COUNT": get_env_int("REG_KWH_COUNT",2),  "TYPE": os.getenv("REG_KWH_TYPE","uint32_be_scale_0p01")},
}

def decode_registers(regs, typ: str) -> Optional[float]:
    if regs is None: return None
    try:
        if typ == "u16":
            return float(regs[0])
        if typ == "s16":
            v = regs[0]; 
            if v >= 0x8000: v -= 0x10000
            return float(v)
        if typ == "float32_be":
            b = regs[0].to_bytes(2,'big') + regs[1].to_bytes(2,'big')
            import struct; return float(struct.unpack(">f", b)[0])
        if typ == "float32_le":
            b = regs[1].to_bytes(2,'big') + regs[0].to_bytes(2,'big')
            import struct; return float(struct.unpack("<f", b)[0])
        if typ == "uint32_be":
            return float((regs[0]<<16) | regs[1])
        if typ == "uint32_le":
            return float((regs[1]<<16) | regs[0])
        if typ == "int32_be":
            v = (regs[0]<<16) | regs[1]
            if v & 0x80000000: v -= 0x100000000
            return float(v)
        if typ == "int32_le":
            v = (regs[1]<<16) | regs[0]
            if v & 0x80000000: v -= 0x100000000
            return float(v)
        if typ == "uint32_be_scale_0p01":
            val = float((regs[0]<<16) | regs[1]); return val*0.01
        if typ == "u16_scale_0p001":
            return float(regs[0]) * 0.001
        # SACI extras
        if typ == "uint32_be_scale_0p001":
            val = float((regs[0] << 16) | regs[1]); return val * 0.001
        if typ == "int32_be_scale_0p001":
            v = (regs[0] << 16) | regs[1]
            if v & 0x80000000: v -= 0x100000000
            return float(v) * 0.001
        if typ == "u16_scale_0p1":
            return float(regs[0]) * 0.1
    except Exception:
        return None
    return None

def read_metric(client: ModbusTcpClient, unit: int, addr: int, count: int):
    resp = client.read_holding_registers(address=addr, count=count, unit=unit)
    if resp.isError():
        raise Exception(str(resp))
    return list(resp.registers)

def poll_once():
    gateways = parse_gateways(os.getenv("GATEWAYS",""))
    units    = parse_units(os.getenv("UNITS","1-32"))
    timeout  = float(os.getenv("MODBUS_TIMEOUT", "2.0"))

    if not gateways:
        logger.error("No GATEWAYS configured. Skipping cycle.")
        return 0

    init_db()
    inserted = 0
    ts = datetime.utcnow().replace(tzinfo=None)

    with SessionLocal() as db:
        gw_rows = db.execute(select(Gateway)).scalars().all()
        gw_by_hp = {(g.host, g.port): g for g in gw_rows}
        for host, port in gateways:
            g = gw_by_hp.get((host, port))
            if not g:
                g = Gateway(label=f"{host}:{port}", host=host, port=port)
                db.add(g); db.commit(); db.refresh(g)
                gw_by_hp[(host,port)] = g

        for host, port in gateways:
            client = ModbusTcpClient(host=host, port=port, timeout=timeout)
            if not client.connect():
                logger.error(f"GW connect failed: {host}:{port}")
                continue
            gid = gw_by_hp[(host,port)].id
            try:
                for unit in units:
                    payload = {}
                    for field, cfg in REGS.items():
                        addr = cfg["ADDR"]
                        if addr is None: continue
                        cnt  = cfg["COUNT"]
                        typ  = cfg["TYPE"]
                        try:
                            regs = read_metric(client, unit, addr, cnt)
                            val  = decode_registers(regs, typ)
                            payload[field] = val
                        except Exception as e:
                            payload[field] = None

                    if any(v is not None for v in payload.values()):
                        m = db.execute(select(Meter).where(Meter.gateway_id==gid, Meter.unit_id==unit)).scalars().first()
                        rd = Reading(
                            ts_utc = ts,
                            gateway_id = gid,
                            unit_id = unit,
                            meter_id = m.id if m else None,
                            volt_v = payload.get("volt_v"),
                            current_a = payload.get("current_a"),
                            power_kw = payload.get("power_kw"),
                            freq_hz = payload.get("freq_hz"),
                            pf = payload.get("pf"),
                            kwh_import = payload.get("kwh_import"),
                        )
                        db.add(rd); inserted += 1
                db.commit()
            finally:
                client.close()

    try:
        state = {"last_poll_utc": datetime.utcnow().isoformat(), "inserted": inserted}
        os.makedirs("./data", exist_ok=True)
        with open("./data/poller_state.json","w",encoding="utf-8") as f:
            json.dump(state, f)
    except Exception:
        pass

    return inserted

if __name__ == "__main__":
    poll_once()
