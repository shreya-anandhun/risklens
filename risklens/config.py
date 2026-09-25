"""Central configuration for RiskLens: paths, feature definitions, thresholds."""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_KAGGLE = ROOT / "data" / "kaggle"          # raw Kaggle downloads (git-ignored, see tools/fetch_datasets.sh)
DATA_PROCESSED = ROOT / "data" / "processed"    # compact files built from them, used at runtime
# Serverless hosts (Vercel) only allow writes under /tmp.
DATA_PORTAL = Path("/tmp/risklens/portal") if os.environ.get("VERCEL") else ROOT / "data" / "portal"
MODELS = ROOT / "models"

MODEL_PATH = MODELS / "risk_model.json"
META_PATH = MODELS / "model_meta.json"

# The shipment data runs to 31 Dec 2025. The portal shows the book as it stood on this date:
# shipments dispatched before it are in transit, later ones are scheduled.
AS_OF = date(2025, 12, 20)

# The client this portal is deployed for.
COMPANY = {
    "name": "Northwind Logistics",
    "short": "NW",
    "team": "Global Operations Desk",
    "currency": "USD",
}

MODES = ["Sea", "Air", "Road", "Rail"]
CATEGORIES = ["Electronics", "Textiles", "Perishables", "Pharmaceuticals", "Automotive"]

# Weather conditions in the shipment data, and the 0-100 severity each maps to.
WEATHER_CONDITIONS = {"Clear": 10, "Rain": 35, "Fog": 45, "Storm": 75, "Hurricane": 95}
WEATHER_LEVELS = {"low": 15, "medium": 45, "high": 85}   # for records that only give a level

# Reference ranges used to normalise raw inputs to a 0-1 risk scale (the ranges in the dataset).
FUEL_MIN, FUEL_MAX = 1.2, 4.5
DISTANCE_MAX_KM = 15_000

# Cargo value is not in the shipment data, so it is estimated from weight with a typical
# value density per category (USD per kg), and packed into units of a typical size.
CATEGORY_SPECS = {
    "Electronics": {"usd_per_kg": 60.0, "kg_per_unit": 0.8},
    "Textiles": {"usd_per_kg": 12.0, "kg_per_unit": 0.4},
    "Perishables": {"usd_per_kg": 3.5, "kg_per_unit": 10.0},
    "Pharmaceuticals": {"usd_per_kg": 40.0, "kg_per_unit": 0.25},
    "Automotive": {"usd_per_kg": 10.0, "kg_per_unit": 6.0},
}

# Risk banding on the model's disruption probability (0-100). The shipment data has a 61% base
# rate, so the bands sit higher than they would for rarer events.
RISK_BANDS = [
    ("low", 0, 40),
    ("elevated", 40, 70),
    ("high", 70, 101),
]

# Ordered model feature set. Every feature is a 0-1 risk factor (1 = riskiest),
# so the parameter scorecard in the portal reads consistently.
FEATURES = [
    {
        "key": "weather_risk",
        "label": "Weather conditions",
        "source": "Weather_Condition",
        "formula": "severity / 100: Clear 10, Rain 35, Fog 45, Storm 75, Hurricane 95",
        "explain": "Weather on the route. Every hurricane shipment in the data was disrupted, and three in four storm shipments.",
        "weight": 0.35,
    },
    {
        "key": "geopolitical_risk",
        "label": "Geopolitical risk",
        "source": "Geopolitical_Risk_Score (0-10)",
        "formula": "score / 10",
        "explain": "Instability along the route and at the ports. Disruption rises steadily with this score in every weather condition.",
        "weight": 0.30,
    },
    {
        "key": "reliability_risk",
        "label": "Carrier reliability",
        "source": "Carrier_Reliability_Score (0-1)",
        "formula": "1 - reliability score",
        "explain": "How often this carrier delivers as planned. A carrier with a 0.90 score rates 0.10.",
        "weight": 0.15,
    },
    {
        "key": "fuel_price_risk",
        "label": "Fuel price",
        "source": "Fuel_Price_Index (1.2-4.5)",
        "formula": "(index - 1.2) / (4.5 - 1.2)",
        "explain": "Fuel cost pressure at the time of shipping, which drives surcharges and rolled bookings.",
        "weight": 0.10,
    },
    {
        "key": "distance_risk",
        "label": "Route distance",
        "source": "Distance_km",
        "formula": "distance / 15,000 km",
        "explain": "Longer routes spend more time exposed to weather and chokepoints.",
        "weight": 0.10,
    },
]
FEATURE_KEYS = [f["key"] for f in FEATURES]
FEATURE_WEIGHTS = {f["key"]: f["weight"] for f in FEATURES}
