"""Cargo profiles: what each consignment physically is and how it must be carried.

The shipment data gives each consignment's product category, weight and mode.
The profile adds how that category is normally shipped: typical HS code,
dangerous-goods class where one applies, packing, equipment for the mode,
stowage and handling rules. Weights come from the data; units, volume,
packages and equipment counts are derived from the weight. Sensor readings and
document statuses are sample values, since none of the datasets record them.
"""
from __future__ import annotations

import math
import zlib

from .config import CATEGORY_SPECS

# Handling rule icons understood by the portal: dry, temp, fragile, up, nostack, esd,
# hazard, vent, segregate, heavy, sun, moisture, secure, shock, dust, seal
CATEGORIES: dict[str, dict] = {
    "Electronics": {
        "commodity": "Consumer electronics: smartphones, laptops and accessories",
        "about": "Boxed consumer devices with lithium-ion batteries installed. High value per kilo, sensitive to shock, moisture and static, and a frequent target for theft, so the load is sealed and tracked end to end.",
        "hs_code": "8517.13", "hs_desc": "Smartphones and other telephones for cellular networks",
        "unit_label": "boxed device", "m3_per_unit": 0.004, "package_label": "pallet", "units_per_package": 240,
        "packing": "Retail boxes in shock-absorbing master cartons, shrink-wrapped on pallets with anti-static film",
        "temperature": None,
        "hazard": {"code": "9", "label": "Class 9 · Lithium batteries", "un": "UN 3481",
                   "name": "Lithium ion batteries packed with or contained in equipment", "pg": None, "marine_pollutant": False},
        "handling": [
            {"icon": "hazard", "title": "Lithium batteries", "text": "Class 9 dangerous goods: declared, labelled and kept away from heat sources.", "critical": True},
            {"icon": "esd", "title": "Static-sensitive", "text": "Open cartons only in ESD-safe areas.", "critical": False},
            {"icon": "seal", "title": "High-value seal", "text": "Check the seal number at every handover. Report any break at once.", "critical": True},
            {"icon": "dry", "title": "Keep dry", "text": "Keep humidity below 60% to protect circuit boards.", "critical": False},
        ],
        "sensors": [("Relative humidity", "% RH", None, 60, 48, 10), ("Temperature", "°C", 0, 35, 22, 7), ("Shock", "g", None, 4, 1.2, 1.2)],
    },
    "Textiles": {
        "commodity": "Apparel and textiles: cotton knitwear",
        "about": "Folded cotton garments in cartons, destined for retail distribution. Cotton absorbs moisture and can mould or stain if the container sweats, so the load is kept dry with desiccants.",
        "hs_code": "6109.10", "hs_desc": "T-shirts, singlets and other vests of cotton, knitted",
        "unit_label": "garment", "m3_per_unit": 0.0025, "package_label": "carton", "units_per_package": 60,
        "packing": "Poly-bagged garments in export cartons, floor-loaded or palletised",
        "temperature": None, "hazard": None,
        "handling": [
            {"icon": "dry", "title": "Keep dry", "text": "Moisture causes mould and staining. No wet floors or open doors in rain.", "critical": True},
            {"icon": "vent", "title": "Desiccants in", "text": "Hang desiccant strips along the side walls before sealing.", "critical": False},
            {"icon": "sun", "title": "Avoid heat", "text": "Keep out of direct sun on the quay to limit condensation.", "critical": False},
        ],
        "sensors": [("Relative humidity", "% RH", None, 70, 58, 14), ("Temperature", "°C", 0, 40, 24, 8), ("Dew-point margin", "°C", 2, None, 6, 3)],
    },
    "Perishables": {
        "commodity": "Chilled fresh produce",
        "about": "Fresh fruit and vegetables under refrigeration. Shelf life starts falling the moment the cold chain breaks, so temperature is controlled and logged throughout, and delays cost directly in spoilage.",
        "hs_code": "0806.10", "hs_desc": "Grapes, fresh",
        "unit_label": "10 kg case", "m3_per_unit": 0.022, "package_label": "pallet", "units_per_package": 96,
        "packing": "Ventilated cartons on pallets, stacked for airflow with corner posts",
        "temperature": {"min": 0, "max": 4},
        "hazard": None,
        "handling": [
            {"icon": "temp", "title": "Keep at 0–4 °C", "text": "Pre-cool before loading. No gaps in the cold chain at handovers.", "critical": True},
            {"icon": "vent", "title": "Ventilate", "text": "Fresh-air vents open to clear ethylene and CO₂.", "critical": True},
            {"icon": "nostack", "title": "Airflow gaps", "text": "Do not block the T-floor or stack above the red load line.", "critical": False},
        ],
        "sensors": [("Temperature", "°C", 0, 4, 2.1, 1.5), ("Relative humidity", "% RH", 85, 95, 90, 4), ("CO₂", "%", None, 1, 0.4, 0.3)],
    },
    "Pharmaceuticals": {
        "commodity": "Pharmaceutical products, packaged medicines",
        "about": "Finished medicines in retail packs, shipped under Good Distribution Practice. They must stay within a validated temperature range, and every excursion has to be logged and assessed before the stock can be released.",
        "hs_code": "3004.90", "hs_desc": "Medicaments, put up in measured doses or for retail sale",
        "unit_label": "pack", "m3_per_unit": 0.0009, "package_label": "pallet", "units_per_package": 1800,
        "packing": "Insulated shippers on pallets, temperature loggers in each shipper",
        "temperature": {"min": 2, "max": 8},
        "hazard": None,
        "handling": [
            {"icon": "temp", "title": "Keep at 2–8 °C", "text": "Validated cold chain. Any excursion is recorded and assessed before release.", "critical": True},
            {"icon": "seal", "title": "GDP seal", "text": "Tamper-evident seals checked and logged at every handover.", "critical": True},
            {"icon": "up", "title": "This way up", "text": "Keep shippers upright so gel packs stay in place.", "critical": False},
        ],
        "sensors": [("Temperature", "°C", 2, 8, 5.2, 2.2), ("Relative humidity", "% RH", None, 65, 45, 10), ("Light exposure", "lux", None, 50, 8, 8)],
    },
    "Automotive": {
        "commodity": "Automotive parts: engine and chassis components",
        "about": "Machined metal components for vehicle assembly lines. Heavy for their size and prone to corrosion, and the plants they supply run just-in-time, so a late arrival can stop a production line.",
        "hs_code": "8708.99", "hs_desc": "Parts and accessories of motor vehicles",
        "unit_label": "component", "m3_per_unit": 0.012, "package_label": "crate", "units_per_package": 40,
        "packing": "Oiled and wrapped in VCI film, packed in timber crates with ISPM 15 treatment",
        "temperature": None, "hazard": None,
        "handling": [
            {"icon": "heavy", "title": "Heavy cargo", "text": "Spread the weight over the floor; check axle and floor limits.", "critical": True},
            {"icon": "moisture", "title": "Prevent corrosion", "text": "Keep VCI film intact. Reject crates that arrive wet.", "critical": False},
            {"icon": "secure", "title": "Lash and block", "text": "Crates blocked and lashed so nothing shifts under braking or in a swell.", "critical": True},
        ],
        "sensors": [("Relative humidity", "% RH", None, 65, 52, 12), ("Tilt", "°", None, 10, 3, 3), ("Shock", "g", None, 6, 2, 1.8)],
    },
}

