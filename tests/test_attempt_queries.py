"""Filtered reads of the attempts document.

These cover the JsonStore implementation. `tests/test_storage_postgres.py`
runs the same contract against Postgres when DATABASE_URL is set, which is the
backend the projection actually saves anything on; the point of testing both
is that a caller must not be able to tell which one it is talking to.
"""
import os

import pytest

from backend.repositories.core_repositories import QuizAttemptRepository
from backend.storage import JsonStore


def _attempt(user_id, topic_id, attempt_id, score=50):
    return {
        "attempt_id": attempt_id,
        "user_id": user_id,
        "topic_id": topic_id,
        "score": score,
        "question_results": [{"text": "a heavy question", "is_correct": True}],
    }


@pytest.fixture
def repo(tmp_path):
    r = QuizAttemptRepository(str(tmp_path / "attempts.json"))
    for a in [
        _attempt("u1", "os", "a1", 10),
        _attempt("u2", "os", "a2", 20),
        _attempt("u1", "dbms", "a3", 30),
        _attempt("u1", "os", "a4", 40),
    ]:
        r.add_attempt(a)
    return r


class TestFilteredReads:
    def test_filters_by_user(self, repo):
        assert [a["attempt_id"] for a in repo.get_user_attempts("u1")] == ["a1", "a3", "a4"]

    def test_filters_by_user_and_topic(self, repo):
        rows = repo.get_user_attempts("u1", topic_id="os")
        assert [a["attempt_id"] for a in rows] == ["a1", "a4"]

    def test_preserves_document_order(self, repo):
        """Callers read the last element as the most recent attempt."""
        assert repo.get_user_attempts("u1")[-1]["attempt_id"] == "a4"
        assert repo.latest_attempt("u1")["attempt_id"] == "a4"

    def test_user_id_compared_as_text(self, tmp_path):
        """An integer user_id must match the string session holds, and vice
        versa. Postgres `->>` always yields text, so the file backend has to
        compare the same way or the two disagree on real data."""
        r = QuizAttemptRepository(str(tmp_path / "a.json"))
        r.add_attempt(_attempt(7, "os", "a1"))
        assert len(r.get_user_attempts("7")) == 1
        assert len(r.get_user_attempts(7)) == 1

    def test_unknown_user_is_empty(self, repo):
        assert repo.get_user_attempts("nobody") == []
        assert repo.latest_attempt("nobody") is None


class TestProjection:
    def test_drops_question_results(self, repo):
        for row in repo.get_user_attempts("u1", include_responses=False):
            assert "question_results" not in row
            assert row["score"] is not None

    def test_keeps_them_by_default(self, repo):
        assert all("question_results" in a for a in repo.get_user_attempts("u1"))

    def test_projection_does_not_mutate_stored_data(self, repo):
        repo.get_user_attempts("u1", include_responses=False)
        assert all("question_results" in a for a in repo.get_user_attempts("u1"))


class TestCount:
    def test_counts_without_fetching(self, repo):
        assert repo.count_user_attempts("u1") == 3
        assert repo.count_user_attempts("u1", topic_id="os") == 2
        assert repo.count_user_attempts("nobody") == 0


class TestSingleAttempt:
    def test_fetches_by_id(self, repo):
        assert repo.get_attempt("u1", "a3")["score"] == 30

    def test_is_scoped_to_its_owner(self, repo):
        """Attempt ids travel in URLs. Looking one up by id alone would let a
        signed-in learner read another learner's answers."""
        assert repo.get_attempt("u1", "a2") is None
        assert repo.get_attempt("u2", "a2") is not None

    def test_missing_id_is_none(self, repo):
        assert repo.get_attempt("u1", "nope") is None

    def test_returns_the_full_attempt(self, repo):
        assert "question_results" in repo.get_attempt("u1", "a1")


class TestAllAttempts:
    def test_returns_every_user(self, repo):
        assert len(repo.all_attempts()) == 4

    def test_can_drop_responses(self, repo):
        assert all("question_results" not in a for a in repo.all_attempts(include_responses=False))


class TestNonListDocuments:
    def test_map_shaped_document_yields_nothing(self, tmp_path):
        """The same table holds map-shaped documents. Asking one for list items
        returns empty rather than raising, on either backend."""
        store = JsonStore(str(tmp_path / "m.json"), default=dict)
        store.write({"a": 1})
        assert store.query_list(match={"user_id": "u1"}) == []
        assert store.count_list() == 0


class TestMatchSemantics:
    """The two backends must agree on what a match value means.

    Found by the round 6 audit, confirmed against a real database, and the
    reason these exist: `match={"flag": True}` returned rows on the file
    backend and nothing on Postgres, because `->>` renders a JSON boolean as
    "true" while `str(True)` is "True". `match={"x": None}` was worse - the
    file backend matched EVERY row whose field was missing.

    `tests/test_storage_postgres.py` asserts the same cases against Postgres.
    Only together do they mean anything: either alone passes while the two
    disagree.
    """

    @pytest.fixture
    def store(self, tmp_path):
        s = JsonStore(str(tmp_path / "rows.json"), default=list)
        s.write([
            {"id": "a", "flag": True, "n": 5},
            {"id": "b", "flag": False, "n": "5"},
            {"id": "c"},
        ])
        return s

    def test_true_matches_as_lowercase(self, store):
        assert [r["id"] for r in store.query_list(match={"flag": True})] == ["a"]

    def test_false_is_not_treated_as_absent(self, store):
        """`False` is a value, not a missing field."""
        assert [r["id"] for r in store.query_list(match={"flag": False})] == ["b"]

    def test_none_means_absent_or_null(self, store):
        assert [r["id"] for r in store.query_list(match={"missing": None})] == ["a", "b", "c"]
        assert [r["id"] for r in store.query_list(match={"flag": None})] == ["c"]

    def test_numbers_compare_as_text_either_way(self, store):
        assert [r["id"] for r in store.query_list(match={"n": 5})] == ["a", "b"]
        assert [r["id"] for r in store.query_list(match={"n": "5"})] == ["a", "b"]

    def test_a_present_field_does_not_match_none(self, store):
        assert store.query_list(match={"id": None}) == []
