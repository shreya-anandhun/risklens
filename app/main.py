"""RiskLens client portal API. Serves the single-page portal and JSON endpoints
for one client's consignment book, built on the Kaggle datasets in risklens/datasets.py."""
from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from risklens import datasets, notify, store, workflow
from risklens.cargo import profile as cargo_profile
from risklens.config import AS_OF, CATEGORIES, COMPANY, FEATURE_KEYS, FEATURES, MODES, RISK_BANDS, WEATHER_CONDITIONS
from risklens.features import frame_to_features
from risklens.geo import PORTS, geo_payload
from risklens.predictor import apply_changes, load_model, portfolio_summary, predict_proba, score_records
from risklens.rules import estimate_disruption_cost
from risklens.validation import OPTIONAL, REQUIRED, validate_dataframe, validate_record

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="RiskLens API", version="3.0.0")


@app.middleware("http")
async def no_cache_static(request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def lane_history() -> dict:
    """Every shipment up to the as-of date, scored by the model, grouped by lane."""
    model, meta = load_model()
    h = datasets.history().copy()
    h["pred"] = (predict_proba(model, frame_to_features(h)) * 100).round(1)
    h["lane"] = h.origin_port + " → " + h.destination_port
    per_lane = {lane: g[["date", "shipment_id", "pred", "disrupted"]].to_dict("records") for lane, g in h.groupby("lane")}
    test_from = meta["test_window"][0]
    return {"per_lane": per_lane, "shipments": h, "test_from": test_from}


def lane_key(r: dict) -> str:
    return f"{r.get('origin_port')} → {r.get('destination_port')}"


def book() -> list[dict]:
    results = score_records(store.list_consignments(), store.load_alternatives())
    per_lane = lane_history()["per_lane"]
    for r in results:
        r["trend"] = [p["pred"] for p in per_lane.get(lane_key(r), [])[-30:]]
    return sorted(results, key=lambda r: -r["risk_score"])


def lane_label(r: dict) -> str:
    return f"{r.get('origin_port') or '?'} → {r.get('destination_port') or '?'}"


# ---------------------------------------------------------------------------
# meta & overview
# ---------------------------------------------------------------------------
@app.get("/api/meta")
def meta():
    _, m = load_model()
    return {
        "company": COMPANY, "as_of": AS_OF.isoformat(), "features": FEATURES,
        "risk_bands": [{"band": b, "min": lo, "max": hi} for b, lo, hi in RISK_BANDS],
        "csv": {"required": REQUIRED, "optional": OPTIONAL},
        "options": {"ports": sorted(PORTS), "modes": MODES, "categories": CATEGORIES, "weather": list(WEATHER_CONDITIONS)},
        "model": {k: m["metrics"][k] for k in ("auc_roc", "avg_precision", "recall", "precision", "base_rate_test")}
                 | {"trained_at": m["trained_at"], "n_train": m["n_train"], "n_test": m["n_test"], "test_window": m["test_window"],
                    "importance": m["importance"]},
        "sources": datasets.sources(),
    }


def _cause(s) -> str:
    parts = [s.weather_condition] if s.weather_condition != "Clear" else []
    if s.geopolitical_risk_index >= 60:
        parts.append(f"geopolitical risk {s.geopolitical_risk_index / 10:.1f}")
    if s.reliability_score < 0.65:
        parts.append(f"carrier reliability {s.reliability_score:.2f}")
    text = " · ".join(parts) or "no single stand-out signal"
    return text[0].upper() + text[1:]


@app.get("/api/overview")
def overview():
    results = book()
    hist = lane_history()
    lanes = {lane_key(r): r for r in results}
    ships = hist["shipments"]
    elevated = RISK_BANDS[1][1]
    test = ships[ships.date >= hist["test_from"]]
    dis = test[(test.disrupted == 1) & test.lane.isin(lanes)].sort_values("date", ascending=False).head(8)
    recent = []
    for s in dis.itertuples():
        units, unit_value = datasets.estimate_value(s.product_category, s.weight_t)
        recent.append({"date": s.date, "lane": s.lane, "consignment_id": lanes[s.lane]["consignment_id"], "shipment_id": s.shipment_id,
                       "mode": s.mode, "disruption_reason": _cause(s), "risk_score": float(s.pred),
                       "recovery_cost_usd": estimate_disruption_cost(units * unit_value, s.mode),
                       "flagged_in_advance": bool(s.pred >= elevated)})
    caught = test[test.disrupted == 1]
    actions = []
    sent, deployed = notify.latest_by_action(), workflow.latest_by_action()
    for r in results:
        for rec in r["recommendations"]:
            if rec["id"] != "maintain":
                k = f"{r['consignment_id']}|{rec['id']}"
                actions.append({**rec, "consignment_id": r["consignment_id"], "lane": lane_label(r),
                                "risk_score": r["risk_score"], "risk_band": r["risk_band"], "executed": rec["id"] in (r.get("executed_actions") or []),
                                "impact": notify.impact(rec, r), "notified": sent.get(k), "deployed": deployed.get(k),
                                "affected": [{"role": w["role"], "name": w["name"]} for w in notify.draft(rec, r, {**r, **r["inputs"]})["recipients"]]})
    actions.sort(key=lambda a: -a["net_benefit_usd"])
    return {
        "summary": portfolio_summary(results), "consignments": results,
        "recent_disruptions": recent,
        "catch_rate": round(float((caught.pred >= elevated).mean() * 100), 1) if len(caught) else None,
        "catch_window": [hist["test_from"], AS_OF.isoformat()], "catch_n": int(len(caught)),
        "lane_disruptions": int(len(dis)), "top_actions": actions[:6], "n_actions": len(actions),
        "workflows_done": len(deployed),
        "geo": geo_payload(results), "gpr_global": datasets.gpr_global(), "sources": datasets.sources(),
    }


# ---------------------------------------------------------------------------
# consignment book (editable)
# ---------------------------------------------------------------------------
@app.get("/api/consignments")
def consignments():
    return book()


@app.get("/api/consignments/{cid}")
def consignment(cid: str):
    rec = store.get_consignment(cid)
    if not rec:
        raise HTTPException(404, "Consignment not found")
    result = score_records([rec], store.load_alternatives())[0]
    result["history"] = lane_history()["per_lane"].get(lane_key(rec), [])
    result["record"] = rec
    return result


def _validated(body: dict) -> dict:
    rec, errors = validate_record(body)
    if errors:
        raise HTTPException(422, {"errors": errors})
    return rec


@app.post("/api/consignments", status_code=201)
def create_consignment(body: dict):
    # The server assigns the consignment ID, so validate with a placeholder.
    rec = _validated({**body, "consignment_id": "NEW"})
    rec.pop("consignment_id")
    saved = store.upsert_consignment(rec)
    return score_records([saved], store.load_alternatives())[0]


@app.put("/api/consignments/{cid}")
def update_consignment(cid: str, body: dict):
    existing = store.get_consignment(cid)
    if not existing:
        raise HTTPException(404, "Consignment not found")
    rec = _validated({**body, "consignment_id": cid})
    rec.setdefault("supplier_id", existing.get("supplier_id"))
    saved = store.upsert_consignment(rec)
    return score_records([saved], store.load_alternatives())[0]


@app.get("/api/consignments/{cid}/cargo")
def consignment_cargo(cid: str):
    rec = store.get_consignment(cid)
    if not rec:
        raise HTTPException(404, "Consignment not found")
    r = score_records([rec], with_alternatives=False)[0]
    return {"consignment": {k: r[k] for k in ("consignment_id", "cargo", "supplier_name", "product_category", "mode", "carrier",
                                            "origin_port", "origin_country", "destination_port", "destination_country",
                                            "journey", "risk_score", "risk_band")},
            "profile": cargo_profile(rec)}


# ---------------------------------------------------------------------------
# warehouse notifications (demo: logged, not delivered)
# ---------------------------------------------------------------------------
def _action_for(cid: str, action_id: str):
    rec = store.get_consignment(cid)
    if not rec:
        raise HTTPException(404, "Consignment not found")
    result = score_records([rec], with_alternatives=False)[0]
    action = next((a for a in result["recommendations"] if a["id"] == action_id and a["id"] != "maintain"), None)
    if not action:
        raise HTTPException(404, "This action is not recommended for the consignment")
    return rec, result, action


@app.get("/api/actions/{cid}/{action_id}/draft")
def notification_draft(cid: str, action_id: str):
    rec, result, action = _action_for(cid, action_id)
    return {"consignment_id": cid, "action_id": action_id, "action": action["action"], **notify.draft(action, result, rec)}


@app.post("/api/notifications", status_code=201)
def send_notification(body: dict):
    cid, action_id = body.get("consignment_id"), body.get("action_id")
    if not cid or not action_id:
        raise HTTPException(422, "consignment_id and action_id are required")
    rec, result, action = _action_for(cid, action_id)
    d = notify.draft(action, result, rec)
    keys = body.get("recipients") or [r["key"] for r in d["recipients"]]
    recipients = [r for r in d["recipients"] if r["key"] in keys]
    if not recipients:
        raise HTTPException(422, "Choose at least one warehouse")
    subject = str(body.get("subject") or d["subject"]).strip()[:300]
    text = str(body.get("body") or d["body"]).strip()[:5000]
    return notify.record({"consignment_id": cid, "action_id": action_id, "action": action["action"], "lane": lane_label(rec),
                          "recipients": [{k: r[k] for k in ("key", "role", "name", "location", "contact", "email", "task")} for r in recipients],
                          "subject": subject, "body": text})


@app.get("/api/notifications")
def notifications():
    return notify.list_notifications()


# ---------------------------------------------------------------------------
# intelligent workflow (agent-to-agent exchange that deploys an action)
# ---------------------------------------------------------------------------
@app.get("/api/workflows")
def workflows():
    return workflow.list_workflows()


@app.get("/api/workflows/{wid}")
def workflow_detail(wid: str):
    w = workflow.get(wid)
    if not w:
        raise HTTPException(404, "Workflow not found")
    return w


@app.post("/api/workflows", status_code=201)
def start_workflow(body: dict):
    cid, action_id = body.get("consignment_id"), body.get("action_id")
    if not cid or not action_id:
        raise HTTPException(422, "consignment_id and action_id are required")
    rec = store.get_consignment(cid)
    if not rec:
        raise HTTPException(404, "Consignment not found")
    result = score_records([rec], store.load_alternatives())[0]
    action = next((a for a in result["recommendations"] if a["id"] == action_id and a["id"] != "maintain"), None)
    if not action:
        raise HTTPException(404, "This action is not recommended for the consignment")
    sent = notify.latest_by_action().get(f"{cid}|{action_id}")
    return workflow.create(rec, result, action, sent)


@app.post("/api/workflows/{wid}/advance")
def advance_workflow(wid: str):
    w = workflow.get(wid)
    if not w:
        raise HTTPException(404, "Workflow not found")
    if w["status"] == "done":
        return w
    rec = store.get_consignment(w["consignment_id"])
    if not rec:
        raise HTTPException(404, "Consignment not found")
    result = score_records([rec], store.load_alternatives())[0]
    action = next((a for a in result["recommendations"] if a["id"] == w["action_id"]), None)
    if not action:
        raise HTTPException(409, "The action is no longer recommended for this consignment")
    w = workflow.advance(wid, rec, result, action, store.upsert_consignment)
    return w


@app.post("/api/consignments/{cid}/apply/{alt_id}")
def apply_alternative(cid: str, alt_id: str):
    rec = store.get_consignment(cid)
    if not rec:
        raise HTTPException(404, "Consignment not found")
    scored = score_records([rec], store.load_alternatives())[0]
    alt = next((a for a in scored["alternatives"] if a["id"] == alt_id), None)
    if not alt:
        raise HTTPException(404, "Alternative not found")
    new, _ = apply_changes(rec, alt["changes"])
    if new.get("eta_date") and alt["eta_delta_days"]:
        new["eta_date"] = (pd.Timestamp(new["eta_date"]) + pd.Timedelta(days=alt["eta_delta_days"])).date().isoformat()
    new["applied_alternative"] = alt_id
    saved = store.upsert_consignment(new)
    return score_records([saved], store.load_alternatives())[0]


@app.delete("/api/consignments/{cid}")
def remove_consignment(cid: str):
    if not store.delete_consignment(cid):
        raise HTTPException(404, "Consignment not found")
    return {"deleted": cid}


@app.post("/api/consignments/reset")
def reset_consignments():
    store.reset()
    notify.clear()
    workflow.clear()
    return {"count": len(store.list_consignments())}


@app.post("/api/consignments/import")
def import_consignments(body: dict):
    """Add already-validated records (from a CSV analysis) to the book."""
    added = 0
    for raw in body.get("records", []):
        rec, errors = validate_record(raw)
        if not errors:
            if store.get_consignment(rec.get("consignment_id", "")) is None:
                store.upsert_consignment(rec)
                added += 1
    return {"added": added}


# ---------------------------------------------------------------------------
# scoring (what-if)
# ---------------------------------------------------------------------------
@app.post("/api/score")
def score(body: dict):
    return score_records([_validated(body)], store.load_alternatives())[0]


@app.post("/api/score/csv")
async def score_csv(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith((".csv", ".txt")):
        raise HTTPException(400, "Please upload a .csv file")
    raw = await file.read()
    if len(raw) > 5_000_000:
        raise HTTPException(413, "File too large (limit 5 MB)")
    try:
        df = pd.read_csv(io.BytesIO(raw), sep=None, engine="python")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Could not parse CSV: {e}") from e
    v = validate_dataframe(df)
    results = score_records(v["records"], store.load_alternatives()) if v["records"] else []
    outcome = None
    actual = [(r["risk_score"], rec["_actual"]) for r, rec in zip(results, v["records"]) if "_actual" in rec]
    if actual:
        threshold = load_model()[1]["metrics"]["decision_threshold"] * 100
        hits = sum(1 for sc, a in actual if (sc >= threshold) == bool(a))
        dis = [sc for sc, a in actual if a]
        outcome = {"rows": len(actual), "agreement": round(hits / len(actual), 3),
                   "caught": round(sum(1 for sc in dis if sc >= RISK_BANDS[1][1]) / len(dis), 3) if dis else None,
                   "disrupted": len(dis)}
    for rec in v["records"]:
        rec.pop("_actual", None)
    return {"outcome": outcome,
        "filename": file.filename, "rows_total": int(len(df)), "rows_scored": len(results),
        "errors": v["errors"], "warnings": v["warnings"], "columns": v["columns"],
        "results": sorted(results, key=lambda r: -r["risk_score"]),
        "records": v["records"], "summary": portfolio_summary(results) if results else None,
    }


@app.get("/api/template.csv")
def template():
    """Five real test-window shipments in the Kaggle file's own layout, so the template doubles as a sample."""
    h = datasets.load()["shipments"]
    rows = h[h.date >= lane_history()["test_from"]].iloc[[3, 120, 480, 800, 1150]]
    out = pd.DataFrame({
        "Shipment_ID": rows.shipment_id, "Date": rows.date, "Origin_Port": rows.origin_port, "Destination_Port": rows.destination_port,
        "Transport_Mode": rows["mode"], "Product_Category": rows.product_category, "Distance_km": rows.distance_km,
        "Weight_MT": rows.weight_t, "Fuel_Price_Index": rows.fuel_price_index,
        "Geopolitical_Risk_Score": (rows.geopolitical_risk_index / 10).round(1), "Weather_Condition": rows.weather_condition,
        "Carrier_Reliability_Score": rows.reliability_score,
    }).to_csv(index=False)
    return PlainTextResponse(out, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=risklens_shipments_template.csv"})


def _journey_text(j: dict) -> str:
    if not j:
        return "Dates not set"
    if j["status"] == "In transit":
        return f"In transit · day {j['elapsed_days']} of {j['total_days']}"
    return f"Departs {j['dispatch_date']}" if j["status"] == "Scheduled" else "Arrived"


def _trend_direction(t: list[float]) -> str:
    if len(t) < 6:
        return "Not enough history"
    early, late = sum(t[:10]) / len(t[:10]), sum(t[-10:]) / len(t[-10:])
    return "Rising" if late - early > 5 else ("Falling" if early - late > 5 else "Steady")


@app.get("/api/export.csv")
def export_csv():
    """The consignment board as a CSV. Input columns use the Kaggle names, so the file uploads straight back into What-if."""
    rows = []
    for r in book():
        j, i, t, best = r["journey"] or {}, r["inputs"], r.get("trend") or [], r.get("best_alternative")
        acts = [x["action"] for x in r["recommendations"] if x["id"] != "maintain"]
        rows.append({
            # inputs, in the Kaggle shipment layout
            "Shipment_ID": r["consignment_id"], "Cargo": r["cargo"], "Product_Category": r["product_category"], "Supplier": r["supplier_name"],
            "Origin_Port": r["origin_port"], "Origin_Country": r["origin_country"], "Destination_Port": r["destination_port"],
            "Destination_Country": r["destination_country"], "Transport_Mode": r["mode"], "Weight_MT": i.get("weight_t"),
            "Distance_km": i.get("distance_km"), "Fuel_Price_Index": i.get("fuel_price_index"),
            "Geopolitical_Risk_Score": round(float(i.get("geopolitical_risk_index") or 0) / 10, 1), "Weather_Condition": i.get("weather_condition"),
            "Carrier_Reliability_Score": i.get("reliability_score"), "Dispatch_Date": j.get("dispatch_date"), "ETA_Date": j.get("eta_date"),
            # the board
            "Route": f"{r['origin_port']} → {r['destination_port']}",
            "Journey_Status": j.get("status"), "Journey": _journey_text(j),
            "Journey_Progress_Pct": round(100 * j.get("progress", 0)), "Days_To_ETA": j.get("days_to_eta"),
            "Trend_30d": " ".join(f"{v:.0f}" for v in t), "Trend_Direction": _trend_direction(t),
            "Trend_Min": round(min(t)) if t else None, "Trend_Max": round(max(t)) if t else None,
            "Trend_Avg": round(sum(t) / len(t)) if t else None,
            "Risk_Score": r["risk_score"], "Risk_Level": r["risk_band"].title(),
            "Top_Driver": r["top_driver"]["label"] if r["top_driver"] else "",
            "Cargo_Value_USD": r["cargo_value_usd"], "Expected_Loss_USD": r["expected_loss_usd"],
            "Best_Alternative": best["title"] if best else ("Stay on current plan" if r["risk_band"] == "low" else "No cheaper option than the mitigations"),
            "Alternative_Risk_Score": best["risk_score"] if best else None,
            "Alternative_Risk_Level": best["risk_band"].title() if best else None,
            "Alternative_Net_Benefit_USD": best["net_benefit_usd"] if best else None,
            "Alternative_ETA_Change_Days": best["eta_delta_days"] if best else None,
            "Recommended_Actions": " | ".join(acts) if acts else "Stay on the current plan",
        })
    out = pd.DataFrame(rows).to_csv(index=False)
    return Response(out, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=risklens_consignments.csv"})


# ---------------------------------------------------------------------------
# static portal
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
