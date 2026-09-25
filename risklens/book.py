"""The consignment book: real December 2025 shipments from the Kaggle data.

Shipments dispatched in the three weeks around the portal's as-of date make up
the active book. They are all in the model's test window, so the scores shown
are genuine out-of-sample predictions. Road and rail only count where the two
ports share a landmass; the dataset also contains land shipments across oceans,
which are kept for training but not shown as live consignments.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from . import datasets
from .config import AS_OF, DATA_PROCESSED, RISK_BANDS
from .features import frame_to_features, weather_level

BOOK_PATH = DATA_PROCESSED / "consignments.csv"
WINDOW = (AS_OF - timedelta(days=14), AS_OF + timedelta(days=11))
LAND_GROUPS = [{"Rotterdam", "Antwerp", "Hamburg", "Marseille"}, {"Shanghai", "Singapore"}]
CARGO_NAMES = {
    "Electronics": "Consumer electronics", "Textiles": "Apparel and textiles", "Perishables": "Chilled food produce",
    "Pharmaceuticals": "Pharmaceutical products", "Automotive": "Automotive parts",
}
TARGET = {"high": 4, "elevated": 3, "low": 3}


def _plausible(r) -> bool:
    if r.origin_port == r.destination_port:
        return False
    if r["mode"] in ("Road", "Rail"):
        return any(r.origin_port in g and r.destination_port in g for g in LAND_GROUPS)
    return True


def planned_days(mode: str, distance_km: float) -> int:
    speed = datasets.benchmarks()["shipments"]["planned_km_per_day"].get(mode, 500)
    return max(1, round(distance_km / speed))


def build(model) -> pd.DataFrame:
    s = datasets.load()["shipments"]
    lo, hi = WINDOW[0].isoformat(), WINDOW[1].isoformat()
    cand = s[(s.date >= lo) & (s.date <= hi)].copy()
    cand = cand[cand.apply(_plausible, axis=1)]
    cand["lead"] = [planned_days(m, d) for m, d in zip(cand["mode"], cand.distance_km)]
    cand["eta"] = [(date.fromisoformat(d) + timedelta(days=int(n))).isoformat() for d, n in zip(cand.date, cand.lead)]
    cand = cand[cand.eta > AS_OF.isoformat()]          # still moving on the as-of date
    import xgboost as xgb
    cand["score"] = model.predict(xgb.DMatrix(frame_to_features(cand))) * 100
    cand["band"] = pd.cut(cand.score, [b[1] for b in RISK_BANDS] + [101], labels=[b[0] for b in RISK_BANDS], right=False).astype(str)

    picked, lanes, modes = [], set(), {}
    for band, n in TARGET.items():
        pool = cand[cand.band == band].sort_values(["date", "shipment_id"])
        for _, r in pool.iterrows():
            if sum(1 for p in picked if p.band == band) >= n:
                break
            lane = (r.origin_port, r.destination_port)
            if lane in lanes or modes.get(r["mode"], 0) >= 4:
                continue
            picked.append(r)
            lanes.add(lane)
            modes[r["mode"]] = modes.get(r["mode"], 0) + 1

    rows = []
    for r in picked:
        o, d = datasets.PORT_INFO[r.origin_port], datasets.PORT_INFO[r.destination_port]
        units, unit_value = datasets.estimate_value(r.product_category, r.weight_t)
        rec = {
            "consignment_id": r.shipment_id, "cargo": CARGO_NAMES[r.product_category], "product_category": r.product_category,
            "mode": r["mode"], "origin_port": r.origin_port, "origin_country": o[0], "region": o[1],
            "destination_port": r.destination_port, "destination_country": d[0], "destination_region": d[1],
            "dispatch_date": r.date, "eta_date": r.eta, "lead_time_days": int(r.lead),
            "weight_t": r.weight_t, "units": units, "average_cost_per_unit": unit_value,
            "distance_km": r.distance_km, "fuel_price_index": r.fuel_price_index,
            "geopolitical_risk_index": r.geopolitical_risk_index, "reliability_score": r.reliability_score,
            "weather_condition": r.weather_condition, "weather_risk_index": r.weather_risk_index,
            "weather_risk_level": weather_level(r.weather_risk_index),
        }
        sup = datasets.supplier_for(rec)
        rec.update(supplier_id=sup["supplier_id"], supplier_name=sup["supplier_name"])
        rows.append(rec)
    book = pd.DataFrame(rows).sort_values("dispatch_date").reset_index(drop=True)
    book.to_csv(BOOK_PATH, index=False)
    return book
