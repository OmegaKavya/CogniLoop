"""
Re-runs the EXACT primary simulation from generate_report.py (same seed,
same archetype definitions, same step loop) but additionally records:
  - per-archetype NLG means/stds for Fig 2
  - per-step mastery trajectories averaged per archetype/group for Fig 3
so both figures are generated from real, reproducible simulation output
instead of hand-typed illustrative arrays.
"""
import random
import json
import numpy as np
from backend.bkt.bkt_engine import BKTEngine
from backend.adaptation.bandit_policy import ContextualBanditAdapter

random.seed(42)
np.random.seed(42)

bkt = BKTEngine(storage_path="data/_fig_bkt.json")
bandit = ContextualBanditAdapter(storage_path="data/_fig_bandit.json")

archetypes = [
    {"type": "Fast", "count": 20, "base_p0": (0.45, 0.58), "gamma": 0.35},
    {"type": "Standard", "count": 20, "base_p0": (0.30, 0.45), "gamma": 0.25},
    {"type": "Slow", "count": 20, "base_p0": (0.15, 0.30), "gamma": 0.15},
]

user_id = 1
rows = []
trajectories = {}  # (archetype, group) -> list of [mastery per step] per profile

for arch in archetypes:
    for i in range(arch["count"]):
        group = "experimental" if (i % 2 == 0) else "control"
        uid = f"SIM-{user_id:03d}"
        p0 = random.uniform(*arch["base_p0"])
        pre_score = round(p0 * 100.0, 1)
        current_mastery = p0
        cluster_name = f"Cluster-{arch['type']}"
        traj = [current_mastery]

        for step in range(6):
            if group == "experimental":
                difficulty = bandit.get_action(cluster_name, current_mastery)
                bkt.p_learn = 0.35
            else:
                difficulty = "medium"
                bkt.p_learn = 0.10

            if difficulty == "easy":
                p_guess, p_slip = 0.30, 0.05
            elif difficulty == "hard":
                p_guess, p_slip = 0.10, 0.15
            else:
                p_guess, p_slip = 0.20, 0.10

            p_correct = current_mastery * (1.0 - p_slip) + (1.0 - current_mastery) * p_guess
            is_correct = random.random() < p_correct
            current_mastery = bkt.update_mastery(uid, "sim_topic", is_correct, difficulty=difficulty)
            traj.append(current_mastery)

            if group == "experimental":
                step_score = 100.0 if is_correct else 30.0
                bandit.update_policy(cluster_name, current_mastery, difficulty, step_score)

        post_score = round(current_mastery * 100.0, 1)
        nlg = round((post_score - pre_score) / (100.0 - pre_score), 4)
        rows.append({"archetype": arch["type"], "group": group, "nlg": nlg})

        key = (arch["type"], group)
        trajectories.setdefault(key, []).append(traj)
        user_id += 1

# --- Fig 2 data: per-archetype NLG mean/std ---
fig2_data = {}
for a in ["Fast", "Standard", "Slow"]:
    for g in ["experimental", "control"]:
        vals = [r["nlg"] for r in rows if r["archetype"] == a and r["group"] == g]
        fig2_data[f"{a}_{g}_mean"] = float(np.mean(vals))
        fig2_data[f"{a}_{g}_std"] = float(np.std(vals, ddof=1))

all_exp = [r["nlg"] for r in rows if r["group"] == "experimental"]
all_ctrl = [r["nlg"] for r in rows if r["group"] == "control"]
fig2_data["Overall_experimental_mean"] = float(np.mean(all_exp))
fig2_data["Overall_experimental_std"] = float(np.std(all_exp, ddof=1))
fig2_data["Overall_control_mean"] = float(np.mean(all_ctrl))
fig2_data["Overall_control_std"] = float(np.std(all_ctrl, ddof=1))

# --- Fig 3 data: per-step mean mastery per archetype/group ---
fig3_data = {}
for (a, g), trajs in trajectories.items():
    arr = np.array(trajs)  # shape (n_profiles, 7) incl. step 0
    fig3_data[f"{a}_{g}"] = arr.mean(axis=0)[1:].tolist()  # steps 1..6

print("=== FIG 2 DATA (per-archetype NLG) ===")
for a in ["Fast", "Standard", "Slow"]:
    print(f"{a}: Exp mean={fig2_data[f'{a}_experimental_mean']:.4f} std={fig2_data[f'{a}_experimental_std']:.4f} | "
          f"Ctrl mean={fig2_data[f'{a}_control_mean']:.4f} std={fig2_data[f'{a}_control_std']:.4f}")
print(f"Overall: Exp mean={fig2_data['Overall_experimental_mean']:.4f} std={fig2_data['Overall_experimental_std']:.4f} | "
      f"Ctrl mean={fig2_data['Overall_control_mean']:.4f} std={fig2_data['Overall_control_std']:.4f}")

print("\n=== FIG 3 DATA (per-step mean mastery) ===")
for key, traj in fig3_data.items():
    print(f"{key}: {[round(v, 3) for v in traj]}")

with open("scripts/_verified_figure_data.json", "w") as f:
    json.dump({"fig2": fig2_data, "fig3": fig3_data}, f, indent=2)

import os
for fpath in ["data/_fig_bkt.json", "data/_fig_bandit.json"]:
    if os.path.exists(fpath):
        os.remove(fpath)
