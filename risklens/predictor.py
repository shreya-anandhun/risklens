"""Loads the trained XGBoost model and scores supplier records with a full
parameter breakdown (value, weight, model contribution) and recommendations."""
from __future__ import annotations

import json
from functools import lru_cache

import numpy as np
import pandas as pd
import xgboost as xgb

from .config import FEATURES, FEATURE_KEYS, FEATURE_WEIGHTS, META_PATH, MODEL_PATH, RISK_BANDS
from .features import composite_index, record_to_factors
from .rules import recommend


@lru_cache(maxsize=1)
def load_model() -> tuple[xgb.XGBClassifier, dict]:
    if not MODEL_PATH.exists() or not META_PATH.exists():
        raise FileNotFoundError("Model not found. Run: python -m risklens.pipeline")
    model = xgb.XGBClassifier()
    model.load_model(MODEL_PATH)
    meta = json.loads(META_PATH.read_text())
    return model, meta


def risk_band(score: float) -> str:
    for band, lo, hi in RISK_BANDS:
        if lo <= score < hi:
            return band
    return RISK_BANDS[-1][0]


def annual_spend(rec: dict) -> float:
    cost = float(rec.get("average_cost_per_unit") or 0)
    vol = float(rec.get("annual_volume_units") or 0)
    return cost * vol


def score_records(records: list[dict]) -> list[dict]:
    """Score a batch of raw supplier records. Returns one result per record."""
    if not records:
        return []
    model, meta = load_model()
    factors = [record_to_factors(r) for r in records]
    X = pd.DataFrame(factors)[FEATURE_KEYS]
    proba = model.predict_proba(X)[:, 1]
    contribs = model.get_booster().predict(xgb.DMatrix(X), pred_contribs=True)  # SHAP values, last col = bias
    threshold = meta["metrics"]["decision_threshold"]

    results = []
    for i, rec in enumerate(records):
        f = factors[i]
        score = float(proba[i] * 100)
        spend = annual_spend(rec)
        margin = abs(proba[i] - threshold) / max(threshold, 1 - threshold)
        breakdown = []
        for j, fd in enumerate(FEATURES):
            k = fd["key"]
            breakdown.append({
                "key": k, "label": fd["label"], "value": round(f[k], 3),
                "weight": FEATURE_WEIGHTS[k], "contribution": round(float(contribs[i][j]), 4),
                "importance": meta["importance"].get(k, 0),
            })
        breakdown.sort(key=lambda b: -abs(b["contribution"]))
        rec_out = recommend(f, rec, score, spend)
        top = next((b for b in breakdown if b["contribution"] > 0), None)
        results.append({
            "supplier_id": rec.get("supplier_id"),
            "supplier_name": rec.get("supplier_name") or "Unnamed supplier",
            "region": rec.get("region"), "product_category": rec.get("product_category"),
            "risk_score": round(score, 1), "risk_band": risk_band(score),
            "flagged": bool(proba[i] >= threshold),
            "confidence": round(float(50 + 50 * min(1, margin)), 1),
            "composite_index": round(composite_index(f), 1),
            "top_driver": {"key": top["key"], "label": top["label"], "value": top["value"]} if top else None,
            "annual_spend_usd": round(spend, 0),
            "factors": breakdown,
            "inputs": {k: rec.get(k) for k in (
                "lead_time_days", "lead_time_std_days", "reliability_score", "geopolitical_risk_index",
                "port_congestion_index", "weather_risk_index", "weather_risk_level", "price_swing_pct",
                "days_since_last_disruption", "single_source", "average_cost_per_unit", "annual_volume_units")},
            **rec_out,
        })
    return results


def portfolio_summary(results: list[dict]) -> dict:
    if not results:
        return {"n": 0}
    spend = np.array([r["annual_spend_usd"] for r in results], dtype=float)
    scores = np.array([r["risk_score"] for r in results], dtype=float)
    bands = {b: sum(1 for r in results if r["risk_band"] == b) for b, _, _ in RISK_BANDS}
    at_risk = np.array([r["risk_band"] != "low" for r in results])
    return {
        "n": len(results),
        "bands": bands,
        "pct_suppliers_at_risk": round(float(at_risk.mean() * 100), 1),
        "pct_spend_at_risk": round(float(spend[at_risk].sum() / spend.sum() * 100), 1) if spend.sum() else 0.0,
        "spend_at_risk_usd": round(float(spend[at_risk].sum()), 0),
        "total_spend_usd": round(float(spend.sum()), 0),
        "avg_risk_score": round(float(scores.mean()), 1),
        "spend_weighted_risk": round(float((scores * spend).sum() / spend.sum()), 1) if spend.sum() else 0.0,
        "expected_loss_usd": round(float(sum(r["expected_loss_usd"] for r in results)), 0),
        "flagged": int(sum(r["flagged"] for r in results)),
    }
