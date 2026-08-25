#!/usr/bin/env python3
"""
Closed-loop real-time monitor:
    tail shared CSV -> feature_extractor -> drift_detector -> enforcer

Run this as its own pod (see k8s/monitor-deployment.yaml), mounting the
SAME hostPath volume the data-generation agents write to.

This process only READS the CSV - it never writes to it, so it can't
corrupt the data-generation agents' writes. It tracks its own byte
offset into the file so a restart resumes tailing rather than
re-processing everything from scratch.
"""

import csv
import io
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "detection"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mitigation"))

from feature_extractor import AgentWindow, RAW_NUMERIC_COLUMNS
from drift_detector import DriftDetector
from enforcer import MitigationEnforcer

DATA_FILE = os.getenv("DATA_FILE", "/data/multi_drift_dataset.csv")
MODEL_DIR = os.getenv("MODEL_DIR", "/app/models")
POLL_SECONDS = float(os.getenv("POLL_SECONDS", "5"))
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"


def wait_for_baseline():
    required = ["isolation_forest.pkl", "scaler.pkl", "baseline_stats.json"]
    while not all(os.path.exists(os.path.join(MODEL_DIR, f)) for f in required):
        print(f"[monitor] waiting for baseline model in {MODEL_DIR} "
              f"(run train_baseline.py first) ...")
        time.sleep(10)


def tail_new_rows(offset, header):
    """Read any bytes appended to DATA_FILE since `offset`, parse
    complete CSV rows out of them, return (rows, new_offset)."""
    if not os.path.exists(DATA_FILE):
        return [], offset

    size = os.path.getsize(DATA_FILE)
    if size <= offset:
        return [], offset

    with open(DATA_FILE, "r", newline="") as f:
        f.seek(offset)
        chunk = f.read()
        new_offset = f.tell()

    # Only keep complete lines - the last line may be a partial write
    # from another pod mid-append.
    lines = chunk.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        incomplete = lines.pop()
        new_offset -= len(incomplete.encode())

    if not lines:
        return [], offset

    rows = []
    reader = csv.DictReader(io.StringIO("".join(lines)), fieldnames=header)
    for row in reader:
        if None in row.values() or len(row) != len(header):
            continue
        try:
            for col in RAW_NUMERIC_COLUMNS:
                float(row[col])
        except (KeyError, ValueError, TypeError):
            continue
        rows.append(row)

    return rows, new_offset


def read_header():
    with open(DATA_FILE, newline="") as f:
        return next(csv.reader(f))


def main():
    print("=" * 60)
    print("Real-time drift monitor starting")
    print(f"  data file : {DATA_FILE}")
    print(f"  model dir : {MODEL_DIR}")
    print(f"  dry run   : {DRY_RUN}")
    print("=" * 60)

    while not os.path.exists(DATA_FILE):
        print(f"[monitor] waiting for {DATA_FILE} to be created by an agent ...")
        time.sleep(10)

    wait_for_baseline()
    detector = DriftDetector(MODEL_DIR)
    enforcer = None if DRY_RUN else MitigationEnforcer()

    header = read_header()
    offset = len(",".join(header)) + 1  # skip past the header line
    windows = {}  # agent_id -> AgentWindow

    print("[monitor] baseline loaded, entering watch loop")

    while True:
        rows, offset = tail_new_rows(offset, header)

        for row in rows:
            agent_id = row["agent_id"]
            if agent_id not in windows:
                windows[agent_id] = AgentWindow()
            window = windows[agent_id]
            features = window.push(row)

            is_drift, score, category, evidence = detector.assess(features)

            true_label = "DRIFT" if row["drift_active"] == "1" else "normal"
            verdict = "DRIFT" if is_drift else "normal"
            match = "match" if verdict == true_label else "MISMATCH"

            if not window.warmed_up:
                print(f"[monitor] agent={agent_id:28s} WARMING UP "
                      f"({window.samples_seen}/{window.window}) - skipping mitigation")
                continue

            print(f"[monitor] agent={agent_id:28s} score={score:+.3f} "
                  f"predicted={verdict:6s} category={str(category):14s} "
                  f"ground_truth={true_label:6s} ({match})")

            if is_drift and enforcer is not None:
                enforcer.mitigate(agent_id, category, evidence)
            elif is_drift and DRY_RUN:
                print(f"[monitor] DRY_RUN=true - would mitigate {agent_id} "
                      f"as {category}: {evidence}")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
