"""Intelligent workflow: an agent-to-agent exchange that ends in a deployed action.

For one recommended action, the RiskLens agent sends the warehouse notification,
the warehouse's system replies with a questionnaire, the RiskLens agent answers
every question from the consignment's data, then mails the warehouse stakeholder
a consolidated summary asking for sign-off. The stakeholder's reply comes back,
the agent reads it (decision, dates, constraints) and deploys the action itself.

The exchange is scripted: every answer is computed from the cargo profile, the
journey, the model, the alternatives and the datasets, and the stakeholder's
reply is generated rather than received. The deployment is real: it applies the
model-scored alternative or records the action on the consignment.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import date, datetime, timedelta, timezone

from . import datasets, notify
from .cargo import TRANSPORT_DOC, profile as cargo_profile
from .config import AS_OF, DATA_PORTAL
from .predictor import apply_changes, score_records

LOG_PATH = DATA_PORTAL / "workflows.json"
_lock = threading.Lock()

STEPS = ["notify", "questions", "answers", "mail", "reply", "understand", "deploy"]
PHASES = [("send", "Mail to be sent", ["notify", "questions", "answers", "mail"]),
          ("understand", "Understand the mail", ["reply", "understand"]),
          ("deploy", "Deploy the action", ["deploy"])]
ALTERNATIVE_FOR = {"weather_window": "A2", "geo_reroute": "A3", "carrier_switch": "A1"}

AGENTS = {
    "risklens": {"name": "RiskLens agent", "short": "RL", "kind": "agent"},
    "warehouse": {"name": "Warehouse system", "short": "WH", "kind": "agent"},
    "stakeholder": {"name": "Warehouse stakeholder", "short": "", "kind": "human"},
}


def _fmt(d: str | None) -> str:
    return datetime.fromisoformat(d).strftime("%-d %b") if d else "—"


def _plus(days: int, start: date = AS_OF) -> str:
    return (start + timedelta(days=days)).isoformat()


def _usd(x: float) -> str:
    return f"${x:,.0f}"


# ---------------------------------------------------------------------------
# the questionnaire and the agent's answers
# ---------------------------------------------------------------------------
def _qa(action: dict, r: dict, rec: dict, prof: dict, recipient: dict) -> list[dict]:
    j, inp, ctx, load = r.get("journey") or {}, r["inputs"], r.get("context") or {}, prof["load"]
    imp = notify.impact(action, r)
    alt = next((a for a in r.get("alternatives") or [] if a["id"] == ALTERNATIVE_FOR.get(action["id"])), None)
    crit = [h["title"] for h in prof["handling"] if h.get("critical")]
    eq = prof["equipment"]
    bench = datasets.benchmarks()["shipments"]
    delay = bench["delay_days_when_disrupted"].get(rec.get("mode") or "Sea", 7)
    role = recipient["key"]

    qa = [
        {"q": "What exactly is in the consignment, and how is it packed?",
         "a": f"{prof['commodity']}: {load['units']:,} {prof['unit_label']}s in {load['packages']:,} {prof['package_label']}s, "
              f"{load['gross_t']:,.0f} t gross in {load['equipment_count']} × {eq['name']}. "
              + (f"Critical handling: {', '.join(crit)}." if crit else "No critical handling rules."),
         "source": "Cargo profile"},
        {"q": "Where is it right now, and when is it due with us?" if role == "destination" else "Where is it right now, and when does it leave?",
         "a": (f"{j.get('status', 'Not dated')}, day {j.get('elapsed_days', 0)} of {j.get('total_days', 0)} by {rec.get('mode', '').lower()}. "
               f"Dispatched {_fmt(j.get('dispatch_date'))}, ETA {_fmt(j.get('eta_date'))} ({j.get('days_to_eta', 0)} days away). "
               f"Weather on the route is {str(inp.get('weather_condition') or 'unknown').lower()}."),
         "source": "Journey"},
    ]
    aid = action["id"]
    if aid == "weather_window":
        hold = alt["eta_delta_days"] if alt else 3
        qa.append({"q": "Which weather window are we avoiding, and how long do we hold?",
                   "a": f"{inp.get('weather_condition')} on the route, severity {float(inp.get('weather_risk_index') or 0):.0f}/100. "
                        f"Hold {hold} days and re-book once it clears: the re-scored risk drops from {r['risk_score']:.0f} to {alt['risk_score']:.0f}, "
                        f"new ETA {_fmt(_plus(hold, date.fromisoformat(j['eta_date'])) if j.get('eta_date') else None)}." if alt else
                        f"{inp.get('weather_condition')} on the route. Hold {hold} days and re-book once it clears.",
                   "source": "Alternatives (re-scored by the model)"})
        qa.append({"q": "Does the cargo need cover or power while it waits?",
                   "a": (f"Yes: keep it at {prof['temperature']['min']}–{prof['temperature']['max']} °C, so the {eq['name'].lower()} stays plugged in."
                         if prof.get("temperature") else f"Under cover is enough. {crit[0] if crit else 'Standard storage'} still applies."),
                   "source": "Cargo profile"})
    elif aid == "geo_reroute":
        g = ctx.get("gpr") or {}
        worst = max((x for x in (g.get("origin"), g.get("destination")) if x), key=lambda x: x.get("ratio") or 0, default=None)
        qa.append({"q": "Which corridor is the problem, and what is the alternative routing?",
                   "a": f"Geopolitical risk on the route is {float(inp.get('geopolitical_risk_index') or 0) / 10:.1f}/10"
                        + (f", and the GPR index for {worst['country']} reads {worst['value']:.2f}, {worst['ratio']:.1f}× its average" if worst else "")
                        + (f". The alternative corridor adds about {alt['eta_delta_days']} days and {alt['cost_usd'] and _usd(alt['cost_usd'])} in cost, "
                           f"and re-scores at {alt['risk_score']:.0f} instead of {r['risk_score']:.0f}." if alt else "."),
                   "source": "GPR index and re-scored alternative"})
        qa.append({"q": "Do the documents change with the new routing?",
                   "a": f"The {TRANSPORT_DOC.get(rec.get('mode') or 'Sea', 'transport document').lower()} is reissued for the new port; "
                        f"{prof['documents_ready']} of {len(prof['documents'])} documents are ready today.",
                   "source": "Cargo profile"})
    elif aid == "carrier_switch":
        qa.append({"q": "What is wrong with the current carrier, and who replaces them?",
                   "a": f"The current carrier scores {float(inp.get('reliability_score') or 0):.2f} for reliability. "
                        + (f"A top-decile carrier on this lane scores {float(alt['changes']['reliability_score'][1:]):.2f}; the switch re-scores the shipment at "
                           f"{alt['risk_score']:.0f} instead of {r['risk_score']:.0f}, at {_usd(alt['cost_usd'])}." if alt else ""),
                   "source": "Lane history (5,000 shipments)"})
    elif aid == "schedule_buffer":
        qa.append({"q": "How much buffer, and what date should we promise customers?",
                   "a": f"Disrupted {str(rec.get('mode') or 'sea').lower()} shipments in the data ran about {delay:.0f} days late. "
                        f"Promise {_fmt(_plus(int(round(delay)), date.fromisoformat(j['eta_date'])) if j.get('eta_date') else None)} instead of {_fmt(j.get('eta_date'))}.",
                   "source": "Lane history (5,000 shipments)"})
    elif aid == "buffer_stock":
        cover = max(1, int(round(load["packages"] * min(1, delay / max(1, j.get("total_days") or 14)))))
        qa.append({"q": "How much stock should we pre-position, and for how long?",
                   "a": f"Enough to cover a {delay:.0f}-day slip: about {cover:,} {prof['package_label']}s of {prof['commodity'].split(':')[0].lower()}, "
                        f"held from {_fmt(j.get('eta_date'))} until the consignment lands.",
                   "source": "Cargo profile and lane history"})
    elif aid == "gpr_watch":
        g = ctx.get("gpr") or {}
        worst = max((x for x in (g.get("origin"), g.get("destination")) if x), key=lambda x: x.get("ratio") or 0, default=None)
        qa.append({"q": "What should we watch, and when do we escalate?",
                   "a": (f"The GPR index for {worst['country']} is {worst['value']:.2f}, {worst['ratio']:.1f}× its 2019–24 average. "
                         f"Escalate if the port announces restrictions or the index passes {worst['value'] * 1.2:.2f}." if worst else
                         "Watch port notices daily and escalate on any restriction."),
                   "source": "GPR index"})
    elif aid == "supplier_check":
        s = ctx.get("supplier") or {}
        qa.append({"q": "Which supplier, and what do we confirm with them?",
                   "a": f"{s.get('supplier_name', 'The supplier')} ({s.get('country', '')}) delivers {float(s.get('on_time_rate') or 0):.0%} of orders on time"
                        + (f", {float(s.get('po_on_time') or 0):.0%} of their {int(s.get('po_count') or 0)} purchase orders by the planned date" if s.get("po_count") else "")
                        + f". Confirm the cargo is packed and documented by {_fmt(j.get('dispatch_date'))}.",
                   "source": "Supplier data"})
    elif aid == "rate_lock":
        qa.append({"q": "What rate are we locking, and for how long?",
                   "a": f"The fuel price index is {float(inp.get('fuel_price_index') or 0):.2f} against a range of 1.2–4.5 in the data. "
                        f"Lock the freight rate and surcharge through delivery on {_fmt(j.get('eta_date'))}.",
                   "source": "Shipment data"})

    qa.append({"q": "What happens if we do nothing, and what does the fix save?",
               "a": f"Disruption risk is {imp['risk_before']:.0f} ({imp['band_before']}) with an expected loss of {_usd(imp['loss_before'])}. "
                    f"Done, it falls to about {imp['risk_after']:.0f} ({imp['band_after']}), avoiding {_usd(imp['loss_avoided'])} for a cost of {_usd(action.get('cost_usd') or 0)}.",
               "source": "Risk model"})
    qa.append({"q": "Who signs off on our side, and what do you need from them?",
               "a": f"Your {recipient['contact'].lower()} at {recipient['name']}. We need one reply: approval to proceed, plus any date or handling constraint.",
               "source": "Warehouse directory"})
    return qa


# ---------------------------------------------------------------------------
# the stakeholder's reply, as text segments the agent can read
# ---------------------------------------------------------------------------
def _reply(action: dict, r: dict, rec: dict, prof: dict, recipient: dict) -> dict:
    j = r.get("journey") or {}
    eta = date.fromisoformat(j["eta_date"]) if j.get("eta_date") else AS_OF + timedelta(days=7)
    first = recipient["contact"].split()[0]
    aid = action["id"]
    seg = lambda text, kind=None: {"text": text, "kind": kind}
    if aid == "weather_window":
        d = _plus(3)
        parts = [seg("Thanks for the detail. "), seg("Approved", "decision"), seg(": hold the cargo and re-book once the weather clears. The earliest slot our yard can release is "),
                 seg(_fmt(d), "date"), seg(". "), seg("Please keep the container under cover and plugged in while it waits" if prof.get("temperature") else "Please keep the container under cover while it waits", "constraint"), seg(".")]
        extracted = {"decision": "approve", "date": d, "date_meaning": "earliest release slot", "constraint": parts[-2]["text"]}
    elif aid == "geo_reroute":
        d = _plus(2)
        parts = [seg("Reviewed with our customs broker. "), seg("Approved for the alternative corridor", "decision"), seg(". "),
                 seg("The broker needs 48 hours' notice, so do not release before ", "constraint"), seg(_fmt(d), "date"), seg(". Send the reissued transport document to us the same day.")]
        extracted = {"decision": "approve", "date": d, "date_meaning": "earliest release", "constraint": "Customs broker needs 48 hours' notice"}
    elif aid == "carrier_switch":
        d = j.get("dispatch_date") or _plus(1)
        parts = [seg("Go ahead with the carrier change", "decision"), seg(". "), seg("New booking references must reach us before loading on ", "constraint"), seg(_fmt(d), "date"), seg(".")]
        extracted = {"decision": "approve", "date": d, "date_meaning": "loading date", "constraint": "New booking references before loading"}
    elif aid == "schedule_buffer":
        d = _plus(int(round(datasets.benchmarks()["shipments"]["delay_days_when_disrupted"].get(rec.get("mode") or "Sea", 7))), eta)
        parts = [seg("Agreed", "decision"), seg(". We have told downstream customers to plan for "), seg(_fmt(d), "date"), seg(". "),
                 seg("Receiving is closed on 25 and 26 December, so anything arriving then waits until the 27th", "constraint"), seg(".")]
        extracted = {"decision": "approve", "date": d, "date_meaning": "buffered delivery date", "constraint": "Receiving closed 25–26 December"}
    elif aid == "buffer_stock":
        d = _plus(-2, eta)
        parts = [seg("Approved", "decision"), seg(". We will reserve the pallet positions from "), seg(_fmt(d), "date"), seg(". "),
                 seg("Chilled space is limited, so send us the exact case count by tomorrow" if prof.get("temperature") else "Send us the exact pallet count by tomorrow so we can block the bays", "constraint"), seg(".")]
        extracted = {"decision": "approve", "date": d, "date_meaning": "stock reserved from", "constraint": parts[-2]["text"]}
    elif aid == "gpr_watch":
        parts = [seg("Confirmed", "decision"), seg(". Our port liaison will send a daily note starting "), seg(_fmt(_plus(1)), "date"), seg(". "),
                 seg("Escalations go to the duty manager, not the shared inbox", "constraint"), seg(".")]
        extracted = {"decision": "approve", "date": _plus(1), "date_meaning": "daily updates start", "constraint": "Escalate to the duty manager"}
    elif aid == "supplier_check":
        d = j.get("dispatch_date") or _plus(2)
        parts = [seg("Spoke to the supplier this morning. "), seg("Confirmed", "decision"), seg(": the cargo is packed and the documents will be ready by "), seg(_fmt(d), "date"), seg(". "),
                 seg("They can only load in the morning slot", "constraint"), seg(".")]
        extracted = {"decision": "approve", "date": d, "date_meaning": "cargo ready", "constraint": "Morning loading slot only"}
    else:
        parts = [seg("Approved", "decision"), seg(", lock the rate through "), seg(_fmt(eta.isoformat()), "date"), seg(". "),
                 seg("Copy finance on the confirmation", "constraint"), seg(".")]
        extracted = {"decision": "approve", "date": eta.isoformat(), "date_meaning": "rate locked through", "constraint": "Copy finance"}
    text = "".join(p["text"] for p in parts)
    body = f"Hi,\n\n{text}\n\nRegards,\n{recipient['contact']}, {recipient['name']}"
    return {"from": {"name": recipient["contact"], "org": recipient["name"], "email": recipient["email"]},
            "subject": f"Re: Sign-off needed: {action['action']} · {rec.get('consignment_id')}",
            "body": body, "segments": parts, "extracted": extracted, "simulated": True}


def _understanding(reply: dict, action: dict, deploy_plan: str) -> dict:
    x = reply["extracted"]
    return {
        "decision": x["decision"], "decision_label": "Approved: proceed",
        "date": x["date"], "date_meaning": x["date_meaning"], "constraint": x["constraint"],
        "checks": [
            {"label": "Sign-off found", "detail": "The reply approves the action without a counter-proposal", "ok": True},
            {"label": "Date extracted", "detail": f"{_fmt(x['date'])} · {x['date_meaning']}", "ok": True},
            {"label": "Constraint noted", "detail": x["constraint"], "ok": True},
            {"label": "Nothing blocks deployment", "detail": "No decline, no request for more information", "ok": True},
        ],
        "plan": deploy_plan,
    }


# ---------------------------------------------------------------------------
# workflow lifecycle
# ---------------------------------------------------------------------------
def _read() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    try:
        return json.loads(LOG_PATH.read_text())
    except json.JSONDecodeError:
        return []


def _write(items: list[dict]) -> None:
    DATA_PORTAL.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(items, indent=2))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def list_workflows() -> list[dict]:
    with _lock:
        return sorted(_read(), key=lambda w: w["created_at"], reverse=True)


def get(wid: str) -> dict | None:
    return next((w for w in list_workflows() if w["id"] == wid), None)


def latest_by_action() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for w in sorted(_read(), key=lambda w: w["created_at"]):
        if w["status"] == "done":
            out[f"{w['consignment_id']}|{w['action_id']}"] = {"id": w["id"], "deployed_at": w["deployed_at"], "result": w["steps"]["deploy"]}
    return out


def clear() -> None:
    with _lock:
        if LOG_PATH.exists():
            LOG_PATH.unlink()


def create(rec: dict, result: dict, action: dict, sent: dict | None = None) -> dict:
    """Plan the whole exchange for one action. Nothing changes on the consignment until the deploy step runs."""
    prof = cargo_profile(rec)
    d = notify.draft(action, result, rec)
    recipient = d["recipients"][0]
    stakeholder = {"name": recipient["contact"], "org": recipient["name"], "email": recipient["email"], "location": recipient["location"]}
    qa = _qa(action, result, rec, prof, recipient)
    alt = next((a for a in result.get("alternatives") or [] if a["id"] == ALTERNATIVE_FOR.get(action["id"])), None)
    plan = (f"Apply “{alt['title']}” to {rec['consignment_id']} and re-score it with the model" if alt
            else f"Record “{action['action']}” as executed on {rec['consignment_id']}" + (" and move the ETA to the buffered date" if action["id"] == "schedule_buffer" else ""))
    reply = _reply(action, result, rec, prof, recipient)
    lines = "\n".join(f"• {x['q']}\n  {x['a']}" for x in qa)
    mail = {
        "to": stakeholder, "cc": [r["email"] for r in d["recipients"][1:]],
        "subject": f"Sign-off needed: {action['action']} · {rec.get('consignment_id')} ({d['recipients'][0]['location'].split(',')[0]} side)",
        "body": (f"Hello {recipient['contact']},\n\n"
                 f"RiskLens recommends this action for consignment {rec.get('consignment_id')} ({rec.get('cargo')}, {result.get('origin_port')} → {result.get('destination_port')}). "
                 f"Your warehouse system asked us {len(qa)} questions about it; the answers are below so you have everything in one place.\n\n"
                 f"ACTION\n{action['action']}\nWhy: {action.get('rationale', '')}\nWhen: {action.get('timeline', '')}\n\n"
                 f"WHAT YOUR SYSTEM ASKED, AND OUR ANSWERS\n{lines}\n\n"
                 f"WHAT WE NEED FROM YOU\nReply with your approval to proceed, and any date or handling constraint on your side. "
                 f"RiskLens will read your reply and deploy the action; you will see the result in the portal.\n\n"
                 f"— RiskLens agent, on behalf of Northwind Global Operations Desk"),
    }
    w = {
        "id": "WF-" + uuid.uuid4().hex[:8].upper(), "created_at": _now(), "status": "running", "revealed": 1, "deployed_at": None,
        "consignment_id": rec["consignment_id"], "action_id": action["id"], "action": action["action"], "lane": f"{result.get('origin_port')} → {result.get('destination_port')}",
        "risk_before": result["risk_score"], "band_before": result["risk_band"], "agents": AGENTS, "stakeholder": stakeholder, "phases": PHASES,
        "steps": {
            "notify": {"subject": sent["subject"] if sent else d["subject"], "body": sent["body"] if sent else d["body"],
                       "to": [r["name"] for r in (sent["recipients"] if sent else d["recipients"])], "sent_at": sent["sent_at"] if sent else None},
            "questions": [x["q"] for x in qa],
            "answers": [{"q": x["q"], "a": x["a"], "source": x["source"]} for x in qa],
            "mail": mail,
            "reply": reply,
            "understand": _understanding(reply, action, plan),
            "deploy": None,
        },
    }
    with _lock:
        items = _read()
        items.append(w)
        _write(items)
    return w


def _deploy(w: dict, rec: dict, result: dict, action: dict, save) -> dict:
    """Make the change on the consignment. Returns what happened."""
    alt = next((a for a in result.get("alternatives") or [] if a["id"] == ALTERNATIVE_FOR.get(action["id"])), None)
    j = result.get("journey") or {}
    if alt:
        new, diffs = apply_changes(rec, alt["changes"])
        if new.get("eta_date") and alt["eta_delta_days"]:
            new["eta_date"] = _plus(alt["eta_delta_days"], date.fromisoformat(new["eta_date"]))
        new["applied_alternative"] = alt["id"]
        new["executed_actions"] = sorted(set(rec.get("executed_actions") or []) | {action["id"]})
        saved = save(new)
        after = score_records([saved], with_alternatives=False)[0]
        return {"kind": "alternative", "title": alt["title"], "changes": diffs, "risk_before": result["risk_score"], "risk_after": after["risk_score"],
                "band_before": result["risk_band"], "band_after": after["risk_band"], "loss_before": result["expected_loss_usd"], "loss_after": after["expected_loss_usd"],
                "eta_before": j.get("eta_date"), "eta_after": (after.get("journey") or {}).get("eta_date"), "rescored": True,
                "summary": f"Applied “{alt['title']}”. The model re-scored {rec['consignment_id']} at {after['risk_score']:.0f}, down from {result['risk_score']:.0f}."}
    imp = notify.impact(action, result)
    new = dict(rec)
    new["executed_actions"] = sorted(set(rec.get("executed_actions") or []) | {action["id"]})
    eta_after = j.get("eta_date")
    changes = []
    if action["id"] == "schedule_buffer" and j.get("eta_date"):
        delay = int(round(datasets.benchmarks()["shipments"]["delay_days_when_disrupted"].get(rec.get("mode") or "Sea", 7)))
        eta_after = _plus(delay, date.fromisoformat(j["eta_date"]))
        new["eta_date"] = eta_after
        changes.append(f"ETA {_fmt(j['eta_date'])} → {_fmt(eta_after)}")
    save(new)
    return {"kind": "recorded", "title": action["action"], "changes": changes, "risk_before": result["risk_score"], "risk_after": imp["risk_after"],
            "band_before": result["risk_band"], "band_after": imp["band_after"], "loss_before": imp["loss_before"], "loss_after": imp["loss_after"],
            "eta_before": j.get("eta_date"), "eta_after": eta_after, "rescored": False,
            "summary": f"Recorded “{action['action']}” as executed on {rec['consignment_id']}. Estimated risk after: {imp['risk_after']:.0f}."}


def advance(wid: str, rec: dict, result: dict, action: dict, save) -> dict:
    with _lock:
        items = _read()
        w = next((x for x in items if x["id"] == wid), None)
        if not w:
            raise KeyError(wid)
        if w["status"] == "done":
            return w
        w["revealed"] = min(len(STEPS), w["revealed"] + 1)
        if STEPS[w["revealed"] - 1] == "deploy":
            w["steps"]["deploy"] = _deploy(w, rec, result, action, save)
            w["status"], w["deployed_at"] = "done", _now()
        _write(items)
        return w
