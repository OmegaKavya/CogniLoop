"""
Tests for BKT parameter fitting and the configuration-driven engine.

The fitter replaces pyBKT, which cannot be imported against scikit-learn >= 1.8.
Its correctness is established by parameter recovery: data is generated from
known parameters and the fitter must return approximately those parameters.
"""
import json

import numpy as np
import pytest

from backend import config
from backend.bkt.bkt_engine import BKTEngine
from backend.bkt.fitting import (
    degeneracy_reasons,
    fit_bkt,
    fit_bkt_by_skill,
)


def simulate_sequences(prior, learn, guess, slip, n_learners=400, n_items=15, seed=0):
    """Generate responses from a known BKT process."""
    rng = np.random.default_rng(seed)
    sequences = []
    for _ in range(n_learners):
        known = rng.random() < prior
        seq = []
        for _ in range(n_items):
            p_correct = (1.0 - slip) if known else guess
            seq.append(1 if rng.random() < p_correct else 0)
            if not known and rng.random() < learn:
                known = True
        sequences.append(seq)
    return sequences


class TestParameterRecovery:
    @pytest.mark.parametrize("prior,learn,guess,slip", [
        (0.30, 0.20, 0.20, 0.10),
        (0.50, 0.10, 0.25, 0.05),
        (0.15, 0.35, 0.30, 0.15),
        (0.40, 0.05, 0.10, 0.20),
    ])
    def test_recovers_known_parameters(self, prior, learn, guess, slip):
        seqs = simulate_sequences(prior, learn, guess, slip, seed=int(prior * 1000))
        result = fit_bkt(seqs)

        assert result is not None
        assert not result.degenerate, result.degeneracy_reasons
        assert result.prior == pytest.approx(prior, abs=0.08)
        assert result.learn == pytest.approx(learn, abs=0.08)
        assert result.guess == pytest.approx(guess, abs=0.08)
        assert result.slip == pytest.approx(slip, abs=0.08)

    def test_fit_is_deterministic_for_a_seed(self):
        seqs = simulate_sequences(0.3, 0.2, 0.2, 0.1, n_learners=120, seed=5)
        a, b = fit_bkt(seqs, seed=11), fit_bkt(seqs, seed=11)
        assert a.as_dict() == b.as_dict()

    def test_returns_none_without_data(self):
        assert fit_bkt([]) is None
        assert fit_bkt([[], []]) is None


class TestDegeneracyDetection:
    def test_guess_plus_slip_above_one_is_degenerate(self):
        reasons = degeneracy_reasons(prior=0.3, learn=0.2, guess=0.6, slip=0.5)
        assert any("guess+slip" in r for r in reasons)

    def test_boundary_pinned_parameters_are_degenerate(self):
        assert any("pinned at 0" in r for r in
                   degeneracy_reasons(prior=0.0, learn=0.2, guess=0.2, slip=0.1))
        assert any("slip pinned at bound" in r for r in
                   degeneracy_reasons(prior=0.3, learn=0.2, guess=0.2, slip=0.45))

    def test_sound_parameters_report_no_reasons(self):
        assert degeneracy_reasons(prior=0.3, learn=0.2, guess=0.2, slip=0.1) == []

    def test_all_constant_responses_produce_degenerate_fit(self):
        """No information to separate guess from mastery."""
        result = fit_bkt([[0] * 10 for _ in range(50)])
        assert result is not None
        assert result.degenerate


class TestFitBySkill:
    def _records(self, skill, sequences):
        return [(f"{skill}-u{i}", skill, c)
                for i, seq in enumerate(sequences) for c in seq]

    def test_skills_below_minimum_are_rejected_with_reason(self):
        records = self._records("sparse", [[1, 0], [1, 1]])
        fitted, rejected = fit_bkt_by_skill(records, min_responses=20)
        assert fitted == {}
        assert "sparse" in rejected
        assert "minimum" in rejected["sparse"]

    def test_degenerate_skill_is_rejected_not_returned(self):
        records = self._records("flat", [[0] * 10 for _ in range(30)])
        fitted, rejected = fit_bkt_by_skill(records, min_responses=20)
        assert "flat" not in fitted
        assert "degenerate" in rejected["flat"]

    def test_sound_skill_is_fitted(self):
        seqs = simulate_sequences(0.3, 0.2, 0.2, 0.1, n_learners=150, seed=3)
        fitted, rejected = fit_bkt_by_skill(self._records("good", seqs),
                                            min_responses=20)
        assert "good" in fitted
        assert rejected == {}
        assert not fitted["good"].degenerate


