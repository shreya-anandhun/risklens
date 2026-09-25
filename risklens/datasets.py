"""The four Kaggle datasets RiskLens is built on.

`build()` turns the raw downloads in data/kaggle (see tools/fetch_datasets.sh)
into small tables in data/processed. The portal only reads the processed files.

  Global Supply Chain Risk & Logistics 2024-2026   5,000 shipments with a disruption label:
                                                   the model's training data and the consignment book
  Geopolitical Risk (GPR) index                    Caldara & Iacoviello's news-based index, daily and
                                                   by country: real-world geopolitical context
  DataCo Smart Supply Chain                        180,519 order lines with scheduled vs actual
                                                   shipping days: on-time benchmarks
  Supply chain master data                         100 suppliers and 2,000 purchase orders:
                                                   supplier on-time rates
"""
from __future__ import annotations

import json
import zlib
from functools import lru_cache

import numpy as np
import pandas as pd

from .config import AS_OF, CATEGORY_SPECS, DATA_KAGGLE, DATA_PROCESSED, WEATHER_CONDITIONS

RAW = {
    "shipments": DATA_KAGGLE / "global-supply-chain-risk-and-logistics-2024-2026" / "global_supply_chain_risk_2026.csv",
    "gpr_daily": DATA_KAGGLE / "geopolitical-risk-datasets" / "data_gpr_daily_recent_.csv",
    "gpr_monthly": DATA_KAGGLE / "geopolitical-risk-datasets" / "data_gpr_export.csv",
    "dataco": DATA_KAGGLE / "dataco-smart-supply-chain-for-big-data-analysis" / "DataCoSupplyChainDataset.csv",
    "suppliers": DATA_KAGGLE / "supply-chain-datasets" / "supplier_master.csv",
    "purchase_orders": DATA_KAGGLE / "supply-chain-datasets" / "procurement_orders.csv",
}
OUT = {
    "shipments": DATA_PROCESSED / "shipments.csv",
    "gpr_country": DATA_PROCESSED / "gpr_country.csv",
    "gpr_daily": DATA_PROCESSED / "gpr_daily.csv",
    "suppliers": DATA_PROCESSED / "suppliers.csv",
    "benchmarks": DATA_PROCESSED / "benchmarks.json",
}

# Ports in the shipment data: country, region, and the country the GPR index covers for it.
# The GPR index has no series for Singapore or the UAE, so their nearest covered neighbour stands in.
PORT_INFO = {
    "Busan": ("South Korea", "East Asia", "KOR"),
    "Shanghai": ("China", "East Asia", "CHN"),
    "Singapore": ("Singapore", "Southeast Asia", "MYS"),
    "Dubai": ("United Arab Emirates", "Middle East", "SAU"),
    "Rotterdam": ("Netherlands", "Europe", "NLD"),
    "Antwerp": ("Belgium", "Europe", "BEL"),
    "Hamburg": ("Germany", "Europe", "DEU"),
    "Marseille": ("France", "Europe", "FRA"),
    "Los Angeles": ("United States", "North America", "USA"),
}
GPR_NAMES = {
    "KOR": "South Korea", "CHN": "China", "MYS": "Malaysia", "SAU": "Saudi Arabia", "NLD": "Netherlands",
    "BEL": "Belgium", "DEU": "Germany", "FRA": "France", "USA": "United States", "EGY": "Egypt",
    "TWN": "Taiwan", "GBR": "United Kingdom", "ESP": "Spain", "IDN": "Indonesia", "ISR": "Israel", "TUR": "Turkey",
}
# Supplier countries in the master data, matched to shipment origin countries where they exist.
SUPPLIER_COUNTRY = {"China": "China", "United States": "USA", "Germany": "Germany"}


