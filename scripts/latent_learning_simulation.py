"""
Latent-mastery generative model and curriculum-policy comparison.

WHY THIS EXISTS
---------------
The original simulation (generate_report.py) scored learners by reading out the
BKT posterior itself: post_score = current_mastery * 100, where current_mastery
is the estimator's belief about the learner. There is no latent learner state
distinct from the system's belief, which has two consequences:

  (1) The primary experimental effect is injected by assumption. The
      experimental arm is assigned p_learn = 0.35 and the control arm
      p_learn = 0.10, and p_learn enters the BKT posterior update directly.
      The reported "learning gain" restates that assumption.

  (2) Difficulty routing cannot influence learning at all. Difficulty enters
      only through the guess/slip parameters of the *inference* step, never
      through the learning dynamics. A routing policy changes how fast the
      estimator becomes confident, not how much the learner knows.

This module separates latent mastery (theta) from the estimator's belief
(theta_hat). Policies act on theta_hat. Outcomes are measured with a held-out
probe test at a fixed reference difficulty identical across all arms, so the
outcome is not confounded with the difficulty a policy chose to serve.

TWO RESPONSE MODELS
-------------------
"guess-slip" reproduces the deployed system exactly: difficulty is expressed
only by per-tier guess/slip asymptotes.

    P(correct | theta, d) = theta * (1 - s_d) + (1 - theta) * g_d

"irt" adds an explicit item-difficulty location b_d, as in item response
theory, while retaining guess/slip as asymptotes:

    P(correct | theta, d) = g_d + (1 - g_d - s_d) * sigmoid(a * (theta - b_d))

The distinction matters because guess and slip are *measurement* parameters
(how noisily a response reveals knowledge) whereas b_d is an *instructional*
parameter (what the learner is asked to do). Conflating them is the defect
analysed in analyse_tier_calibration().

TWO LEARNING KERNELS
--------------------
"success-target": learning is fastest at a target success rate P_STAR.
    K = exp(-(P(correct) - P_STAR)^2 / (2 * sigma_p^2))
P_STAR = 0.85 follows Wilson, Shenhav, Straccia & Cohen (2019), who derive an
optimal training accuracy of ~85% (optimal error 15.87%) for stochastic
gradient-descent learners. Their demonstrations are on artificial neural
networks and biologically plausible models of animal learning, NOT on human
classroom learning; it is used as a pre-specified parameter, not as empirical
evidence about humans.

"zpd-distance": learning is fastest when item difficulty matches current
mastery, the standard formalisation of Vygotsky's zone of proximal development.
    K = exp(-(theta - b_d)^2 / (2 * sigma_zpd^2))
Requires the "irt" response model, since it refers to b_d.

Both kernels encode the same qualitative claim -- difficulty has an interior
optimum -- which is the content of the desirable-difficulties literature
(Schmidt & Bjork, 1992). Conclusions are reported under both so that the
policy ranking can be checked for robustness to this modelling choice.

All model parameters are fixed before any policy is evaluated. No parameter is
tuned to favour any policy.
"""

import copy
import math
import os
import sys

import numpy as np
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random  # noqa: E402  (after sys.path setup, kept for seeded streams)

TIERS = ["easy", "medium", "hard"]

BASE_CONFIG = {
    # Measurement parameters, identical to backend/bkt/bkt_engine.py
    "guess": {"easy": 0.30, "medium": 0.20, "hard": 0.10},
    "slip": {"easy": 0.05, "medium": 0.10, "hard": 0.15},
    # Instructional difficulty location, used only by the "irt" response model
    "b": {"easy": 0.25, "medium": 0.50, "hard": 0.75},
    "discrimination": 5.0,
    "response_model": "guess-slip",
    "kernel": "success-target",
    "p_star": 0.85,
    "sigma_p": 0.12,
    "sigma_zpd": 0.20,
    "n_steps": 6,
    "p_learn": 0.35,
    "reference_tier": "medium",
    "n_probe_items": 40,
    # Block length for the probe-interleaved controller: one reference-difficulty
    # probe followed by (probe_block - 1) instructional items of a single tier.
    "probe_block": 4,
}

ARCHETYPES = [
    {"type": "Fast", "count": 20, "theta0": (0.45, 0.58), "gamma": 0.35},
    {"type": "Standard", "count": 20, "theta0": (0.30, 0.45), "gamma": 0.25},
    {"type": "Slow", "count": 20, "theta0": (0.15, 0.30), "gamma": 0.15},
]


