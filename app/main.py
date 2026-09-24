"""RiskLens portal API. Serves the single-page portal and JSON endpoints."""
from __future__ import annotations

import io
import json
from functools import lru_cache

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from risklens import store
from risklens.config import DATA_PROCESSED, DATA_RAW, FEATURE_KEYS, HORIZON_DAYS, RISK_BANDS
from risklens.predictor import load_model, portfolio_summary, score_records
from risklens.rules import rules_catalogue
from risklens.validation import OPTIONAL, REQUIRED, validate_dataframe, validate_record

STATIC = __import__("pathlib").Path(__file__).parent / "static"
app = FastAPI(title="RiskLens API", version="1.0.0")


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
def backtest_timeline() -> dict:
    """Score the historical panel with the trained model to show how the
    predicted risk tracked actual disruptions (per day and per supplier)."""
    model, meta = load_model()
    feats = pd.read_csv(DATA_PROCESSED / "supply_chain_features.csv")
    feats["pred"] = model.predict_proba(feats[FEATURE_KEYS])[:, 1] * 100
    daily = feats.groupby("date").agg(avg_risk=("pred", "mean"), max_risk=("pred", "max"),
                                      disruptions=("disrupted", "sum"), high=("pred", lambda s: int((s >= RISK_BANDS[2][1]).sum()))).reset_index()
    per_supplier = {
        sid: g[["date", "pred", "disrupted", "weather_risk_index", "geopolitical_risk_index"]].round(1).to_dict("records")
        for sid, g in feats.groupby("supplier_id")
    }
    dis = pd.read_csv(DATA_RAW / "disruptions.csv")
    dis = dis.merge(pd.read_csv(DATA_RAW / "suppliers.csv")[["supplier_id", "supplier_name", "region"]], on="supplier_id")
    # Did the model flag it? Look at the predicted risk 1..7 days before each event.
    lookup = feats.set_index(["supplier_id", "date"])["pred"]
    caught = []
    for _, d in dis.iterrows():
        prior = [lookup.get((d.supplier_id, (pd.Timestamp(d.date) - pd.Timedelta(days=k)).date().isoformat())) for k in range(1, HORIZON_DAYS + 1)]
        prior = [p for p in prior if p is not None and not pd.isna(p)]
        caught.append(bool(prior) and max(prior) >= RISK_BANDS[1][1])
    dis["flagged_in_advance"] = caught
    return {
        "daily": daily.round(1).to_dict("records"),
        "per_supplier": per_supplier,
        "disruptions": dis.sort_values("date", ascending=False).to_dict("records"),
        "catch_rate": round(float(sum(caught) / len(caught) * 100), 1) if caught else 0.0,
        "reasons": dis.disruption_reason.value_counts().to_dict(),
    }


def scored_portfolio() -> list[dict]:
    return sorted(score_records(store.list_suppliers()), key=lambda r: -r["risk_score"])


# ---------------------------------------------------------------------------
# meta & overview
# ---------------------------------------------------------------------------
@app.get("/api/meta")
def meta():
    _, m = load_model()
    return {
        "model": m, "rules": rules_catalogue(), "horizon_days": HORIZON_DAYS,
        "risk_bands": [{"band": b, "min": lo, "max": hi} for b, lo, hi in RISK_BANDS],
        "csv": {"required": REQUIRED, "optional": OPTIONAL},
        "data": {
            "suppliers": int(len(pd.read_csv(DATA_RAW / "suppliers.csv"))),
            "signal_rows": int(len(pd.read_csv(DATA_RAW / "external_signals.csv"))),
            "disruptions": int(len(pd.read_csv(DATA_RAW / "disruptions.csv"))),
            "window": m["train_window"][0] + " → " + m["test_window"][1],
        },
    }


@app.get("/api/overview")
def overview():
    results = scored_portfolio()
    bt = backtest_timeline()
    actions = []
    for r in results:
        for rec in r["recommendations"]:
            if rec["id"] != "maintain":
                actions.append({**rec, "supplier_id": r["supplier_id"], "supplier_name": r["supplier_name"],
                                "risk_score": r["risk_score"], "risk_band": r["risk_band"]})
    actions.sort(key=lambda a: (-a["net_benefit_usd"]))
    return {
        "summary": portfolio_summary(results), "suppliers": results, "timeline": bt["daily"],
        "recent_disruptions": bt["disruptions"][:8], "catch_rate": bt["catch_rate"],
        "reasons": bt["reasons"], "top_actions": actions[:8],
    }


