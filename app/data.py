"""Read-only exports from QuickDrop systems (data/*.csv). Loaded once."""
import csv, pathlib, functools, re
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from . import config

IST = timezone(timedelta(hours=5, minutes=30))

def to_ist(ts: str) -> datetime:
    """Trip timestamps are UTC ('...Z'); policy days are IST calendar days."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(IST)

def _rows(name):
    with open(pathlib.Path(config.DATA_DIR) / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def norm_rider(r: str) -> str:
    """The trips export has 'R7' and 'r19' for R007 and R019."""
    m = re.fullmatch(r"\s*[Rr]\s*0*(\d+)\s*", r or "")
    return f"R{int(m.group(1)):03d}" if m else (r or "").strip().upper()

def norm_km(raw: str) -> Decimal:
    """222 rows carry metres in the distance_km column (800..11400, all multiples of 100; real km is <= 13)."""
    d = Decimal(raw)
    return d / 1000 if d > 100 else d

@functools.lru_cache(maxsize=1)
def load():
    seen, trips = set(), []
    for t in _rows("trips.csv"):
        if t["trip_id"] in seen: continue            # 10 exact duplicate rows in the export
        seen.add(t["trip_id"])
        t["rider_id"] = norm_rider(t["rider_id"])
        t["km"] = norm_km(t["distance_km"])
        t["day"] = to_ist(t["started_at"]).date().isoformat()
        trips.append(t)
    lines = _rows("payout_lines.csv")
    for l in lines: l["rider_id"] = norm_rider(l["rider_id"])
    riders = {r["rider_id"]: r for r in _rows("riders.csv")}
    return trips, lines, riders
