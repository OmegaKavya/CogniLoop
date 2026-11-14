import json
import os
import pickle
import sys
import pandas as pd
import numpy as np
from sklearn.cluster import KMeans
from sklearn import __version__ as sklearn_version
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from backend import config  # noqa: E402
from backend.bkt.fitting import fit_bkt_by_skill  # noqa: E402


DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
MODELS_DIR = os.path.join(PROJECT_ROOT, 'models')

MICRO_PATTERNS_FILE = os.path.join(DATA_DIR, 'micro_patterns.json')
QUIZ_ATTEMPTS_FILE = os.path.join(DATA_DIR, 'quiz_attempts.json')
CLUSTERING_MODEL_PATH = os.path.join(MODELS_DIR, 'clustering_model.pkl')
BKT_MODEL_PATH = os.path.join(MODELS_DIR, 'bkt_model.pkl')
FEATURE_COLUMNS = ['pause_count', 'rewatch_count', 'skip_ratio', 'watch_percentage']

def ensure_dir(directory):
    if not os.path.exists(directory):
        os.makedirs(directory)

def load_json(filepath):
    if not os.path.exists(filepath):
        print(f"Warning: File not found at {filepath}")
        return []
    with open(filepath, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            print(f"Error: Could not decode JSON from {filepath}")
            return []

def train_clustering():
    print("--- Training Micro-Pattern Clustering Model ---")
    data = load_json(MICRO_PATTERNS_FILE)
    if len(data) < 5:
        print(f"Insufficient data for clustering (found {len(data)}, need at least 5). Skipping.")
        return

    df = pd.DataFrame(data)
    X = df[FEATURE_COLUMNS]
    
    print(f"Fitting KMeans on {len(data)} interaction records...")
    kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
    kmeans.fit(X)
    
    ensure_dir(MODELS_DIR)
    with open(CLUSTERING_MODEL_PATH, 'wb') as f:
        pickle.dump({
            'model': kmeans,
            'sklearn_version': sklearn_version,
            'feature_columns': FEATURE_COLUMNS
        }, f)
    print(f"Successfully saved clustering model to {CLUSTERING_MODEL_PATH}")

def train_bkt():
    """Fit per-skill BKT parameters and write them where the engine reads them.

    Parameters are written as JSON rather than a pickle so they can be
    inspected, diffed and overridden, and so loading them does not execute
    arbitrary code.
    """
    print("\n--- Fitting BKT parameters ---")

    data = load_json(QUIZ_ATTEMPTS_FILE)
    if not data:
        print("No quiz attempts found. Skipping BKT fitting.")
        return

    records = []
    for attempt in data:
        user_id = attempt.get('user_id')
        skill = attempt.get('topic_id')
        if not user_id or not skill:
            continue
        correct = attempt.get('score', 0) >= config.MASTERY_CORRECT_THRESHOLD
        records.append((user_id, skill, correct))

    if not records:
        print("No usable (user, skill, score) records. Skipping BKT fitting.")
        return

    print(f"Fitting on {len(records)} responses "
          f"(threshold: score >= {config.MASTERY_CORRECT_THRESHOLD:g} counts as correct)...")

    fitted, rejected = fit_bkt_by_skill(
        records,
        min_responses=config.BKT_FIT_MIN_RESPONSES,
        max_iterations=config.BKT_FIT_MAX_ITERATIONS,
        tolerance=config.BKT_FIT_TOLERANCE,
        max_guess=config.BKT_FIT_MAX_GUESS,
        max_slip=config.BKT_FIT_MAX_SLIP,
    )

    for skill, reason in sorted(rejected.items()):
        print(f"  skipped {skill}: {reason}")

    if not fitted:
        print("No skill produced a usable fit; the engine will use configured "
              "defaults. This is the safe outcome, not a failure: a parameter "
              "the data cannot identify is worse than an honest default.")
        return

    payload = {
        "fitted_at": datetime.now().isoformat(timespec="seconds"),
        "min_responses": config.BKT_FIT_MIN_RESPONSES,
        "skills": {skill: result.as_dict() for skill, result in fitted.items()},
    }

    ensure_dir(MODELS_DIR)
    with open(config.BKT_PARAMS_PATH, 'w') as f:
        json.dump(payload, f, indent=2)

    for skill, result in sorted(fitted.items()):
        print(f"  {skill}: prior={result.prior:.3f} learn={result.learn:.3f} "
              f"guess={result.guess:.3f} slip={result.slip:.3f} "
              f"(n={result.n_responses}, converged={result.converged})")
    print(f"Saved {len(fitted)} skill parameter set(s) to {config.BKT_PARAMS_PATH}")

if __name__ == "__main__":
    print(f"Model Training Session - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Project Root: {PROJECT_ROOT}")
    train_clustering()
    train_bkt()
    print("\nAll training tasks completed successfully.")