def cfg_with(**overrides):
    c = copy.deepcopy(BASE_CONFIG)
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(c.get(k), dict):
            c[k].update(v)
        else:
            c[k] = v
    return c


def p_correct(theta, tier, cfg):
    g, s = cfg["guess"][tier], cfg["slip"][tier]
    if cfg["response_model"] == "guess-slip":
        return theta * (1.0 - s) + (1.0 - theta) * g
    z = cfg["discrimination"] * (theta - cfg["b"][tier])
    return g + (1.0 - g - s) / (1.0 + math.exp(-z))


def learning_kernel(theta, tier, cfg):
    if cfg["kernel"] == "difficulty-independent":
        # Learning does not depend on which tier is served. This is the standard
        # assumption when BKT's learn rate is fitted per skill rather than per
        # difficulty, which is how simulated-learner evaluations of difficulty
        # routing are usually built. Under it no routing policy can change what
        # a learner knows, so any difference a policy shows in *estimated*
        # mastery is produced by the estimator, not by learning.
        return 1.0
    if cfg["kernel"] == "success-target":
        p = p_correct(theta, tier, cfg)
        return math.exp(-((p - cfg["p_star"]) ** 2) / (2.0 * cfg["sigma_p"] ** 2))
    if cfg["kernel"] == "zpd-distance":
        if cfg["response_model"] != "irt":
            raise ValueError("zpd-distance kernel requires the irt response model")
        d = theta - cfg["b"][tier]
        return math.exp(-(d ** 2) / (2.0 * cfg["sigma_zpd"] ** 2))
    raise ValueError(cfg["kernel"])


def advance_mastery(theta, tier, gamma, cfg):
    """Latent learning update, independent of the BKT estimator."""
    return theta + gamma * learning_kernel(theta, tier, cfg) * (1.0 - theta)


def bkt_posterior(p_prev, is_correct, tier, cfg):
    """Pure-function mirror of BKTEngine.update_mastery.

    Returns (returned, stored). The live engine returns the full-precision
    posterior but persists round(., 4), so the value read back on the next
    update is the rounded one. Callers carry `stored` forward and use
    `returned` as the current estimate. Verified bit-exact against the engine
    by tests/test_latent_learning_simulation.py.
    """
    g, s = cfg["guess"][tier], cfg["slip"][tier]
    if is_correct:
        ev = (p_prev * (1 - s)) / (p_prev * (1 - s) + (1 - p_prev) * g)
    else:
        ev = (p_prev * s) / (p_prev * s + (1 - p_prev) * (1 - g))
    returned = ev + (1 - ev) * cfg["p_learn"]
    return returned, round(returned, 4)


class ThompsonBandit:
    """Mirror of ContextualBanditAdapter with its design choices made explicit.

    multipliers : utility weights applied to the sampled posterior at selection
    epsilon     : probability of a forced uniform-random action layered on top
                  of Thompson sampling
    """

    # Tier favoured by the cold-start prior for each mastery bin.
    PRIOR_TIER_BY_BIN = {"Low": "easy", "Medium": "medium", "High": "hard"}

    def __init__(self, rng, multipliers=None, epsilon=0.0, mode="maximize",
                 target=None, prior_pseudocount=1.0, prior_scheme="bin"):
        self.rng = rng
        self.multipliers = multipliers or {"easy": 0.8, "medium": 1.0, "hard": 1.2}
        self.epsilon = epsilon
        # "maximize": pick the tier with the highest weighted sampled reward.
        # "target":   pick the tier whose sampled success rate is closest to
        #             `target`. Exploration still comes from posterior sampling,
        #             but the objective is difficulty matching rather than
        #             reward maximisation, which is what an interior learning
        #             optimum requires.
        self.mode = mode
        self.target = target
        # Pseudo-counts favouring the tier matching the mastery bin for a state
        # no learner has reached. 1.0 reproduces a uniform Beta(1, 1) prior.
        self.prior_pseudocount = prior_pseudocount
        self.prior_scheme = prior_scheme
        self.table = {}

    @staticmethod
    def state_key(cluster, mastery):
        if mastery > 0.75:
            b = "High"
        elif mastery > 0.4:
            b = "Medium"
        else:
            b = "Low"
        return f"{cluster}_{b}"

    def _ensure(self, state):
        if state not in self.table:
            if self.prior_scheme == "conservative":
                # Favour the easiest tier regardless of mastery bin: routing a
                # learner above their level costs more than routing below it.
                favoured = "easy"
            else:
                favoured = self.PRIOR_TIER_BY_BIN.get(state.rsplit("_", 1)[-1])
            self.table[state] = {
                a: {"alpha": self.prior_pseudocount if a == favoured else 1.0,
                    "beta": 1.0}
                for a in TIERS
            }

    def get_action(self, cluster, mastery):
        state = self.state_key(cluster, mastery)
        self._ensure(state)
        if self.epsilon > 0.0 and self.rng.random() < self.epsilon:
            return self.rng.choice(TIERS)
        samples = {}
        for a in TIERS:
            node = self.table[state][a]
            samples[a] = self.rng.betavariate(node["alpha"], node["beta"])
        if self.mode == "target":
            return min(TIERS, key=lambda a: abs(samples[a] - self.target))
        return max(TIERS, key=lambda a: samples[a] * self.multipliers[a])

    def update(self, cluster, mastery, action, reward):
        state = self.state_key(cluster, mastery)
        self._ensure(state)
        r = max(0.0, min(1.0, reward))
        self.table[state][action]["alpha"] += r
        self.table[state][action]["beta"] += 1.0 - r


