"""Phase 4 — mitigation rules engine (consignment view).

Deterministic IF-THEN rules over the parameter scorecard. Each triggered
rule yields an action with rationale, cost band, a cost estimate scaled to
the consignment's cargo value, a timeline, and an expected reduction in
disruption probability so the portal can show cost vs. benefit.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Callable

from .config import RISK_BANDS


@dataclass
class Rule:
    id: str
    trigger: str                      # human-readable condition
    condition: Callable[[dict, dict, float], bool]
    action: str
    rationale: str
    cost_band: str                    # None / Low / Medium / High
    cost_pct_of_value: float          # cost as % of cargo value
    timeline: str
    risk_reduction: float             # fraction of disruption probability removed
    category: str


RULES: list[Rule] = [
    Rule("geo_reroute", "Geopolitical risk ≥ 0.60",
         lambda f, r, s: f["geopolitical_risk"] >= 0.60,
         "Reroute through a lower-risk corridor or port",
         "Instability or congestion along the current corridor is high. A different port or routing caps exposure to a single chokepoint.",
         "Medium", 2.0, "Decide within 48 hours", 0.35, "Routing"),
    Rule("buffer_stock", "Lead time exposure ≥ 0.70",
         lambda f, r, s: f["lead_time_risk"] >= 0.70,
         "Pre-position buffer stock at the destination",
         "A long lead time means weeks of recovery if this consignment slips. Buffer stock at destination covers the gap.",
         "Low", 1.0, "Immediate", 0.20, "Inventory"),
    Rule("weather_window", "Weather risk ≥ 0.65",
         lambda f, r, s: f["weather_risk"] >= 0.65,
         "Reschedule the sailing to avoid the weather window",
         "Severe weather is likely at origin or along the lane. Moving the departure or sailing avoids the worst of it.",
         "Low", 0.8, "Before departure", 0.40, "Scheduling"),
    Rule("carrier_switch", "Carrier reliability risk ≥ 0.25 (on-time < 75%)",
         lambda f, r, s: f["reliability_risk"] >= 0.25,
         "Switch to a higher-reliability carrier",
         "This carrier's on-time record on the lane is poor. A stronger carrier, or SLA penalties, shortens recovery.",
         "Medium", 2.0, "1–2 weeks", 0.25, "Carrier"),
    Rule("rate_lock", "Price volatility ≥ 0.60",
         lambda f, r, s: f["price_volatility"] >= 0.60,
         "Lock the freight rate and fuel surcharge",
         "Sharp fuel and commodity moves lead to surcharges, rolled bookings and space being reallocated. Fixing the rate removes that incentive.",
         "Low", 0.6, "1 week", 0.20, "Commercial"),
    Rule("schedule_buffer", "Lead time variability ≥ 0.50",
         lambda f, r, s: f["lead_time_variability"] >= 0.50,
         "Add a schedule buffer to the delivery promise",
         "Transit times on this lane are inconsistent. Commit to the customer on the slow end of the range, not the average.",
         "Low", 0.3, "Immediate", 0.30, "Planning"),
    Rule("post_incident", "Disruption on this lane in the last ~3 weeks",
         lambda f, r, s: f["disruption_recency"] >= 0.45,
         "Track daily and confirm the last disruption is resolved",
         "A recent failure on the lane raises the odds of a repeat. Confirm the root cause is closed and watch the consignment daily.",
         "Low", 0.2, "Immediate", 0.15, "Monitoring"),
    Rule("split_consignment", "Single carrier and risk not Low",
         lambda f, r, s: bool(r.get("single_source")) and s >= RISK_BANDS[0][2],
         "Split the consignment across two carriers",
         "All of the cargo sits with one carrier. Splitting it turns a full stop into a partial delay.",
         "High", 2.5, "Next booking", 0.45, "Carrier"),
]

MAINTAIN = {
    "id": "maintain", "trigger": "No rule triggered", "action": "Stay on the current plan",
    "rationale": "All monitored parameters are inside tolerance. Keep the consignment on standard tracking.",
    "cost_band": "None", "cost_usd": 0, "timeline": "Ongoing", "risk_reduction": 0.0,
    "benefit_usd": 0, "net_benefit_usd": 0, "category": "Monitoring",
}


def estimate_disruption_cost(cargo_value: float, lead_time_days: float) -> float:
    """Expected cost if this consignment is disrupted: a delay of roughly
    0.3 × lead time + 5 days, costing ~1.2% of cargo value per day (demurrage,
    expediting, penalties, stock-outs), plus a fixed 4% handling impact."""
    delay_days = 0.3 * lead_time_days + 5
    return round(cargo_value * (0.04 + 0.012 * delay_days), 0)


def recommend(factors: dict, record: dict, risk_score: float, cargo_value: float) -> dict:
    """Return triggered rules with cost/benefit, plus expected loss context."""
    p = risk_score / 100
    dis_cost = estimate_disruption_cost(cargo_value, float(record.get("lead_time_days") or 30))
    expected_loss = round(p * dis_cost, 0)

    recs = []
    for rule in RULES:
        if rule.condition(factors, record, risk_score):
            cost = round(cargo_value * rule.cost_pct_of_value / 100, 0)
            benefit = round(expected_loss * rule.risk_reduction, 0)
            d = asdict(rule)
            d.pop("condition")
            d.pop("cost_pct_of_value")
            d.update(cost_usd=cost, benefit_usd=benefit, net_benefit_usd=benefit - cost)
            recs.append(d)

    if not recs:
        recs = [dict(MAINTAIN)]
    else:
        recs.sort(key=lambda d: (-d["risk_reduction"] * p, d["cost_usd"]))

    combined_reduction = 1.0
    for d in recs:
        combined_reduction *= (1 - d["risk_reduction"])
    return {
        "recommendations": recs,
        "estimated_disruption_cost_usd": dis_cost,
        "expected_loss_usd": expected_loss,
        "residual_risk_score": round(risk_score * combined_reduction, 1),
        "total_mitigation_cost_usd": sum(d["cost_usd"] for d in recs),
    }


def rules_catalogue() -> list[dict]:
    out = []
    for r in RULES:
        d = asdict(r)
        d.pop("condition")
        out.append(d)
    out.append({k: MAINTAIN[k] for k in ("id", "trigger", "action", "rationale", "cost_band", "timeline", "risk_reduction", "category")})
    return out
