"""Central configuration for RiskLens: paths, feature definitions, thresholds."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
DATA_PORTAL = ROOT / "data" / "portal"
MODELS = ROOT / "models"

MODEL_PATH = MODELS / "risk_model.json"
META_PATH = MODELS / "model_meta.json"

# Prediction horizon: the model predicts whether a disruption occurs within
# this many days. This is the "lead time" the system gives planners.
HORIZON_DAYS = 7

# Reference ranges used to normalise raw inputs to a 0-1 risk scale.
LEAD_TIME_MIN, LEAD_TIME_MAX = 10, 90          # days
LEAD_TIME_CV_CAP = 0.50                        # std/mean above this = max risk
PRICE_SWING_CAP = 25.0                         # 30-day % swing above this = max risk
RECENCY_HALF_LIFE = 30.0                       # days; recency risk decays with e^(-d/30)
NO_HISTORY_DAYS = 999                          # sentinel when no disruption on record

WEATHER_LEVELS = {"low": 0.15, "medium": 0.5, "high": 0.9}
REGIONS = ["South Asia", "Southeast Asia", "East Asia", "Middle East", "Europe", "Africa", "North America", "Latin America"]
CATEGORIES = ["Electronics", "Raw Materials", "Machinery", "Chemicals", "Packaging"]

# Risk banding on the model's disruption probability (0-100).
RISK_BANDS = [
    ("low", 0, 12),
    ("elevated", 12, 30),
    ("high", 30, 101),
]

# Ordered model feature set. Every feature is a 0-1 risk factor (1 = riskiest),
# so the parameter scorecard in the portal reads consistently.
FEATURES = [
    {
        "key": "reliability_risk",
        "label": "Supplier reliability",
        "source": "on_time_deliveries / total_deliveries",
        "formula": "1 - reliability_score",
        "explain": "Share of late or failed deliveries. A supplier that delivers on time 90% of the time scores 0.10.",
        "weight": 0.20,
    },
    {
        "key": "lead_time_risk",
        "label": "Lead time exposure",
        "source": "lead_time_days",
        "formula": "(lead_time_days - 10) / (90 - 10), clipped to 0-1",
        "explain": "Longer lead times mean a longer recovery window once something goes wrong.",
        "weight": 0.10,
    },
    {
        "key": "lead_time_variability",
        "label": "Lead time variability",
        "source": "lead_time_std_days / lead_time_days",
        "formula": "min(1, coefficient_of_variation / 0.50)",
        "explain": "How inconsistent deliveries are. A supplier whose lead time swings by half its average scores 1.0.",
        "weight": 0.10,
    },
    {
        "key": "geopolitical_risk",
        "label": "Geopolitical risk",
        "source": "geopolitical_risk_index, port_congestion_index",
        "formula": "0.7 × geopolitical_index/100 + 0.3 × port_congestion_index/100",
        "explain": "Country and trade-route instability, blended with logistics congestion in the region.",
        "weight": 0.18,
    },
    {
        "key": "weather_risk",
        "label": "Weather & climate risk",
        "source": "weather_risk_index or weather_risk_level",
        "formula": "weather_risk_index / 100 (or low=0.15, medium=0.50, high=0.90)",
        "explain": "Severe weather likelihood at the supplier's site and shipping lanes.",
        "weight": 0.14,
    },
    {
        "key": "price_volatility",
        "label": "Commodity price volatility",
        "source": "commodity_price_index (30-day window)",
        "formula": "min(1, 30-day % swing / 25)",
        "explain": "Input-cost instability. Sharp price moves precede supplier renegotiation, allocation and default.",
        "weight": 0.12,
    },
    {
        "key": "disruption_recency",
        "label": "Disruption recency",
        "source": "days_since_last_disruption",
        "formula": "exp(-days_since_last_disruption / 30)",
        "explain": "How fresh the last failure is. Yesterday's disruption scores ~0.97; one 90 days ago scores ~0.05.",
        "weight": 0.16,
    },
]
FEATURE_KEYS = [f["key"] for f in FEATURES]
FEATURE_WEIGHTS = {f["key"]: f["weight"] for f in FEATURES}
