"""Loads the trained XGBoost model and scores consignments with a full
parameter breakdown (value, weight, model contribution), recommended
mitigations and model-scored alternative plans."""
from __future__ import annotations

import json
from datetime import date, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd
import xgboost as xgb

from .config import FEATURES, FEATURE_KEYS, FEATURE_WEIGHTS, META_PATH, MODEL_PATH, RISK_BANDS
from .features import composite_index, record_to_factors
from .rules import estimate_disruption_cost, recommend
from .validation import NUMERIC_RANGES


@lru_cache(maxsize=1)
def load_model() -> tuple[xgb.Booster, dict]:
    if not MODEL_PATH.exists() or not META_PATH.exists():
        raise FileNotFoundError("Model not found. Run: python -m risklens.pipeline")
    # A plain Booster, so serving does not need scikit-learn (XGBClassifier requires it).
    model = xgb.Booster()
    model.load_model(MODEL_PATH)
    meta = json.loads(META_PATH.read_text())
    return model, meta


def risk_band(score: float) -> str:
    for band, lo, hi in RISK_BANDS:
        if lo <= score < hi:
            return band
    return RISK_BANDS[-1][0]


def cargo_value(rec: dict) -> float:
    unit = float(rec.get("average_cost_per_unit") or 0)
    units = rec.get("units")
    if units is None or units == "":
        units = rec.get("annual_volume_units") or 0
    return unit * float(units)


def predict_proba(model: xgb.Booster, X: pd.DataFrame) -> np.ndarray:
    """Probability of disruption within the horizon for each row of X."""
    return model.predict(xgb.DMatrix(X[FEATURE_KEYS]))


def _predict(records: list[dict]):
    model, _ = load_model()
    factors = [record_to_factors(r) for r in records]
    X = pd.DataFrame(factors)[FEATURE_KEYS]
    proba = predict_proba(model, X)
    return factors, X, proba


# ---------------------------------------------------------------------------
# Alternatives
# ---------------------------------------------------------------------------
LABELS = {
    "reliability_score": ("Carrier on-time rate", "{:.2f}"), "lead_time_days": ("Lead time", "{:.0f} d"),
    "lead_time_std_days": ("Lead time spread", "±{:.1f} d"), "geopolitical_risk_index": ("Geopolitical index", "{:.0f}"),
    "port_congestion_index": ("Port congestion", "{:.0f}"), "weather_risk_index": ("Weather index", "{:.0f}"),
    "days_since_last_disruption": ("Days since lane disruption", "{:.0f}"), "price_swing_pct": ("Price swing", "{:.1f}%"),
}
TEXT_LABELS = {"carrier": "Carrier", "mode": "Mode", "origin_port": "From", "destination_port": "To",
               "route_via": "Via", "origin_country": "Origin country", "destination_country": "Destination country"}


def apply_changes(rec: dict, changes: dict) -> tuple[dict, list[str]]:
    """Apply an alternative's changes to a record. Returns (new_record, human-readable diffs)."""
    new = dict(rec)
    diffs = []
    for k, v in changes.items():
        old = rec.get(k)
        if k in NUMERIC_RANGES:
            base = float(old) if old not in (None, "") else 0.0
            if isinstance(v, str):
                op, x = v[0], float(v[1:])
                val = {"*": base * x, "+": base + x, "-": base - x, "^": max(base, x)}[op]
            else:
                val = float(v)
            lo, hi = NUMERIC_RANGES[k]
            val = round(min(hi, max(lo, val)), 3)
            new[k] = val
            if k in LABELS and abs(val - base) > 1e-9:
                name, fmt = LABELS[k]
                diffs.append(f"{name} {fmt.format(base)} → {fmt.format(val)}")
        else:
            new[k] = v
            if k in TEXT_LABELS and v != old:
                diffs.append(f"{TEXT_LABELS[k]}: {v}" if not old else f"{TEXT_LABELS[k]}: {old} → {v}")
    if "weather_risk_index" in changes:
        w = new["weather_risk_index"]
        new["weather_risk_level"] = "low" if w < 40 else ("medium" if w < 65 else "high")
    return new, diffs


