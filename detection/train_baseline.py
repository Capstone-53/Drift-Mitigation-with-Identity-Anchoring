#!/usr/bin/env python3
"""
Trains the drift-detection baseline from historical data written by
multi_drift_agent.py.

Only rows with drift_type == "normal" are used to fit the model - this
mirrors how you'd do it in production: you don't have "drift" labels
for a live agent, so the model has to learn what NORMAL looks like and
flag deviations from that, rather than being trained to recognize each
drift category directly. The ground-truth drift_type/drift_active
columns in the CSV are only used afterward, in evaluate.py, to check
how well the unsupervised approach did.

Usage:
    python3 train_baseline.py --data /data/multi_drift_dataset.csv \
                               --out  /app/models
"""

import argparse
import json
import os
import pickle
import sys

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, os.path.dirname(__file__))
from feature_extractor import (
    FEATURE_COLUMNS, AgentWindow, read_csv_rows, row_to_feature_vector,
)


def build_feature_matrix(csv_path, only_normal=True):
    windows = {}
    rows_out = []
    for row in read_csv_rows(csv_path):
        if only_normal and row["drift_type"] != "normal":
            continue
        agent_id = row["agent_id"]
        if agent_id not in windows:
            windows[agent_id] = AgentWindow()
        window = windows[agent_id]
        features = window.push(row)
        if not window.warmed_up:
            continue  # skip cold-start rows - see AgentWindow.warmed_up
        rows_out.append(row_to_feature_vector(features))
    return np.array(rows_out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="path to multi_drift_dataset.csv")
    ap.add_argument("--out", default="./models", help="output dir for model artifacts")
    ap.add_argument("--contamination", type=float, default=0.05,
                     help="expected fraction of outliers even within 'normal' data")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    print(f"Reading {args.data} ...")
    X = build_feature_matrix(args.data, only_normal=True)
    if len(X) < 30:
        print(f"ERROR: only {len(X)} normal rows found - need at least ~30 "
              f"(5 minutes of one normal agent) before training is meaningful. "
              f"Let the normal-agents deployment run longer and try again.")
        sys.exit(1)
    print(f"Training on {len(X)} normal-agent rows, {X.shape[1]} features")

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = IsolationForest(
        n_estimators=200,
        contamination=args.contamination,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_scaled)

    # Per-feature mean/std of the NORMAL baseline, used later by
    # drift_detector.py to categorize *which* drift type a flagged
    # agent looks like (largest z-score among a category's features).
    stats = {
        col: {"mean": float(X[:, i].mean()), "std": float(X[:, i].std() + 1e-9)}
        for i, col in enumerate(FEATURE_COLUMNS)
    }

    with open(os.path.join(args.out, "isolation_forest.pkl"), "wb") as f:
        pickle.dump(model, f)
    with open(os.path.join(args.out, "scaler.pkl"), "wb") as f:
        pickle.dump(scaler, f)
    with open(os.path.join(args.out, "baseline_stats.json"), "w") as f:
        json.dump(stats, f, indent=2)

    print(f"Saved model artifacts to {args.out}/")
    print("  isolation_forest.pkl, scaler.pkl, baseline_stats.json")


if __name__ == "__main__":
    main()
