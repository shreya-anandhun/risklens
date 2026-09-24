"""Phase 2 — feature engineering.

Every model feature is a 0-1 *risk factor* (1 = riskiest). The same
functions serve both the offline pipeline (panel of daily rows) and the
portal (a single supplier record typed in or uploaded), so what the model
was trained on is exactly what the portal computes.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import (
    DATA_PROCESSED, DATA_RAW, FEATURE_KEYS, FEATURE_WEIGHTS, HORIZON_DAYS,
    LEAD_TIME_CV_CAP, LEAD_TIME_MAX, LEAD_TIME_MIN, NO_HISTORY_DAYS,
    PRICE_SWING_CAP, RECENCY_HALF_LIFE, WEATHER_LEVELS,
)


# ---------------------------------------------------------------------------
# Scalar transforms (used for single records in the portal)
# ---------------------------------------------------------------------------
def reliability_risk(reliability_score: float) -> float:
    return float(np.clip(1.0 - reliability_score, 0, 1))


def lead_time_risk(lead_time_days: float) -> float:
    return float(np.clip((lead_time_days - LEAD_TIME_MIN) / (LEAD_TIME_MAX - LEAD_TIME_MIN), 0, 1))


def lead_time_variability(lead_time_days: float, lead_time_std_days: float) -> float:
    if lead_time_days <= 0:
        return 0.0
    return float(np.clip((lead_time_std_days / lead_time_days) / LEAD_TIME_CV_CAP, 0, 1))


def geopolitical_risk(geopolitical_risk_index: float, port_congestion_index: float | None = None) -> float:
    geo = np.clip(geopolitical_risk_index / 100, 0, 1)
    if port_congestion_index is None or pd.isna(port_congestion_index):
        return float(geo)
    return float(np.clip(0.7 * geo + 0.3 * np.clip(port_congestion_index / 100, 0, 1), 0, 1))


def weather_risk(weather_risk_index: float | None = None, weather_risk_level: str | None = None) -> float:
    if weather_risk_index is not None and not pd.isna(weather_risk_index):
        return float(np.clip(weather_risk_index / 100, 0, 1))
    return WEATHER_LEVELS.get(str(weather_risk_level).strip().lower(), WEATHER_LEVELS["medium"])


def price_volatility(price_swing_pct: float) -> float:
    return float(np.clip(price_swing_pct / PRICE_SWING_CAP, 0, 1))


def disruption_recency(days_since_last_disruption: float | None) -> float:
    if days_since_last_disruption is None or pd.isna(days_since_last_disruption):
        days_since_last_disruption = NO_HISTORY_DAYS
    return float(np.exp(-max(0.0, float(days_since_last_disruption)) / RECENCY_HALF_LIFE))


def composite_index(factors: dict[str, float]) -> float:
    """Transparent weighted index (0-100) shown next to the model score."""
    return float(100 * sum(FEATURE_WEIGHTS[k] * factors[k] for k in FEATURE_KEYS))


def record_to_factors(rec: dict) -> dict[str, float]:
    """Compute the 7 model features for one supplier record (portal path).

    Expected keys (missing ones fall back to neutral defaults):
      reliability_score (0-1) | on_time_deliveries + total_deliveries
      lead_time_days, lead_time_std_days
      geopolitical_risk_index (0-100), port_congestion_index (0-100, optional)
      weather_risk_index (0-100) or weather_risk_level (low/medium/high)
      price_swing_pct (30-day % swing), days_since_last_disruption
    """
    rel = rec.get("reliability_score")
    if rel is None or pd.isna(rel):
        tot = rec.get("total_deliveries") or 0
        rel = (rec.get("on_time_deliveries") or 0) / tot if tot else 0.85
    lead = float(rec.get("lead_time_days") or 30)
    std = rec.get("lead_time_std_days")
    if std is None or pd.isna(std):
        std = lead * 0.15
    return {
        "reliability_risk": reliability_risk(float(rel)),
        "lead_time_risk": lead_time_risk(lead),
        "lead_time_variability": lead_time_variability(lead, float(std)),
        "geopolitical_risk": geopolitical_risk(float(rec.get("geopolitical_risk_index") or 0), rec.get("port_congestion_index")),
        "weather_risk": weather_risk(rec.get("weather_risk_index"), rec.get("weather_risk_level")),
        "price_volatility": price_volatility(float(rec.get("price_swing_pct") or 0)),
        "disruption_recency": disruption_recency(rec.get("days_since_last_disruption")),
    }


# ---------------------------------------------------------------------------
# Panel transforms (offline pipeline)
# ---------------------------------------------------------------------------
def build_feature_panel(combined: pd.DataFrame) -> pd.DataFrame:
    df = combined.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["supplier_id", "date"]).reset_index(drop=True)

    g = df.groupby("supplier_id", sort=False)

    # 30-day commodity price swing per supplier: (max - min) / mean, in %.
    roll = g["commodity_price_index"].rolling(30, min_periods=5)
    swing = ((roll.max() - roll.min()) / roll.mean() * 100).reset_index(level=0, drop=True)
    df["price_swing_pct"] = swing.fillna(0).round(2)

    # Days since last disruption, using only *past* information (shifted).
    def _days_since(s: pd.Series) -> pd.Series:
        last = pd.Series(pd.NaT, index=s.index)
        dates = df.loc[s.index, "date"]
        last[s.values == 1] = dates[s.values == 1]
        last = last.shift(1).ffill()
        out = (dates - last).dt.days
        return out.fillna(NO_HISTORY_DAYS)
    df["days_since_last_disruption"] = g["disrupted"].transform(_days_since).astype(int)

    # Forward-looking target: any disruption in the next HORIZON_DAYS days.
    def _future(s: pd.Series) -> pd.Series:
        rev = s[::-1].rolling(HORIZON_DAYS, min_periods=1).sum()[::-1]
        return (rev.shift(-1).fillna(0) > 0).astype(int)
    df["target_disruption_7d"] = g["disrupted"].transform(_future)
    # Rows without a full horizon of future data can't be labelled reliably.
    last_date = df["date"].max()
    df["label_valid"] = (last_date - df["date"]).dt.days >= HORIZON_DAYS

    # Vectorised feature computation.
    df["reliability_risk"] = (1 - df["reliability_score"]).clip(0, 1)
    df["lead_time_risk"] = ((df["lead_time_days"] - LEAD_TIME_MIN) / (LEAD_TIME_MAX - LEAD_TIME_MIN)).clip(0, 1)
    df["lead_time_variability"] = ((df["lead_time_std_days"] / df["lead_time_days"]) / LEAD_TIME_CV_CAP).clip(0, 1)
    df["geopolitical_risk"] = (0.7 * df["geopolitical_risk_index"] / 100 + 0.3 * df["port_congestion_index"] / 100).clip(0, 1)
    df["weather_risk"] = (df["weather_risk_index"] / 100).clip(0, 1)
    df["price_volatility"] = (df["price_swing_pct"] / PRICE_SWING_CAP).clip(0, 1)
    df["disruption_recency"] = np.exp(-df["days_since_last_disruption"].clip(lower=0) / RECENCY_HALF_LIFE)
    df["composite_index"] = sum(FEATURE_WEIGHTS[k] * df[k] for k in FEATURE_KEYS) * 100

    cols = [
        "date", "supplier_id", "supplier_name", "region", "product_category",
        "lead_time_days", "lead_time_std_days", "reliability_score",
        "geopolitical_risk_index", "port_congestion_index", "weather_risk_index", "weather_risk_level",
        "commodity_price_index", "price_swing_pct", "days_since_last_disruption",
        "average_cost_per_unit", "annual_volume_units", "single_source",
        *FEATURE_KEYS, "composite_index", "disrupted", "target_disruption_7d", "label_valid",
    ]
    out = df[cols].copy()
    for k in FEATURE_KEYS + ["composite_index"]:
        out[k] = out[k].round(4)
    out["date"] = out["date"].dt.date.astype(str)
    return out


def main():
    combined = pd.read_csv(DATA_RAW / "supply_chain_combined.csv")
    feats = build_feature_panel(combined)
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    path = DATA_PROCESSED / "supply_chain_features.csv"
    feats.to_csv(path, index=False)
    valid = feats[feats.label_valid]
    print(f"wrote {path.name}: {len(feats)} rows, {len(valid)} labelled, "
          f"7-day disruption rate {valid.target_disruption_7d.mean():.1%}")
    print(feats[FEATURE_KEYS].describe().loc[["mean", "min", "max"]].round(3).to_string())


if __name__ == "__main__":
    main()