class ProbeGainController:
    """Probe-interleaved credit assignment over difficulty tiers.

    The obstacle this solves: no directly observable signal measures learning.
    Raw correctness rewards easy items because they are easy. The BKT posterior
    delta rewards hard items because a correct answer on a low-guess item is
    strong evidence -- that is correct inference, but it measures information
    gained about the learner, not learning caused in the learner. Both signals
    are confounded with the very choice being evaluated.

    The fix is to measure at a fixed reference difficulty. Instruction is
    delivered in blocks: one reference-difficulty probe, then (B-1) items of a
    single tier. The change between consecutive probe outcomes is a
    difficulty-neutral measurement of progress, and is credited to the tier used
    in the intervening block. Probes are ordinary medium items, so they instruct
    as well as measure; their only cost is forgoing the preferred tier for one
    item per block.

    Posteriors are Beta over the normalised probe delta, keyed by
    (cluster, mastery bin, tier), pooled across learners, and sampled
    Thompson-style. The controller is given no knowledge of the learning model:
    it estimates which tier produces measured progress for each state.
    """

    def __init__(self, rng, prior_strength=1.0):
        self.rng = rng
        self.table = {}
        self.prior = prior_strength

    def _ensure(self, state):
        if state not in self.table:
            self.table[state] = {t: {"alpha": self.prior, "beta": self.prior} for t in TIERS}

    def select(self, state):
        self._ensure(state)
        samples = {t: self.rng.betavariate(self.table[state][t]["alpha"],
                                           self.table[state][t]["beta"]) for t in TIERS}
        return max(TIERS, key=lambda t: samples[t])

    def update(self, state, tier, normalised_gain):
        self._ensure(state)
        g = max(0.0, min(1.0, normalised_gain))
        self.table[state][tier]["alpha"] += g
        self.table[state][tier]["beta"] += 1.0 - g


