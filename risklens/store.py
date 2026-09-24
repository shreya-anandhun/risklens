"""The client's consignment book, persisted as JSON so portal edits survive
restarts. Seeded on first run from data/raw/consignments.csv joined with the
latest day of external signals on each consignment's lane."""
from __future__ import annotations

import json
import threading
from datetime import date

import pandas as pd

from .config import DATA_PORTAL, DATA_PROCESSED, DATA_RAW

STORE_PATH = DATA_PORTAL / "consignments.json"
_lock = threading.Lock()

RECORD_KEYS = [
    "consignment_id", "supplier_id", "supplier_name", "cargo", "product_category", "mode", "carrier",
    "origin_port", "origin_country", "region", "destination_port", "destination_country", "destination_region",
    "route_via", "dispatch_date", "eta_date", "units", "average_cost_per_unit", "annual_volume_units",
    "lead_time_days", "lead_time_std_days", "reliability_score",
    "geopolitical_risk_index", "port_congestion_index", "weather_risk_index", "weather_risk_level",
    "price_swing_pct", "days_since_last_disruption", "single_source", "contract_type", "applied_alternative",
]


def _py(v):
    return v.item() if hasattr(v, "item") else v


def seed_from_dataset() -> list[dict]:
    feats = pd.read_csv(DATA_PROCESSED / "supply_chain_features.csv")
    suppliers = pd.read_csv(DATA_RAW / "suppliers.csv")
    cons = pd.read_csv(DATA_RAW / "consignments.csv")
    latest = feats.sort_values("date").groupby("supplier_id").tail(1).drop(columns=["region"])
    latest = latest.merge(suppliers[["supplier_id", "contract_type"]], on="supplier_id")
    merged = cons.merge(latest, on="supplier_id", how="left")
    records = []
    for _, r in merged.iterrows():
        rec = {k: _py(r[k]) for k in RECORD_KEYS if k in r and not (isinstance(r[k], float) and pd.isna(r[k]))}
        records.append(rec)
    return records


def load_alternatives() -> dict[str, list[dict]]:
    path = DATA_RAW / "consignment_alternatives.csv"
    if not path.exists():
        return {}
    out: dict[str, list[dict]] = {}
    for i, r in pd.read_csv(path).iterrows():
        out.setdefault(r.consignment_id, []).append({
            "id": f"{r.consignment_id}-A{len(out.get(r.consignment_id, [])) + 1}",
            "title": r.title, "description": r.description, "changes": json.loads(r.changes),
            "cost_delta_pct": float(r.cost_delta_pct), "eta_delta_days": int(r.eta_delta_days),
        })
    return out


def _read() -> list[dict]:
    if not STORE_PATH.exists():
        records = seed_from_dataset()
        _write(records)
        return records
    return json.loads(STORE_PATH.read_text())


def _write(records: list[dict]) -> None:
    DATA_PORTAL.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(records, indent=2))


def list_consignments() -> list[dict]:
    with _lock:
        return _read()


def get_consignment(cid: str) -> dict | None:
    return next((r for r in list_consignments() if r["consignment_id"] == cid), None)


def _next_id(records: list[dict]) -> str:
    yy = date.today().strftime("%y")
    nums = [int(r["consignment_id"].split("-")[-1]) for r in records
            if str(r.get("consignment_id", "")).startswith(f"CN-{yy}-") and r["consignment_id"].split("-")[-1].isdigit()]
    return f"CN-{yy}-{(max(nums) + 1 if nums else 1):04d}"


def upsert_consignment(rec: dict) -> dict:
    with _lock:
        records = _read()
        cid = rec.get("consignment_id") or _next_id(records)
        rec["consignment_id"] = cid
        clean = {k: rec.get(k) for k in RECORD_KEYS if rec.get(k) is not None}
        for i, r in enumerate(records):
            if r["consignment_id"] == cid:
                records[i] = {**r, **clean}
                _write(records)
                return records[i]
        records.append(clean)
        _write(records)
        return clean


def delete_consignment(cid: str) -> bool:
    with _lock:
        records = _read()
        new = [r for r in records if r["consignment_id"] != cid]
        if len(new) == len(records):
            return False
        _write(new)
        return True


def reset() -> list[dict]:
    with _lock:
        records = seed_from_dataset()
        _write(records)
        return records
