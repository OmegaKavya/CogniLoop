import json
import os
import sys
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from backend import config  # noqa: E402
from backend.adaptation.micro_pattern import _write_atomically  # noqa: E402
from backend.bkt.fitting import fit_bkt_by_skill  # noqa: E402
from backend.storage import open_store  # noqa: E402


# Both read through the storage layer, so with DATABASE_URL set this trains on
# what production recorded, and without it on the local JSON files. It used to
# open data/*.json directly, which against a Postgres deployment meant fitting
# on whatever stale local copy happened to exist.


def train_clustering():
    print("--- Training Micro-Pattern Clustering Model ---")
    # One implementation: the one the application loads from.
    from backend.adaptation.micro_pattern import mp_manager
    if mp_manager.train_model():
        print(f"Saved clustering model to {config.CLUSTERING_MODEL_PATH}")
    else:
        print("Not trained: scikit-learn is missing, or there are fewer than 5 "
              "usable behaviour records.")

def train_bkt():
    """Fit per-skill BKT parameters and write them where the engine reads them.

    Parameters are written as JSON rather than a pickle so they can be
    inspected, diffed and overridden, and so loading them does not execute
    arbitrary code.
    """
    print("\n--- Fitting BKT parameters ---")

    data = open_store(config.QUIZ_ATTEMPTS_PATH, default=list).read()
    data = [a for a in data if isinstance(a, dict)] if isinstance(data, list) else []
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

    _write_atomically(config.BKT_PARAMS_PATH,
                      json.dumps(payload, indent=2).encode("utf-8"))

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
