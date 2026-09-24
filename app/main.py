"""RiskLens client portal API. Serves the single-page portal and JSON endpoints
for one client's consignment book."""
from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from risklens import store
from risklens.geo import geo_payload
from risklens.config import COMPANY, DATA_PROCESSED, DATA_RAW, FEATURE_KEYS, FEATURES, HORIZON_DAYS, RISK_BANDS
from risklens.predictor import apply_changes, load_model, portfolio_summary, score_records
from risklens.validation import OPTIONAL, REQUIRED, validate_dataframe, validate_record

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="RiskLens API", version="2.0.0")


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
    """Score each lane's daily history with the trained model: predicted
    7-day risk alongside the disruptions that actually happened."""
    model, _ = load_model()
    feats = pd.read_csv(DATA_PROCESSED / "supply_chain_features.csv")
    feats["pred"] = model.predict_proba(feats[FEATURE_KEYS])[:, 1] * 100
    per_lane = {
        sid: g[["date", "pred", "disrupted"]].round(1).to_dict("records")
        for sid, g in feats.groupby("supplier_id")
    }
    dis = pd.read_csv(DATA_RAW / "disruptions.csv")
    lookup = feats.set_index(["supplier_id", "date"])["pred"]
    caught = []
    for _, d in dis.iterrows():
        prior = [lookup.get((d.supplier_id, (pd.Timestamp(d.date) - pd.Timedelta(days=k)).date().isoformat())) for k in range(1, HORIZON_DAYS + 1)]
        prior = [p for p in prior if p is not None and not pd.isna(p)]
        caught.append(bool(prior) and max(prior) >= RISK_BANDS[1][1])
    dis["flagged_in_advance"] = caught
    return {"per_lane": per_lane, "disruptions": dis}


def book() -> list[dict]:
    return sorted(score_records(store.list_consignments(), store.load_alternatives()), key=lambda r: -r["risk_score"])


def lane_label(r: dict) -> str:
    return f"{r.get('origin_port') or '?'} → {r.get('destination_port') or '?'}"


# ---------------------------------------------------------------------------
# meta & overview
# ---------------------------------------------------------------------------
@app.get("/api/meta")
def meta():
    _, m = load_model()
    return {
        "company": COMPANY, "horizon_days": HORIZON_DAYS, "features": FEATURES,
        "risk_bands": [{"band": b, "min": lo, "max": hi} for b, lo, hi in RISK_BANDS],
        "csv": {"required": REQUIRED, "optional": OPTIONAL},
        "model": {"auc_roc": m["metrics"]["auc_roc"], "trained_at": m["trained_at"]},
    }


@app.get("/api/overview")
def overview():
    results = book()
    hist = lane_history()
    lanes = {r["supplier_id"]: r for r in results if r.get("supplier_id")}
    for r in results:
        h = hist["per_lane"].get(r.get("supplier_id"), [])
        r["trend"] = [p["pred"] for p in h[-30:]]
    dis = hist["disruptions"]
    dis = dis[dis.supplier_id.isin(lanes)].copy()
    dis["lane"] = dis.supplier_id.map(lambda s: lane_label(lanes[s]))
    dis["consignment_id"] = dis.supplier_id.map(lambda s: lanes[s]["consignment_id"])
    actions = []
    for r in results:
        for rec in r["recommendations"]:
            if rec["id"] != "maintain":
                actions.append({**rec, "consignment_id": r["consignment_id"], "lane": lane_label(r),
                                "risk_score": r["risk_score"], "risk_band": r["risk_band"]})
    actions.sort(key=lambda a: -a["net_benefit_usd"])
    return {
        "summary": portfolio_summary(results), "consignments": results,
        "recent_disruptions": dis.sort_values("date", ascending=False).head(8).to_dict("records"),
        "catch_rate": round(float(dis.flagged_in_advance.mean() * 100), 1) if len(dis) else None,
        "lane_disruptions": int(len(dis)),
        "reasons": dis.disruption_reason.value_counts().to_dict(), "top_actions": actions[:6],
        "n_actions": len(actions), "geo": geo_payload(results),
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
    result["history"] = lane_history()["per_lane"].get(rec.get("supplier_id"), [])
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
    return {
        "filename": file.filename, "rows_total": int(len(df)), "rows_scored": len(results),
        "errors": v["errors"], "warnings": v["warnings"], "columns": v["columns"],
        "results": sorted(results, key=lambda r: -r["risk_score"]),
        "records": v["records"], "summary": portfolio_summary(results) if results else None,
    }


@app.get("/api/template.csv")
def template():
    csv = (
        "consignment_id,cargo,supplier_name,product_category,mode,carrier,origin_port,origin_country,region,"
        "destination_port,destination_country,destination_region,dispatch_date,eta_date,units,average_cost_per_unit,"
        "lead_time_days,lead_time_std_days,reliability_score,geopolitical_risk_index,port_congestion_index,"
        "weather_risk_level,price_swing_pct,days_since_last_disruption,single_source\n"
        "CN-26-1001,Laptop batteries,Shenzhen Boards,Electronics,Sea,Pacific Arc Lines,Shenzhen,China,East Asia,"
        "Hamburg,Germany,Europe,2026-10-06,2026-11-10,12000,85,38,6,0.91,42,55,medium,6.5,40,0\n"
        "CN-26-1002,Cotton yarn,Karachi Cotton,Raw Materials,Sea,Gulfstar Lines,Karachi,Pakistan,South Asia,"
        "Mombasa,Kenya,Africa,2026-10-03,2026-10-24,40000,6.5,39,11,0.70,62,48,high,14.2,9,1\n"
        "CN-26-1003,Auto brake assemblies,Pune Autoparts,Machinery,Road,Interstate Haulage Co.,Pune,India,South Asia,"
        "Chennai,India,South Asia,2026-09-30,2026-10-03,2500,140,6,1,0.95,30,25,low,3.1,,0\n"
    )
    return PlainTextResponse(csv, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=risklens_consignments_template.csv"})


@app.get("/api/export.csv")
def export_csv():
    rows = []
    for r in book():
        j = r["journey"] or {}
        best = r.get("best_alternative")
        rows.append({
            "consignment_id": r["consignment_id"], "cargo": r["cargo"], "shipper": r["supplier_name"],
            "from": f"{r['origin_port']}, {r['origin_country']}", "to": f"{r['destination_port']}, {r['destination_country']}",
            "mode": r["mode"], "carrier": r["carrier"], "dispatch_date": j.get("dispatch_date"), "eta_date": j.get("eta_date"),
            "status": j.get("status"), "cargo_value_usd": r["cargo_value_usd"],
            "risk_score": r["risk_score"], "risk_band": r["risk_band"], "expected_loss_usd": r["expected_loss_usd"],
            **{f"factor_{f['key']}": f["value"] for f in r["factors"]},
            "top_driver": r["top_driver"]["label"] if r["top_driver"] else "",
            "recommended_alternative": best["title"] if best else "Stay on current plan",
            "alternative_net_benefit_usd": best["net_benefit_usd"] if best else 0,
            "mitigations": " | ".join(x["action"] for x in r["recommendations"]),
        })
    out = pd.DataFrame(rows).to_csv(index=False)
    return Response(out, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=risklens_consignments.csv"})


# ---------------------------------------------------------------------------
# static portal
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
