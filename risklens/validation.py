"""Record / CSV validation for the portal. Tolerant of column naming, strict
about values; bad rows are reported with row number, field and reason while
good rows still get scored. The Kaggle shipment file's own columns are
understood as-is, so it can be uploaded straight into the What-if page."""
from __future__ import annotations

import re
from datetime import date

import pandas as pd

from .config import WEATHER_CONDITIONS

# A row needs an identifier plus these; weather can come as a condition, an index or a level.
REQUIRED = ["reliability_score", "geopolitical_risk_index"]
WEATHER_FIELDS = ["weather_condition", "weather_risk_index", "weather_risk_level"]
ID_FIELDS = ["consignment_id", "supplier_name"]
TEXT_FIELDS = [
    "consignment_id", "supplier_id", "supplier_name", "cargo", "product_category", "mode", "carrier",
    "origin_port", "origin_country", "region", "destination_port", "destination_country",
    "destination_region", "route_via", "applied_alternative",
]
DATE_FIELDS = ["dispatch_date", "eta_date"]
NUMERIC_RANGES = {
    "reliability_score": (0, 1), "geopolitical_risk_index": (0, 100), "weather_risk_index": (0, 100),
    "fuel_price_index": (0, 10), "distance_km": (0, 25_000), "weight_t": (0, 100_000), "lead_time_days": (0, 400),
    "average_cost_per_unit": (0, 1_000_000), "units": (0, 1_000_000_000),
}
OPTIONAL = [c for c in TEXT_FIELDS + DATE_FIELDS + list(NUMERIC_RANGES) + WEATHER_FIELDS + ["geopolitical_risk_score"] if c not in REQUIRED]
ALIASES = {
    "consignment": "consignment_id", "shipment": "consignment_id", "shipment_id": "consignment_id", "id": "consignment_id",
    "supplier": "supplier_name", "shipper": "supplier_name", "vendor": "supplier_name",
    "from": "origin_port", "origin": "origin_port", "to": "destination_port", "destination": "destination_port",
    "transport_mode": "mode", "shipping_mode": "mode", "category": "product_category",
    "carrier_reliability_score": "reliability_score", "carrier_reliability": "reliability_score",
    "reliability": "reliability_score", "on_time_rate": "reliability_score", "otd": "reliability_score",
    "geopolitical_risk": "geopolitical_risk_index", "geopolitical": "geopolitical_risk_index",
    "weather": "weather_condition", "weather_risk": "weather_risk_level",
    "fuel_price": "fuel_price_index", "fuel": "fuel_price_index",
    "distance": "distance_km", "weight_mt": "weight_t", "weight": "weight_t", "weight_tonnes": "weight_t",
    "lead_time": "lead_time_days", "leadtime": "lead_time_days",
    "cost_per_unit": "average_cost_per_unit", "unit_cost": "average_cost_per_unit", "unit_value": "average_cost_per_unit",
    "quantity": "units", "qty": "units",
    "date": "dispatch_date", "dispatch": "dispatch_date", "departure_date": "dispatch_date", "eta": "eta_date",
}
WEATHER = {"low", "medium", "high"}
CONDITIONS = {c.lower(): c for c in WEATHER_CONDITIONS}
IGNORED = {"disruption_occurred"}   # the outcome, when a file of past shipments is uploaded


def _norm(col: str) -> str:
    c = re.sub(r"[^a-z0-9]+", "_", str(col).strip().lower()).strip("_")
    return ALIASES.get(c, c)


def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and not v.strip())


def normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [_norm(c) for c in df.columns]
    return df.loc[:, ~df.columns.duplicated()]