def generic_alternatives(rec: dict) -> list[dict]:
    """Fallback plans for consignments without curated alternatives."""
    lead = float(rec.get("lead_time_days") or 30)
    alts = [
        {"id": "G1", "title": "Switch to a higher-reliability carrier",
         "description": "Book with a carrier holding a 95% on-time record on this lane.",
         "changes": {"reliability_score": "^0.95", "lead_time_std_days": "*0.7"}, "cost_delta_pct": 2.5, "eta_delta_days": 0},
        {"id": "G2", "title": "Reroute through a lower-risk corridor",
         "description": "Use an alternative port and routing away from the current chokepoint.",
         "changes": {"geopolitical_risk_index": "*0.65", "port_congestion_index": "*0.7"}, "cost_delta_pct": 2.0, "eta_delta_days": 4},
    ]
    if str(rec.get("mode", "")).lower() != "air" and lead > 10:
        alts.append({"id": "G3", "title": "Upgrade to air freight",
                     "description": "Move the consignment by air to cut transit time and exposure.",
                     "changes": {"mode": "Air", "lead_time_days": 7, "lead_time_std_days": 1.5, "weather_risk_index": "*0.7"},
                     "cost_delta_pct": 20.0, "eta_delta_days": -int(round(0.5 * (lead - 7)))})
    return alts


def score_alternatives(rec: dict, base: dict, options: list[dict]) -> list[dict]:
    options = [o for o in options if o["id"] != rec.get("applied_alternative")]
    if not options:
        return []
    applied = [apply_changes(rec, o["changes"]) for o in options]
    _, _, proba = _predict([a for a, _ in applied])
    value = base["cargo_value_usd"]
    out = []
    for o, (new, diffs), p in zip(options, applied, (float(x) for x in proba)):
        score = float(p * 100)
        dis_cost = estimate_disruption_cost(value, float(new.get("lead_time_days") or 30))
        loss = round(p * dis_cost, 0)
        cost = round(value * o["cost_delta_pct"] / 100, 0)
        avoided = round(base["expected_loss_usd"] - loss, 0)
        out.append({
            "id": o["id"], "title": o["title"], "description": o["description"], "changes": o["changes"],
            "diffs": diffs, "risk_score": round(score, 1), "risk_band": risk_band(score),
            "delta_risk": round(score - base["risk_score"], 1), "eta_delta_days": o["eta_delta_days"],
            "cost_usd": cost, "expected_loss_usd": loss, "loss_avoided_usd": avoided,
            "net_benefit_usd": avoided - cost, "recommended": False,
        })
    best = max(out, key=lambda a: a["net_benefit_usd"])
    if best["net_benefit_usd"] > 0 and best["delta_risk"] < 0:
        best["recommended"] = True
    out.sort(key=lambda a: (not a["recommended"], a["risk_score"]))
    return out


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def journey(rec: dict, today: date | None = None) -> dict | None:
    try:
        dep, eta = date.fromisoformat(rec["dispatch_date"]), date.fromisoformat(rec["eta_date"])
    except (KeyError, TypeError, ValueError):
        return None
    today = today or date.today()
    total = max(1, (eta - dep).days)
    elapsed = (today - dep).days
    status = "Scheduled" if elapsed < 0 else ("Arrived" if today >= eta else "In transit")
    return {"dispatch_date": dep.isoformat(), "eta_date": eta.isoformat(), "total_days": total,
            "elapsed_days": max(0, min(total, elapsed)), "progress": round(max(0.0, min(1.0, elapsed / total)), 3),
            "days_to_eta": (eta - today).days, "status": status}