EQUIPMENT = {
    "Sea": {"name": "40' dry container", "short": "40' DC", "payload_t": 26.5, "volume_m3": 67.7},
    "Sea_cold": {"name": "40' reefer container", "short": "40' RF", "payload_t": 27.5, "volume_m3": 59.3},
    "Air": {"name": "PMC air cargo pallet", "short": "PMC", "payload_t": 6.8, "volume_m3": 10.8},
    "Air_cold": {"name": "Temperature-controlled air container", "short": "RKN", "payload_t": 1.2, "volume_m3": 3.6},
    "Road": {"name": "Curtain-side semi-trailer", "short": "Trailer", "payload_t": 24.0, "volume_m3": 90.0},
    "Road_cold": {"name": "Refrigerated semi-trailer", "short": "Reefer trailer", "payload_t": 22.0, "volume_m3": 80.0},
    "Rail": {"name": "45' rail container", "short": "45' HC", "payload_t": 28.0, "volume_m3": 85.0},
    "Rail_cold": {"name": "45' rail reefer", "short": "45' RF", "payload_t": 26.0, "volume_m3": 74.0},
}
TRANSPORT_DOC = {"Sea": "Bill of lading", "Air": "Air waybill", "Road": "CMR consignment note", "Rail": "CIM rail consignment note"}


