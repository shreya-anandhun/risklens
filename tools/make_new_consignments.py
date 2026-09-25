"""Write data/samples/new_consignments.csv: 10 more December 2025 shipments from the Kaggle data
that are not in the book, scored by the model, in the portal's export layout. Drop the file into
What-if and press "Add to consignments" to grow the book to 20."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from app.main import export_row, lane_history, lane_key
from risklens import book, datasets, store
from risklens.config import AS_OF, RISK_BANDS
from risklens.features import frame_to_features, weather_level
from risklens.predictor import load_model, predict_proba, score_records

OUT = Path(__file__).resolve().parent.parent / "data" / "samples" / "new_consignments.csv"
TARGET = {"high": 4, "elevated": 3, "low": 3}


def main():
    taken = {r["consignment_id"] for r in store.seed_from_dataset()}
    s = datasets.load()["shipments"]
    lo, hi = (AS_OF - timedelta(days=16)).isoformat(), (AS_OF + timedelta(days=11)).isoformat()
    cand = s[(s.date >= lo) & (s.date <= hi) & ~s.shipment_id.isin(taken)].copy()
    cand = cand[cand.apply(book._plausible, axis=1)]
    cand["lead"] = [book.planned_days(m, d) for m, d in zip(cand["mode"], cand.distance_km)]
    cand["eta"] = [(date.fromisoformat(d) + timedelta(days=int(n))).isoformat() for d, n in zip(cand.date, cand.lead)]
    cand = cand[cand.eta > AS_OF.isoformat()]
    model, _ = load_model()
    cand["score"] = predict_proba(model, frame_to_features(cand)) * 100
    cand["band"] = pd.cut(cand.score, [b[1] for b in RISK_BANDS] + [101], labels=[b[0] for b in RISK_BANDS], right=False).astype(str)

    picked, lanes, cats = [], set(), {}
    for band, n in TARGET.items():
        for _, r in cand[cand.band == band].sort_values(["date", "shipment_id"]).iterrows():
            if sum(1 for p in picked if p.band == band) >= n:
                break
            lane = (r.origin_port, r.destination_port)
            if lane in lanes or cats.get(r.product_category, 0) >= 3:
                continue
            picked.append(r); lanes.add(lane); cats[r.product_category] = cats.get(r.product_category, 0) + 1

    records = []
    for r in picked:
        o, d = datasets.PORT_INFO[r.origin_port], datasets.PORT_INFO[r.destination_port]
        units, unit_value = datasets.estimate_value(r.product_category, r.weight_t)
        rec = {"consignment_id": r.shipment_id, "cargo": book.CARGO_NAMES[r.product_category], "product_category": r.product_category,
               "mode": r["mode"], "origin_port": r.origin_port, "origin_country": o[0], "region": o[1],
               "destination_port": r.destination_port, "destination_country": d[0], "destination_region": d[1],
               "dispatch_date": r.date, "eta_date": r.eta, "lead_time_days": int(r.lead), "weight_t": r.weight_t,
               "units": units, "average_cost_per_unit": unit_value, "distance_km": r.distance_km, "fuel_price_index": r.fuel_price_index,
               "geopolitical_risk_index": r.geopolitical_risk_index, "reliability_score": r.reliability_score,
               "weather_condition": r.weather_condition, "weather_risk_index": r.weather_risk_index,
               "weather_risk_level": weather_level(r.weather_risk_index)}
        sup = datasets.supplier_for(rec)
        rec.update(supplier_id=sup["supplier_id"], supplier_name=sup["supplier_name"])
        records.append(rec)

    per_lane = lane_history()["per_lane"]
    results = score_records(records)
    for r in results:
        r["trend"] = [p["pred"] for p in per_lane.get(lane_key(r), [])[-30:]]
    rows = [export_row(r) for r in sorted(results, key=lambda x: -x["risk_score"])]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT, index=False)
    print(f"wrote {OUT} ({len(rows)} consignments)")


if __name__ == "__main__":
    main()
