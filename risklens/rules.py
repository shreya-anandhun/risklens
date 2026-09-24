"""Phase 4 — mitigation rules engine.

Deterministic IF-THEN rules over the parameter scorecard. Each triggered
rule yields an action with rationale, cost band, a cost estimate scaled to
the supplier's annual spend, a timeline, and an expected reduction in
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
    cost_pct_of_spend: float          # one-off + first-year cost as % of annual spend
    timeline: str
    risk_reduction: float             # fraction of disruption probability removed
    category: str


RULES: list[Rule] = [
    Rule("geo_diversify", "Geopolitical risk ≥ 0.60",
         lambda f, r, s: f["geopolitical_risk"] >= 0.60,
         "Diversify sourcing region",
         "Country and trade-route instability in the supplier's region is high; a second region caps exposure to a single corridor.",
         "Medium", 3.0, "4–8 weeks", 0.35, "Sourcing"),
    Rule("safety_stock", "Lead time exposure ≥ 0.70",
         lambda f, r, s: f["lead_time_risk"] >= 0.70,
         "Increase safety stock by 25%",
         "Long lead times mean weeks of recovery once a shipment slips; buffer stock absorbs the first shock.",
         "Low", 0.6, "Immediate", 0.20, "Inventory"),
    Rule("weather_backup", "Weather risk ≥ 0.65",
         lambda f, r, s: f["weather_risk"] >= 0.65,
         "Activate backup supplier / pre-position inventory",
         "Severe weather is likely at the site or shipping lanes; shifting near-term volume avoids the outage window.",
         "Medium", 1.5, "1–2 weeks", 0.40, "Continuity"),
    Rule("renegotiate", "Reliability risk ≥ 0.25 (on-time < 75%)",
         lambda f, r, s: f["reliability_risk"] >= 0.25,
         "Renegotiate contract with SLA penalties and expediting clauses",
         "Historical on-time performance is poor; contractual levers and expedite rights shorten recovery.",
         "Low", 0.3, "2–3 weeks", 0.25, "Commercial"),
    Rule("forward_contract", "Price volatility ≥ 0.60",
         lambda f, r, s: f["price_volatility"] >= 0.60,
         "Lock in a forward contract or hedge input cost",
         "Sharp commodity price moves precede allocation, renegotiation and supplier default; fixing price removes the incentive to divert supply.",
         "Low", 1.0, "1–2 weeks", 0.20, "Commercial"),
    Rule("schedule_buffer", "Lead time variability ≥ 0.50",
         lambda f, r, s: f["lead_time_variability"] >= 0.50,
         "Add schedule buffer and start dual-source qualification",
         "Deliveries are inconsistent; planning to the P90 lead time and qualifying an alternate removes the variance.",
         "Medium", 1.2, "6–10 weeks", 0.30, "Planning"),
    Rule("post_incident", "Disruption in the last ~3 weeks",
         lambda f, r, s: f["disruption_recency"] >= 0.45,
         "Run post-incident review and expedite open orders",
         "A recent failure raises the odds of a repeat; confirm root cause is closed and expedite in-flight orders.",
         "Low", 0.2, "Immediate", 0.15, "Recovery"),
    Rule("second_source", "Single-sourced and risk not Low",
         lambda f, r, s: bool(r.get("single_source")) and s >= RISK_BANDS[0][2],
         "Qualify a second source",
         "The part is single-sourced; any disruption is a full stock-out. A qualified alternate turns a stop into a slowdown.",
         "High", 3.5, "8–12 weeks", 0.45, "Sourcing"),
]

MAINTAIN = {
    "id": "maintain", "trigger": "No rule triggered", "action": "Maintain current strategy",
    "rationale": "All monitored parameters are inside tolerance. Keep the supplier on the monitoring cadence.",
    "cost_band": "None", "cost_usd": 0, "timeline": "Ongoing", "risk_reduction": 0.0,
    "benefit_usd": 0, "net_benefit_usd": 0, "category": "Monitoring",
}


def estimate_disruption_cost(annual_spend: float, lead_time_days: float) -> float:
    """Expected cost of one disruption: recovery period ≈ half a lead time + a week,
    at ~2.5× daily spend (expediting, lost throughput, penalties)."""
    daily = annual_spend / 365
    recovery_days = 0.5 * lead_time_days + 7
    return round(daily * recovery_days * 2.5, 0)


def recommend(factors: dict, record: dict, risk_score: float, annual_spend: float) -> dict:
    """Return triggered rules with cost/benefit, plus expected loss context."""
    p = risk_score / 100
    dis_cost = estimate_disruption_cost(annual_spend, float(record.get("lead_time_days") or 30))
    expected_loss = round(p * dis_cost, 0)

    recs = []
    for rule in RULES:
        if rule.condition(factors, record, risk_score):
            cost = round(annual_spend * rule.cost_pct_of_spend / 100, 0)
            benefit = round(expected_loss * rule.risk_reduction, 0)
            d = asdict(rule)
            d.pop("condition")
            d.pop("cost_pct_of_spend")
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
