import os
import random
import numpy as np
from scipy import stats
from backend.bkt.bkt_engine import BKTEngine
from backend.adaptation.bandit_policy import ContextualBanditAdapter

def run_simulation_and_generate_report():
    random.seed(42)
    np.random.seed(42)

    bkt = BKTEngine(storage_path="data/bkt_states_sim.json")
    bandit = ContextualBanditAdapter(storage_path="data/bandit_q_table_sim.json")

    # 3 Archetypes with calibrated prior baseline intervals
    archetypes = [
        {"type": "Fast", "count": 20, "base_p0": (0.45, 0.58), "speed": "Fast"},
        {"type": "Standard", "count": 20, "base_p0": (0.30, 0.45), "speed": "Steady"},
        {"type": "Slow", "count": 20, "base_p0": (0.15, 0.30), "speed": "Slow"}
    ]

    user_id = 1
    rows = []

    for arch in archetypes:
        for i in range(arch["count"]):
            group = "experimental" if (i % 2 == 0) else "control"
            uid = f"SIM-{user_id:03d}"
            
            # Initial baseline pre-test score
            p0 = random.uniform(*arch["base_p0"])
            pre_score = round(p0 * 100.0, 1)
            
            current_mastery = p0
            cluster_name = f"Cluster-{arch['type']}"

            # 6 sequential instructional iterations
            for step in range(6):
                if group == "experimental":
                    difficulty = bandit.get_action(cluster_name, current_mastery)
                    bkt.p_learn = 0.35
                else:
                    difficulty = "medium"  # Static linear video
                    bkt.p_learn = 0.10

                # Difficulty-conditioned guess/slip parameters
                if difficulty == "easy":
                    p_guess, p_slip = 0.30, 0.05
                elif difficulty == "hard":
                    p_guess, p_slip = 0.10, 0.15
                else:
                    p_guess, p_slip = 0.20, 0.10

                # Independent observation generation model:
                # P(Correct) = P(L)*(1 - P(S)) + (1 - P(L))*P(G)
                p_correct = current_mastery * (1.0 - p_slip) + (1.0 - current_mastery) * p_guess
                is_correct = random.random() < p_correct
                
                # Bayesian Knowledge Tracing transition
                current_mastery = bkt.update_mastery(uid, "sim_topic", is_correct, difficulty=difficulty)

                if group == "experimental":
                    step_score = 100.0 if is_correct else 30.0
                    bandit.update_policy(cluster_name, current_mastery, difficulty, step_score)

            post_score = round(current_mastery * 100.0, 1)
            nlg = round((post_score - pre_score) / (100.0 - pre_score), 4)

            rows.append({
                "user_id": uid,
                "archetype": arch["type"],
                "group": group,
                "pre_score": pre_score,
                "post_score": post_score,
                "nlg": nlg
            })
            user_id += 1

    exp_rows = [r for r in rows if r["group"] == "experimental"]
    ctrl_rows = [r for r in rows if r["group"] == "control"]

    exp_nlg = [r["nlg"] for r in exp_rows]
    ctrl_nlg = [r["nlg"] for r in ctrl_rows]

    # Welch's t-test (unequal variances assumed for statistical rigor)
    t_stat_welch, p_val_welch = stats.ttest_ind(exp_nlg, ctrl_nlg, equal_var=False)
    t_stat_std, p_val_std = stats.ttest_ind(exp_nlg, ctrl_nlg, equal_var=True)
    u_stat, u_pval = stats.mannwhitneyu(exp_nlg, ctrl_nlg, alternative="two-sided")

    exp_sd = float(np.std(exp_nlg, ddof=1))
    ctrl_sd = float(np.std(ctrl_nlg, ddof=1))
    
    # Cohen's d effect size calculation
    n_exp, n_ctrl = len(exp_nlg), len(ctrl_nlg)
    s_pooled = np.sqrt(((n_exp - 1) * exp_sd**2 + (n_ctrl - 1) * ctrl_sd**2) / (n_exp + n_ctrl - 2))
    cohens_d = float((np.mean(exp_nlg) - np.mean(ctrl_nlg)) / s_pooled)

    exp_avg_nlg = float(np.mean(exp_nlg))
    ctrl_avg_nlg = float(np.mean(ctrl_nlg))

    exp_pre_avg = float(np.mean([r["pre_score"] for r in exp_rows]))
    ctrl_pre_avg = float(np.mean([r["pre_score"] for r in ctrl_rows]))

    exp_post_avg = float(np.mean([r["post_score"] for r in exp_rows]))
    ctrl_post_avg = float(np.mean([r["post_score"] for r in ctrl_rows]))

    # Cleanup temporary simulation JSON files
    for tmp_file in ["data/bkt_states_sim.json", "data/bandit_q_table_sim.json"]:
        if os.path.exists(tmp_file):
            os.remove(tmp_file)

    print(f"--- SIMULATION RESULTS ---")
    print(f"Exp Pre: {exp_pre_avg:.1f}%, Post: {exp_post_avg:.1f}%, NLG: {exp_avg_nlg:.4f}")
    print(f"Ctrl Pre: {ctrl_pre_avg:.1f}%, Post: {ctrl_post_avg:.1f}%, NLG: {ctrl_avg_nlg:.4f}")
    print(f"Welch's t-statistic: {t_stat_welch:.4f}, p-value: {p_val_welch:.6e}")
    print(f"Student's t-statistic: {t_stat_std:.4f}, p-value: {p_val_std:.6e}")
    print(f"Mann-Whitney U: {u_stat:.1f}, p-value: {u_pval:.6f}")
    print(f"Cohen's d: {cohens_d:.4f}")

    return {
        "exp_pre": exp_pre_avg,
        "ctrl_pre": ctrl_pre_avg,
        "exp_post": exp_post_avg,
        "ctrl_post": ctrl_post_avg,
        "exp_nlg": exp_avg_nlg,
        "ctrl_nlg": ctrl_avg_nlg,
        "exp_sd": exp_sd,
        "ctrl_sd": ctrl_sd,
        "welch_t": t_stat_welch,
        "welch_p": p_val_welch,
        "mann_u": u_stat,
        "mann_p": u_pval,
        "cohens_d": cohens_d,
        "rows": rows
    }

if __name__ == "__main__":
    run_simulation_and_generate_report()