def _jitter(key: str, spread: float) -> float:
    return ((zlib.crc32(key.encode()) % 2001) / 1000 - 1) * spread


def _sensor_status(s: dict) -> str:
    """breach = outside the safe range, watch = within 10% of a limit, ok otherwise."""
    v, lo, hi = s["value"], s.get("min"), s.get("max")
    if (hi is not None and v > hi) or (lo is not None and v < lo):
        return "breach"
    if (hi is not None and hi - v <= 0.1 * max(abs(hi), 1)) or (lo is not None and v - lo <= 0.1 * max(abs(lo), 1)):
        return "watch"
    return "ok"


def profile(rec: dict) -> dict:
    """Cargo profile for one consignment record, with load figures derived from its weight."""
    cat = rec.get("product_category") if rec.get("product_category") in CATEGORIES else "Electronics"
    c = CATEGORIES[cat]
    cid = str(rec.get("consignment_id") or "")
    mode = rec.get("mode") if rec.get("mode") in TRANSPORT_DOC else "Sea"
    eq = EQUIPMENT[f"{mode}_cold" if c["temperature"] else mode]
    kg_per_unit = CATEGORY_SPECS[cat]["kg_per_unit"]
    net_t = float(rec.get("weight_t") or 0) or float(rec.get("units") or 0) * kg_per_unit / 1000
    units = int(round(net_t * 1000 / kg_per_unit)) if net_t else 0
    gross_t = net_t * 1.06            # packaging, pallets and dunnage
    volume = units * c["m3_per_unit"]
    n_eq = max(1, math.ceil(max(gross_t / eq["payload_t"], volume / eq["volume_m3"]))) if units else 0
    by_weight = gross_t / (n_eq * eq["payload_t"]) if n_eq else 0
    by_volume = volume / (n_eq * eq["volume_m3"]) if n_eq else 0
    rough = str(rec.get("weather_condition") or "") in ("Storm", "Hurricane")
    sensors = []
    for name, unit, lo, hi, typical, spread in c["sensors"]:
        v = typical + _jitter(cid + name, spread) + (spread * 0.8 if rough and name in ("Relative humidity", "Shock", "Tilt") else 0)
        s = {"name": name, "unit": unit, "value": round(v, 1), "min": lo, "max": hi}
        sensors.append({**s, "status": _sensor_status(s)})
    docs = ["Commercial invoice", "Packing list", "Certificate of origin", TRANSPORT_DOC[mode]]
    if c["hazard"]:
        docs.append("Dangerous goods declaration")
    if c["temperature"]:
        docs.append("Temperature log")
    value = units * float(rec.get("average_cost_per_unit") or 0) if rec.get("average_cost_per_unit") else net_t * 1000 * CATEGORY_SPECS[cat]["usd_per_kg"]
    documents = [{"name": d, "status": "pending" if zlib.crc32((cid + d).encode()) % 4 == 0 else "ready"} for d in docs]
    dest = rec.get("destination_port") or "destination"
    return {
        **{k: v for k, v in c.items() if k != "sensors"},
        "kg_per_unit": kg_per_unit, "equipment": eq,
        "stowage": "Reefer plugged in and monitored; under deck, away from heat" if c["temperature"] and mode == "Sea"
                   else ("Segregated per IMDG class 9; away from heat sources" if c["hazard"] else "Standard stowage, weight spread evenly"),
        "securing": "Blocked and braced; airbags in voids" if mode in ("Sea", "Rail") else ("Netted and strapped to the pallet base" if mode == "Air" else "Load-locking bars and straps every row"),
        "sensors": sensors, "sensor_note": "Sample readings. None of the datasets record sensor data.",
        "documents": documents, "documents_ready": sum(1 for d in documents if d["status"] == "ready"),
        "incoterm": f"CIF {dest}" if mode == "Sea" else f"CPT {dest}", "insurance": "Institute Cargo Clauses (A)", "consignee": None,
        "generic": False,
        "load": {
            "units": units, "net_t": round(net_t, 1), "gross_t": round(gross_t, 1), "volume_m3": round(volume, 1),
            "packages": math.ceil(units / c["units_per_package"]) if units else 0, "equipment_count": n_eq,
            "fill_weight": round(min(1, by_weight), 3), "fill_volume": round(min(1, by_volume), 3),
            "limited_by": "weight" if by_weight >= by_volume else "volume",
        },
        "value_usd": round(value, 0), "insured_value_usd": round(value * 1.1, 0),
    }