POLICY_SPECS = {
    "fixed-easy": {"kind": "fixed", "tier": "easy"},
    "fixed-medium": {"kind": "fixed", "tier": "medium"},
    "fixed-hard": {"kind": "fixed", "tier": "hard"},
    "random": {"kind": "random"},
    # Deployed configuration: skewed weights, forced 20% uniform exploration,
    # reward = raw correctness.
    "bandit-production": {"kind": "bandit", "reward": "correctness",
                          "mult": {"easy": 0.8, "medium": 1.0, "hard": 1.2}, "eps": 0.2},
    "bandit-no-epsilon": {"kind": "bandit", "reward": "correctness",
                          "mult": {"easy": 0.8, "medium": 1.0, "hard": 1.2}, "eps": 0.0},
    "bandit-neutral-weights": {"kind": "bandit", "reward": "correctness",
                               "mult": {"easy": 1.0, "medium": 1.0, "hard": 1.0}, "eps": 0.0},
    "bandit-gain-reward": {"kind": "bandit", "reward": "gain",
                           "mult": {"easy": 1.0, "medium": 1.0, "hard": 1.0}, "eps": 0.0},
    # Proposed: Thompson sampling over the per-tier success rate, selecting the
    # tier whose sampled rate is closest to a target rate. Uses strict Bernoulli
    # updates so the Beta posterior is a calibrated estimate of that rate.
    "bandit-target-rate": {"kind": "bandit", "reward": "bernoulli",
                           "mult": {"easy": 1.0, "medium": 1.0, "hard": 1.0}, "eps": 0.0,
                           "mode": "target"},
    # Credit assignment from a raw binary probe delta: unbiased but very noisy,
    # since a single probe outcome carries one bit.
    # The routing configuration as originally deployed: skewed tier weights,
    # forced uniform exploration layered on Thompson sampling, a uniform
    # cold-start prior, and a hardcoded estimator learn rate.
    "deployed-before": {"kind": "bandit", "reward": "correctness",
                        "mult": {"easy": 0.8, "medium": 1.0, "hard": 1.2},
                        "eps": 0.2, "prior": 1.0, "prior_scheme": "bin",
                        "p_learn": 0.35},
    # The configuration after the fixes, matching what the application now runs.
    "deployed-after": {"kind": "bandit", "reward": "correctness",
                       "mult": {"easy": 1.0, "medium": 1.0, "hard": 1.0},
                       "eps": 0.0, "prior": 4.0, "prior_scheme": "conservative",
                       "p_learn": 0.20},
    # Not yet deployed: selects the tier whose sampled success rate is nearest a
    # target rather than the tier with the highest reward.
    "candidate-target-rate": {"kind": "bandit", "reward": "bernoulli",
                              "mult": {"easy": 1.0, "medium": 1.0, "hard": 1.0},
                              "eps": 0.0, "mode": "target", "prior": 4.0,
                              "prior_scheme": "conservative", "p_learn": 0.20},
    "probe-gain-binary": {"kind": "probe-gain", "signal": "binary"},
    # Credit assignment from a reference-tier-only mastery estimate. Probes all
    # share one difficulty, so this estimate stays difficulty-neutral while
    # pooling evidence across probes instead of discarding it.
    "probe-gain-controller": {"kind": "probe-gain", "signal": "bkt"},
    "oracle-estimate": {"kind": "oracle", "use_true": False},
    "oracle-true": {"kind": "oracle", "use_true": True},
}

DEFAULT_POLICIES = list(POLICY_SPECS.keys())


def probe_test(theta, draws, cfg):
    """Held-out test at a fixed reference tier, identical across all arms."""
    return float(np.mean(draws < p_correct(theta, cfg["reference_tier"], cfg)))


