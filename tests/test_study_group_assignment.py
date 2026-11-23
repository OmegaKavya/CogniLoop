"""Cohort allocation stays balanced at the sizes this is actually run at.

Assignment was `random.choice` per registration. That is unbiased in
expectation and badly unbalanced in practice when N is ten: a fair coin lands
7-3 or worse in 34.7% of runs, measured over 10,000 simulated allocations, and
a pilot that small cannot afford a one-in-three chance of losing a third of
one arm. Filling the smaller cohort keeps the split
even after every single registration, which also means stopping early - or
people dropping out - still leaves something comparable.
"""
import random
import threading

import pytest

from backend.repositories.core_repositories import (
    UserRepository, assign_study_group)


def _users(control, experimental):
    return ([{"study_group": "control"}] * control
            + [{"study_group": "experimental"}] * experimental)


class TestAssignStudyGroup:
    def test_empty_cohort_is_a_coin_flip(self):
        assert assign_study_group([]) in ("control", "experimental")

    def test_fills_the_smaller_cohort(self):
        assert assign_study_group(_users(3, 1)) == "experimental"
        assert assign_study_group(_users(1, 3)) == "control"

    def test_breaks_ties_randomly(self):
        """Not simply alternating, so the next assignment is not fully
        predictable from outside."""
        seen = {assign_study_group(_users(2, 2), rng=random.Random(seed))
                for seed in range(30)}
        assert seen == {"control", "experimental"}

    def test_ignores_users_with_no_cohort(self):
        """Accounts predating the field, or seeded fixtures, must not skew it."""
        assert assign_study_group(_users(2, 0) + [{"name": "no group"}] * 5) == "experimental"

    def test_ignores_unknown_cohort_values(self):
        assert assign_study_group(_users(0, 2) + [{"study_group": "pilot"}]) == "control"

    def test_stays_balanced_over_a_realistic_run(self):
        """The property that matters: after each of twenty registrations the
        two arms never differ by more than one."""
        users = []
        for _ in range(20):
            group = assign_study_group(users)
            users.append({"study_group": group})
            counts = [sum(1 for u in users if u["study_group"] == g)
                      for g in ("control", "experimental")]
            assert abs(counts[0] - counts[1]) <= 1, counts
        assert counts == [10, 10]

    def test_balance_holds_at_the_size_this_is_run_at(self):
        """Ten participants, the real case, always splits 5-5."""
        for seed in range(50):
            rng = random.Random(seed)
            users = []
            for _ in range(10):
                users.append({"study_group": assign_study_group(users, rng=rng)})
            control = sum(1 for u in users if u["study_group"] == "control")
            assert control == 5, f"seed {seed} gave {control}/10 in control"


class TestAssignmentThroughRegistration:
    def test_concurrent_registrations_stay_balanced(self, tmp_path):
        """Allocation reads the existing users, so it must happen inside the
        lock that allocates the id. Outside it, simultaneous registrations
        read the same counts and pick the same arm."""
        repo = UserRepository(str(tmp_path / "users.json"))

        def build(email):
            def make(new_id, users):
                from backend.repositories.core_repositories import assign_study_group
                return {"id": new_id, "email": email, "name": "U",
                        "study_group": assign_study_group(users)}
            return make

        threads = [threading.Thread(target=repo.create,
                                    args=(f"u{i}@test.com", build(f"u{i}@test.com")))
                   for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        users = repo.get_all()
        assert len(users) == 20, "a registration was lost"
        control = sum(1 for u in users if u.get("study_group") == "control")
        assert abs(control - 10) <= 1, f"{control}/20 in control"
