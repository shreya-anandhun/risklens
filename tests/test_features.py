import math

import pandas as pd

from risklens import datasets
from risklens.config import FEATURE_KEYS, WEATHER_CONDITIONS
from risklens.features import frame_to_features, record_to_factors, weather_index, weather_level


def test_record_to_factors_is_bounded_and_directional():
    f = record_to_factors({"reliability_score": 0.9, "geopolitical_risk_index": 30, "weather_condition": "Clear",
                           "fuel_price_index": 1.2, "distance_km": 0})
    assert set(f) == set(FEATURE_KEYS) and all(0 <= v <= 1 for v in f.values())
    assert math.isclose(f["reliability_risk"], 0.1) and f["fuel_price_risk"] == 0 and f["distance_risk"] == 0
    g = record_to_factors({"reliability_score": 0.5, "geopolitical_risk_index": 100, "weather_condition": "Hurricane",
                           "fuel_price_index": 9, "distance_km": 40_000})
    assert all(g[k] >= f[k] for k in FEATURE_KEYS) and g["fuel_price_risk"] == 1 and g["distance_risk"] == 1


def test_weather_from_condition_index_or_level():
    assert weather_index({"weather_condition": "storm"}) == WEATHER_CONDITIONS["Storm"]
    assert weather_index({"weather_risk_index": 12}) == 12
    assert weather_index({"weather_risk_level": "high"}) > weather_index({"weather_risk_level": "low"})
    assert weather_level(95) == "high" and weather_level(10) == "low"


def test_missing_inputs_fall_back_to_dataset_middle():
    f = record_to_factors({})
    assert all(0 < f[k] < 1 for k in FEATURE_KEYS)


def test_frame_and_record_versions_agree():
    s = datasets.load()["shipments"].head(25)
    frame = frame_to_features(s)
    for i, row in s.iterrows():
        rec = record_to_factors(row.to_dict())
        assert all(math.isclose(rec[k], frame.loc[i, k], abs_tol=1e-9) for k in FEATURE_KEYS)


def test_processed_datasets_are_complete():
    d = datasets.load()
    s = d["shipments"]
    assert len(s) == 5000 and s.disrupted.isin([0, 1]).all() and s.date.is_monotonic_increasing
    assert set(s.origin_port) <= set(datasets.PORT_INFO)
    b = d["benchmarks"]
    assert b["dataco"]["rows"] == 180_519 and b["suppliers"]["rows"] == 100 and b["shipments"]["lanes"] > 50
    assert datasets.gpr_country("CHN")["ratio"] > 0 and datasets.port_gpr("Singapore")["proxy"]
    assert pd.Timestamp(datasets.history().date.max()) <= pd.Timestamp("2025-12-20")
