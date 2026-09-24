# RiskLens: Consignment Risk Intelligence

**RiskLens predicts which of a logistics company's consignments are likely to be disrupted in the next 7 days, explains why, and recommends what to do about it.**
For each consignment it gives a risk score, shows how every risk parameter moved that score, lists costed mitigations,
and compares alternative routes, carriers and timings, each re-scored by the model.

The portal is the client's view. This demo is set up for one fictional company, **Northwind Logistics**, managing
seven consignments across seven regions. All data is dummy data, built for Datathon 2K26 (BDA & CC track).

```
data/raw  ──►  features  ──►  XGBoost  ──►  rules + alternatives  ──►  client portal
dummy CSVs     7 factors      P(disruption    costed mitigations and       FastAPI + JS
               (0–1 each)     in 7 days)      re-scored route options      light theme
```

## The demo consignments

| ID | Cargo | From | To | Mode | Status |
|---|---|---|---|---|---|
| CN-26-0911 | Corrugated export cartons | Chittagong, Bangladesh | Felixstowe, UK | Sea | Scheduled |
| CN-26-0914 | Crop-protection chemicals | Mombasa, Kenya | Jebel Ali, UAE | Sea | Scheduled |
| CN-26-0917 | Aluminium alloy ingots | Sohar, Oman | Chennai, India | Sea | Scheduled |
| CN-26-0920 | Power semiconductors | Kaohsiung, Taiwan | Los Angeles, USA | Sea | In transit |
| CN-26-0922 | Zinc concentrate | Callao, Peru | Rotterdam, Netherlands | Sea | Scheduled |
| CN-26-0925 | CNC machine spindles | Hamburg, Germany | Newark, USA | Sea | In transit |
| CN-26-0928 | PET packaging film | Columbus, USA | Monterrey, Mexico | Road | Scheduled |

Carrier names are made up. Status is worked out from today's date against the dispatch date and ETA.

## Quick start

```bash
./run.sh            # creates .venv, installs deps, builds data + model if missing, serves on :8000
```

Open http://localhost:8000. On macOS, XGBoost needs the OpenMP runtime: `brew install libomp`.

Rebuild the data and model from scratch, or run the tests:

```bash
.venv/bin/python -m risklens.pipeline
```

```bash
.venv/bin/python -m pytest -q
```

## What the portal shows

| Page | What you can do |
|---|---|
| **Overview** | KPIs for the consignment book, then an interactive **3D risk globe**. It shows every route coloured by risk, with animated flow and pulsing rings on high-risk positions and hotspots. Zoom in and each location gets an icon: ship, flight, truck or rail for where each consignment is now, a flag for its destination, an anchor for its origin, and a warning sign for chokepoints such as Hormuz, Suez or the Panama Canal. Hover any place for a description of it and its current situation. Click a route or vehicle to open the consignment. Below the globe: a risk-profile radar, cargo value by risk band, a departure and arrival timeline, and recent disruptions on the company's own lanes. |
| **Consignments** | The consignment board: route, journey progress, 30-day lane risk trend, risk score and best alternative. Click a consignment for its **cargo profile**: what the goods are (HS code, dangerous-goods class), how much is loaded (units, net and gross weight, volume, packages, containers and fill), how it is packed, stowed and secured, handling rules such as "keep dry" or "away from foodstuffs", condition sensors against safe limits, documents, insurance and consignee. |
| **Recommended actions** | Summary of net benefit, loss avoided and cost to act; a benefit-vs-cost chart; and a card for each mitigation with its rank, category, timing, reason, consignment, risk-reduction ring, cost, loss avoided, net benefit and return. Filter by category, sort, and mark actions as done (remembered in the browser). Clicking a consignment opens its risk details and alternatives. |
| **What-if analysis** | Assess a planned consignment before booking it, with alternatives and mitigations, then add it to the book. Or upload a CSV batch; problems are reported by line and field and valid rows are still scored. |

**Reset demo data** in the sidebar restores the seven original consignments after a demo.

