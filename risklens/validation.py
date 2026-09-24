"""CSV / record validation for the portal. Tolerant of column naming, strict
about values; bad rows are reported with row number, field and reason while
good rows still get scored."""
from __future__ import annotations

import re

import pandas as pd

REQUIRED = ["supplier_name", "lead_time_days", "reliability_score", "geopolitical_risk_index", "weather_risk_level"]
OPTIONAL = [
    "supplier_id", "region", "product_category", "lead_time_std_days", "port_congestion_index",
    "weather_risk_index", "price_swing_pct", "days_since_last_disruption", "single_source",
    "average_cost_per_unit", "annual_volume_units",
]
ALIASES = {
    "supplier": "supplier_name", "name": "supplier_name", "vendor": "supplier_name",
    "lead_time": "lead_time_days", "leadtime": "lead_time_days", "lead_time_(days)": "lead_time_days",
    "reliability": "reliability_score", "on_time_rate": "reliability_score", "otd": "reliability_score",
    "geopolitical_risk": "geopolitical_risk_index", "geo_risk": "geopolitical_risk_index", "geopolitical": "geopolitical_risk_index",
    "weather_risk": "weather_risk_level", "weather": "weather_risk_level",
    "price_volatility": "price_swing_pct", "price_swing": "price_swing_pct",
    "category": "product_category", "cost_per_unit": "average_cost_per_unit", "unit_cost": "average_cost_per_unit",
    "volume": "annual_volume_units", "annual_volume": "annual_volume_units",
    "days_since_disruption": "days_since_last_disruption", "port_congestion": "port_congestion_index",
}
WEATHER = {"low", "medium", "high"}
NUMERIC_RANGES = {
    "lead_time_days": (1, 365), "lead_time_std_days": (0, 365), "reliability_score": (0, 1),
    "geopolitical_risk_index": (0, 100), "port_congestion_index": (0, 100), "weather_risk_index": (0, 100),
    "price_swing_pct": (0, 100), "days_since_last_disruption": (0, 100_000),
    "average_cost_per_unit": (0, 1_000_000), "annual_volume_units": (0, 1_000_000_000),
}


def _norm(col: str) -> str:
    c = re.sub(r"[^a-z0-9]+", "_", str(col).strip().lower()).strip("_")
    return ALIASES.get(c, c)


def normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [_norm(c) for c in df.columns]
    return df.loc[:, ~df.columns.duplicated()]


def validate_dataframe(df: pd.DataFrame) -> dict:
    """Returns {'records': [...], 'errors': [...], 'warnings': [...], 'columns': {...}}."""
    df = normalise_columns(df)
    missing = [c for c in REQUIRED if c not in df.columns]
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

    name = raw.get("supplier_name")
    if name is None or (isinstance(name, float) and pd.isna(name)) or not str(name).strip():
        errors.append({"field": "supplier_name", "message": "Supplier name is required"})
    else:
        rec["supplier_name"] = str(name).strip()

    for key in ("supplier_id", "region", "product_category"):
        v = raw.get(key)
        if v is not None and not (isinstance(v, float) and pd.isna(v)) and str(v).strip():
            rec[key] = str(v).strip()

    for key, (lo, hi) in NUMERIC_RANGES.items():
        v = raw.get(key)
        required = key in REQUIRED
        if v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, float) and pd.isna(v)):
            if required:
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
    if w is None or (isinstance(w, float) and pd.isna(w)) or not str(w).strip():
        if "weather_risk_index" not in rec:
            errors.append({"field": "weather_risk_level", "message": "weather_risk_level is required (low / medium / high)"})
    else:
        w = str(w).strip().lower()
        if w not in WEATHER:
            errors.append({"field": "weather_risk_level", "message": f"weather_risk_level must be low, medium or high (got '{w}')"})
        else:
            rec["weather_risk_level"] = w

    ss = raw.get("single_source")
    if ss is not None and not (isinstance(ss, float) and pd.isna(ss)):
        rec["single_source"] = 1 if str(ss).strip().lower() in ("1", "true", "yes", "y") else 0

    return rec, errors