def run_policy(policy_name, learners, response_draws, pre_draws, post_draws, rng, cfg):
    spec = POLICY_SPECS[policy_name]

    # A policy may carry its own estimator learn rate, so that a before/after
    # comparison reflects the parameter each configuration actually used. Only
    # the estimator changes; the generative model is held fixed, otherwise the
    # arms would not be comparable.
    if "p_learn" in spec:
        cfg = cfg_with(**{**cfg, "p_learn": spec["p_learn"]})

    bandit = controller = None
    if spec["kind"] == "bandit":
        bandit = ThompsonBandit(rng, spec["mult"], spec["eps"],
                                mode=spec.get("mode", "maximize"),
                                target=cfg.get("bandit_target", cfg["p_star"]),
                                prior_pseudocount=spec.get(
                                    "prior", cfg.get("bandit_prior", 1.0)),
                                prior_scheme=spec.get(
                                    "prior_scheme",
                                    cfg.get("bandit_prior_scheme", "bin")))
    elif spec["kind"] == "probe-gain":
        controller = ProbeGainController(rng)

    block = cfg["probe_block"]
    nlgs, true_gains = [], []
    for idx, lr in enumerate(learners):
        theta = lr["theta0"]
        gamma = lr["gamma"]
        cluster = f"Cluster-{lr['archetype']}"
        theta_hat = lr["theta0"]
        theta_stored = round(lr["theta0"], 4)
        last_probe = block_tier = block_state = None
        # Mastery estimate built only from reference-tier probes, so that the
        # progress signal is never confounded by the tier being credited.
        ref_hat = lr["theta0"]
        ref_stored = round(lr["theta0"], 4)

        pre = probe_test(theta, pre_draws[idx], cfg)

        for step in range(cfg["n_steps"]):
            if spec["kind"] == "fixed":
                tier = spec["tier"]
            elif spec["kind"] == "random":
                tier = TIERS[int(response_draws[idx][step] * 3) % 3]
            elif spec["kind"] == "oracle":
                basis = theta if spec["use_true"] else theta_hat
                tier = max(TIERS, key=lambda a: learning_kernel(basis, a, cfg))
            elif controller is not None:
                if step % block == 0:
                    tier = cfg["reference_tier"]  # measurement probe
                else:
                    if step % block == 1:
                        block_state = ThompsonBandit.state_key(cluster, theta_hat)
                        block_tier = controller.select(block_state)
                    tier = block_tier
            else:
                tier = bandit.get_action(cluster, theta_hat)

            is_correct = response_draws[idx][step] < p_correct(theta, tier, cfg)
            theta = advance_mastery(theta, tier, gamma, cfg)

            hat_prev = theta_hat
            theta_hat, theta_stored = bkt_posterior(theta_stored, is_correct, tier, cfg)

            if bandit is not None:
                if spec["reward"] == "correctness":
                    r = 1.0 if is_correct else 0.3
                elif spec["reward"] == "bernoulli":
                    r = 1.0 if is_correct else 0.0
                else:
                    r = (theta_hat - hat_prev) / max(1e-9, 1.0 - hat_prev)
                bandit.update(cluster, theta_hat, tier, r)

            if controller is not None and step % block == 0:
                # Probes are difficulty-neutral, so change between consecutive
                # probes measures progress without being confounded by the tier
                # whose effect is being credited.
                if spec["signal"] == "binary":
                    probe = 1.0 if is_correct else 0.0
                    gain = None if last_probe is None else (probe - last_probe + 1.0) / 2.0
                else:
                    prev_ref = ref_hat
                    ref_hat, ref_stored = bkt_posterior(
                        ref_stored, is_correct, cfg["reference_tier"], cfg)
                    probe = ref_hat
                    gain = None if last_probe is None else \
                        (ref_hat - prev_ref) / max(1e-9, 1.0 - prev_ref)
                if gain is not None and block_tier is not None:
                    controller.update(block_state, block_tier, gain)
                last_probe = probe

        post = probe_test(theta, post_draws[idx], cfg)
        nlgs.append((post - pre) / max(1e-9, 1.0 - pre))
        true_gains.append(theta - lr["theta0"])

    return np.array(nlgs), np.array(true_gains)


def build_population(rng):
    learners = []
    for arch in ARCHETYPES:
        for _ in range(arch["count"]):
            learners.append({
                "archetype": arch["type"],
                "theta0": rng.uniform(*arch["theta0"]),
                "gamma": arch["gamma"],
            })
    return learners


def trial(seed, cfg, policies):
    """One trial: one learner population, all policies, common random numbers."""
    rng = random.Random(seed)
    nprng = np.random.default_rng(seed)

    learners = build_population(rng)
    n = len(learners)
    response_draws = nprng.random((n, cfg["n_steps"]))
    pre_draws = nprng.random((n, cfg["n_probe_items"]))
    post_draws = nprng.random((n, cfg["n_probe_items"]))

    out = {}
    for pol_idx, name in enumerate(policies):
        # Deterministic per-policy stream; str.__hash__ is salted per process.
        prng = random.Random(seed * 7919 + pol_idx * 104729)
        nlg, tg = run_policy(name, learners, response_draws, pre_draws, post_draws, prng, cfg)
        out[name] = {"nlg": float(nlg.mean()), "true_gain": float(tg.mean())}
    return out


def compare(cfg, n_trials=200, policies=None, baseline="fixed-medium"):
    policies = policies or DEFAULT_POLICIES
    results = [trial(1000 + i, cfg, policies) for i in range(n_trials)]
    base = np.array([r[baseline]["nlg"] for r in results])
    rows = []
    for name in policies:
        arm = np.array([r[name]["nlg"] for r in results])
        tg = float(np.mean([r[name]["true_gain"] for r in results]))
        if name == baseline:
            rows.append({"policy": name, "nlg": arm.mean(), "diff": 0.0,
                         "ci": None, "t": None, "p": None, "d": None, "true_gain": tg})
            continue
        diff = arm - base
        sd = diff.std(ddof=1)
        t, p = stats.ttest_rel(arm, base)
        ci = stats.t.interval(0.95, len(diff) - 1, loc=diff.mean(), scale=stats.sem(diff)) \
            if sd > 0 else (float("nan"), float("nan"))
        rows.append({"policy": name, "nlg": arm.mean(), "diff": diff.mean(), "ci": ci,
                     "t": float(t), "p": float(p),
                     "d": float(diff.mean() / sd) if sd > 0 else float("nan"),
                     "true_gain": tg})
    return rows


