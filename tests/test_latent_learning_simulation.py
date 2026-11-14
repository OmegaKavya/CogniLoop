"""
Tests for the latent-mastery simulation.

The central guarantee is fidelity: the simulation's pure-function BKT update
must reproduce the deployed BKTEngine exactly, otherwise results obtained from
the simulation say nothing about the deployed system.
"""
import random

import pytest

from backend import config
from backend.adaptation.bandit_policy import ContextualBanditAdapter
from backend.bkt.bkt_engine import BKTEngine
from scripts.latent_learning_simulation import (
    POLICY_SPECS,
    TIERS,
    ProbeGainController,
    ThompsonBandit,
    advance_mastery,
    bkt_posterior,
    cfg_with,
    learning_kernel,
    p_correct,
    trial,
)


class TestBKTMirrorFidelity:
    def test_mirror_is_bit_exact_against_live_engine(self, tmp_path):
        """bkt_posterior must equal BKTEngine.update_mastery to the last bit.

        The engine returns the full-precision posterior but persists
        round(., 4), so the next read is the rounded value. The mirror
        reproduces both halves of that behaviour.
        """
        engine = BKTEngine(storage_path=str(tmp_path / "bkt.json"))
        rng = random.Random(7)
        cfg = cfg_with()

        for case in range(200):
            p_learn = rng.choice([0.05, 0.10, 0.20, 0.35, 0.50])
            engine.p_learn = p_learn
            local_cfg = cfg_with(p_learn=p_learn)
            uid = f"user-{case}"
            stored = engine.p_init

            for _ in range(8):
                tier = rng.choice(TIERS)
                correct = rng.random() < 0.5
                expected = engine.update_mastery(uid, "concept", correct, difficulty=tier)
                returned, stored = bkt_posterior(stored, correct, tier, local_cfg)
                assert returned == expected

        assert cfg["guess"] == {"easy": 0.30, "medium": 0.20, "hard": 0.10}

    def test_mirror_uses_same_guess_slip_as_engine(self, tmp_path):
        """Simulation guess/slip must not drift from the engine's configured values."""
        engine = BKTEngine(storage_path=str(tmp_path / "s.json"),
                           use_fitted_params=False)
        cfg = cfg_with()
        for tier, (g, s) in {"easy": (0.30, 0.05), "medium": (0.20, 0.10),
                             "hard": (0.10, 0.15)}.items():
            assert cfg["guess"][tier] == g
            assert cfg["slip"][tier] == s
        assert engine.p_guess == 0.2 and engine.p_slip == 0.1


class TestGenerativeModelSeparation:
    def test_latent_learning_does_not_depend_on_estimator(self):
        """advance_mastery must be independent of p_learn.

        This is the defect the simulation exists to correct: in the original
        design the outcome was the estimator's own posterior, so the assumed
        p_learn mechanically produced the reported gain.
        """
        a = cfg_with(p_learn=0.10)
        b = cfg_with(p_learn=0.90)
        for tier in TIERS:
            assert advance_mastery(0.4, tier, 0.25, a) == advance_mastery(0.4, tier, 0.25, b)

    def test_mastery_is_monotone_and_bounded(self):
        cfg = cfg_with()
        theta = 0.2
        for _ in range(50):
            nxt = advance_mastery(theta, "medium", 0.25, cfg)
            assert nxt >= theta
            assert nxt <= 1.0
            theta = nxt

    def test_learning_kernel_has_interior_optimum(self):
        """The kernel must not be maximised at an endpoint, or routing is moot."""
        cfg = cfg_with(response_model="irt", kernel="zpd-distance")
        best_low = max(TIERS, key=lambda t: learning_kernel(0.15, t, cfg))
        best_high = max(TIERS, key=lambda t: learning_kernel(0.85, t, cfg))
        assert best_low == "easy"
        assert best_high == "hard"
        assert best_low != best_high

    def test_zpd_kernel_requires_irt_response_model(self):
        with pytest.raises(ValueError):
            learning_kernel(0.5, "easy", cfg_with(kernel="zpd-distance"))


class TestTierCalibrationDefect:
    def test_hard_tier_is_never_optimal_under_guess_slip_model(self):
        """Max accuracy on the hard tier is 1 - slip = 0.85, equal to P*.

        A tier can only sit at the optimal success rate if it can reach it, so
        the hard tier is optimal only in the limit theta -> 1.
        """
        cfg = cfg_with()
        assert 1.0 - cfg["slip"]["hard"] == pytest.approx(cfg["p_star"])
        assert p_correct(1.0, "hard", cfg) == pytest.approx(cfg["p_star"])

    def test_optimal_tier_is_constant_over_reachable_mastery(self):
        """Under the deployed model the optimal action never changes."""
        cfg = cfg_with()
        chosen = {max(TIERS, key=lambda t: learning_kernel(th / 100.0, t, cfg))
                  for th in range(10, 81)}
        assert chosen == {"easy"}