class TestEngineUsesFittedParameters:
    def _write_params(self, tmp_path, skill, params):
        path = tmp_path / "bkt_params.json"
        path.write_text(json.dumps({"skills": {skill: params}}))
        return str(path)

    def test_fitted_learn_rate_is_applied(self, tmp_path):
        """The fitted learn rate must drive the update, not the default."""
        params_path = self._write_params(
            tmp_path, "algebra",
            {"prior": 0.2, "learn": 0.9, "guess": 0.2, "slip": 0.1})
        engine = BKTEngine(storage_path=str(tmp_path / "s.json"),
                           params_path=params_path)
        resolved = engine.params_for("algebra")
        assert resolved["learn"] == 0.9
        assert resolved["prior"] == 0.2

    def test_unfitted_skill_falls_back_to_defaults(self, tmp_path):
        params_path = self._write_params(
            tmp_path, "algebra",
            {"prior": 0.2, "learn": 0.9, "guess": 0.2, "slip": 0.1})
        engine = BKTEngine(storage_path=str(tmp_path / "s.json"),
                           params_path=params_path)
        resolved = engine.params_for("unseen-skill")
        assert resolved["learn"] == config.BKT_DEFAULTS["learn"]

    def test_prior_from_fit_is_used_for_unseen_learner(self, tmp_path):
        params_path = self._write_params(
            tmp_path, "algebra",
            {"prior": 0.77, "learn": 0.2, "guess": 0.2, "slip": 0.1})
        engine = BKTEngine(storage_path=str(tmp_path / "s.json"),
                           params_path=params_path)
        assert engine.get_mastery("new-user", "algebra") == 0.77

    def test_difficulty_tier_supplies_guess_and_slip(self, tmp_path):
        engine = BKTEngine(storage_path=str(tmp_path / "s.json"),
                           use_fitted_params=False)
        hard = engine.params_for("any", difficulty="hard")
        easy = engine.params_for("any", difficulty="easy")
        assert hard["guess"] == config.DIFFICULTY_PARAMS["hard"]["guess"]
        assert easy["slip"] == config.DIFFICULTY_PARAMS["easy"]["slip"]
        assert hard["guess"] < easy["guess"]

    def test_explicit_params_override_defaults(self, tmp_path):
        engine = BKTEngine(storage_path=str(tmp_path / "s.json"),
                           params={"learn": 0.42}, use_fitted_params=False)
        assert engine.params_for("any")["learn"] == 0.42

    def test_missing_params_file_is_not_an_error(self, tmp_path):
        engine = BKTEngine(storage_path=str(tmp_path / "s.json"),
                           params_path=str(tmp_path / "absent.json"))
        assert engine.fitted_params == {}
        assert engine.params_for("any")["learn"] == config.BKT_DEFAULTS["learn"]

    def test_corrupt_params_file_is_not_an_error(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json")
        engine = BKTEngine(storage_path=str(tmp_path / "s.json"),
                           params_path=str(bad))
        assert engine.fitted_params == {}

    def test_fitted_parameters_change_the_posterior(self, tmp_path):
        """End-to-end: a higher fitted learn rate yields a higher posterior."""
        def params_file(name, learn):
            path = tmp_path / name
            path.write_text(json.dumps({"skills": {"s": {
                "prior": 0.3, "learn": learn, "guess": 0.2, "slip": 0.1}}}))
            return str(path)

        e_slow = BKTEngine(storage_path=str(tmp_path / "slow.json"),
                           params_path=params_file("slow_params.json", 0.05))
        e_fast = BKTEngine(storage_path=str(tmp_path / "fast.json"),
                           params_path=params_file("fast_params.json", 0.60))
        m_slow = e_slow.update_mastery("u", "s", True, difficulty="medium")
        m_fast = e_fast.update_mastery("u", "s", True, difficulty="medium")
        assert m_fast > m_slow


class TestConfigLoader:
    def test_accepts_bare_skill_mapping(self, tmp_path):
        p = tmp_path / "p.json"
        p.write_text(json.dumps({"skill": {"prior": 0.4, "learn": 0.3}}))
        loaded = config.load_fitted_bkt_params(str(p))
        assert loaded["skill"]["prior"] == 0.4

    def test_accepts_wrapped_payload(self, tmp_path):
        p = tmp_path / "p.json"
        p.write_text(json.dumps({"fitted_at": "now",
                                 "skills": {"skill": {"prior": 0.4}}}))
        assert config.load_fitted_bkt_params(str(p))["skill"]["prior"] == 0.4