def print_table(title, rows):
    print(f"\n{title}")
    print(f"{'policy':<24}{'mean NLG':>10}{'true dTheta':>13}{'vs base':>10}"
          f"{'95% CI':>22}{'p':>12}{'d':>8}")
    print("-" * 99)
    for r in rows:
        if r["ci"] is None:
            print(f"{r['policy']:<24}{r['nlg']:>10.4f}{r['true_gain']:>13.4f}"
                  f"{'baseline':>10}{'--':>22}{'--':>12}{'--':>8}")
        else:
            ci = f"[{r['ci'][0]:+.4f}, {r['ci'][1]:+.4f}]"
            print(f"{r['policy']:<24}{r['nlg']:>10.4f}{r['true_gain']:>13.4f}"
                  f"{r['diff']:>+10.4f}{ci:>22}{r['p']:>12.2e}{r['d']:>8.2f}")


def analyse_tier_calibration(cfg):
    """Mastery at which each tier is ZPD-optimal under the success-target kernel.

    Solving theta*(1-s) + (1-theta)*g = P_STAR gives the mastery level at which
    a tier sits exactly at the optimal success rate. A tier whose maximum
    achievable accuracy (1 - s) is at or below P_STAR is never optimal for any
    attainable mastery.
    """
    print("\nTier calibration under the deployed guess/slip difficulty model")
    print(f"{'tier':<10}{'guess':>8}{'slip':>8}{'max acc (1-s)':>16}{'ZPD-optimal theta':>20}")
    print("-" * 62)
    for t in TIERS:
        g, s = cfg["guess"][t], cfg["slip"][t]
        mx = 1.0 - s
        den = (1.0 - s) - g
        th = (cfg["p_star"] - g) / den
        th_s = f"{th:.4f}" if th <= 1.0 else f"{th:.4f} (unattainable)"
        print(f"{t:<10}{g:>8.2f}{s:>8.2f}{mx:>16.3f}{th_s:>20}")
    print("All three points lie in the top of the mastery scale, and the hard")
    print("tier's maximum accuracy equals P* exactly, so its curve MEETS the")
    print("target only as theta -> 1.")
    print()
    print("Meeting the target is not the same as being the nearest tier, and")
    print("conflating the two was an error in an earlier draft. Taking")
    print("argmin_d |P(correct | theta, d) - P*|, the nearest tier switches at")
    print("theta = 0.889 and theta = 0.966. Both sit inside the top ninth, so")
    print("the optimal action is constant over roughly the lowest nine tenths")
    print("of the range rather than over all of it.")
    print()
    print("The compression depends on the target as well as on guess and slip:")
    print("at P* = 0.65 the same tiers meet it at 0.538, 0.643 and 0.733.")


