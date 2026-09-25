"""Feature engineering.

Every model feature is a 0-1 *risk factor* (1 = riskiest). The same
functions serve training (the Kaggle shipment table) and the portal (a single
consignment typed in or uploaded), so what the model was trained on is exactly
what the portal computes.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import (
    DISTANCE_MAX_KM, FEATURE_KEYS, FEATURE_WEIGHTS, FUEL_MAX, FUEL_MIN, WEATHER_CONDITIONS, WEATHER_LEVELS,
)


def _num(v, default: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return default if np.isnan(x) else x


def weather_index(rec: dict) -> float:
    """0-100 weather severity from an explicit index, a condition name or a low/medium/high level."""
    if rec.get("weather_risk_index") not in (None, "") and not pd.isna(rec.get("weather_risk_index")):
        return float(np.clip(float(rec["weather_risk_index"]), 0, 100))
    cond = str(rec.get("weather_condition") or "").strip().title()
    if cond in WEATHER_CONDITIONS:
        return float(WEATHER_CONDITIONS[cond])
    return float(WEATHER_LEVELS.get(str(rec.get("weather_risk_level") or "").strip().lower(), WEATHER_LEVELS["medium"]))


def weather_level(index: float) -> str:
    return "low" if index < 40 else ("medium" if index < 65 else "high")


def record_to_factors(rec: dict) -> dict[str, float]:
    """The model features for one consignment record. Missing values fall back to the dataset's middle."""
    return {
        "weather_risk": weather_index(rec) / 100,
        "geopolitical_risk": float(np.clip(_num(rec.get("geopolitical_risk_index"), 50) / 100, 0, 1)),
        "reliability_risk": float(np.clip(1 - _num(rec.get("reliability_score"), 0.75), 0, 1)),
        "fuel_price_risk": float(np.clip((_num(rec.get("fuel_price_index"), 2.85) - FUEL_MIN) / (FUEL_MAX - FUEL_MIN), 0, 1)),
        "distance_risk": float(np.clip(_num(rec.get("distance_km"), 7700) / DISTANCE_MAX_KM, 0, 1)),
    }


def frame_to_features(df: pd.DataFrame) -> pd.DataFrame:
    """Vectorised version of record_to_factors for a table of shipments."""
    return pd.DataFrame({
        "weather_risk": df["weather_risk_index"].clip(0, 100) / 100,
        "geopolitical_risk": (df["geopolitical_risk_index"] / 100).clip(0, 1),
        "reliability_risk": (1 - df["reliability_score"]).clip(0, 1),
        "fuel_price_risk": ((df["fuel_price_index"] - FUEL_MIN) / (FUEL_MAX - FUEL_MIN)).clip(0, 1),
        "distance_risk": (df["distance_km"] / DISTANCE_MAX_KM).clip(0, 1),
    }, index=df.index)[FEATURE_KEYS]


def composite_index(factors: dict[str, float]) -> float:
    """Transparent weighted index (0-100) shown next to the model score."""
    return float(100 * sum(FEATURE_WEIGHTS[k] * factors[k] for k in FEATURE_KEYS))
