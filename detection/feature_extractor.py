"""
Feature extraction shared by both offline baseline training and the
real-time monitor. Keeping this in one module guarantees the features
used to train the model are computed exactly the same way as the
features used to score live data - a common source of silent bugs in
drift detection pipelines.
"""

from collections import deque, defaultdict

# Columns straight from multi_drift_agent.py's CSV header
RAW_NUMERIC_COLUMNS = [
    "cpu_percent", "memory_usage_mib", "memory_percent",
    "network_tx_bytes", "network_rx_bytes",
    "disk_read_bytes", "disk_write_bytes", "open_file_descriptors",
    "request_rate_per_min", "error_rate",
    "state_transitions", "avg_task_execution_ms",
]

# The final feature vector fed to the model. Rolling means smooth out
# noise; deltas capture rate-of-change, which is often a stronger drift
# signal than the raw level (a slow climb in error_rate looks different
# from a sudden jump even if both land at the same value).
FEATURE_COLUMNS = [
    "cpu_percent", "memory_usage_mib", "network_tx_bytes", "network_rx_bytes",
    "disk_write_bytes", "open_file_descriptors", "request_rate_per_min",
    "error_rate", "state_transitions", "avg_task_execution_ms",
    "error_rate_rolling_mean", "cpu_percent_rolling_mean",
    "avg_task_execution_ms_rolling_mean",
    "error_rate_delta", "cpu_percent_delta", "avg_task_execution_ms_delta",
]

# Which raw features feed each drift category, per the mitigation
# strategy table in the project doc. Used by drift_detector.py to turn
# "this agent is anomalous" into "this looks like a communication drift".
DRIFT_CATEGORY_FEATURES = {
    "performance": ["error_rate", "avg_task_execution_ms"],
    "resource": ["cpu_percent", "memory_usage_mib", "open_file_descriptors"],
    "communication": ["network_tx_bytes", "network_rx_bytes"],
    "operational": ["state_transitions", "request_rate_per_min"],
}

ROLLING_WINDOW = 6  # ~1 minute at the agent's 10s collection interval


class AgentWindow:
    """Rolling history for a single agent_id, used to compute rolling
    mean / delta features as new rows arrive in real time."""

    def __init__(self, window=ROLLING_WINDOW):
        self.window = window
        self.history = defaultdict(lambda: deque(maxlen=window))
        self.last_row = None
        self.samples_seen = 0

    @property
    def warmed_up(self) -> bool:
        """False for an agent's first `window` cycles (e.g. right after
        a pod (re)starts). psutil's cpu_percent() always reads 0.0 on
        its first call, and a fresh process's memory/fd usage is
        naturally lower than steady-state - both look like anomalies
        to the model even though they're just cold-start artifacts,
        not real drift. Callers should skip mitigation until this is
        True, same as the identity layer filters on
        identity_source == "grpc-verified" past its own warmup."""
        return self.samples_seen >= self.window

    def push(self, row: dict) -> dict:
        """Add a new raw row, return the engineered feature dict."""
        self.samples_seen += 1
        for col in ["error_rate", "cpu_percent", "avg_task_execution_ms"]:
            self.history[col].append(float(row[col]))

        features = {col: float(row[col]) for col in RAW_NUMERIC_COLUMNS}

        for col in ["error_rate", "cpu_percent", "avg_task_execution_ms"]:
            hist = self.history[col]
            features[f"{col}_rolling_mean"] = sum(hist) / len(hist)
            prev = float(self.last_row[col]) if self.last_row else float(row[col])
            features[f"{col}_delta"] = float(row[col]) - prev

        self.last_row = row
        return features


def row_to_feature_vector(features: dict):
    """Order a feature dict into the fixed vector the model expects."""
    return [features[c] for c in FEATURE_COLUMNS]


def read_csv_rows(path):
    """Robust CSV reader - skips malformed rows from concurrent writes
    by multiple agent pods, same issue you hit with the K8s dataset
    before. Yields dicts."""
    import csv
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        expected = reader.fieldnames
        for row in reader:
            if None in row.values() or len(row) != len(expected):
                continue
            try:
                for col in RAW_NUMERIC_COLUMNS:
                    float(row[col])
            except (KeyError, ValueError, TypeError):
                continue
            yield row
