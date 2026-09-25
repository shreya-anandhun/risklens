"""XGBoost training on the Kaggle shipment data.

Predicts whether a shipment is disrupted from the signals known before it
leaves. The split is by date, so the test set is always in the model's future:
train on shipments before July 2025, tune the alert threshold on the last
months of that window, and test on July to December 2025.

Lead_Time_Days is left out on purpose: disrupted shipments in the data have
about three times the lead time of on-time ones, so it records the actual
transit time after the disruption, not the planned one.

Outputs:
  models/risk_model.json   XGBoost model (native format, version-safe)
  models/model_meta.json   features, metrics, importance, training window
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import (
    accuracy_score, average_precision_score, brier_score_loss, f1_score, precision_score, recall_score, roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score

from . import datasets
from .config import FEATURE_KEYS, FEATURES, META_PATH, MODEL_PATH, MODELS, RISK_BANDS
from .features import frame_to_features

TEST_FROM = "2025-07-01"
VALID_FROM = "2025-04-01"

PARAMS = dict(
    n_estimators=300,
    max_depth=4,
    learning_rate=0.04,
    subsample=0.85,
    colsample_bytree=0.85,
    min_child_weight=3,
    reg_lambda=2.0,
    # Every feature is a risk factor (1 = riskiest); force monotone increasing effects.
    monotone_constraints="(" + ",".join("1" for _ in FEATURE_KEYS) + ")",
    objective="binary:logistic",
    eval_metric="logloss",
    random_state=42,
)


def train(ships: pd.DataFrame):
    X, y = frame_to_features(ships), ships.disrupted
    tr, va, te = ships.date < VALID_FROM, (ships.date >= VALID_FROM) & (ships.date < TEST_FROM), ships.date >= TEST_FROM

    # Tune the alert threshold on the validation months with a model that has not seen them.
    probe = xgb.XGBClassifier(**PARAMS).fit(X[tr], y[tr])
    va_proba = probe.predict_proba(X[va])[:, 1]
    grid = np.linspace(0.3, 0.8, 51)
    threshold = float(grid[int(np.argmax([f1_score(y[va], va_proba >= t, zero_division=0) for t in grid]))])

    model = xgb.XGBClassifier(**PARAMS).fit(X[tr | va], y[tr | va])
    proba = model.predict_proba(X[te])[:, 1]
    pred = (proba >= threshold).astype(int)
    base = float(y[te].mean())
    elevated = RISK_BANDS[1][1] / 100
    metrics = {
        "auc_roc": round(float(roc_auc_score(y[te], proba)), 4),
        "avg_precision": round(float(average_precision_score(y[te], proba)), 4),
        "accuracy": round(float(accuracy_score(y[te], pred)), 4),
        "precision": round(float(precision_score(y[te], pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y[te], pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y[te], pred, zero_division=0)), 4),
        "brier": round(float(brier_score_loss(y[te], proba)), 4),
        "brier_baseline": round(base * (1 - base), 4),
        "decision_threshold": round(threshold, 3),
        "base_rate_test": round(base, 4),
        "caught_elevated_or_high": round(float((proba[y[te] == 1] >= elevated).mean()), 4),
    }
    cv = StratifiedKFold(5, shuffle=True, random_state=42)
    cv_auc = cross_val_score(xgb.XGBClassifier(**PARAMS), X, y, cv=cv, scoring="roc_auc")
    metrics["cv_auc_mean"] = round(float(cv_auc.mean()), 4)
    metrics["cv_auc_std"] = round(float(cv_auc.std()), 4)

    gain = model.get_booster().get_score(importance_type="gain")
    total = sum(gain.values()) or 1
    importance = dict(sorted({k: round(gain.get(k, 0) / total, 4) for k in FEATURE_KEYS}.items(), key=lambda kv: -kv[1]))

    all_scores = model.predict_proba(X)[:, 1] * 100
    meta = {
        "model": "XGBoost gradient-boosted trees (binary:logistic)",
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target": "disruption on the shipment (Disruption_Occurred)",
        "dataset": "Global Supply Chain Risk & Logistics 2024-2026 (Kaggle)",
        "params": {k: v for k, v in PARAMS.items() if k not in ("objective", "eval_metric")},
        "n_train": int((tr | va).sum()), "n_test": int(te.sum()), "n_validation": int(va.sum()),
        "train_window": [ships.date[tr | va].min(), ships.date[tr | va].max()],
        "test_window": [ships.date[te].min(), ships.date[te].max()],
        "excluded": {"Lead_Time_Days": "records transit time after a disruption, so it leaks the outcome"},
        "features": FEATURES,
        "feature_keys": FEATURE_KEYS,
        "importance": importance,
        "metrics": metrics,
        "risk_bands": [{"band": b, "min": lo, "max": hi} for b, lo, hi in RISK_BANDS],
        "score_percentiles": {str(p): round(float(np.percentile(all_scores, p)), 1) for p in (10, 25, 50, 75, 90)},
    }
    return model, meta


def main():
    ships = datasets.load()["shipments"]
    model, meta = train(ships)
    MODELS.mkdir(parents=True, exist_ok=True)
    model.save_model(MODEL_PATH)
    META_PATH.write_text(json.dumps(meta, indent=2))
    print(f"saved {MODEL_PATH.name} and {META_PATH.name}")
    print("metrics:", json.dumps(meta["metrics"], indent=2))
    print("importance:", json.dumps(meta["importance"], indent=2))
    print("score percentiles:", meta["score_percentiles"])


if __name__ == "__main__":
    main()
