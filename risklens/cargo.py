"""Cargo profiles: what each consignment physically is and how it must be carried.

All figures are dummy data for the demo. Commodity codes, IMDG/IMSBC classes and
handling rules reflect how these goods are normally shipped, so the profiles read
realistically, but the readings and document statuses are invented.

Weights, volumes, package and container counts are derived from the
consignment's current unit count, so they stay consistent if the record changes.
"""
from __future__ import annotations

import math

# Handling rule icons understood by the portal: dry, temp, fragile, up, nostack, esd,
# hazard, vent, segregate, heavy, sun, moisture, secure, shock, dust, seal
PROFILES: dict[str, dict] = {
    "CN-26-0911": {
        "commodity": "Corrugated fibreboard export cartons, flat-packed",
        "about": "Double-wall corrugated boxes supplied flat to a UK packing centre, where they are erected and used to ship consumer goods. Corrugated board takes up moisture from the air and loses much of its stacking strength when damp, so the load must stay dry end to end.",
        "hs_code": "4819.10", "hs_desc": "Cartons, boxes and cases of corrugated paper or paperboard",
        "unit_label": "flat carton", "kg_per_unit": 0.42, "m3_per_unit": 0.0017,
        "package_label": "pallet", "units_per_package": 1300,
        "packing": "Banded in bundles of 25, stretch-wrapped on ISPM 15 heat-treated pallets with corner boards",
        "equipment": {"name": "40' High Cube dry container", "short": "40' HC", "payload_t": 26.5, "volume_m3": 76.3},
        "stowage": "Under deck, away from engine-room bulkheads to limit condensation (container sweat)",
        "securing": "Pallets blocked and braced; desiccant strips hung along the side walls",
        "hazard": None,
        "handling": [
            {"icon": "dry", "title": "Keep dry", "text": "Board strength drops sharply above 70% relative humidity. No wet pallets or open doors in rain.", "critical": True},
            {"icon": "nostack", "title": "Stack limit 2 high", "text": "Do not double-stack pallets beyond two tiers or crush the edges.", "critical": False},
            {"icon": "vent", "title": "Desiccants in", "text": "Replace desiccant strips if the container is re-opened for inspection.", "critical": False},
        ],
        "sensors": [
            {"name": "Relative humidity", "unit": "% RH", "value": 64, "min": None, "max": 70},
            {"name": "Temperature", "unit": "°C", "value": 31, "min": 0, "max": 40},
            {"name": "Shock", "unit": "g", "value": 0.8, "min": None, "max": 5},
        ],
        "documents": [
            {"name": "Commercial invoice", "status": "ready"}, {"name": "Packing list", "status": "ready"},
            {"name": "Certificate of origin", "status": "ready"}, {"name": "ISPM 15 pallet declaration", "status": "ready"},
            {"name": "Bill of lading", "status": "pending"},
        ],
        "incoterm": "FOB Chittagong", "insurance": "Institute Cargo Clauses (A)", "consignee": "Northwind UK Packing Centre, Ipswich",
    },
    "CN-26-0914": {
        "commodity": "Crop-protection chemicals, liquid formulation",
        "about": "A liquid insecticide concentrate in 10-litre jerrycans, bound for distributors in the Gulf. It is toxic and a marine pollutant, so it travels as dangerous goods and must be kept away from food and animal feed.",
        "hs_code": "3808.91", "hs_desc": "Insecticides, put up for retail sale or as preparations",
        "unit_label": "10 L jerrycan", "kg_per_unit": 11.5, "m3_per_unit": 0.0145,
        "package_label": "pallet", "units_per_package": 96,
        "packing": "UN-approved HDPE jerrycans, 4 per fibreboard box, 24 boxes per pallet, shrink-hooded",
        "equipment": {"name": "20' dry container, DG placarded", "short": "20' DG", "payload_t": 21.7, "volume_m3": 33.2},
        "stowage": "Deck or under deck per IMDG segregation, away from living quarters and heat sources",
        "securing": "Pallets strapped to lashing rings; absorbent pads under each pallet",
        "hazard": {"code": "6.1", "label": "IMDG Class 6.1 · Toxic", "un": "UN 2902", "name": "Pesticide, liquid, toxic, n.o.s.", "pg": "III", "marine_pollutant": True},
        "handling": [
            {"icon": "hazard", "title": "Dangerous goods", "text": "Placard all four sides. Only DG-trained staff handle damaged packages.", "critical": True},
            {"icon": "segregate", "title": "Away from foodstuffs", "text": "Segregate from food, feed and Class 8 corrosives in the terminal and on board.", "critical": True},
            {"icon": "up", "title": "This way up", "text": "Jerrycans must stay upright to keep caps sealed.", "critical": False},
            {"icon": "temp", "title": "5 to 35 °C", "text": "Avoid direct sun at the terminal. High heat builds pressure in the cans.", "critical": False},
        ],
        "sensors": [
            {"name": "Temperature", "unit": "°C", "value": 33, "min": 5, "max": 35},
            {"name": "Tilt", "unit": "°", "value": 3, "min": None, "max": 15},
            {"name": "Shock", "unit": "g", "value": 1.4, "min": None, "max": 6},
        ],
        "documents": [
            {"name": "Dangerous goods declaration", "status": "ready"}, {"name": "Safety data sheet (SDS)", "status": "ready"},
            {"name": "Container packing certificate", "status": "pending"}, {"name": "Import permit (UAE)", "status": "ready"},
            {"name": "Bill of lading", "status": "pending"},
        ],
        "incoterm": "CIF Jebel Ali", "insurance": "Institute Cargo Clauses (A) with DG extension", "consignee": "Northwind Gulf Agri-Distribution, Dubai",
    },
    "CN-26-0917": {
        "commodity": "Primary aluminium alloy ingots (A356)",
        "about": "Foundry-grade aluminium alloy ingots of about 22.7 kg each, sold to an automotive die-casting plant. Aluminium does not rust, but moisture trapped between ingots causes white water-staining, so the bundles must be dry when loaded and kept dry in transit.",
        "hs_code": "7601.20", "hs_desc": "Unwrought aluminium alloys",
        "unit_label": "ingot", "kg_per_unit": 22.7, "m3_per_unit": 0.0085,
        "package_label": "bundle", "units_per_package": 44, "tare_factor": 1.02,
        "packing": "Strapped 1-tonne bundles of 44 ingots on timber bearers",
        "equipment": {"name": "20' dry container, heavy-duty floor", "short": "20' HD", "payload_t": 24.0, "volume_m3": 33.2},
        "stowage": "Low in the stack; weight spread evenly over the container floor",
        "securing": "Bundles chocked and lashed; floor load limits checked before stuffing",
        "hazard": None,
        "handling": [
            {"icon": "dry", "title": "Keep dry, no condensation", "text": "Moisture between ingots stains the metal. Load only dry bundles into dry containers.", "critical": True},
            {"icon": "heavy", "title": "Heavy cargo", "text": "About 24 tonnes per container. Check crane and chassis limits at both ends.", "critical": True},
            {"icon": "secure", "title": "Chock and lash", "text": "Loose bundles can shift and puncture container walls in heavy seas.", "critical": False},
        ],
        "sensors": [
            {"name": "Relative humidity", "unit": "% RH", "value": 55, "min": None, "max": 65},
            {"name": "Dew-point margin", "unit": "°C", "value": 6.5, "min": 3, "max": None},
            {"name": "Shock", "unit": "g", "value": 2.1, "min": None, "max": 8},
        ],
        "documents": [
            {"name": "Mill test certificate", "status": "ready"}, {"name": "Commercial invoice", "status": "ready"},
            {"name": "Certificate of origin", "status": "ready"}, {"name": "Weight certificate (VGM)", "status": "pending"},
            {"name": "Bill of lading", "status": "pending"},
        ],
        "incoterm": "CFR Chennai", "insurance": "Institute Cargo Clauses (B)", "consignee": "Northwind India Auto Components Hub, Chennai",
    },
    "CN-26-0920": {
        "commodity": "Power semiconductor modules (MOSFET and IGBT)",
        "about": "Surface-mount power transistors and modules for EV chargers and industrial drives, packed in moisture-barrier bags with desiccant. They are sensitive to static, humidity and shock, and high value, so they travel in a temperature-controlled container with a GPS tracker and high-security seal.",
        "hs_code": "8541.29", "hs_desc": "Transistors, other than photosensitive, dissipation ≥ 1 W",
        "unit_label": "module", "kg_per_unit": 0.08, "m3_per_unit": 0.0006,
        "package_label": "carton", "units_per_package": 240,
        "packing": "Anti-static reels and trays in sealed moisture-barrier bags (MSL 3), 240 modules per carton",
        "equipment": {"name": "40' reefer set to controlled ambient (20 °C)", "short": "40' RF", "payload_t": 27.0, "volume_m3": 59.3},
        "stowage": "Reefer plug position under deck; power monitored throughout",
        "securing": "Cartons on anti-static pallets, airbags between rows, ISO 17712 high-security seal",
        "hazard": None,
        "handling": [
            {"icon": "esd", "title": "Static-sensitive", "text": "Open bags only in an ESD-protected area. Never handle modules by the leads.", "critical": True},
            {"icon": "moisture", "title": "Keep below 60% RH", "text": "Moisture-sensitive level 3: once the bag is open, parts must be used or re-baked within 168 hours.", "critical": True},
            {"icon": "temp", "title": "15 to 25 °C", "text": "Reefer set point 20 °C. Alarm if the unit loses power for more than 2 hours.", "critical": False},
            {"icon": "fragile", "title": "Fragile, high value", "text": "Shock limit 10 g. Tracker and seal checked at every hand-over.", "critical": False},
        ],
        "sensors": [
            {"name": "Temperature", "unit": "°C", "value": 20.4, "min": 15, "max": 25},
            {"name": "Relative humidity", "unit": "% RH", "value": 41, "min": None, "max": 60},
            {"name": "Shock", "unit": "g", "value": 4.2, "min": None, "max": 10},
            {"name": "Reefer power", "unit": "%", "value": 100, "min": 95, "max": None},
        ],
        "documents": [
            {"name": "Commercial invoice", "status": "ready"}, {"name": "Packing list", "status": "ready"},
            {"name": "Export control screening", "status": "ready"}, {"name": "ISF filing (US customs)", "status": "ready"},
            {"name": "Bill of lading", "status": "ready"},
        ],
        "incoterm": "DAP Los Angeles", "insurance": "Institute Cargo Clauses (A) with theft cover", "consignee": "Northwind West Coast Electronics DC, Ontario CA",
    },
    "CN-26-0922": {
        "commodity": "Zinc concentrate (flotation), bulk",
        "about": "Fine, damp mineral powder from a Peruvian mine, sold to a European smelter. It is a Group A cargo under the IMSBC Code: if its moisture content rises above the Transportable Moisture Limit it can liquefy and shift. Moisture must be measured before loading and kept down in transit.",
        "hs_code": "2608.00", "hs_desc": "Zinc ores and concentrates",
        "unit_label": "50 kg lot", "kg_per_unit": 50.0, "m3_per_unit": 0.022,
        "package_label": "liner bag", "units_per_package": 500, "tare_factor": 1.0,
        "packing": "Loose bulk in sealed container liner bags, about 25 tonnes per container",
        "equipment": {"name": "20' dry container with bulk liner", "short": "20' BL", "payload_t": 25.0, "volume_m3": 33.2},
        "stowage": "Under deck, weight distributed; liners closed to stop dust and water ingress",
        "securing": "Liner bulkhead bars at the door end; containers top-sealed",
        "hazard": {"code": "IMSBC A", "label": "IMSBC Group A · May liquefy", "un": None, "name": "Zinc concentrate", "pg": None, "marine_pollutant": False},
        "handling": [
            {"icon": "moisture", "title": "Moisture below TML", "text": "Moisture content 8.2% against a Transportable Moisture Limit of 9.8%. Retest if rain reaches the stockpile.", "critical": True},
            {"icon": "dust", "title": "Dusty cargo", "text": "Keep liners sealed. Workers need dust masks when stuffing.", "critical": False},
            {"icon": "heavy", "title": "Heavy, dense cargo", "text": "25 tonnes in a small volume. Keep the load level and centred.", "critical": False},
        ],
        "sensors": [
            {"name": "Moisture content", "unit": "%", "value": 8.2, "min": None, "max": 9.8},
            {"name": "Relative humidity", "unit": "% RH", "value": 72, "min": None, "max": 85},
            {"name": "Tilt", "unit": "°", "value": 2, "min": None, "max": 10},
        ],
        "documents": [
            {"name": "TML and moisture certificate", "status": "ready"}, {"name": "Cargo information form (IMSBC)", "status": "ready"},
            {"name": "Assay certificate", "status": "pending"}, {"name": "Commercial invoice", "status": "ready"},
            {"name": "Bill of lading", "status": "pending"},
        ],
        "incoterm": "FOB Callao", "insurance": "Institute Cargo Clauses (C)", "consignee": "Northwind Metals Europe, Rotterdam (for smelter delivery)",
    },
    "CN-26-0925": {
        "commodity": "CNC machine spindle cartridges",
        "about": "Precision spindle cartridges for machining centres, going to a US machine-tool rebuilder. The bearings are extremely sensitive to shock and corrosion: one hard drop can ruin a unit, so each crate carries shock and tilt indicators.",
        "hs_code": "8466.93", "hs_desc": "Parts and accessories for metal-working machine tools",
        "unit_label": "spindle", "kg_per_unit": 14.0, "m3_per_unit": 0.028,
        "package_label": "crate", "units_per_package": 12,
        "packing": "VCI anti-corrosion film, foam-lined wooden crates of 12 with shock and tilt indicators",
        "equipment": {"name": "40' dry container", "short": "40' DC", "payload_t": 26.5, "volume_m3": 67.7},
        "stowage": "Under deck, mid-ship for the lowest motion",
        "securing": "Crates blocked, nothing stacked on top, fork-lift points marked",
        "hazard": None,
        "handling": [
            {"icon": "fragile", "title": "Fragile precision parts", "text": "Shock limit 25 g. Any tripped indicator must be photographed and reported before signing.", "critical": True},
            {"icon": "nostack", "title": "Do not stack", "text": "Nothing on top of the crates.", "critical": True},
            {"icon": "dry", "title": "Keep dry", "text": "VCI film protects against corrosion only while it stays sealed and dry.", "critical": False},
            {"icon": "up", "title": "This way up", "text": "Tilt indicators trip at 30°.", "critical": False},
        ],
        "sensors": [
            {"name": "Shock", "unit": "g", "value": 6.3, "min": None, "max": 25},
            {"name": "Tilt", "unit": "°", "value": 4, "min": None, "max": 30},
            {"name": "Relative humidity", "unit": "% RH", "value": 48, "min": None, "max": 65},
        ],
        "documents": [
            {"name": "Commercial invoice", "status": "ready"}, {"name": "Packing list", "status": "ready"},
            {"name": "ISPM 15 crate certificate", "status": "ready"}, {"name": "ISF filing (US customs)", "status": "ready"},
            {"name": "Bill of lading", "status": "ready"},
        ],
        "incoterm": "DAP Newark", "insurance": "Institute Cargo Clauses (A)", "consignee": "Northwind Industrial Services, Edison NJ",
    },
    "CN-26-0928": {
        "commodity": "PET packaging film, biaxially oriented",
        "about": "Clear polyester film on rolls, used by a food-packaging converter in Monterrey. The film scratches and creases easily and softens in heat, so rolls travel suspended in cradles in closed trailers.",
        "hs_code": "3920.62", "hs_desc": "Plates, sheets and film of poly(ethylene terephthalate)",
        "unit_label": "roll", "kg_per_unit": 5.2, "m3_per_unit": 0.011,
        "package_label": "pallet", "units_per_package": 120,
        "packing": "Rolls wrapped in PE, suspended on core plugs in end-board cradles, 120 rolls per pallet",
        "equipment": {"name": "53' dry van trailer", "short": "53' van", "payload_t": 20.0, "volume_m3": 110.0},
        "stowage": "Closed trailer, parked in shade during border waits",
        "securing": "Load bars every second pallet row; no rolls resting on their surface",
        "hazard": None,
        "handling": [
            {"icon": "sun", "title": "Below 40 °C", "text": "Keep out of direct sun. Film softens and blocks (sticks together) in heat.", "critical": True},
            {"icon": "fragile", "title": "Do not crush the rolls", "text": "Handle by the cores only. Surface dents show up in the final packaging.", "critical": False},
            {"icon": "seal", "title": "Customs seal", "text": "Keep the trailer sealed through the Laredo crossing to avoid a re-inspection.", "critical": False},
        ],
        "sensors": [
            {"name": "Trailer temperature", "unit": "°C", "value": 34, "min": None, "max": 40},
            {"name": "Door status", "unit": "", "value": 0, "min": None, "max": 0, "text": "Sealed"},
            {"name": "Shock", "unit": "g", "value": 1.1, "min": None, "max": 5},
        ],
        "documents": [
            {"name": "USMCA certificate of origin", "status": "ready"}, {"name": "Commercial invoice", "status": "ready"},
            {"name": "Pedimento (Mexican customs entry)", "status": "pending"}, {"name": "Bill of lading (road)", "status": "ready"},
        ],
        "incoterm": "DAP Monterrey", "insurance": "Institute Cargo Clauses (A)", "consignee": "Northwind Mexico Packaging Hub, Apodaca",
    },
}

