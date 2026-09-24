import math

import pandas as pd

from risklens import features as F
from risklens.config import FEATURE_KEYS, NO_HISTORY_DAYS
from risklens.features import build_feature_panel, record_to_factors


def test_scalar_transforms_are_bounded_and_directional():
    assert F.reliability_risk(1.0) == 0 and F.reliability_risk(0.6) == 0.4
    assert F.lead_time_risk(5) == 0 and F.lead_time_risk(90) == 1 and F.lead_time_risk(200) == 1
    assert F.lead_time_variability(40, 0) == 0 and F.lead_time_variability(40, 40) == 1
    assert F.geopolitical_risk(50) == 0.5 and math.isclose(F.geopolitical_risk(50, 100), 0.65)
    assert F.weather_risk(None, "HIGH ") == 0.9 and F.weather_risk(30) == 0.3
    assert F.price_volatility(0) == 0 and F.price_volatility(50) == 1
    assert F.disruption_recency(0) == 1 and F.disruption_recency(None) < 0.001


def test_record_to_factors_handles_missing_and_percent_inputs():
    f = record_to_factors({"lead_time_days": 30, "reliability_score": 0.9, "geopolitical_risk_index": 10, "weather_risk_level": "low"})
    assert set(f) == set(FEATURE_KEYS)
    assert all(0 <= v <= 1 for v in f.values())
    assert f["disruption_recency"] < 0.001  # no history → sentinel
    g = record_to_factors({"lead_time_days": 30, "on_time_deliveries": 45, "total_deliveries": 50, "geopolitical_risk_index": 10})
    assert math.isclose(g["reliability_risk"], 0.1)


def test_panel_uses_only_past_information_for_recency():
    rows = []
    for i, d in enumerate(pd.date_range("2026-01-01", periods=12)):
        rows.append({"date": d.date().isoformat(), "supplier_id": "S1", "supplier_name": "S1", "region": "Europe",
                     "product_category": "Packaging", "lead_time_days": 30, "lead_time_std_days": 3, "reliability_score": 0.9,
                     "geopolitical_risk_index": 20, "port_congestion_index": 20, "weather_risk_index": 20, "weather_risk_level": "low",
                     "commodity_price_index": 100 + i, "average_cost_per_unit": 1, "annual_volume_units": 1, "single_source": 0,
                     "disrupted": 1 if i == 3 else 0})
    p = build_feature_panel(pd.DataFrame(rows))
    assert p.loc[3, "days_since_last_disruption"] == NO_HISTORY_DAYS  # the event day itself sees no *past* event
    assert p.loc[4, "days_since_last_disruption"] == 1
    assert p.loc[0, "target_disruption_7d"] == 1 and p.loc[3, "target_disruption_7d"] == 0
    assert not p["label_valid"].iloc[-1] and p["label_valid"].iloc[0]
