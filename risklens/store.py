"""The client's consignment book, persisted as JSON so portal edits survive
restarts. Seeded from data/processed/consignments.csv: real December 2025
shipments from the Kaggle shipment data (see risklens/book.py)."""
from __future__ import annotations

import json
import threading

import pandas as pd

from .config import AS_OF, DATA_PORTAL, DATA_PROCESSED

STORE_PATH = DATA_PORTAL / "consignments.json"
BOOK_PATH = DATA_PROCESSED / "consignments.csv"
_lock = threading.Lock()

RECORD_KEYS = [
    "consignment_id", "supplier_id", "supplier_name", "cargo", "product_category", "mode", "carrier",
    "origin_port", "origin_country", "region", "destination_port", "destination_country", "destination_region",
    "route_via", "dispatch_date", "eta_date", "lead_time_days", "weight_t", "units", "average_cost_per_unit",
    "distance_km", "fuel_price_index", "geopolitical_risk_index", "reliability_score",
    "weather_condition", "weather_risk_index", "weather_risk_level", "applied_alternative", "executed_actions",
]


def _py(v):
    return v.item() if hasattr(v, "item") else v


def seed_from_dataset() -> list[dict]:
    records = []
    for _, r in pd.read_csv(BOOK_PATH).iterrows():
        records.append({k: _py(r[k]) for k in RECORD_KEYS if k in r and not (isinstance(r[k], float) and pd.isna(r[k]))})
    return records


def load_alternatives() -> dict[str, list[dict]]:
    """Alternatives are built per consignment from the shipment data (predictor.alternatives_for)."""
    return {}


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
    yy = AS_OF.strftime("%y")
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
