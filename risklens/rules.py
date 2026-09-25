"""Mitigation rules engine.

Deterministic IF-THEN rules over a consignment's risk factors and its data
context (lane history, real GPR readings, supplier record). Each triggered rule
yields an action with a rationale drawn from the datasets, a cost scaled to the
cargo value, a timeline, and an estimated reduction in disruption probability
so the portal can show cost against benefit. The reductions are planning
estimates; alternatives, by contrast, are re-scored by the model itself.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Callable, Union

from . import datasets
from .config import RISK_BANDS


@lru_cache(maxsize=1)
def facts() -> dict:
    """Figures from the datasets that the rationales quote."""
    b = datasets.benchmarks()
    s = datasets.load()["shipments"]
    q = s.geopolitical_risk_index.quantile([0.25, 0.75])
    dc = b["dataco"]
    by_service = {x["service"]: x["late_share"] for x in dc["by_service"]}
    return {
        "weather": b["shipments"]["by_weather"],
        "geo_low": float(s[s.geopolitical_risk_index <= q[0.25]].disrupted.mean()),
        "geo_high": float(s[s.geopolitical_risk_index >= q[0.75]].disrupted.mean()),
        "rel_top": float(s.reliability_score.quantile(0.9)),
        "delay": b["shipments"]["delay_days_when_disrupted"],
        "dataco_rows": dc["rows"], "dataco_late": dc["late_share"], "dataco_std_late": by_service.get("Standard Class", 0),
        "dataco_delay": dc["mean_delay_days_when_late"],
        "po_on_time": b["suppliers"]["po_on_time"], "po_count": b["suppliers"]["purchase_orders"],
    }


Rationale = Union[str, Callable[[dict, dict, dict], str]]


@dataclass
class Rule:
    id: str
    trigger: str                      # human-readable condition
    condition: Callable[[dict, dict, float, dict], bool]
    action: str
    rationale: Rationale
    cost_band: str                    # None / Low / Medium / High
    cost_pct_of_value: float          # cost as % of cargo value
    timeline: str
    risk_reduction: float             # estimated fraction of disruption probability removed
    category: str


def _worst_gpr(ctx: dict) -> dict | None:
    gpr = ctx.get("gpr") or {}
    g = [x for x in (gpr.get("origin"), gpr.get("destination")) if x and x.get("ratio")]
    return max(g, key=lambda x: x["ratio"]) if g else None


def _weather_text(r, ctx, fx):
    w = fx["weather"]
    return (f"{r.get('weather_condition') or 'Severe weather'} on the route. In the shipment data, {w.get('Hurricane', 0):.0%} of hurricane "
            f"and {w.get('Storm', 0):.0%} of storm shipments were disrupted, against {w.get('Clear', 0):.0%} in clear weather.")


def _geo_text(r, ctx, fx):
    return (f"Geopolitical risk on this route is {float(r.get('geopolitical_risk_index') or 0) / 10:.1f} out of 10. In the shipment data, "
            f"disruption rose from {fx['geo_low']:.0%} for the lowest quarter of scores to {fx['geo_high']:.0%} for the highest.")


def _gpr_text(r, ctx, fx):
    g = _worst_gpr(ctx)
    proxy = " (nearest country the index covers)" if g.get("proxy") else ""
    return (f"The Geopolitical Risk Index for {g['country']}{proxy} read {g['value']:.2f} in {g['month']}, "
            f"{g['ratio']:.1f}× its average since 2019. News-driven risk around this port is running high.")


def _carrier_text(r, ctx, fx):
    return (f"This carrier scores {float(r.get('reliability_score') or 0):.2f} for reliability. "
            f"The top 10% of carriers in the shipment data score {fx['rel_top']:.2f} or better.")


def _supplier_text(r, ctx, fx):
    s = ctx.get("supplier") or {}
    return (f"{s.get('supplier_name', 'The supplier')} delivers {float(s.get('on_time_rate') or 0):.0%} of orders on time. "
            f"Across the {fx['po_count']:,} purchase orders in the supplier data, only {fx['po_on_time']:.0%} arrived by the planned date.")


def _buffer_text(r, ctx, fx):
    mode = r.get("mode") or "Sea"
    return (f"When {mode.lower()} shipments in the data were disrupted, transit ran about {fx['delay'].get(mode, 5):.0f} days longer. "
            f"In DataCo's {fx['dataco_rows']:,} real order lines, {fx['dataco_late']:.0%} arrived late, by {fx['dataco_delay']:.1f} days on average.")


RULES: list[Rule] = [
    Rule("weather_window", "Storm or hurricane on the route",
         lambda f, r, s, c: f["weather_risk"] >= 0.70,
         "Reschedule around the weather window",
         _weather_text, "Low", 0.6, "Before departure, or hold at the next port", 0.40, "Scheduling"),
    Rule("geo_reroute", "Geopolitical risk ≥ 6 out of 10",
         lambda f, r, s, c: f["geopolitical_risk"] >= 0.60,
         "Reroute through a lower-risk corridor or port",
         _geo_text, "Medium", 1.8, "Decide within 48 hours", 0.30, "Routing"),
    Rule("gpr_watch", "Real GPR index ≥ 1.25× its average at either port",
         lambda f, r, s, c: bool(_worst_gpr(c)) and _worst_gpr(c)["ratio"] >= 1.25,
         "Track geopolitical news on the route daily",
         _gpr_text, "Low", 0.1, "Immediate", 0.10, "Monitoring"),
    Rule("carrier_switch", "Carrier reliability below 0.70",
         lambda f, r, s, c: f["reliability_risk"] >= 0.30,
         "Switch to a higher-reliability carrier",
         _carrier_text, "Medium", 2.0, "Next booking", 0.15, "Carrier"),
    Rule("supplier_check", "Supplier on-time rate below 80%",
         lambda f, r, s, c: float(((c.get("supplier") or {}).get("on_time_rate")) or 1) < 0.80,
         "Confirm cargo readiness with the supplier",
         _supplier_text, "Low", 0.1, "Before departure", 0.10, "Supplier"),
    Rule("schedule_buffer", "Risk not Low on a sea, road or rail leg",
         lambda f, r, s, c: s >= RISK_BANDS[1][1] and (r.get("mode") or "Sea") != "Air",
         "Add a schedule buffer to the delivery promise",
         _buffer_text, "Low", 0.3, "Immediate", 0.20, "Planning"),
    Rule("buffer_stock", "High risk",
         lambda f, r, s, c: s >= RISK_BANDS[2][1],
         "Pre-position buffer stock at the destination",
         "The shipment is more likely than not to be disrupted. Safety stock at the destination keeps customers supplied while it recovers.",
         "Low", 1.0, "Immediate", 0.20, "Inventory"),
    Rule("rate_lock", "Fuel price index ≥ 3.5",
         lambda f, r, s, c: f["fuel_price_risk"] >= 0.70,
         "Lock the freight rate and fuel surcharge",
         "Fuel prices are near the top of the range in the data. Fixing the rate now avoids surcharges and rolled bookings.",
         "Low", 0.4, "1 week", 0.05, "Commercial"),
]

MAINTAIN = {
    "id": "maintain", "trigger": "No rule triggered", "action": "Stay on the current plan",
    "rationale": "All monitored signals are inside tolerance. Keep the consignment on standard tracking.",
    "cost_band": "None", "cost_usd": 0, "timeline": "Ongoing", "risk_reduction": 0.0,
    "benefit_usd": 0, "net_benefit_usd": 0, "category": "Monitoring",
}


def estimate_disruption_cost(cargo_value: float, mode: str | None) -> float:
    """Expected cost if this consignment is disrupted: the extra transit days disrupted shipments of this
    mode took in the data, at ~1.2% of cargo value per day (demurrage, expediting, penalties, stock-outs),
    plus a fixed 4% handling impact."""
    delay_days = datasets.benchmarks()["shipments"]["delay_days_when_disrupted"].get(mode or "Sea", 7.0)
    return round(cargo_value * (0.04 + 0.012 * delay_days), 0)


def recommend(factors: dict, record: dict, risk_score: float, cargo_value: float, ctx: dict | None = None) -> dict:
    """Return triggered rules with cost/benefit, plus expected loss context."""
    ctx = ctx or {}
    p = risk_score / 100
    dis_cost = estimate_disruption_cost(cargo_value, record.get("mode"))
    expected_loss = round(p * dis_cost, 0)
    fx = facts()

    recs = []
    for rule in RULES:
        if rule.condition(factors, record, risk_score, ctx):
            cost = round(cargo_value * rule.cost_pct_of_value / 100, 0)
            benefit = round(expected_loss * rule.risk_reduction, 0)
            d = asdict(rule)
            d.pop("condition")
            d.pop("cost_pct_of_value")
            d["rationale"] = rule.rationale(record, ctx, fx) if callable(rule.rationale) else rule.rationale
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
        if callable(d["rationale"]):
            d["rationale"] = "Quotes the relevant figures from the datasets for each consignment."
        out.append(d)
    out.append({k: MAINTAIN[k] for k in ("id", "trigger", "action", "rationale", "cost_band", "timeline", "risk_reduction", "category")})
    return out