# ---------------------------------------------------------------------------
# supplier portfolio (editable)
# ---------------------------------------------------------------------------
@app.get("/api/suppliers")
def suppliers():
    return scored_portfolio()


@app.get("/api/suppliers/{sid}")
def supplier(sid: str):
    rec = store.get_supplier(sid)
    if not rec:
        raise HTTPException(404, "Supplier not found")
    result = score_records([rec])[0]
    result["history"] = backtest_timeline()["per_supplier"].get(sid, [])
    result["record"] = rec
    return result


@app.post("/api/suppliers", status_code=201)
def create_supplier(body: dict):
    rec, errors = validate_record(body)
    if errors:
        raise HTTPException(422, {"errors": errors})
    for k in ("country", "contract_type"):
        if body.get(k):
            rec[k] = body[k]
    saved = store.upsert_supplier(rec)
    return score_records([saved])[0]


@app.put("/api/suppliers/{sid}")
def update_supplier(sid: str, body: dict):
    if not store.get_supplier(sid):
        raise HTTPException(404, "Supplier not found")
    rec, errors = validate_record({**body, "supplier_id": sid})
    if errors:
        raise HTTPException(422, {"errors": errors})
    for k in ("country", "contract_type"):
        if body.get(k):
            rec[k] = body[k]
    saved = store.upsert_supplier(rec)
    return score_records([saved])[0]


@app.delete("/api/suppliers/{sid}")
def remove_supplier(sid: str):
    if not store.delete_supplier(sid):
        raise HTTPException(404, "Supplier not found")
    return {"deleted": sid}


@app.post("/api/suppliers/reset")
def reset_suppliers():
    store.reset()
    return {"count": len(store.list_suppliers())}


@app.post("/api/suppliers/import")
def import_suppliers(body: dict):
    """Add already-validated records (from a CSV analysis) to the portfolio."""
    added = []
    for raw in body.get("records", []):
        rec, errors = validate_record(raw)
        if not errors:
            added.append(store.upsert_supplier(rec))
    return {"added": len(added)}


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------
@app.post("/api/score")
def score(body: dict):
    rec, errors = validate_record(body)
    if errors:
        raise HTTPException(422, {"errors": errors})
    return score_records([rec])[0]


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
    results = score_records(v["records"]) if v["records"] else []
    return {
        "filename": file.filename, "rows_total": int(len(df)), "rows_scored": len(results),
        "errors": v["errors"], "warnings": v["warnings"], "columns": v["columns"],
        "results": sorted(results, key=lambda r: -r["risk_score"]),
        "records": v["records"], "summary": portfolio_summary(results) if results else None,
    }


@app.get("/api/template.csv")
def template():
    csv = (
        "supplier_name,region,product_category,lead_time_days,lead_time_std_days,reliability_score,"
        "geopolitical_risk_index,port_congestion_index,weather_risk_level,price_swing_pct,"
        "days_since_last_disruption,single_source,average_cost_per_unit,annual_volume_units\n"
        "TechParts Asia,East Asia,Electronics,61,9,0.89,45.2,38,low,6.5,120,0,180.50,42000\n"
        "QuickShip Ltd,South Asia,Packaging,84,21,0.73,62.5,71,medium,14.2,9,1,12.00,88000\n"
        "GlobalLogistics Inc,Southeast Asia,Machinery,12,2,0.96,23.1,40,high,3.1,,0,310.00,6000\n"
    )
    return PlainTextResponse(csv, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=risklens_template.csv"})


@app.get("/api/export.csv")
def export_csv():
    rows = []
    for r in scored_portfolio():
        rows.append({
            "supplier_id": r["supplier_id"], "supplier_name": r["supplier_name"], "region": r["region"],
            "product_category": r["product_category"], "risk_score": r["risk_score"], "risk_band": r["risk_band"],
            "flagged": r["flagged"], "composite_index": r["composite_index"], "annual_spend_usd": r["annual_spend_usd"],
            "expected_loss_usd": r["expected_loss_usd"],
            **{f"factor_{f['key']}": f["value"] for f in r["factors"]},
            "top_driver": r["top_driver"]["label"] if r["top_driver"] else "",
            "recommended_actions": " | ".join(x["action"] for x in r["recommendations"]),
        })
    out = pd.DataFrame(rows).to_csv(index=False)
    return Response(out, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=risklens_portfolio.csv"})


# ---------------------------------------------------------------------------
# static portal
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