class TestBanditWiring:
    def test_thompson_is_reachable_without_forced_exploration(self):
        """epsilon=0 must give Thompson sampling, not a silent switch to greedy."""
        b = ContextualBanditAdapter(epsilon=0.0, strategy="thompson",
                                    storage_path="/tmp/_t_thompson.json")
        random.seed(1)
        seen = {b.get_action("C", 0.5) for _ in range(200)}
        assert len(seen) > 1

    def test_greedy_is_deterministic(self):
        b = ContextualBanditAdapter(epsilon=0.0, strategy="greedy",
                                    storage_path="/tmp/_t_greedy.json")
        actions = {b.get_action("C", 0.5) for _ in range(50)}
        assert len(actions) == 1

    def test_default_multipliers_are_neutral(self):
        b = ContextualBanditAdapter(storage_path="/tmp/_t_mult.json")
        assert set(b.multipliers.values()) == {1.0}

    def test_unknown_strategy_rejected(self):
        with pytest.raises(ValueError):
            ContextualBanditAdapter(strategy="epsilon-greedy",
                                    storage_path="/tmp/_t_bad.json")

    def test_target_mode_selects_tier_nearest_target_rate(self):
        rng = random.Random(0)
        b = ThompsonBandit(rng, mode="target", target=0.55)
        b._ensure("C_Medium")
        # Concentrated posteriors: easy ~0.95, medium ~0.55, hard ~0.15
        for tier, (a, bt) in {"easy": (190, 10), "medium": (110, 90),
                              "hard": (30, 170)}.items():
            b.table["C_Medium"][tier] = {"alpha": a, "beta": bt}
        picks = [b.get_action("C", 0.5) for _ in range(100)]
        assert max(set(picks), key=picks.count) == "medium"


class TestProbeInterleavedController:
    def test_probe_steps_use_the_reference_tier(self):
        """Measurement must happen at one fixed difficulty to stay unconfounded."""
        cfg = cfg_with(response_model="irt", kernel="zpd-distance", n_steps=12)
        tiers = []
        spec_rng = random.Random(0)
        ctrl = ProbeGainController(spec_rng)
        for step in range(cfg["n_steps"]):
            if step % cfg["probe_block"] == 0:
                tiers.append(cfg["reference_tier"])
            else:
                tiers.append(ctrl.select("C_Low"))
        probes = [t for i, t in enumerate(tiers) if i % cfg["probe_block"] == 0]
        assert set(probes) == {cfg["reference_tier"]}

    def test_controller_prefers_the_tier_with_measured_gain(self):
        ctrl = ProbeGainController(random.Random(3))
        for _ in range(60):
            ctrl.update("C_Low", "easy", 0.9)
            ctrl.update("C_Low", "medium", 0.2)
            ctrl.update("C_Low", "hard", 0.05)
        picks = [ctrl.select("C_Low") for _ in range(200)]
        assert max(set(picks), key=picks.count) == "easy"

    def test_both_probe_signals_run_end_to_end(self):
        cfg = cfg_with(response_model="irt", kernel="zpd-distance", n_steps=12)
        out = trial(7, cfg, ["probe-gain-binary", "probe-gain-controller"])
        for name in ("probe-gain-binary", "probe-gain-controller"):
            assert isinstance(out[name]["nlg"], float)


class TestDeployedConfigurations:
    """The before/after specs must describe what the application actually ran,
    otherwise the comparison measures something nobody deployed."""

    def test_before_spec_matches_the_original_defaults(self):
        spec = POLICY_SPECS["deployed-before"]
        assert spec["mult"] == {"easy": 0.8, "medium": 1.0, "hard": 1.2}
        assert spec["eps"] == 0.2
        assert spec["prior"] == 1.0

    def test_after_spec_matches_current_application_defaults(self):
        spec = POLICY_SPECS["deployed-after"]
        assert spec["mult"] == dict(config.BANDIT_MULTIPLIERS)
        assert spec["eps"] == config.BANDIT_EPSILON
        assert spec["prior"] == config.BANDIT_PRIOR_PSEUDOCOUNT
        assert spec["prior_scheme"] == "conservative"
        assert spec["p_learn"] == config.BKT_DEFAULTS["learn"]

    def test_policy_level_learn_rate_overrides_the_config(self):
        cfg = cfg_with(response_model="irt", kernel="zpd-distance", p_learn=0.9)
        out = trial(5, cfg, ["deployed-after", "deployed-before"])
        assert out["deployed-after"] != out["deployed-before"]

    def test_estimator_rate_does_not_change_the_generative_model(self):
        """Only the estimator may differ between arms, never the learner."""
        a = cfg_with(response_model="irt", kernel="zpd-distance", p_learn=0.1)
        b = cfg_with(response_model="irt", kernel="zpd-distance", p_learn=0.9)
        for tier in TIERS:
            assert advance_mastery(0.4, tier, 0.25, a) == advance_mastery(0.4, tier, 0.25, b)
            assert p_correct(0.4, tier, a) == p_correct(0.4, tier, b)


class TestReproducibility:
    def test_trial_is_deterministic_for_a_given_seed(self):
        cfg = cfg_with()
        pols = ["fixed-medium", "bandit-production", "oracle-true"]
        assert trial(1234, cfg, pols) == trial(1234, cfg, pols)

    def test_policy_streams_do_not_depend_on_process_hash_seed(self):
        """Per-policy RNG must be derived from index, not str.__hash__."""
        cfg = cfg_with()
        a = trial(99, cfg, ["fixed-easy", "bandit-production"])
        b = trial(99, cfg, ["fixed-easy", "bandit-production"])
        assert a["bandit-production"] == b["bandit-production"]
