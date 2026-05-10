"""
Unit Tests: Contextual Bandit Policy
Covers: state key generation, action selection, Q-value updates, exploration/exploitation.
"""
import os
import json
import tempfile
import pytest
from backend.adaptation.bandit_policy import ContextualBanditAdapter


@pytest.fixture
def bandit(tmp_path):
    storage = str(tmp_path / "q_table.json")
    return ContextualBanditAdapter(epsilon=0.0, storage_path=storage)  # epsilon=0 forces exploit


@pytest.fixture
def bandit_explore(tmp_path):
    storage = str(tmp_path / "q_table_explore.json")
    return ContextualBanditAdapter(epsilon=1.0, storage_path=storage)  # epsilon=1 forces explore


class TestBanditStateKey:
    def test_high_mastery(self, bandit):
        assert bandit._get_state_key("General Learner", 0.9) == "General Learner_High"

    def test_medium_mastery(self, bandit):
        assert bandit._get_state_key("Passive Viewer", 0.6) == "Passive Viewer_Medium"

    def test_low_mastery(self, bandit):
        assert bandit._get_state_key("Active Learner", 0.2) == "Active Learner_Low"

    def test_boundary_high(self, bandit):
        # 0.75 uses strict > so 0.75 itself falls to Medium, 0.76 is High
        assert bandit._get_state_key("G", 0.75) == "G_Medium"
        assert bandit._get_state_key("G", 0.76) == "G_High"

    def test_boundary_medium(self, bandit):
        # 0.4 uses strict > so 0.4 itself falls to Low, 0.41 is Medium
        assert bandit._get_state_key("G", 0.4) == "G_Low"
        assert bandit._get_state_key("G", 0.41) == "G_Medium"


class TestBanditGetAction:
    def test_returns_valid_action(self, bandit):
        action = bandit.get_action("General Learner", 0.5)
        assert action in ["easy", "medium", "hard"]

    def test_exploit_selects_best_q_value(self, bandit):
        # Manually set Q-table so "hard" is clearly best
        state = "General Learner_Medium"
        bandit.q_table[state] = {
            "easy":   {"q_value": 0.3, "count": 5},
            "medium": {"q_value": 0.5, "count": 5},
            "hard":   {"q_value": 0.9, "count": 5},
        }
        action = bandit.get_action("General Learner", 0.6)
        assert action == "hard"

    def test_explore_does_not_crash(self, bandit_explore):
        # With epsilon=1.0, should always explore (random) without raising
        for _ in range(20):
            action = bandit_explore.get_action("General Learner", 0.5)
            assert action in ["easy", "medium", "hard"]

    def test_new_state_gets_initialized(self, bandit):
        bandit.get_action("Brand New Cluster", 0.1)
        state = "Brand New Cluster_Low"
        assert state in bandit.q_table
        for a in ["easy", "medium", "hard"]:
            assert bandit.q_table[state][a]["q_value"] == 0.5

    def test_q_table_persisted_to_disk(self, bandit):
        bandit.get_action("General Learner", 0.3)
        assert os.path.exists(bandit.storage_path)
        with open(bandit.storage_path) as f:
            data = json.load(f)
        assert len(data) > 0


class TestBanditUpdatePolicy:
    def test_high_score_increases_q_value(self, bandit):
        bandit.get_action("General Learner", 0.5)  # Initialize state
        state = "General Learner_Medium"
        old_q = bandit.q_table[state]["hard"]["q_value"]
        bandit.update_policy("General Learner", 0.5, "hard", score=100)
        new_q = bandit.q_table[state]["hard"]["q_value"]
        assert new_q > old_q  # reward(1.0*1.2=1.2) > initial(0.5)

    def test_low_score_decreases_q_value(self, bandit):
        bandit.get_action("General Learner", 0.5)
        state = "General Learner_Medium"
        old_q = bandit.q_table[state]["hard"]["q_value"]
        bandit.update_policy("General Learner", 0.5, "hard", score=0)
        new_q = bandit.q_table[state]["hard"]["q_value"]
        assert new_q < old_q  # reward(0) < initial(0.5)

    def test_count_increments(self, bandit):
        bandit.get_action("General Learner", 0.5)
        state = "General Learner_Medium"
        bandit.update_policy("General Learner", 0.5, "medium", score=70)
        assert bandit.q_table[state]["medium"]["count"] == 1
        bandit.update_policy("General Learner", 0.5, "medium", score=80)
        assert bandit.q_table[state]["medium"]["count"] == 2

    def test_invalid_action_does_not_crash(self, bandit):
        bandit.update_policy("General Learner", 0.5, "ultra_hard", score=100)

    def test_convergence_over_episodes(self, bandit):
        """After many correct 'hard' answers, hard should be the greedy choice."""
        for _ in range(20):
            bandit.update_policy("General Learner", 0.5, "hard", score=90)
        state = "General Learner_Medium"
        best = max(bandit.q_table[state], key=lambda a: bandit.q_table[state][a]["q_value"])
        assert best == "hard"
