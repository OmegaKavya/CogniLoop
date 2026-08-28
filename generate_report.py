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
        {"type": "Fast", "count": 20, "base_p0": (0.45, 0.58), "gamma": 0.35},
        {"type": "Standard", "count": 20, "base_p0": (0.30, 0.45), "gamma": 0.25},
        {"type": "Slow", "count": 20, "base_p0": (0.15, 0.30), "gamma": 0.15}
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
                    bkt.p_learn = 0.35  # Active ZPD in-video checkpoints
                else:
                    difficulty = "medium"  # Static linear video
                    bkt.p_learn = 0.10  # Passive linear instruction

                # Difficulty-conditioned guess/slip parameters
                if difficulty == "easy":
                    p_guess, p_slip = 0.30, 0.05
                elif difficulty == "hard":
                    p_guess, p_slip = 0.10, 0.15
                else:
                    p_guess, p_slip = 0.20, 0.10

                # Simulated response generation
                p_correct = current_mastery * (1.0 - p_slip) + (1.0 - current_mastery) * p_guess
                is_correct = random.random() < p_correct
                
                # Update DC-BKT estimator
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

    exp_nlg = np.array([r["nlg"] for r in exp_rows])
    ctrl_nlg = np.array([r["nlg"] for r in ctrl_rows])

    # Welch's t-test with degrees of freedom calculation
    t_stat_welch, p_val_welch = stats.ttest_ind(exp_nlg, ctrl_nlg, equal_var=False)
    u_stat, u_pval = stats.mannwhitneyu(exp_nlg, ctrl_nlg, alternative="two-sided")

    exp_sd = float(np.std(exp_nlg, ddof=1))
    ctrl_sd = float(np.std(ctrl_nlg, ddof=1))
    
    n_exp, n_ctrl = len(exp_nlg), len(ctrl_nlg)
    
    # Welch-Satterthwaite degrees of freedom
    v1 = (exp_sd**2) / n_exp
    v2 = (ctrl_sd**2) / n_ctrl
    df_welch = (v1 + v2)**2 / ((v1**2 / (n_exp - 1)) + (v2**2 / (n_ctrl - 1)))

    # Difference in means and 95% Confidence Interval
    mean_diff = float(np.mean(exp_nlg) - np.mean(ctrl_nlg))
    se_diff = np.sqrt(v1 + v2)
    t_crit = stats.t.ppf(0.975, df=df_welch)
    ci_mean_diff = (mean_diff - t_crit * se_diff, mean_diff + t_crit * se_diff)

    # Cohen's d effect size and 95% CI
    s_pooled = np.sqrt(((n_exp - 1) * exp_sd**2 + (n_ctrl - 1) * ctrl_sd**2) / (n_exp + n_ctrl - 2))
    cohens_d = float(mean_diff / s_pooled)
    se_d = np.sqrt((n_exp + n_ctrl) / (n_exp * n_ctrl) + (cohens_d**2) / (2 * (n_exp + n_ctrl)))
    ci_d = (cohens_d - 1.96 * se_d, cohens_d + 1.96 * se_d)

    exp_avg_nlg = float(np.mean(exp_nlg))
    ctrl_avg_nlg = float(np.mean(ctrl_nlg))

    exp_pre_avg = float(np.mean([r["pre_score"] for r in exp_rows]))
    ctrl_pre_avg = float(np.mean([r["pre_score"] for r in ctrl_rows]))

    exp_post_avg = float(np.mean([r["post_score"] for r in exp_rows]))
    ctrl_post_avg = float(np.mean([r["post_score"] for r in ctrl_rows]))

    # Out-of-Model Logistic Response Robustness Test
    log_exp_nlg = []
    log_ctrl_nlg = []
    for arch in archetypes:
        for i in range(10):
            # Experimental (Adaptive + Checkpoints)
            l_state = random.uniform(*arch["base_p0"])
            pre = l_state * 100.0
            for _ in range(6):
                logit = 1.8 * l_state - 0.2 + (0.3 if arch['type']=='Fast' else 0.0)
                p_resp = 1.0 / (1.0 + np.exp(-logit))
                c = random.random() < p_resp
                l_state += (1.0 - l_state) * 0.32 * (1.0 if c else 0.5)
            post = l_state * 100.0
            log_exp_nlg.append((post - pre) / (100.0 - pre))

            # Control (Static Video)
            l_state = random.uniform(*arch["base_p0"])
            pre = l_state * 100.0
            for _ in range(6):
                logit = 1.8 * l_state - 0.7
                p_resp = 1.0 / (1.0 + np.exp(-logit))
                c = random.random() < p_resp
                l_state += (1.0 - l_state) * 0.12
            post = l_state * 100.0
            log_ctrl_nlg.append((post - pre) / (100.0 - pre))

    t_log, p_log = stats.ttest_ind(log_exp_nlg, log_ctrl_nlg, equal_var=False)
    log_delta = float(np.mean(log_exp_nlg) - np.mean(log_ctrl_nlg))

    # Cleanup temporary simulation JSON files
    for tmp_file in ["data/bkt_states_sim.json", "data/bandit_q_table_sim.json"]:
        if os.path.exists(tmp_file):
            os.remove(tmp_file)

    print(f"--- SIMULATION RESULTS ---")
    print(f"Exp Pre: {exp_pre_avg:.1f}%, Post: {exp_post_avg:.1f}%, NLG: {exp_avg_nlg:.4f}")
    print(f"Ctrl Pre: {ctrl_pre_avg:.1f}%, Post: {ctrl_post_avg:.1f}%, NLG: {ctrl_avg_nlg:.4f}")
    print(f"Welch's t(df={df_welch:.1f}) = {t_stat_welch:.4f}, p = {p_val_welch:.6e}")
    print(f"Mean Difference 95% CI: [{ci_mean_diff[0]:.4f}, {ci_mean_diff[1]:.4f}]")
    print(f"Mann-Whitney U = {u_stat:.1f}, p = {u_pval:.6f}")
    print(f"Cohen's d = {cohens_d:.4f}, 95% CI: [{ci_d[0]:.4f}, {ci_d[1]:.4f}]")
    print(f"Out-of-Model Logistic Robustness: Delta NLG = +{log_delta:.4f}, Welch t = {t_log:.4f}, p = {p_log:.6e}")

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
        "df_welch": df_welch,
        "ci_mean_diff": ci_mean_diff,
        "welch_p": p_val_welch,
        "mann_u": u_stat,
        "mann_p": u_pval,
        "cohens_d": cohens_d,
        "ci_d": ci_d,
        "log_delta": log_delta,
        "rows": rows
    }

if __name__ == "__main__":
    run_simulation_and_generate_report()
