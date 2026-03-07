#!/usr/bin/env python3
# SACI M1DL3-MID probe via Modbus/TCP (Ethergate)
# - Una conexión TCP por gateway; lee unidades 1..32
# - Timeout por operación; sin reintentos
# - CSV diario con device_uid (serial BCD en 0x1000)

import socket, struct, time, os, csv, argparse
from datetime import datetime

DEFAULT_GATEWAYS = [
    ("192.168.1.101", 502),
    ("192.168.1.102", 502),
    ("192.168.1.103", 502),
    ("192.168.1.104", 502),
]
DEFAULT_UNITS   = list(range(1, 33))
DEFAULT_TIMEOUT = 2.0
DEFAULT_OUT_DIR = "./logs"

# --- M1DL3-MID registers (manual SACI) ---
REG_VOLT     = 0x0100  # 2 regs, uint32 BE,  /1000 -> V
REG_CURRENT  = 0x0102  # 2 regs,  int32 BE,  /1000 -> A
REG_POWER_W  = 0x0104  # 2 regs,  int32 BE,  /1000 -> kW
REG_FREQ     = 0x010A  # 1 reg,   int16,     /10   -> Hz
REG_PF       = 0x010B  # 1 reg,   int16,     /1000 -> pf
REG_KWH_IMP  = 0x010E  # 2 regs, uint32 BE,  /100  -> kWh

REG_SERIAL_BCD = 0x1000 # 3 regs, 12 dígitos BCD (½ byte)
# -----------------------------------------

def parse_gateways(arg: str):
    gw = []
    for token in arg.split(","):
        token = token.strip()
        if not token: continue
        if ":" in token:
            h, p = token.split(":", 1)
            gw.append((h.strip(), int(p)))
        else:
            gw.append((token, 502))
    return gw

def parse_units(arg: str):
    out = set()
    for part in arg.split(","):
        part = part.strip()
        if not part: continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(min(int(a),int(b)), max(int(a),int(b))+1))
        else:
            out.add(int(part))
    return sorted(out)

def day_csv_path(out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, f"readings_{datetime.utcnow():%Y%m%d}.csv")

def ensure_header(path: str):
    header = ["timestamp_utc","gateway","unit","device_uid",
              "volt_v","current_a","power_kw","freq_hz","pf","kwh_import",
              "ok","error"]
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        with open(path, "a", encoding="utf-8", newline="") as f:
            csv.writer(f).writerow(header)

def fmt3(x): 
    try: return f"{float(x):.3f}"
    except: return ""
def fmt2(x):
    try: return f"{float(x):.2f}"
    except: return ""

# ---- MBAP/PDU helpers ----
def _mbap_send(sock: socket.socket, unit: int, pdu: bytes):
    tx = int(time.time() * 1000) & 0xFFFF
    mbap = struct.pack(">HHHB", tx, 0, len(pdu)+1, unit & 0xFF)
    sock.sendall(mbap + pdu)

def _mbap_recv(sock: socket.socket):
    hdr = b""
    while len(hdr) < 7:
        chunk = sock.recv(7 - len(hdr))
        if not chunk: raise RuntimeError("short MBAP header")
        hdr += chunk
    _, _, length, _ = struct.unpack(">HHHB", hdr)
    pdu_len = length - 1
    pdu = b""
    while len(pdu) < pdu_len:
        chunk = sock.recv(pdu_len - len(pdu))
        if not chunk: raise RuntimeError("short PDU body")
        pdu += chunk
    return pdu

def send_pdu(sock: socket.socket, unit: int, body: bytes) -> bytes:
    _mbap_send(sock, unit, body)
    pdu = _mbap_recv(sock)
    if pdu[0] & 0x80:
        code = pdu[1] if len(pdu) > 1 else 0
        raise RuntimeError(f"exception fc=0x{pdu[0]:02X} code=0x{code:02X}")
    return pdu

def read_holding(sock: socket.socket, unit: int, addr: int, qty: int):
    pdu = struct.pack(">BHH", 0x03, addr, qty)
    r = send_pdu(sock, unit, pdu)
    if r[0] != 0x03: raise RuntimeError(f"unexpected FC {r[0]:#x}")
    bc = r[1]
    if bc != qty*2: raise RuntimeError(f"bytecount {bc} != {qty*2}")
    return [ (r[2+i*2]<<8) | r[3+i*2] for i in range(qty) ]

