from risklens.rules import recommend, rules_catalogue


def _factors(**over):
    base = {k: 0.1 for k in ("reliability_risk", "lead_time_risk", "lead_time_variability", "geopolitical_risk", "weather_risk", "price_volatility", "disruption_recency")}
    return {**base, **over}


def test_no_triggers_yields_maintain():
    out = recommend(_factors(), {"lead_time_days": 30}, 5.0, 1_000_000)
    assert [r["id"] for r in out["recommendations"]] == ["maintain"]
    assert out["residual_risk_score"] == 5.0


def test_triggers_and_cost_benefit():
    out = recommend(_factors(geopolitical_risk=0.8, weather_risk=0.9), {"lead_time_days": 60, "single_source": 1}, 50.0, 2_000_000)
    ids = {r["id"] for r in out["recommendations"]}
    assert {"geo_reroute", "weather_window", "split_consignment"} <= ids
    for r in out["recommendations"]:
        assert r["cost_usd"] >= 0 and r["net_benefit_usd"] == r["benefit_usd"] - r["cost_usd"]
    assert out["residual_risk_score"] < 50.0
    assert out["expected_loss_usd"] == round(0.5 * out["estimated_disruption_cost_usd"], 0)


def test_catalogue_is_serialisable():
    cat = rules_catalogue()
    assert all("condition" not in r for r in cat) and cat[-1]["id"] == "maintain"