def score_records(records: list[dict], alternatives: dict[str, list[dict]] | None = None, with_alternatives: bool = True) -> list[dict]:
    """Score a batch of consignment records. Returns one result per record."""
    if not records:
        return []
    model, meta = load_model()
    factors, X, proba = _predict(records)
    contribs = model.predict(xgb.DMatrix(X[FEATURE_KEYS]), pred_contribs=True)  # SHAP values, last col = bias
    threshold = meta["metrics"]["decision_threshold"]
    alternatives = alternatives or {}

    results = []
    for i, rec in enumerate(records):
        f = factors[i]
        score = float(proba[i] * 100)
        value = cargo_value(rec)
        margin = abs(proba[i] - threshold) / max(threshold, 1 - threshold)
        breakdown = []
        for j, fd in enumerate(FEATURES):
            k = fd["key"]
            breakdown.append({
                "key": k, "label": fd["label"], "value": round(f[k], 3),
                "weight": FEATURE_WEIGHTS[k], "contribution": round(float(contribs[i][j]), 4),
                "importance": meta["importance"].get(k, 0), "formula": fd["formula"], "explain": fd["explain"],
            })
        breakdown.sort(key=lambda b: -abs(b["contribution"]))
        top = next((b for b in breakdown if b["contribution"] > 0), None)
        rec_out = recommend(f, rec, score, value)
        cid = rec.get("consignment_id")
        result = {
            "consignment_id": cid, "supplier_id": rec.get("supplier_id"),
            "supplier_name": rec.get("supplier_name"), "cargo": rec.get("cargo"),
            "product_category": rec.get("product_category"), "mode": rec.get("mode"), "carrier": rec.get("carrier"),
            "origin_port": rec.get("origin_port"), "origin_country": rec.get("origin_country"), "region": rec.get("region"),
            "destination_port": rec.get("destination_port"), "destination_country": rec.get("destination_country"),
            "destination_region": rec.get("destination_region"), "route_via": rec.get("route_via"),
            "journey": journey(rec), "applied_alternative": rec.get("applied_alternative"),
            "risk_score": round(score, 1), "risk_band": risk_band(score),
            "flagged": bool(proba[i] >= threshold),
            "confidence": round(float(50 + 50 * min(1, margin)), 1),
            "composite_index": round(composite_index(f), 1),
            "top_driver": {"key": top["key"], "label": top["label"], "value": top["value"]} if top else None,
            "cargo_value_usd": round(value, 0),
            "factors": breakdown,
            "inputs": {k: rec.get(k) for k in (
                "lead_time_days", "lead_time_std_days", "reliability_score", "geopolitical_risk_index",
                "port_congestion_index", "weather_risk_index", "weather_risk_level", "price_swing_pct",
                "days_since_last_disruption", "single_source", "average_cost_per_unit", "units", "annual_volume_units")},
            **rec_out,
        }
        if with_alternatives:
            options = alternatives.get(cid) or generic_alternatives(rec)
            result["alternatives"] = score_alternatives(rec, result, options)
            result["best_alternative"] = next((a for a in result["alternatives"] if a["recommended"]), None)
        results.append(result)
    return results


def portfolio_summary(results: list[dict]) -> dict:
    if not results:
        return {"n": 0}
    value = np.array([r["cargo_value_usd"] for r in results], dtype=float)
    scores = np.array([r["risk_score"] for r in results], dtype=float)
    bands = {b: sum(1 for r in results if r["risk_band"] == b) for b, _, _ in RISK_BANDS}
    at_risk = np.array([r["risk_band"] != "low" for r in results])
    best = [r.get("best_alternative") for r in results if r.get("best_alternative")]
    js = [r["journey"] for r in results if r.get("journey")]
    in_transit = sum(1 for j in js if j["status"] == "In transit")
    departing = sum(1 for j in js if j["status"] == "Scheduled" and (date.fromisoformat(j["dispatch_date"]) - date.today()).days <= 7)
    return {
        "n": len(results),
        "bands": bands,
        "n_at_risk": int(at_risk.sum()),
        "pct_at_risk": round(float(at_risk.mean() * 100), 1),
        "pct_value_at_risk": round(float(value[at_risk].sum() / value.sum() * 100), 1) if value.sum() else 0.0,
        "value_at_risk_usd": round(float(value[at_risk].sum()), 0),
        "total_value_usd": round(float(value.sum()), 0),
        "avg_risk_score": round(float(scores.mean()), 1),
        "value_weighted_risk": round(float((scores * value).sum() / value.sum()), 1) if value.sum() else 0.0,
        "expected_loss_usd": round(float(sum(r["expected_loss_usd"] for r in results)), 0),
        "flagged": int(sum(r["flagged"] for r in results)),
        "alternatives_available": len(best),
        "alternative_savings_usd": round(float(sum(a["net_benefit_usd"] for a in best)), 0),
        "in_transit": in_transit,
        "scheduled": sum(1 for j in js if j["status"] == "Scheduled"),
        "departing_7d": departing,
    }
