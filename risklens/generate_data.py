"""Phase 1 — synthetic data foundation.

Produces three raw CSVs (all dummy data) and a combined daily panel:
  data/raw/suppliers.csv          supplier master data
  data/raw/external_signals.csv   daily external risk signals per supplier
  data/raw/disruptions.csv        historical disruption events
  data/raw/supply_chain_combined.csv  joined daily panel used by feature engineering

Disruptions are drawn from a latent risk process so the ML model has a
real (but noisy) pattern to learn — the way real supply-chain data behaves.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import DATA_RAW, REGIONS, CATEGORIES

START = "2026-06-01"
END = "2026-09-23"
SEED = 42

SUPPLIERS = [
    ("SUP_001", "TechParts Asia", "East Asia", "China", "Electronics"),
    ("SUP_002", "QuickShip Ltd", "South Asia", "India", "Packaging"),
    ("SUP_003", "GlobalLogistics Inc", "Southeast Asia", "Vietnam", "Machinery"),
    ("SUP_004", "Meridian Chemicals", "Middle East", "Saudi Arabia", "Chemicals"),
    ("SUP_005", "Nordvik Components", "Europe", "Sweden", "Electronics"),
    ("SUP_006", "Sahara Minerals", "Africa", "Morocco", "Raw Materials"),
    ("SUP_007", "Pacific Semis", "East Asia", "Taiwan", "Electronics"),
    ("SUP_008", "Ganges Textiles", "South Asia", "Bangladesh", "Raw Materials"),
    ("SUP_009", "Rhine Precision", "Europe", "Germany", "Machinery"),
    ("SUP_010", "Gulf Polymers", "Middle East", "UAE", "Chemicals"),
    ("SUP_011", "Mekong Packaging", "Southeast Asia", "Thailand", "Packaging"),
    ("SUP_012", "Andes Copper", "Latin America", "Chile", "Raw Materials"),
    ("SUP_013", "Great Lakes Steel", "North America", "USA", "Raw Materials"),
    ("SUP_014", "Lagos Agro Inputs", "Africa", "Nigeria", "Chemicals"),
    ("SUP_015", "Kansai Robotics", "East Asia", "Japan", "Machinery"),
    ("SUP_016", "Iberia Circuits", "Europe", "Spain", "Electronics"),
    ("SUP_017", "Bosphorus Metals", "Middle East", "Turkey", "Raw Materials"),
    ("SUP_018", "Hanoi Plastics", "Southeast Asia", "Vietnam", "Packaging"),
    ("SUP_019", "Pune Autoparts", "South Asia", "India", "Machinery"),
    ("SUP_020", "Shenzhen Boards", "East Asia", "China", "Electronics"),
    ("SUP_021", "Baltic Chemicals", "Europe", "Poland", "Chemicals"),
    ("SUP_022", "Cape Ferro", "Africa", "South Africa", "Raw Materials"),
    ("SUP_023", "Monterrey Castings", "Latin America", "Mexico", "Machinery"),
    ("SUP_024", "Ohio Valley Plastics", "North America", "USA", "Packaging"),
    ("SUP_025", "Seoul Displays", "East Asia", "South Korea", "Electronics"),
    ("SUP_026", "Karachi Cotton", "South Asia", "Pakistan", "Raw Materials"),
    ("SUP_027", "Jakarta Resins", "Southeast Asia", "Indonesia", "Chemicals"),
    ("SUP_028", "Doha Petrochem", "Middle East", "Qatar", "Chemicals"),
    ("SUP_029", "Lyon Actuators", "Europe", "France", "Machinery"),
    ("SUP_030", "Nairobi Agrichem", "Africa", "Kenya", "Chemicals"),
    ("SUP_031", "Sao Paulo Sensors", "Latin America", "Brazil", "Electronics"),
    ("SUP_032", "Ontario Fasteners", "North America", "Canada", "Machinery"),
    ("SUP_033", "Penang Semis", "Southeast Asia", "Malaysia", "Electronics"),
    ("SUP_034", "Chennai Forgings", "South Asia", "India", "Machinery"),
    ("SUP_035", "Osaka Ceramics", "East Asia", "Japan", "Raw Materials"),
    ("SUP_036", "Milano Packaging", "Europe", "Italy", "Packaging"),
    ("SUP_037", "Accra Cocoa Inputs", "Africa", "Ghana", "Raw Materials"),
    ("SUP_038", "Lima Minerals", "Latin America", "Peru", "Raw Materials"),
    ("SUP_039", "Texas Petro Films", "North America", "USA", "Packaging"),
    ("SUP_040", "Manila Assemblies", "Southeast Asia", "Philippines", "Electronics"),
    ("SUP_041", "Dhaka Cartons", "South Asia", "Bangladesh", "Packaging"),
    ("SUP_042", "Muscat Alloys", "Middle East", "Oman", "Raw Materials"),
    ("SUP_043", "Prague Gearworks", "Europe", "Czechia", "Machinery"),
    ("SUP_044", "Casablanca Phosphates", "Africa", "Morocco", "Chemicals"),
    ("SUP_045", "Bogota Films", "Latin America", "Colombia", "Packaging"),
    ("SUP_046", "Taipei Optics", "East Asia", "Taiwan", "Electronics"),
    ("SUP_047", "Riyadh Polymers", "Middle East", "Saudi Arabia", "Chemicals"),
    ("SUP_048", "Rotterdam Additives", "Europe", "Netherlands", "Chemicals"),
]

# Region-level baselines for external signals (0-100).
REGION_GEO = {
    "South Asia": 48, "Southeast Asia": 38, "East Asia": 42, "Middle East": 62,
    "Europe": 18, "Africa": 55, "North America": 12, "Latin America": 40,
}
REGION_WEATHER = {
    "South Asia": 58, "Southeast Asia": 62, "East Asia": 45, "Middle East": 30,
    "Europe": 25, "Africa": 40, "North America": 35, "Latin America": 42,
}
CATEGORY_COST = {
    "Electronics": (40, 500), "Raw Materials": (5, 60), "Machinery": (120, 500),
    "Chemicals": (15, 120), "Packaging": (5, 30),
}

REASONS = [
    ("Port congestion", 0.22), ("Severe weather", 0.20), ("Geopolitical / customs hold", 0.18),
    ("Supplier capacity shortfall", 0.15), ("Quality rejection", 0.10),
    ("Raw material shortage", 0.10), ("Labour strike", 0.05),
]


def _sigmoid(x):
    return 1 / (1 + np.exp(-x))


def _ar1(rng, n, mean, sd, rho=0.85):
    """Autocorrelated daily series around a mean."""
    x = np.empty(n)
    x[0] = mean + rng.normal(0, sd)
    for i in range(1, n):
        x[i] = mean + rho * (x[i - 1] - mean) + rng.normal(0, sd * np.sqrt(1 - rho**2))
    return x


def generate(seed: int = SEED) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    dates = pd.date_range(START, END, freq="D")
    n = len(dates)

    # ---- suppliers.csv -------------------------------------------------
    rows = []
    for sid, name, region, country, cat in SUPPLIERS:
        lo, hi = CATEGORY_COST[cat]
        lead = int(rng.integers(12, 86))
        cv = float(np.clip(rng.beta(2, 6) * 0.8, 0.03, 0.6))
        total = int(rng.integers(40, 140))
        reliability = float(np.clip(rng.beta(7, 1.6), 0.55, 0.99))
        rows.append({
            "supplier_id": sid, "supplier_name": name, "region": region, "country": country,
            "product_category": cat,
            "lead_time_days": lead,
            "lead_time_std_days": round(lead * cv, 1),
            "average_cost_per_unit": round(float(rng.uniform(lo, hi)), 2),
            "annual_volume_units": int(rng.integers(1_000, 100_000)),
            "total_deliveries": total,
            "on_time_deliveries": int(round(total * reliability)),
            "single_source": int(rng.random() < 0.35),
            "contract_type": rng.choice(["spot", "annual", "multi-year"], p=[0.3, 0.5, 0.2]),
        })
    suppliers = pd.DataFrame(rows)

    # ---- external_signals.csv ------------------------------------------
    sig_rows = []
    latent_by_supplier = {}
    for _, s in suppliers.iterrows():
        geo = np.clip(_ar1(rng, n, REGION_GEO[s.region], 9), 0, 100)
        weather = np.clip(_ar1(rng, n, REGION_WEATHER[s.region], 14, rho=0.75), 0, 100)
        # Inject a few weather storms and geopolitical flare-ups.
        for _ in range(rng.integers(1, 3)):
            t = rng.integers(0, n - 8)
            weather[t:t + 7] = np.clip(weather[t:t + 7] + rng.uniform(25, 40), 0, 100)
        if rng.random() < 0.5:
            t = rng.integers(0, n - 15)
            geo[t:t + 14] = np.clip(geo[t:t + 14] + rng.uniform(15, 30), 0, 100)
        port = np.clip(_ar1(rng, n, 35 + 20 * (s.region in ("South Asia", "Southeast Asia")), 10), 0, 100)
        vol_sd = rng.uniform(0.4, 1.6)
        price = 100 + np.cumsum(rng.normal(0, vol_sd, n))
        price = np.clip(price, 70, 135)
        latent_by_supplier[s.supplier_id] = (geo, weather, port, price)
        for i, d in enumerate(dates):
            w = weather[i]
            level = "low" if w < 40 else ("medium" if w < 65 else "high")
            sig_rows.append({
                "date": d.date().isoformat(), "supplier_id": s.supplier_id,
                "weather_risk_index": round(float(w), 1), "weather_risk_level": level,
                "geopolitical_risk_index": round(float(geo[i]), 1),
                "port_congestion_index": round(float(port[i]), 1),
                "commodity_price_index": round(float(price[i]), 2),
            })
    signals = pd.DataFrame(sig_rows)

    # ---- disruptions.csv (latent-risk driven) ---------------------------
    dis_rows = []
    supplier_effect = {sid: rng.normal(0, 0.25) for sid in suppliers.supplier_id}
    for _, s in suppliers.iterrows():
        geo, weather, port, price = latent_by_supplier[s.supplier_id]
        reliability = s.on_time_deliveries / s.total_deliveries
        cv = s.lead_time_std_days / s.lead_time_days
        last = -999
        for i in range(n):
            swing = (price[max(0, i - 29):i + 1].max() - price[max(0, i - 29):i + 1].min()) / price[max(0, i - 29):i + 1].mean() * 100
            recency = np.exp(-(i - last) / 30) if last >= 0 else 0.0
            z = (
                -7.6
                + 2.4 * (1 - reliability)
                + 2.4 * (0.7 * geo[i] / 100 + 0.3 * port[i] / 100)
                + 2.6 * (weather[i] / 100)
                + 1.1 * min(1, swing / 25)
                + 0.6 * min(1, cv / 0.5)
                + 0.5 * (s.lead_time_days - 10) / 80
                + 1.2 * recency
                + 0.5 * s.single_source
                + supplier_effect[s.supplier_id]
            )
            if rng.random() < _sigmoid(z):
                # pick a reason consistent with the dominant driver
                weights = np.array([w for _, w in REASONS], dtype=float)
                if weather[i] > 60:
                    weights[1] *= 3
                if geo[i] > 55:
                    weights[2] *= 3
                if port[i] > 55:
                    weights[0] *= 2
                reason = REASONS[rng.choice(len(REASONS), p=weights / weights.sum())][0]
                duration = int(rng.integers(2, 18))
                spend = s.average_cost_per_unit * s.annual_volume_units
                cost = round(float(spend / 365 * duration * rng.uniform(1.5, 4.0)), 0)
                dis_rows.append({
                    "disruption_id": f"DIS_{len(dis_rows) + 1:03d}",
                    "date": dates[i].date().isoformat(), "supplier_id": s.supplier_id,
                    "disruption_reason": reason, "duration_days": duration,
                    "recovery_cost_usd": cost,
                })
                last = i
    disruptions = pd.DataFrame(dis_rows)

    # ---- combined panel -------------------------------------------------
    combined = signals.merge(suppliers, on="supplier_id", how="left")
    combined["reliability_score"] = (combined.on_time_deliveries / combined.total_deliveries).round(3)
    combined["disrupted"] = 0
    combined = combined.merge(
        disruptions[["date", "supplier_id", "disruption_reason", "recovery_cost_usd"]],
        on=["date", "supplier_id"], how="left",
    )
    combined.loc[combined.disruption_reason.notna(), "disrupted"] = 1
    combined = combined.sort_values(["supplier_id", "date"]).reset_index(drop=True)

    return {
        "suppliers": suppliers, "external_signals": signals,
        "disruptions": disruptions, "supply_chain_combined": combined,
    }


def main():
    DATA_RAW.mkdir(parents=True, exist_ok=True)
    frames = generate()
    for name, df in frames.items():
        path = DATA_RAW / f"{name}.csv"
        df.to_csv(path, index=False)
        print(f"wrote {path.relative_to(DATA_RAW.parent.parent)}  ({len(df)} rows)")
    c = frames["supply_chain_combined"]
    print(f"disruption rate: {c.disrupted.mean():.1%}  events: {int(c.disrupted.sum())}")


if __name__ == "__main__":
    main()
