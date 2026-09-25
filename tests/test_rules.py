from risklens.rules import estimate_disruption_cost, recommend, rules_catalogue


def _factors(**over):
    base = {k: 0.1 for k in ("weather_risk", "geopolitical_risk", "reliability_risk", "fuel_price_risk", "distance_risk")}
    return {**base, **over}


def test_no_triggers_yields_maintain():
    out = recommend(_factors(), {"mode": "Air"}, 5.0, 1_000_000)
    assert [r["id"] for r in out["recommendations"]] == ["maintain"]
    assert out["residual_risk_score"] == 5.0


def test_triggers_quote_the_data_and_cost_benefit_adds_up():
    ctx = {"supplier": {"supplier_name": "Test Co", "on_time_rate": 0.7},
           "gpr": {"origin": {"country": "Egypt", "value": 1.2, "month": "2024-07", "ratio": 1.6, "proxy": False}, "destination": None}}
    out = recommend(_factors(geopolitical_risk=0.8, weather_risk=0.95, reliability_risk=0.4),
                    {"mode": "Sea", "weather_condition": "Hurricane", "geopolitical_risk_index": 80, "reliability_score": 0.6}, 95.0, 2_000_000, ctx)
    ids = {r["id"] for r in out["recommendations"]}
    assert {"weather_window", "geo_reroute", "gpr_watch", "carrier_switch", "supplier_check", "schedule_buffer", "buffer_stock"} <= ids
    by = {r["id"]: r for r in out["recommendations"]}
    assert "hurricane" in by["weather_window"]["rationale"] and "Egypt" in by["gpr_watch"]["rationale"]
    for r in out["recommendations"]:
        assert r["cost_usd"] >= 0 and r["net_benefit_usd"] == r["benefit_usd"] - r["cost_usd"]
    assert out["residual_risk_score"] < 95.0
    assert out["expected_loss_usd"] == round(0.95 * out["estimated_disruption_cost_usd"], 0)


def test_disruption_cost_follows_mode_delays_in_the_data():
    assert estimate_disruption_cost(1_000_000, "Sea") > estimate_disruption_cost(1_000_000, "Air") > 0


def test_catalogue_is_serialisable():
    cat = rules_catalogue()
    assert all("condition" not in r and isinstance(r["rationale"], str) for r in cat) and cat[-1]["id"] == "maintain"