# ---- tipos ----
def u32_be(rh, rl): return float(((rh & 0xFFFF)<<16) | (rl & 0xFFFF))
def i32_be(rh, rl):
    u = ((rh & 0xFFFF)<<16) | (rl & 0xFFFF)
    return float(u if u < (1<<31) else u - (1<<32))
def i16(v): return float(v if v < (1<<15) else v - (1<<16))

# ---- serial BCD (0x1000, len=3) ----
def read_serial_bcd(sock: socket.socket, unit: int) -> str:
    regs = read_holding(sock, unit, REG_SERIAL_BCD, 3)
    # 3 palabras -> 6 bytes -> 12 nibbles (dígitos)
    b = bytes([(regs[0]>>8)&0xFF, regs[0]&0xFF,
               (regs[1]>>8)&0xFF, regs[1]&0xFF,
               (regs[2]>>8)&0xFF, regs[2]&0xFF])
    digits = []
    for byte in b:
        digits.append(str((byte>>4) & 0xF))
        digits.append(str(byte & 0xF))
    return "".join(digits)  # conserva ceros a la izquierda

# ---- medidas ----
def read_values(sock: socket.socket, unit: int):
    out = {}
    r = read_holding(sock, unit, REG_VOLT, 2)
    out["volt_v"] = u32_be(r[0], r[1]) / 1000.0
    r = read_holding(sock, unit, REG_CURRENT, 2)
    out["current_a"] = i32_be(r[0], r[1]) / 1000.0
    r = read_holding(sock, unit, REG_POWER_W, 2)
    out["power_kw"] = i32_be(r[0], r[1]) / 1000.0
    r = read_holding(sock, unit, REG_FREQ, 1)
    out["freq_hz"] = i16(r[0]) / 10.0
    r = read_holding(sock, unit, REG_PF, 1)
    out["pf"] = i16(r[0]) / 1000.0
    r = read_holding(sock, unit, REG_KWH_IMP, 2)
    out["kwh_import"] = u32_be(r[0], r[1]) / 100.0
    return out

def probe_gateway_once(host: str, port: int, units, timeout: float, csv_writer):
    label = f"{host}:{port}"
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            s.settimeout(timeout)
            print(f"[GATEWAY OPEN] {label}")
            for unit in units:
                ok, err = True, ""
                uid = volt_v = curr_a = p_kw = f_hz = pf = kwh = ""
                try:
                    uid  = read_serial_bcd(s, unit)    # ← serial del equipo (12 dígitos)
                    vals = read_values(s, unit)
                    volt_v = fmt3(vals["volt_v"])
                    curr_a = fmt3(vals["current_a"])
                    p_kw   = fmt3(vals["power_kw"])
                    f_hz   = fmt3(vals["freq_hz"])
                    pf     = fmt3(vals["pf"])
                    kwh    = fmt2(vals["kwh_import"])
                except Exception as e:
                    ok, err = False, str(e)

                csv_writer.writerow([ts, label, unit, uid,
                                     volt_v, curr_a, p_kw, f_hz, pf, kwh, ok, err])
                print(f"{ts}  {label}  u={unit:02d}  UID={uid or '-':>12}  "
                      f"V={volt_v:>7}  A={curr_a:>7}  kW={p_kw:>7}  Hz={f_hz:>5}  "
                      f"PF={pf:>5}  kWh={kwh:>8}  ok={ok}  {err}")
    except Exception as e:
        err = str(e)
        csv_writer.writerow([ts, label, 0, "", "", "", "", "", "", "", False, err])
        print(f"[GATEWAY ERROR] {label} :: {err}")

def main():
    ap = argparse.ArgumentParser(description="One-shot SACI Modbus/TCP probe")
    ap.add_argument("--gateways", help="ip:port,ip:port,...", default=None)
    ap.add_argument("--units",    help="1-8,10,12-14",       default=None)
    ap.add_argument("--timeout",  type=float, default=DEFAULT_TIMEOUT)
    ap.add_argument("--outdir",   default=DEFAULT_OUT_DIR)
    args = ap.parse_args()

    gateways = parse_gateways(args.gateways) if args.gateways else DEFAULT_GATEWAYS
    units    = parse_units(args.units) if args.units else DEFAULT_UNITS
    out_path = day_csv_path(args.outdir)
    ensure_header(out_path)

    with open(out_path, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        for (host, port) in gateways:
            probe_gateway_once(host, port, units, args.timeout, w)

    print(f"[DONE] Appended rows to {out_path}")

if __name__ == "__main__":
    main()