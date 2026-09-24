"""Phase 3 — XGBoost model training.

Trains a gradient-boosted classifier to predict whether a supplier will be
disrupted within the next HORIZON_DAYS days. Uses a *time-based* split so
the test set is genuinely in the future relative to training, which is the
honest way to evaluate a forecasting model.

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
    accuracy_score, average_precision_score, f1_score, precision_score,
    recall_score, roc_auc_score, brier_score_loss,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score

from .config import DATA_PROCESSED, FEATURE_KEYS, FEATURES, HORIZON_DAYS, META_PATH, MODEL_PATH, MODELS, RISK_BANDS

TARGET = "target_disruption_7d"

PARAMS = dict(
    n_estimators=300,
    max_depth=4,
    learning_rate=0.04,
    subsample=0.85,
    colsample_bytree=0.85,
    min_child_weight=3,
    reg_lambda=2.0,
    # Every feature is a risk factor (1 = riskiest); force monotone increasing effects.
    monotone_constraints="(1,1,1,1,1,1,1)",
    objective="binary:logistic",
    eval_metric="logloss",
    random_state=42,
)


def train(feats: pd.DataFrame):
    df = feats[feats.label_valid].copy()
    df["date"] = pd.to_datetime(df["date"])
    dates = np.sort(df["date"].unique())
    cutoff = dates[int(len(dates) * 0.8)]
    train_df, test_df = df[df.date < cutoff], df[df.date >= cutoff]

    X_tr, y_tr = train_df[FEATURE_KEYS], train_df[TARGET]
    X_te, y_te = test_df[FEATURE_KEYS], test_df[TARGET]
    pos_weight = float((y_tr == 0).sum() / max(1, (y_tr == 1).sum()))

    model = xgb.XGBClassifier(**PARAMS, scale_pos_weight=1.0)
    model.fit(X_tr, y_tr, eval_set=[(X_te, y_te)], verbose=False)

    proba = model.predict_proba(X_te)[:, 1]
    # Decision threshold tuned on train set for F1 so the "flag" is sensible on imbalanced data.
    tr_proba = model.predict_proba(X_tr)[:, 1]
    grid = np.linspace(0.1, 0.7, 61)
    f1s = [f1_score(y_tr, tr_proba >= t, zero_division=0) for t in grid]
    threshold = float(grid[int(np.argmax(f1s))])
    pred = (proba >= threshold).astype(int)

    metrics = {
        "auc_roc": round(float(roc_auc_score(y_te, proba)), 4),
        "avg_precision": round(float(average_precision_score(y_te, proba)), 4),
        "accuracy": round(float(accuracy_score(y_te, pred)), 4),
        "precision": round(float(precision_score(y_te, pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_te, pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_te, pred, zero_division=0)), 4),
        "brier": round(float(brier_score_loss(y_te, proba)), 4),
        "decision_threshold": round(threshold, 3),
        "base_rate_test": round(float(y_te.mean()), 4),
    }
    cv = StratifiedKFold(5, shuffle=True, random_state=42)
    cv_auc = cross_val_score(xgb.XGBClassifier(**PARAMS), df[FEATURE_KEYS], df[TARGET], cv=cv, scoring="roc_auc")
    metrics["cv_auc_mean"] = round(float(cv_auc.mean()), 4)
    metrics["cv_auc_std"] = round(float(cv_auc.std()), 4)

    booster = model.get_booster()
    gain = booster.get_score(importance_type="gain")
    total = sum(gain.values()) or 1
    importance = {k: round(gain.get(k, 0) / total, 4) for k in FEATURE_KEYS}
    importance = dict(sorted(importance.items(), key=lambda kv: -kv[1]))

    meta = {
        "model": "XGBoost gradient-boosted trees (binary:logistic)",
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "horizon_days": HORIZON_DAYS,
        "target": f"disruption within next {HORIZON_DAYS} days",
        "params": {k: v for k, v in PARAMS.items() if k not in ("objective", "eval_metric")},
        "n_train": int(len(train_df)), "n_test": int(len(test_df)),
        "train_window": [str(train_df.date.min().date()), str(train_df.date.max().date())],
        "test_window": [str(test_df.date.min().date()), str(test_df.date.max().date())],
        "n_suppliers": int(df.supplier_id.nunique()),
        "n_disruption_events": int(feats.disrupted.sum()),
        "features": FEATURES,
        "feature_keys": FEATURE_KEYS,
        "importance": importance,
        "metrics": metrics,
        "risk_bands": [{"band": b, "min": lo, "max": hi} for b, lo, hi in RISK_BANDS],
        "score_percentiles": {str(p): round(float(np.percentile(model.predict_proba(df[FEATURE_KEYS])[:, 1] * 100, p)), 1) for p in (10, 25, 50, 75, 90, 95)},
    }
    return model, meta


def main():
    feats = pd.read_csv(DATA_PROCESSED / "supply_chain_features.csv")
    model, meta = train(feats)
    MODELS.mkdir(parents=True, exist_ok=True)
    model.save_model(MODEL_PATH)
    META_PATH.write_text(json.dumps(meta, indent=2))
    print(f"saved {MODEL_PATH.name} and {META_PATH.name}")
    print("metrics:", json.dumps(meta["metrics"], indent=2))
    print("importance:", json.dumps(meta["importance"], indent=2))
    print("score percentiles:", meta["score_percentiles"])


if __name__ == "__main__":
    main()