def main():
    n_trials = int(os.environ.get("N_TRIALS", "200"))
    print(f"Latent-mastery policy comparison | trials={n_trials} learners=60 "
          f"steps={BASE_CONFIG['n_steps']}")
    print("Outcome: NLG on a held-out 40-item probe test at fixed 'medium' "
          "difficulty, identical across arms.")

    analyse_tier_calibration(BASE_CONFIG)

    a = cfg_with(response_model="guess-slip", kernel="success-target")
    print_table("A. As deployed: difficulty via guess/slip only, success-target kernel",
                compare(a, n_trials))

    b = cfg_with(response_model="irt", kernel="success-target")
    print_table("B. Corrected: explicit IRT difficulty b_d, success-target kernel",
                compare(b, n_trials))

    c = cfg_with(response_model="irt", kernel="zpd-distance")
    print_table("C. Corrected: explicit IRT difficulty b_d, ZPD-distance kernel",
                compare(c, n_trials))

    estimator_inflation(n_trials=max(50, n_trials // 2))
    misrouting_cost(n_trials=max(50, n_trials // 2))
    configuration_comparison(n_trials=max(50, n_trials // 2))
    target_sweep(b, c, n_trials=max(50, n_trials // 2))


MODEL_SPECS = (
    ("A", {"response_model": "guess-slip", "kernel": "success-target"}),
    ("B", {"response_model": "irt", "kernel": "success-target"}),
    ("C", {"response_model": "irt", "kernel": "zpd-distance"}),
)


def oracle_fraction(policies, n_steps, n_trials=120, **cfg_overrides):
    """Each policy's NLG as a percentage of the oracle, per model specification.

    Reported against the oracle because the attainable gain differs between
    specifications, so raw NLG is not comparable across them. The worst case
    over specifications is the honest summary: it is what a configuration
    guarantees without knowing which learning model is right.
    """
    scores = {}
    for name, overrides in MODEL_SPECS:
        cfg = cfg_with(**{**overrides, **cfg_overrides}, n_steps=n_steps)
        rows = compare(cfg, n_trials, policies=list(policies) + ["oracle-true"],
                       baseline=policies[0])
        by = {r["policy"]: r["nlg"] for r in rows}
        oracle = by["oracle-true"]
        scores[name] = {p: 100.0 * by[p] / oracle for p in policies}
    return scores


def estimator_inflation(tiers=TIERS, horizons=(2, 3, 5, 8, 12),
                        p_learn_values=(0.10, 0.20), n_trials=200):
    """Measure how much difficulty alone moves the *estimate* without moving learning.

    Run under the difficulty-independent kernel, so every policy produces the
    same latent gain by construction. Whatever separation appears between tiers
    in the estimated gain is therefore attributable entirely to the estimator:
    a correct answer on a low-guess item is stronger evidence of mastery, so
    serving harder items raises the posterior faster without teaching more.

    This matters because simulated-learner evaluations of difficulty routing
    commonly fit BKT's learn rate per skill rather than per difficulty, and then
    report the BKT posterior as the outcome. Under exactly those two choices the
    comparison cannot distinguish a policy that teaches better from one that
    merely asks harder questions.
    """
    def run(cfg, tier):
        true_gain, est_gain = [], []
        for t in range(n_trials):
            seed = 2000 + t
            rng = random.Random(seed)
            nprng = np.random.default_rng(seed)
            learners = build_population(rng)
            draws = nprng.random((len(learners), cfg["n_steps"]))
            for i, lr in enumerate(learners):
                theta = hat = lr["theta0"]
                stored = round(lr["theta0"], 4)
                for step in range(cfg["n_steps"]):
                    correct = draws[i][step] < p_correct(theta, tier, cfg)
                    theta = advance_mastery(theta, tier, lr["gamma"], cfg)
                    hat, stored = bkt_posterior(stored, correct, tier, cfg)
                true_gain.append(theta - lr["theta0"])
                est_gain.append(hat - lr["theta0"])
        return float(np.mean(true_gain)), float(np.mean(est_gain))

    print("\nEstimator inflation under difficulty-independent learning")
    print("Latent gain is identical for every tier by construction, so all "
          "separation below is produced by the estimator.")

    for p_learn in p_learn_values:
        print(f"\n  estimator learn rate = {p_learn}")
        head = (f"  {'items':>6}{'latent gain':>13}"
                + "".join(f"{'est ' + t:>12}" for t in tiers)
                + f"{'hard-easy':>12}{'as % latent':>13}")
        print(head)
        print("  " + "-" * (len(head) - 2))
        for n_steps in horizons:
            cfg = cfg_with(kernel="difficulty-independent",
                           response_model="guess-slip",
                           n_steps=n_steps, p_learn=p_learn)
            latent, _ = run(cfg, tiers[0])
            estimates = {t: run(cfg, t)[1] for t in tiers}
            spread = estimates[tiers[-1]] - estimates[tiers[0]]
            print(f"  {n_steps:>6}{latent:>13.4f}"
                  + "".join(f"{estimates[t]:>12.4f}" for t in tiers)
                  + f"{spread:>+12.4f}{100 * spread / latent:>12.1f}%")

    print("\n  Routing toward harder items can report a materially larger gain "
          "while teaching nothing extra. The effect is largest early and shrinks "
          "as the assumed learn rate saturates the estimate.")


def misrouting_cost(horizons=(6, 24), n_trials=150):
    """Cost of serving one tier above vs one tier below the optimum.

    Measured directly rather than inferred from an estimator's error rates: both
    policies here misroute on every item and differ only in direction, so the
    comparison isolates the cost asymmetry from estimator quality.

    An earlier version of this analysis combined error rates measured under one
    model specification with attainment measured as a worst case across three,
    which made the asymmetry look far larger than it is. The two quantities must
    come from the same experiment.
    """
    def run(cfg, offset):
        gains = []
        for t in range(n_trials):
            seed = 4000 + t
            rng = random.Random(seed)
            nprng = np.random.default_rng(seed)
            learners = build_population(rng)
            nprng.random((len(learners), cfg["n_steps"]))
            for lr in learners:
                theta = lr["theta0"]
                for _ in range(cfg["n_steps"]):
                    best = max(range(len(TIERS)),
                               key=lambda j: learning_kernel(theta, TIERS[j], cfg))
                    tier = TIERS[min(len(TIERS) - 1, max(0, best + offset))]
                    theta = advance_mastery(theta, tier, lr["gamma"], cfg)
                gains.append(theta - lr["theta0"])
        return float(np.mean(gains))

    print("\nCost of mis-routing by one tier, relative to always serving the optimum")
    for n_steps in horizons:
        print(f"\n  horizon {n_steps} items")
        print(f"  {'model':<8}{'optimal':>10}{'too easy':>12}{'too hard':>12}")
        print("  " + "-" * 42)
        for name, overrides in MODEL_SPECS:
            cfg = cfg_with(**overrides, n_steps=n_steps)
            optimal = run(cfg, 0)
            print(f"  {name:<8}{optimal:>10.4f}"
                  f"{100 * (run(cfg, -1) - optimal) / optimal:>11.1f}%"
                  f"{100 * (run(cfg, +1) - optimal) / optimal:>11.1f}%")

    print("\n  The asymmetry is large but its direction is specification-dependent. "
          "Erring easy is the minimax choice because its worst case is bounded "
          "more tightly, not because it is always better.")


def configuration_comparison(n_trials=120):
    """Routing quality before and after the configuration fixes."""
    policies = ["deployed-before", "deployed-after", "candidate-target-rate",
                "fixed-easy", "fixed-medium"]

    print("\nRouting quality as a percentage of the oracle")
    print("Worst case is taken over the three learning-model specifications.")
    header = (f"{'items':>6}" + "".join(f"{p:>22}" for p in policies))
    print(header)
    print("-" * len(header))

    for n_steps in (4, 6, 10, 16, 24, 36, 50):
        scores = oracle_fraction(policies, n_steps, n_trials)
        worst = {p: min(scores[m][p] for m, _ in MODEL_SPECS) for p in policies}
        print(f"{n_steps:>6}" + "".join(f"{worst[p]:>22.1f}" for p in policies))

    print("\nThe fixes improve routing at every course length. Adaptive routing "
          "only overtakes the best fixed policy once a learner answers roughly "
          "ten items; below that a fixed easy curriculum is as good or better.")


def target_sweep(cfg_b, cfg_c, n_trials=100):
    """Sensitivity of the target-rate bandit to its calibration parameter.

    The target success rate is not identifiable from simulation: it is an
    empirical property of real learners. This sweep characterises how much
    performance depends on getting it right, and where the optimum sits under
    each learning kernel.
    """
    targets = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]
    pols = ["fixed-medium", "fixed-easy", "bandit-target-rate",
            "oracle-estimate", "oracle-true"]

    for label, cfg in (("B success-target kernel", cfg_b), ("C ZPD-distance kernel", cfg_c)):
        print(f"\nTarget-rate calibration sweep -- {label}")
        ref = compare(cfg, n_trials, policies=pols)
        by = {r["policy"]: r for r in ref}
        print(f"  reference: best fixed = {max(by['fixed-medium']['nlg'], by['fixed-easy']['nlg']):.4f}"
              f" | oracle-estimate = {by['oracle-estimate']['nlg']:.4f}"
              f" | oracle-true = {by['oracle-true']['nlg']:.4f}")
        print(f"  {'target':>8}{'bandit NLG':>13}{'vs best fixed':>16}")
        best_fixed = max(by["fixed-medium"]["nlg"], by["fixed-easy"]["nlg"])
        for t in targets:
            rows = compare(cfg_with(**{**cfg, "bandit_target": t}), n_trials,
                           policies=["fixed-medium", "bandit-target-rate"])
            nlg = [r for r in rows if r["policy"] == "bandit-target-rate"][0]["nlg"]
            print(f"  {t:>8.2f}{nlg:>13.4f}{nlg - best_fixed:>+16.4f}")


if __name__ == "__main__":
    main()