The globe uses [globe.gl](https://github.com/vasturiano/globe.gl) with Natural Earth country shapes from world-atlas. Both are vendored in `app/static/vendor`, so the portal runs offline. Port coordinates, sea-lane waypoints and hotspots live in `risklens/geo.py`. Hotspot and place risk levels are always computed from the consignment signals. Cargo profiles (commodity, load, handling, sensors, documents) live in `risklens/cargo.py`; load figures are derived from each consignment's unit count. A consignment whose ports are not in the geography file is listed as "not on the map" rather than guessed.

## How it works

| Phase | Where | Notes |
|---|---|---|
| 1 Data | `risklens/generate_data.py` → `data/raw/` | `consignments.csv` (the 7 consignments with from/to, dates, carrier, units) and `consignment_alternatives.csv` (2–3 options each). Historical training data: `suppliers.csv` (48 lanes), `external_signals.csv` (daily weather, geopolitical, port congestion and commodity prices), and `disruptions.csv`. Each consignment rides on one historical lane, which supplies its signals and history. |
| 2 Features | `risklens/features.py` | Seven 0–1 risk factors: carrier reliability, lead-time exposure, lead-time variability, geopolitical risk blended with port congestion, weather, fuel and commodity price volatility, and disruption recency. The portal uses the same functions as training. |
| 3 Model | `risklens/train.py` → `models/` | XGBoost with monotonic constraints, so a worse input never lowers the score. Target is disruption within 7 days. Time-based split, test AUC ≈ 0.80. |
| 4 Rules & alternatives | `risklens/rules.py`, `risklens/predictor.py` | Eight logistics mitigations (reroute, buffer stock, reschedule sailing, switch carrier, lock freight rate, schedule buffer, daily tracking, split consignment), costed as a share of cargo value. Each alternative's changes are applied to the consignment and the new version is re-scored by the model. Net benefit = expected loss avoided − extra cost. |
| 5 Portal | `app/main.py`, `app/static/` | FastAPI JSON API and a hand-built single-page UI. Chart.js is vendored locally. |
| 6 Tests | `tests/` | Feature invariants, rules, API contract, alternatives and apply, CSV edge cases. |

**Cost model.** A disruption is assumed to delay a consignment by about 0.3 × lead time + 5 days. Each delay day costs 1.2% of cargo value, on top of a fixed 4% handling impact. Expected loss is the model's probability multiplied by that cost.

## CSV format for batch checks

Required: an ID (`consignment_id`, or `supplier_name`), `lead_time_days`, `reliability_score`, `geopolitical_risk_index`, `weather_risk_level`.
Useful optional columns: `cargo, mode, carrier, origin_port, origin_country, region, destination_port, destination_country, destination_region, dispatch_date, eta_date, units, average_cost_per_unit, lead_time_std_days, port_congestion_index, weather_risk_index, price_swing_pct, days_since_last_disruption, single_source`.

Column names are matched loosely, so `From`, `To`, `Shipment ID`, `ETA` and `OTD` all work. Reliability can be 0–1 or a percentage. Get a template from the What-if page or `GET /api/template.csv`.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/meta` | company, parameter definitions, risk bands |
| GET | `/api/overview` | KPIs, scored consignments with trends, lane disruptions, top actions |
| GET / POST | `/api/consignments` | list the scored book / add a consignment |
| GET / PUT / DELETE | `/api/consignments/{id}` | detail with alternatives and history / edit / remove |
| POST | `/api/consignments/{id}/apply/{alternative}` | apply an alternative to a consignment |
| POST | `/api/consignments/reset` · `/api/consignments/import` | restore the demo book / add a validated batch |
| POST | `/api/score` · `/api/score/csv` | what-if for one consignment / a CSV |
| GET | `/api/template.csv` · `/api/export.csv` | template / export of the scored book |

## Project layout

```
risklens/   config, generate_data, features, train, rules, predictor, validation, store, geo, cargo, pipeline
app/        main.py (FastAPI), static/ (index.html, styles.css, app.js, vendor/: Chart.js, globe.gl, topojson, country shapes)
data/       raw/ processed/ portal/ (portal edits, git-ignored)
models/     risk_model.json, model_meta.json
tests/      pytest suite
```

To demo a different company, change `COMPANY` in `risklens/config.py` and the `CONSIGNMENTS` and `ALTERNATIVES` lists in `risklens/generate_data.py`, then run the pipeline and press Reset demo data.
