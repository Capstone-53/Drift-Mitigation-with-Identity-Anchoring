"""
Loads the offline-trained baseline and scores live feature vectors.

Two independent signals combine to decide "is this drift":
  1. Isolation Forest - good at catching subtler, correlated
     multivariate patterns spread across several features.
  2. A raw z-score safety net - catches the case Isolation Forest can
     miss: one feature wildly off baseline while ~15 others look
     normal. With many features, IsolationForest's random per-node
     feature selection means most tree splits land on the *boring*
     features before ever touching the genuinely anomalous one, so
     the extreme signal gets diluted ("masked") across the ensemble.
     A direct z-score check has no such blind spot.

If EITHER signal fires, it's drift. Verified empirically: a resource-
drift row 337 std devs off baseline on memory_usage_mib alone was
missed by the Isolation Forest (decision_function stayed positive)
but is caught instantly by the z-score check.

Stage 2 (categorization) stays a simple/interpretable z-score
comparison against the four drift categories' feature groups - for a
mitigation system, being able to say *why* a decision was made matters
more than squeezing out extra ensemble accuracy.
"""

import json
import os
import pickle

from feature_extractor import DRIFT_CATEGORY_FEATURES, row_to_feature_vector

# Any single feature this many standard deviations from baseline counts
# as drift on its own, regardless of what the Isolation Forest says.
STAT_ZSCORE_THRESHOLD = 4.0


class DriftDetector:
    def __init__(self, model_dir):
        with open(os.path.join(model_dir, "isolation_forest.pkl"), "rb") as f:
            self.model = pickle.load(f)
        with open(os.path.join(model_dir, "scaler.pkl"), "rb") as f:
            self.scaler = pickle.load(f)
        with open(os.path.join(model_dir, "baseline_stats.json")) as f:
            self.stats = json.load(f)

    def _zscore(self, features: dict, col: str) -> float:
        s = self.stats[col]
        return (features[col] - s["mean"]) / s["std"]

    def assess(self, features: dict):
        """
        Returns (is_drift: bool, anomaly_score: float, category: str|None, evidence: dict)

        anomaly_score: raw Isolation Forest decision_function output.
        Negative = more anomalous per the ensemble. Note this can stay
        positive even when is_drift is True, if it was the z-score
        safety net (not the ensemble) that fired - it's reported for
        visibility/tuning, not as the sole verdict.
        """
        vec = [row_to_feature_vector(features)]
        vec_scaled = self.scaler.transform(vec)

        iso_is_drift = self.model.predict(vec_scaled)[0] == -1
        anomaly_score = float(self.model.decision_function(vec_scaled)[0])

        zscores = {col: self._zscore(features, col) for col in self.stats}
        max_col, max_z = max(zscores.items(), key=lambda kv: abs(kv[1]))
        stat_is_drift = abs(max_z) > STAT_ZSCORE_THRESHOLD

        is_drift = iso_is_drift or stat_is_drift

        if not is_drift:
            return False, anomaly_score, None, {}

        # Categorize: whichever category's features have the highest
        # average |z-score| against the normal baseline is the best guess.
        category_scores = {}
        evidence = {}
        for category, cols in DRIFT_CATEGORY_FEATURES.items():
            cat_zscores = {c: zscores[c] for c in cols}
            category_scores[category] = sum(abs(z) for z in cat_zscores.values()) / len(cat_zscores)
            evidence[category] = cat_zscores

        best_category = max(category_scores, key=category_scores.get)
        return True, anomaly_score, best_category, evidence[best_category]