# Fallbacks for consignments added through the portal.
CATEGORY_DEFAULTS: dict[str, dict] = {
    "Electronics": {"kg_per_unit": 0.5, "m3_per_unit": 0.002, "units_per_package": 200, "package_label": "carton",
                    "equipment": {"name": "40' dry container", "short": "40' DC", "payload_t": 26.5, "volume_m3": 67.7},
                    "handling": [{"icon": "esd", "title": "Static-sensitive", "text": "Handle in ESD-safe areas only.", "critical": True},
                                 {"icon": "dry", "title": "Keep dry", "text": "Keep humidity below 60%.", "critical": False}]},
    "Raw Materials": {"kg_per_unit": 25.0, "m3_per_unit": 0.012, "units_per_package": 40, "package_label": "bundle",
                      "equipment": {"name": "20' dry container", "short": "20' DC", "payload_t": 24.0, "volume_m3": 33.2},
                      "handling": [{"icon": "heavy", "title": "Heavy cargo", "text": "Check floor and chassis limits.", "critical": True},
                                   {"icon": "dry", "title": "Keep dry", "text": "Avoid condensation on the load.", "critical": False}]},
    "Machinery": {"kg_per_unit": 40.0, "m3_per_unit": 0.08, "units_per_package": 4, "package_label": "crate",
                  "equipment": {"name": "40' dry container", "short": "40' DC", "payload_t": 26.5, "volume_m3": 67.7},
                  "handling": [{"icon": "fragile", "title": "Fragile", "text": "Avoid drops and shocks.", "critical": True},
                               {"icon": "nostack", "title": "Do not stack", "text": "Nothing on top of crates.", "critical": False}]},
    "Chemicals": {"kg_per_unit": 20.0, "m3_per_unit": 0.025, "units_per_package": 40, "package_label": "pallet",
                  "equipment": {"name": "20' dry container", "short": "20' DC", "payload_t": 21.7, "volume_m3": 33.2},
                  "handling": [{"icon": "up", "title": "This way up", "text": "Keep drums upright.", "critical": True},
                               {"icon": "temp", "title": "Temperature controlled", "text": "Avoid heat and direct sun.", "critical": False}]},
    "Packaging": {"kg_per_unit": 0.5, "m3_per_unit": 0.003, "units_per_package": 1000, "package_label": "pallet",
                  "equipment": {"name": "40' High Cube dry container", "short": "40' HC", "payload_t": 26.5, "volume_m3": 76.3},
                  "handling": [{"icon": "dry", "title": "Keep dry", "text": "Packaging loses strength when damp.", "critical": True}]},
}