# ---------------------------------------------------------------------------
# Build (offline)
# ---------------------------------------------------------------------------
def _shipments() -> pd.DataFrame:
    g = pd.read_csv(RAW["shipments"])
    df = pd.DataFrame({
        "shipment_id": g.Shipment_ID,
        "date": pd.to_datetime(g.Date).dt.date.astype(str),
        "origin_port": g.Origin_Port, "destination_port": g.Destination_Port,
        "mode": g.Transport_Mode, "product_category": g.Product_Category,
        "distance_km": g.Distance_km.round(1), "weight_t": g.Weight_MT.round(2),
        "fuel_price_index": g.Fuel_Price_Index.round(2),
        "geopolitical_risk_index": (g.Geopolitical_Risk_Score * 10).round(1),
        "weather_condition": g.Weather_Condition,
        "weather_risk_index": g.Weather_Condition.map(WEATHER_CONDITIONS).astype(float),
        "reliability_score": g.Carrier_Reliability_Score.round(3),
        "lead_time_days": g.Lead_Time_Days.round(2),
        "disrupted": g.Disruption_Occurred.astype(int),
    })
    df["origin_country"] = df.origin_port.map(lambda p: PORT_INFO[p][0])
    df["destination_country"] = df.destination_port.map(lambda p: PORT_INFO[p][0])
    return df.sort_values(["date", "shipment_id"]).reset_index(drop=True)


