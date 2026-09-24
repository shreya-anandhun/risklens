# RiskLens — Supply Chain Risk Intelligence

Predicts which suppliers are likely to be disrupted in the next 7 days, explains
why parameter by parameter, and recommends costed mitigations. Built for
Datathon 2K26 (BDA & CC track). All data is synthetic.

```
data/raw  ──►  features  ──►  XGBoost  ──►  rules engine  ──►  web portal
3 CSVs         7 factors      P(disruption   IF-THEN with      FastAPI + JS
(dummy)        (0-1 each)     in 7 days)     cost / benefit    light theme
```

## Quick start

```bash
./run.sh            # creates .venv, installs deps, builds data + model, serves on :8000
```

Open http://localhost:8000. On macOS, XGBoost needs the OpenMP runtime:
`brew install libomp`.

Rebuild data and model from scratch at any time:

```bash
.venv/bin/python -m risklens.pipeline
```

Run the tests:

```bash
.venv/bin/python -m pytest -q
```

## What the portal does

| Page | What you can do |
|---|---|
| **Overview** | Portfolio KPIs (% of spend at risk, high-risk count, expected 7-day loss), back-test of predicted risk vs. actual disruptions, supplier × parameter heatmap, priority actions ranked by net benefit. |
| **Suppliers** | Editable portfolio. Search, filter by band, sort. Click a row to open the inspector: score dial, parameter scorecard with SHAP contributions, costed mitigations, risk history, and an edit form that re-scores live. Save persists to `data/portal/suppliers.json`; Delete removes; Reset restores the seed. |
| **Analyze** | Score a single supplier from a form (updates as you type; can be saved to the portfolio), or upload a CSV batch. Row-level validation errors are reported by line and field; valid rows are still scored. Download the template, download results, or add the batch to the portfolio. |
| **Methodology** | Model card with metrics, feature importance, exact normalisation formulas, rule catalogue, risk bands, and data lineage. |

## Phase map (matches the build roadmap)

| Phase | Where | Notes |
|---|---|---|
| 1 Data foundation | `risklens/generate_data.py` → `data/raw/*.csv` | 48 suppliers × 115 days. `suppliers.csv`, `external_signals.csv`, `disruptions.csv`, plus the joined `supply_chain_combined.csv`. Disruptions are drawn from a latent-risk process so there is a real pattern to learn. |
| 2 Feature engineering | `risklens/features.py` → `data/processed/supply_chain_features.csv` | Seven 0–1 risk factors: reliability, lead-time exposure, lead-time variability, geopolitical (blended with port congestion), weather, commodity price volatility (30-day swing), disruption recency (`exp(-days/30)`). Same functions serve the portal so training and inference agree. Target = disruption within the next 7 days, using only past information. |
| 3 ML model | `risklens/train.py` → `models/risk_model.json`, `model_meta.json` | XGBoost, 300 trees, depth 4, monotonic constraints on all factors. Time-based 80/20 split. Test AUC ≈ 0.80, recall ≈ 0.71 at the F1-optimal threshold. |
| 4 Rules engine | `risklens/rules.py` | Eight IF-THEN rules (diversify region, safety stock, backup supplier, renegotiate, forward contract, schedule buffer, post-incident review, second source) with cost scaled to annual spend, timeline, expected risk reduction and net benefit. |
| 5 Portal | `app/main.py`, `app/static/` | FastAPI JSON API and a hand-built single-page UI (no framework, Chart.js vendored). |
| 6 Integration & tests | `tests/` | Feature invariants, rule logic, API contract, CSV edge cases (bad values, missing columns, empty file, wrong type, aliases). |

## CSV format for batch scoring

Required: `supplier_name, lead_time_days, reliability_score, geopolitical_risk_index, weather_risk_level`
Optional: `region, product_category, lead_time_std_days, port_congestion_index, weather_risk_index, price_swing_pct, days_since_last_disruption, single_source, average_cost_per_unit, annual_volume_units`

Column names are matched case-insensitively with common aliases (`Lead Time (days)`, `OTD`, `Geo Risk`…). Reliability may be given as 0–1 or as a percentage. Download a template from the Analyze page or `GET /api/template.csv`.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/meta` | model card, feature definitions, rules, bands |
| GET | `/api/overview` | KPIs, scored portfolio, back-test timeline, top actions |
| GET/POST | `/api/suppliers` | list scored portfolio / add supplier |
| GET/PUT/DELETE | `/api/suppliers/{id}` | inspect (with history) / edit / remove |
| POST | `/api/suppliers/reset` · `/api/suppliers/import` | restore seed / add validated batch |
| POST | `/api/score` · `/api/score/csv` | score one record / a CSV upload |
| GET | `/api/template.csv` · `/api/export.csv` | template / scored portfolio export |

## Project layout

```
risklens/   config, generate_data, features, train, rules, predictor, validation, store, pipeline
app/        main.py (FastAPI), static/ (index.html, styles.css, app.js, vendor/chart.umd.js)
data/       raw/ processed/ portal/ (portal state, git-ignored)
models/     risk_model.json, model_meta.json
tests/      pytest suite
```