def _generic(rec: dict) -> dict:
    cat = rec.get("product_category") or "Packaging"
    base = CATEGORY_DEFAULTS.get(cat, CATEGORY_DEFAULTS["Packaging"])
    return {
        "commodity": rec.get("cargo") or f"{cat} consignment",
        "about": f"{cat} shipped by {rec.get('supplier_name') or 'the shipper'}. A detailed cargo profile has not been set up for this consignment yet, so standard {cat.lower()} handling applies.",
        "hs_code": None, "hs_desc": None, "unit_label": "unit", "packing": "Standard export packing",
        "stowage": "Standard stowage", "securing": "Standard securing", "hazard": None,
        "sensors": [], "documents": [{"name": "Commercial invoice", "status": "pending"}, {"name": "Packing list", "status": "pending"},
                                     {"name": "Bill of lading", "status": "pending"}],
        "incoterm": None, "insurance": None, "consignee": None, "generic": True, **base,
    }


def _sensor_status(s: dict) -> str:
    """breach = outside the safe range, watch = within 10% of a limit, ok otherwise."""
    if s.get("text"):
        return "ok"
    v, lo, hi = s["value"], s.get("min"), s.get("max")
    if (hi is not None and v > hi) or (lo is not None and v < lo):
        return "breach"
    if (hi is not None and hi - v <= 0.1 * max(abs(hi), 1)) or (lo is not None and v - lo <= 0.1 * max(abs(lo), 1)):
        return "watch"
    return "ok"