def validate_dataframe(df: pd.DataFrame) -> dict:
    """Returns {'records': [...], 'errors': [...], 'warnings': [...], 'columns': {...}}."""
    df = normalise_columns(df)
    has_geo = "geopolitical_risk_index" in df.columns or "geopolitical_risk_score" in df.columns
    missing = [c for c in REQUIRED if c not in df.columns and not (c == "geopolitical_risk_index" and has_geo)]
    if not any(c in df.columns for c in ID_FIELDS):
        missing = ["consignment_id"] + missing
    if not any(c in df.columns for c in WEATHER_FIELDS):
        missing.append("weather_condition")
    if missing:
        return {"records": [], "errors": [{"row": None, "field": ",".join(missing),
                "message": f"Missing required column(s): {', '.join(missing)}. Download the template for the expected layout."}],
                "warnings": [], "columns": {"found": list(df.columns), "missing": missing}}
    if df.empty:
        return {"records": [], "errors": [{"row": None, "field": None, "message": "The file has a header but no rows."}],
                "warnings": [], "columns": {"found": list(df.columns), "missing": []}}

    warnings = []
    unknown = [c for c in df.columns if c not in REQUIRED + OPTIONAL and c not in IGNORED]
    if unknown:
        warnings.append(f"Ignored unrecognised column(s): {', '.join(unknown)}")
    records, errors = [], []
    for i, row in df.iterrows():
        rec, row_errors = validate_record(row.to_dict())
        for e in row_errors:
            e["row"] = int(i) + 2  # 1-based + header
            errors.append(e)
        if not row_errors:
            if "disruption_occurred" in df.columns and not _blank(row["disruption_occurred"]):
                rec["_actual"] = int(float(row["disruption_occurred"]))
            records.append(rec)
    return {"records": records, "errors": errors, "warnings": warnings,
            "columns": {"found": list(df.columns), "missing": []}}


def validate_record(raw: dict) -> tuple[dict, list[dict]]:
    errors: list[dict] = []
    rec: dict = {}
    raw = {_norm(k): v for k, v in raw.items()}

    if _blank(raw.get("geopolitical_risk_index")) and not _blank(raw.get("geopolitical_risk_score")):
        try:
            raw["geopolitical_risk_index"] = float(raw["geopolitical_risk_score"]) * 10   # 0-10 score in the Kaggle file
        except (TypeError, ValueError):
            errors.append({"field": "geopolitical_risk_score", "message": f"geopolitical_risk_score must be a number (got '{raw['geopolitical_risk_score']}')"})

    for key in TEXT_FIELDS:
        if not _blank(raw.get(key)):
            rec[key] = str(raw[key]).strip()
    if not any(k in rec for k in ID_FIELDS):
        errors.append({"field": "consignment_id", "message": "A consignment ID or shipper name is required"})

    for key in DATE_FIELDS:
        v = raw.get(key)
        if _blank(v):
            continue
        try:
            rec[key] = date.fromisoformat(str(v).strip()[:10]).isoformat()
        except ValueError:
            errors.append({"field": key, "message": f"{key} must be a date like 2025-12-14 (got '{v}')"})
    if "dispatch_date" in rec and "eta_date" in rec and rec["eta_date"] < rec["dispatch_date"]:
        errors.append({"field": "eta_date", "message": "ETA cannot be before the dispatch date"})

    for key, (lo, hi) in NUMERIC_RANGES.items():
        v = raw.get(key)
        if _blank(v):
            if key in REQUIRED:
                errors.append({"field": key, "message": f"{key} is required"})
            continue
        try:
            x = float(str(v).replace("%", "").replace(",", "").replace("$", ""))
        except ValueError:
            errors.append({"field": key, "message": f"{key} must be a number (got '{v}')"})
            continue
        if key == "reliability_score" and 1 < x <= 100:
            x = x / 100  # accept percentages
        if not (lo <= x <= hi):
            errors.append({"field": key, "message": f"{key} must be between {lo} and {hi} (got {x:g})"})
            continue
        rec[key] = x

    cond = raw.get("weather_condition")
    if not _blank(cond):
        c = CONDITIONS.get(str(cond).strip().lower())
        if not c:
            errors.append({"field": "weather_condition", "message": f"weather_condition must be one of {', '.join(WEATHER_CONDITIONS)} (got '{cond}')"})
        else:
            rec["weather_condition"] = c
    w = raw.get("weather_risk_level")
    if not _blank(w):
        w = str(w).strip().lower()
        if w not in WEATHER:
            errors.append({"field": "weather_risk_level", "message": f"weather_risk_level must be low, medium or high (got '{w}')"})
        else:
            rec["weather_risk_level"] = w
    if not any(k in rec for k in WEATHER_FIELDS) and not any(e["field"] in WEATHER_FIELDS for e in errors):
        errors.append({"field": "weather_condition", "message": f"weather_condition is required ({', '.join(WEATHER_CONDITIONS)})"})

    return rec, errors
