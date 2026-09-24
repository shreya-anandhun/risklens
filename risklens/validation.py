"""Record / CSV validation for the portal. Tolerant of column naming, strict
about values; bad rows are reported with row number, field and reason while
good rows still get scored."""
from __future__ import annotations

import re
from datetime import date

import pandas as pd

# A row needs an identifier (consignment_id or supplier_name) plus these.
REQUIRED = ["lead_time_days", "reliability_score", "geopolitical_risk_index", "weather_risk_level"]
ID_FIELDS = ["consignment_id", "supplier_name"]
TEXT_FIELDS = [
    "consignment_id", "supplier_id", "supplier_name", "cargo", "product_category", "mode", "carrier",
    "origin_port", "origin_country", "region", "destination_port", "destination_country",
    "destination_region", "route_via", "contract_type", "applied_alternative",
]
DATE_FIELDS = ["dispatch_date", "eta_date"]
NUMERIC_RANGES = {
    "lead_time_days": (1, 365), "lead_time_std_days": (0, 365), "reliability_score": (0, 1),
    "geopolitical_risk_index": (0, 100), "port_congestion_index": (0, 100), "weather_risk_index": (0, 100),
    "price_swing_pct": (0, 100), "days_since_last_disruption": (0, 100_000),
    "average_cost_per_unit": (0, 1_000_000), "annual_volume_units": (0, 1_000_000_000),
    "units": (0, 1_000_000_000),
}
OPTIONAL = [c for c in TEXT_FIELDS + DATE_FIELDS + list(NUMERIC_RANGES) + ["single_source"] if c not in REQUIRED]
ALIASES = {
    "consignment": "consignment_id", "shipment": "consignment_id", "shipment_id": "consignment_id", "id": "consignment_id",
    "supplier": "supplier_name", "shipper": "supplier_name", "vendor": "supplier_name",
    "from": "origin_port", "origin": "origin_port", "to": "destination_port", "destination": "destination_port",
    "origin_region": "region", "lead_time": "lead_time_days", "leadtime": "lead_time_days",
    "reliability": "reliability_score", "on_time_rate": "reliability_score", "otd": "reliability_score",
    "geopolitical_risk": "geopolitical_risk_index", "geo_risk": "geopolitical_risk_index", "geopolitical": "geopolitical_risk_index",
    "weather_risk": "weather_risk_level", "weather": "weather_risk_level",
    "price_volatility": "price_swing_pct", "price_swing": "price_swing_pct",
    "category": "product_category", "cost_per_unit": "average_cost_per_unit", "unit_cost": "average_cost_per_unit",
    "unit_value": "average_cost_per_unit", "quantity": "units", "qty": "units",
    "volume": "annual_volume_units", "annual_volume": "annual_volume_units",
    "days_since_disruption": "days_since_last_disruption", "port_congestion": "port_congestion_index",
    "dispatch": "dispatch_date", "departure_date": "dispatch_date", "eta": "eta_date",
}
WEATHER = {"low", "medium", "high"}


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
    missing = [c for c in REQUIRED if c not in df.columns]
    if not any(c in df.columns for c in ID_FIELDS):
        missing = ["consignment_id"] + missing
    if missing:
        return {"records": [], "errors": [{"row": None, "field": ",".join(missing),
                "message": f"Missing required column(s): {', '.join(missing)}. Download the template for the expected layout."}],
                "warnings": [], "columns": {"found": list(df.columns), "missing": missing}}
    if df.empty:
        return {"records": [], "errors": [{"row": None, "field": None, "message": "The file has a header but no rows."}],
                "warnings": [], "columns": {"found": list(df.columns), "missing": []}}

    warnings = []
    unknown = [c for c in df.columns if c not in REQUIRED + OPTIONAL]
    if unknown:
        warnings.append(f"Ignored unrecognised column(s): {', '.join(unknown)}")
    records, errors = [], []
    for i, row in df.iterrows():
        rec, row_errors = validate_record(row.to_dict())
        for e in row_errors:
            e["row"] = int(i) + 2  # 1-based + header
            errors.append(e)
        if not row_errors:
            records.append(rec)
    return {"records": records, "errors": errors, "warnings": warnings,
            "columns": {"found": list(df.columns), "missing": []}}


def validate_record(raw: dict) -> tuple[dict, list[dict]]:
    errors: list[dict] = []
    rec: dict = {}
    raw = {_norm(k): v for k, v in raw.items()}

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
            errors.append({"field": key, "message": f"{key} must be a date like 2026-10-14 (got '{v}')"})
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

    w = raw.get("weather_risk_level")
    if _blank(w):
        if "weather_risk_index" not in rec:
            errors.append({"field": "weather_risk_level", "message": "weather_risk_level is required (low / medium / high)"})
    else:
        w = str(w).strip().lower()
        if w not in WEATHER:
            errors.append({"field": "weather_risk_level", "message": f"weather_risk_level must be low, medium or high (got '{w}')"})
        else:
            rec["weather_risk_level"] = w

    ss = raw.get("single_source")
    if not _blank(ss):
        rec["single_source"] = 1 if str(ss).strip().lower() in ("1", "1.0", "true", "yes", "y") else 0

    return rec, errors