def profile(rec: dict) -> dict:
    """Cargo profile for one consignment record, with load figures derived from its units."""
    p = dict(PROFILES.get(rec.get("consignment_id")) or _generic(rec))
    units = float(rec.get("units") or 0)
    value = units * float(rec.get("average_cost_per_unit") or 0)
    eq = p["equipment"]
    net_t = units * p["kg_per_unit"] / 1000
    gross_t = net_t * p.get("tare_factor", 1.06)  # packaging, pallets and dunnage
    volume = units * p["m3_per_unit"]
    n_eq = max(1, math.ceil(max(gross_t / eq["payload_t"], volume / eq["volume_m3"]))) if units else 0
    by_weight = gross_t / (n_eq * eq["payload_t"]) if n_eq else 0
    by_volume = volume / (n_eq * eq["volume_m3"]) if n_eq else 0
    packages = math.ceil(units / p["units_per_package"]) if units else 0
    sensors = [{**s, "status": _sensor_status(s)} for s in p.get("sensors", [])]
    return {
        **{k: v for k, v in p.items() if k not in ("sensors",)},
        "sensors": sensors,
        "load": {
            "units": int(units), "net_t": round(net_t, 1), "gross_t": round(gross_t, 1), "volume_m3": round(volume, 1),
            "packages": packages, "equipment_count": n_eq, "fill_weight": round(min(1, by_weight), 3),
            "fill_volume": round(min(1, by_volume), 3), "limited_by": "weight" if by_weight >= by_volume else "volume",
        },
        "value_usd": round(value, 0), "insured_value_usd": round(value * 1.1, 0),
        "documents_ready": sum(1 for d in p["documents"] if d["status"] == "ready"),
    }
