"""Editable supplier portfolio persisted as JSON so portal changes survive
restarts. Seeded from the synthetic dataset's latest day on first run."""
from __future__ import annotations

import json
import threading
import uuid

import pandas as pd

from .config import DATA_PORTAL, DATA_PROCESSED, DATA_RAW

STORE_PATH = DATA_PORTAL / "suppliers.json"
_lock = threading.Lock()

RECORD_KEYS = [
    "supplier_id", "supplier_name", "region", "country", "product_category",
    "lead_time_days", "lead_time_std_days", "reliability_score",
    "geopolitical_risk_index", "port_congestion_index", "weather_risk_index", "weather_risk_level",
    "price_swing_pct", "days_since_last_disruption", "single_source",
    "average_cost_per_unit", "annual_volume_units", "contract_type",
]


def seed_from_dataset() -> list[dict]:
    feats = pd.read_csv(DATA_PROCESSED / "supply_chain_features.csv")
    suppliers = pd.read_csv(DATA_RAW / "suppliers.csv")
    latest = feats.sort_values("date").groupby("supplier_id").tail(1)
    latest = latest.merge(suppliers[["supplier_id", "country", "contract_type"]], on="supplier_id")
    records = []
    for _, r in latest.sort_values("supplier_id").iterrows():
        rec = {k: r[k] for k in RECORD_KEYS if k in r}
        for k, v in rec.items():
            if hasattr(v, "item"):
                rec[k] = v.item()
        records.append(rec)
    return records


def _read() -> list[dict]:
    if not STORE_PATH.exists():
        records = seed_from_dataset()
        _write(records)
        return records
    return json.loads(STORE_PATH.read_text())


def _write(records: list[dict]) -> None:
    DATA_PORTAL.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(records, indent=2))


def list_suppliers() -> list[dict]:
    with _lock:
        return _read()


def get_supplier(sid: str) -> dict | None:
    return next((r for r in list_suppliers() if r["supplier_id"] == sid), None)


def upsert_supplier(rec: dict) -> dict:
    with _lock:
        records = _read()
        sid = rec.get("supplier_id")
        if not sid:
            sid = "SUP_" + uuid.uuid4().hex[:6].upper()
            rec["supplier_id"] = sid
        clean = {k: rec.get(k) for k in RECORD_KEYS if rec.get(k) is not None}
        for i, r in enumerate(records):
            if r["supplier_id"] == sid:
                records[i] = {**r, **clean}
                _write(records)
                return records[i]
        records.append(clean)
        _write(records)
        return clean


def delete_supplier(sid: str) -> bool:
    with _lock:
        records = _read()
        new = [r for r in records if r["supplier_id"] != sid]
        if len(new) == len(records):
            return False
        _write(new)
        return True


def reset() -> list[dict]:
    with _lock:
        records = seed_from_dataset()
        _write(records)
        return records
