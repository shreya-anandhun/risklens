"""Warehouse notifications for recommended actions, plus the expected impact of each fix.

This is a demo: notifications are drafted and written to a local log
(data/portal/notifications.json). Nothing is emailed or texted. Warehouse names
are fictional and contact addresses use the reserved example.com domain.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone

from .cargo import profile as cargo_profile
from .config import DATA_PORTAL, RISK_BANDS

LOG_PATH = DATA_PORTAL / "notifications.json"
_lock = threading.Lock()

# Which warehouses each type of action affects.
AFFECTS = {
    "geo_reroute": ("origin", "destination"), "buffer_stock": ("destination",), "weather_window": ("origin",),
    "carrier_switch": ("origin",), "rate_lock": ("origin",), "schedule_buffer": ("destination", "origin"),
    "post_incident": ("origin", "destination"), "split_consignment": ("origin", "destination"),
}

# What each warehouse is asked to do, and what gets better once the issue is fixed.
TASKS = {
    "geo_reroute": {"origin": "Hold the booking and prepare to release the cargo to the alternative port or routing.",
                    "destination": "Expect the consignment through a different port and update inbound slots.",
                    "effects": ["Cargo avoids the unstable corridor or congested chokepoint",
                                "Fewer customs holds and unplanned port stops", "Delivery date becomes more predictable"]},
    "buffer_stock": {"destination": "Reserve space and pull forward safety stock so customers are covered if this consignment slips.",
                     "effects": ["Customers keep receiving goods even if the ship is late",
                                 "No emergency air freight to cover a stock-out", "Warehouse can plan labour for a known volume"]},
    "weather_window": {"origin": "Re-slot the container for the rescheduled sailing and keep the cargo under cover until then.",
                       "effects": ["Cargo avoids the severe-weather window at sea", "Lower chance of water damage and lashing failure",
                                   "Fewer delays from port closures during storms"]},
    "carrier_switch": {"origin": "Prepare to hand the cargo to the new carrier and update the booking references.",
                       "effects": ["More reliable on-time performance on the lane", "Shorter recovery if a sailing is missed"]},
    "rate_lock": {"origin": "Confirm the locked freight rate with the carrier before loading.",
                  "effects": ["No surprise fuel or peak-season surcharges", "Space on the vessel is less likely to be reallocated"]},
    "schedule_buffer": {"destination": "Plan the receiving slot on the later, buffered date and tell downstream customers.",
                        "origin": "Share the buffered ETA with the shipper so everyone works to the same date.",
                        "effects": ["Customers get a delivery date the lane can actually meet",
                                    "Fewer missed slots and penalty claims", "Receiving teams are staffed on the right day"]},
    "post_incident": {"origin": "Confirm the cause of the last disruption is closed and report daily until departure.",
                      "destination": "Watch the daily status and flag any change in the ETA straight away.",
                      "effects": ["Early warning if the lane fails again", "Faster reaction time: hours instead of days",
                                  "Clear record of the cause for the carrier review"]},
    "split_consignment": {"origin": "Split the load across two bookings and label each part clearly.",
                          "destination": "Expect two arrivals and receive each part separately.",
                          "effects": ["A problem with one carrier no longer stops the whole load",
                                      "Part of the cargo still arrives on time if one sailing slips"]},
}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())[:18] or "site"


def warehouses(rec: dict) -> dict[str, dict]:
    """The Northwind warehouses at each end of a consignment."""
    prof = cargo_profile(rec)
    o_port, d_port = rec.get("origin_port") or "Origin", rec.get("destination_port") or "Destination"
    dest_name = (prof.get("consignee") or "").split(",")[0].strip() or f"Northwind {d_port} Distribution Centre"
    return {
        "origin": {"role": "Origin", "name": f"Northwind {o_port} Export Warehouse", "location": f"{o_port}, {rec.get('origin_country') or ''}".strip(", "),
                   "contact": "Warehouse manager", "email": f"wh.{_slug(o_port)}@northwind.example.com"},
        "destination": {"role": "Destination", "name": dest_name, "location": f"{d_port}, {rec.get('destination_country') or ''}".strip(", "),
                        "contact": "Inbound operations lead", "email": f"inbound.{_slug(d_port)}@northwind.example.com"},
    }


def _band(score: float) -> str:
    for b, lo, hi in RISK_BANDS:
        if lo <= score < hi:
            return b
    return RISK_BANDS[-1][0]


def impact(action: dict, result: dict) -> dict:
    """Expected effect once the action is done: risk and loss before and after."""
    rr = float(action.get("risk_reduction") or 0)
    before, after = result["risk_score"], round(result["risk_score"] * (1 - rr), 1)
    loss_before = result["expected_loss_usd"]
    loss_after = round(loss_before * (1 - rr), 0)
    return {
        "risk_before": before, "risk_after": after, "band_before": _band(before), "band_after": _band(after),
        "loss_before": loss_before, "loss_after": loss_after, "loss_avoided": round(loss_before - loss_after, 0),
        "effects": TASKS.get(action["id"], {}).get("effects", ["Lower chance of disruption on this consignment"]),
    }


def draft(action: dict, result: dict, rec: dict) -> dict:
    """Recipients and a ready-to-send message for one action."""
    whs = warehouses(rec)
    roles = AFFECTS.get(action["id"], ("origin", "destination"))
    tasks = TASKS.get(action["id"], {})
    imp = impact(action, result)
    recipients = [{**whs[r], "key": r, "task": tasks.get(r, "Review the action and confirm what you need from the operations desk.")} for r in roles]
    lane = f"{rec.get('origin_port')} → {rec.get('destination_port')}"
    subject = f"Action needed: {action['action']} · {rec.get('consignment_id')} ({lane})"
    body = (
        f"Consignment {rec.get('consignment_id')}: {rec.get('cargo') or ''}, {lane}.\n"
        f"Current 7-day disruption risk: {imp['risk_before']:.0f} ({imp['band_before']}).\n\n"
        f"Why: {action.get('rationale', '')}\n"
        f"Trigger: {action.get('trigger', '')}\n"
        f"When: {action.get('timeline', '')}\n\n"
        f"Once done, risk is expected to fall to about {imp['risk_after']:.0f} ({imp['band_after']}) "
        f"and the expected loss from ${imp['loss_before']:,.0f} to ${imp['loss_after']:,.0f}.\n\n"
        "Please confirm receipt and reply with any blockers.\n— Northwind Global Operations Desk (sent via RiskLens)"
    )
    return {"recipients": recipients, "subject": subject, "body": body, "impact": imp}


# ---------------------------------------------------------------------------
# log
# ---------------------------------------------------------------------------
def _read() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    try:
        return json.loads(LOG_PATH.read_text())
    except json.JSONDecodeError:
        return []


def list_notifications() -> list[dict]:
    with _lock:
        return sorted(_read(), key=lambda n: n["sent_at"], reverse=True)


def record(entry: dict) -> dict:
    with _lock:
        log = _read()
        entry = {"id": "NTF-" + uuid.uuid4().hex[:8].upper(), "sent_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "status": "logged (demo, not delivered)", **entry}
        log.append(entry)
        DATA_PORTAL.mkdir(parents=True, exist_ok=True)
        LOG_PATH.write_text(json.dumps(log, indent=2))
        return entry


def clear() -> None:
    with _lock:
        if LOG_PATH.exists():
            LOG_PATH.unlink()


def latest_by_action() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for n in sorted(_read(), key=lambda n: n["sent_at"]):
        out[f"{n['consignment_id']}|{n['action_id']}"] = n
    return out