def _gpr() -> tuple[pd.DataFrame, pd.DataFrame]:
    m = pd.read_csv(RAW["gpr_monthly"], encoding="utf-8-sig")
    m["month"] = pd.to_datetime(m["month"], format="%m/%d/%Y", errors="coerce")
    m = m[(m.month >= "2019-01-01") & m.GPR.notna()]
    cols = ["GPR"] + [f"GPRC_{c}" for c in GPR_NAMES]
    monthly = m[["month", *cols]].copy()
    monthly["month"] = monthly.month.dt.strftime("%Y-%m")
    d = pd.read_csv(RAW["gpr_daily"], encoding="utf-8-sig")
    d["day"] = pd.to_datetime(d["DAY"].astype(str), format="%Y%m%d")
    d = d[d.day >= d.day.max() - pd.Timedelta(days=365)].copy()
    for c in ("GPRD", "GPRD_MA7", "GPRD_MA30"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    daily = pd.DataFrame({"day": d.day.dt.date.astype(str), "gprd": d.GPRD.round(1), "ma7": d.GPRD_MA7.round(1),
                          "ma30": d.GPRD_MA30.round(1), "event": d.event.fillna("").str.strip()})
    return monthly.round(3), daily


def _dataco() -> dict:
    d = pd.read_csv(RAW["dataco"], encoding="latin-1", usecols=[
        "Days for shipping (real)", "Days for shipment (scheduled)", "Late_delivery_risk", "Shipping Mode", "Market",
        "order date (DateOrders)", "Order Id"])
    d["delay"] = d["Days for shipping (real)"] - d["Days for shipment (scheduled)"]
    late = d[d.delay > 0]
    dates = pd.to_datetime(d["order date (DateOrders)"])
    by_mode = (d.groupby("Shipping Mode").agg(orders=("delay", "size"), late_share=("Late_delivery_risk", "mean"),
                                              scheduled_days=("Days for shipment (scheduled)", "mean"))
               .round(3).reset_index().rename(columns={"Shipping Mode": "service"}).to_dict("records"))
    return {
        "rows": int(len(d)), "orders": int(d["Order Id"].nunique()),
        "period": [str(dates.min().date()), str(dates.max().date())],
        "late_share": round(float(d.Late_delivery_risk.mean()), 3),
        "mean_delay_days_when_late": round(float(late.delay.mean()), 2),
        "by_service": by_mode,
        "by_market": d.groupby("Market").Late_delivery_risk.mean().round(3).to_dict(),
    }


def _suppliers() -> pd.DataFrame:
    s = pd.read_csv(RAW["suppliers"])
    p = pd.read_csv(RAW["purchase_orders"], parse_dates=["Delivery_Date_Planned", "Delivery_Date_Actual"])
    p["late_days"] = (p.Delivery_Date_Actual - p.Delivery_Date_Planned).dt.days
    po = p.groupby("Supplier_ID").agg(po_count=("PO_ID", "size"), po_on_time=("late_days", lambda x: (x <= 0).mean()),
                                      po_mean_delay_days=("late_days", lambda x: x[x > 0].mean() if (x > 0).any() else 0.0))
    out = s.merge(po, left_on="Supplier_ID", right_index=True, how="left")
    return pd.DataFrame({
        "supplier_id": out.Supplier_ID, "supplier_name": out.Supplier_Name, "country": out.Country, "region": out.Region,
        "on_time_rate": out.On_Time_Delivery_Rate, "certification": out.Certification_Level.fillna(""),
        "preferred": out.Preferred_Supplier_Flag.astype(int), "po_count": out.po_count.fillna(0).astype(int),
        "po_on_time": out.po_on_time.round(3), "po_mean_delay_days": out.po_mean_delay_days.round(2),
    })


def _shipment_benchmarks(s: pd.DataFrame) -> dict:
    ok, bad = s[s.disrupted == 0], s[s.disrupted == 1]
    speed = (ok.distance_km / ok.lead_time_days.clip(lower=0.5)).groupby(ok["mode"]).median()
    extra = (bad.groupby("mode").lead_time_days.median() - ok.groupby("mode").lead_time_days.median()).clip(lower=0.5)
    return {
        "rows": int(len(s)), "period": [s.date.min(), s.date.max()], "disruption_rate": round(float(s.disrupted.mean()), 3),
        "by_weather": s.groupby("weather_condition").disrupted.mean().round(3).to_dict(),
        "planned_km_per_day": speed.round(1).to_dict(),
        "delay_days_when_disrupted": extra.round(1).to_dict(),
        "lanes": int(s.groupby(["origin_port", "destination_port"]).ngroups),
    }


def build() -> dict:
    missing = [str(p) for p in RAW.values() if not p.exists()]
    if missing:
        raise FileNotFoundError("Kaggle files missing. Run tools/fetch_datasets.sh first:\n  " + "\n  ".join(missing))
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    ships = _shipments()
    ships.to_csv(OUT["shipments"], index=False)
    monthly, daily = _gpr()
    monthly.to_csv(OUT["gpr_country"], index=False)
    daily.to_csv(OUT["gpr_daily"], index=False)
    sup = _suppliers()
    sup.to_csv(OUT["suppliers"], index=False)
    bench = {
        "shipments": _shipment_benchmarks(ships),
        "dataco": _dataco(),
        "suppliers": {"rows": int(len(sup)), "purchase_orders": int(sup.po_count.sum()),
                      "mean_on_time_rate": round(float(sup.on_time_rate.mean()), 3),
                      "po_on_time": round(float((sup.po_on_time * sup.po_count).sum() / max(1, sup.po_count.sum())), 3)},
        "gpr": {"monthly_to": monthly.month.max(), "daily_to": daily.day.max(), "countries": len(GPR_NAMES)},
    }
    OUT["benchmarks"].write_text(json.dumps(bench, indent=2))
    load.cache_clear()
    return bench


# ---------------------------------------------------------------------------
# Runtime lookups (processed files only)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def load() -> dict:
    return {
        "shipments": pd.read_csv(OUT["shipments"]),
        "gpr_country": pd.read_csv(OUT["gpr_country"]),
        "gpr_daily": pd.read_csv(OUT["gpr_daily"]).fillna({"event": ""}),
        "suppliers": pd.read_csv(OUT["suppliers"]).fillna({"certification": ""}),
        "benchmarks": json.loads(OUT["benchmarks"].read_text()),
    }


def benchmarks() -> dict:
    return load()["benchmarks"]


def history() -> pd.DataFrame:
    """Shipments dated up to the portal's as-of date."""
    s = load()["shipments"]
    return s[s.date <= AS_OF.isoformat()]


@lru_cache(maxsize=64)
def gpr_country(code: str | None) -> dict | None:
    """Latest monthly GPR reading for one country, against its own 2019-onwards average."""
    col = f"GPRC_{code}"
    m = load()["gpr_country"]
    if not code or col not in m:
        return None
    series = m[["month", col]].dropna()
    if series.empty:
        return None
    last = series.iloc[-1]
    base = float(series[col].mean())
    return {"code": code, "country": GPR_NAMES.get(code, code), "month": last.month, "value": round(float(last[col]), 3),
            "average": round(base, 3), "ratio": round(float(last[col]) / base, 2) if base else None,
            "trend": [round(float(v), 3) for v in series[col].tail(12)]}


def port_gpr(port: str | None) -> dict | None:
    info = PORT_INFO.get(port or "")
    if not info:
        return None
    g = gpr_country(info[2])
    return {**g, "proxy": GPR_NAMES[info[2]] != info[0]} if g else None


@lru_cache(maxsize=1)
def gpr_global() -> dict:
    d = load()["gpr_daily"]
    last = d.iloc[-1]
    events = d[d.event != ""].tail(3)
    year = d.gprd.mean()
    return {"day": last.day, "ma7": float(last.ma7), "ma30": float(last.ma30), "year_average": round(float(year), 1),
            "events": [{"day": r.day, "event": r.event} for r in events.itertuples()]}


def _py(v):
    if isinstance(v, (np.generic,)):
        v = v.item()
    return None if isinstance(v, float) and np.isnan(v) else v


def _pick(key: str, n: int) -> int:
    return zlib.crc32(key.encode()) % n


def supplier_for(rec: dict) -> dict | None:
    sup = load()["suppliers"]
    country = SUPPLIER_COUNTRY.get(rec.get("origin_country") or "")
    pool = sup[sup.country == country] if country else sup
    if pool.empty:
        pool = sup
    row = pool.iloc[_pick(str(rec.get("consignment_id") or rec.get("origin_port") or ""), len(pool))]
    return {k: _py(v) for k, v in row.to_dict().items()}


@lru_cache(maxsize=256)
def lane_stats(origin: str | None, destination: str | None) -> dict | None:
    if not origin or not destination:
        return None
    h = history()
    lane = h[(h.origin_port == origin) & (h.destination_port == destination)]
    if lane.empty:
        return None
    dis = lane[lane.disrupted == 1]
    last = dis.iloc[-1] if len(dis) else None
    return {"shipments": int(len(lane)), "disrupted": int(len(dis)), "disrupted_share": round(float(dis.shape[0] / len(lane)), 3),
            "last_disruption": None if last is None else {"date": last.date, "weather": last.weather_condition,
                                                          "shipment_id": last.shipment_id},
            "first_date": lane.date.min(), "last_date": lane.date.max()}


def estimate_value(category: str | None, weight_t: float | None) -> tuple[int, float]:
    """(units, value per unit) for a load of this category and weight."""
    spec = CATEGORY_SPECS.get(category or "", CATEGORY_SPECS["Electronics"])
    kg = float(weight_t or 0) * 1000
    units = max(1, int(round(kg / spec["kg_per_unit"])))
    return units, round(spec["usd_per_kg"] * spec["kg_per_unit"], 2)


def enrich(rec: dict) -> dict:
    """Context attached to a consignment for display and rules: lane history, real GPR, supplier."""
    out = dict(rec)
    for side in ("origin", "destination"):
        info = PORT_INFO.get(rec.get(f"{side}_port") or "")
        if info:
            out.setdefault(f"{side}_country", info[0])
            out.setdefault("region" if side == "origin" else "destination_region", info[1])
    if out.get("weight_t") and not out.get("units"):
        out["units"], out["average_cost_per_unit"] = estimate_value(out.get("product_category"), out["weight_t"])
    return out


def context(rec: dict) -> dict:
    gprs = [g for g in (port_gpr(rec.get("origin_port")), port_gpr(rec.get("destination_port"))) if g]
    sup = None
    if rec.get("supplier_id"):
        s = load()["suppliers"]
        row = s[s.supplier_id == rec["supplier_id"]]
        sup = row.iloc[0].to_dict() if len(row) else None
    return {
        "lane": lane_stats(rec.get("origin_port"), rec.get("destination_port")),
        "gpr": {"origin": port_gpr(rec.get("origin_port")), "destination": port_gpr(rec.get("destination_port")),
                "max_ratio": max((g["ratio"] or 0 for g in gprs), default=None)},
        "supplier": None if sup is None else {k: _py(v) for k, v in sup.items()},
    }


def sources() -> list[dict]:
    b = benchmarks()
    s, d, sp, g = b["shipments"], b["dataco"], b["suppliers"], b["gpr"]
    return [
        {"name": "Global Supply Chain Risk & Logistics 2024–2026", "kaggle": "nudratabbas/global-supply-chain-risk-and-logistics-2024-2026",
         "rows": s["rows"], "period": s["period"], "used_for": "Model training, the consignment book, lane history"},
        {"name": "Geopolitical Risk (GPR) index", "kaggle": "princehobby/geopolitical-risk-datasets",
         "rows": None, "period": ["2019-01", g["monthly_to"]], "used_for": f"Real geopolitical readings for {g['countries']} countries on the routes"},
        {"name": "DataCo Smart Supply Chain", "kaggle": "shashwatwork/dataco-smart-supply-chain-for-big-data-analysis",
         "rows": d["rows"], "period": d["period"], "used_for": "On-time benchmarks by service level"},
        {"name": "Supply chain master data", "kaggle": "ayodejiibrahimlateef/supply-chain-datasets",
         "rows": sp["rows"] + sp["purchase_orders"], "period": None, "used_for": "Supplier on-time rates from purchase orders"},
    ]
