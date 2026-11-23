"""Integration tests for the Postgres store.

These need a real database and are skipped without one, so the default suite
and CI stay dependency-free:

    DATABASE_URL=postgresql://... PYTHONPATH=. pytest tests/test_storage_postgres.py

They use their own key namespace (`tests/_pg_*`) and delete it afterwards, so
running them against the production database cannot touch application data.
That matters because the obvious way to test this is to point it at the only
database you have.

What is actually being tested is the CONTRACT, not psycopg. `PgStore` is only
correct if it is indistinguishable from `JsonStore` to a caller, so most of
these assert the same behaviours `tests/test_storage.py` asserts of the file
backend, against the same expectations.
"""
import json
import os
import threading
import uuid

import pytest

# conftest blanks DATABASE_URL before the application is imported, so the rest
# of the suite cannot reach a real database by accident. This module is the
# opt-in and puts the URL back - but ONLY while its own tests are running.
#
# The obvious version of this, assigning os.environ at module level, is wrong
# and was briefly shipped. Module bodies execute during COLLECTION, before any
# test runs, so it restored the variable for the entire session and every
# later test went back to writing into the real database. It repolluted the
# production database with 51 documents on 23 Nov 2026, which is the same
# defect the conftest change exists to prevent. A fixture is what confines it
# to this module, because fixtures run at test time, not collection time.
_PG_URL = os.environ.get("_PG_TEST_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not _PG_URL,
    reason="DATABASE_URL is not set; Postgres integration tests are opt-in",
)


@pytest.fixture
def pg_env():
    """Expose DATABASE_URL for one test, then take it away again."""
    previous = os.environ.get("DATABASE_URL", "")
    os.environ["DATABASE_URL"] = _PG_URL
    try:
        yield _PG_URL
    finally:
        os.environ["DATABASE_URL"] = previous


@pytest.fixture
def store_factory(pg_env):
    """Hand out stores under a unique key prefix, and clean up after."""
    from backend.storage_pg import PgStore, TABLE, pool

    created = []
    prefix = f"tests/_pg_{uuid.uuid4().hex[:8]}"

    def make(name, default=None):
        store = PgStore(f"{prefix}_{name}.json", default=default)
        created.append(store.key)
        return store

    yield make

    with pool().connection() as conn:
        with conn.cursor() as cur:
            for key in created:
                cur.execute(f"DELETE FROM {TABLE} WHERE key = %s", (key,))
        conn.commit()


class TestContract:
    def test_absent_document_reads_as_the_default(self, store_factory):
        assert store_factory("absent").read() == {}
        assert store_factory("absent_list", default=list).read() == []

    def test_write_then_read_round_trips(self, store_factory):
        store = store_factory("round")
        payload = {"a": 1, "nested": {"b": [1, 2, 3]}, "unicode": "तमिल"}
        store.write(payload)
        assert store.read() == payload

    def test_update_returns_the_mutator_result_and_persists_the_data(self, store_factory):
        store = store_factory("update")
        store.write({"n": 1})
        result = store.update(lambda d: d.update({"n": d["n"] + 1}) or "done")
        assert result == "done"
        assert store.read() == {"n": 2}

    def test_update_replacing_persists_the_returned_value(self, store_factory):
        """Required for list documents.

        A mutator cannot replace the caller's object by rebinding its own
        parameter, so a document whose top level is a list has to come back as
        a return value. micro_patterns.json is exactly this shape.
        """
        store = store_factory("replacing", default=list)
        store.write([1, 2])
        out = store.update_replacing(lambda d: d + [3], default=list)
        assert out == [1, 2, 3]
        assert store.read() == [1, 2, 3]

    def test_ensure_exists_creates_but_does_not_clobber(self, store_factory):
        store = store_factory("ensure")
        store.ensure_exists()
        assert store.read() == {}
        store.write({"kept": True})
        store.ensure_exists()
        assert store.read() == {"kept": True}


class TestConcurrency:
    def test_concurrent_updates_do_not_lose_writes(self, store_factory):
        """The defect this whole class exists to prevent.

        With an unsynchronised read-modify-write this lands far below the
        expected total: the original file implementation scored 4 surviving
        writes out of 200. `SELECT ... FOR UPDATE` serialises the readers, and
        unlike the advisory lock it replaces, it does so across machines.
        """
        store = store_factory("race")
        store.write({"n": 0})

        threads = 4
        each = 20

        def bump():
            for _ in range(each):
                store.update(lambda d: d.__setitem__("n", d.get("n", 0) + 1))

        workers = [threading.Thread(target=bump) for _ in range(threads)]
        for w in workers:
            w.start()
        for w in workers:
            w.join()

        assert store.read()["n"] == threads * each

    def test_two_stores_on_one_key_see_each_other(self, store_factory):
        """Two instances are two connections, not two caches.

        The file backend could be given a stale view by caching; this asserts
        a write through one handle is visible through another, which is what
        makes running several web workers safe.
        """
        a = store_factory("shared")
        b = type(a)(a.path)
        a.write({"from": "a"})
        assert b.read() == {"from": "a"}
        b.update(lambda d: d.__setitem__("from", "b"))
        assert a.read() == {"from": "b"}


class TestKeying:
    def test_key_is_the_repository_relative_path(self):
        from backend.storage_pg import PgStore

        assert PgStore._key_for("data/users.json") == "data/users.json"

    def test_key_is_stable_across_equivalent_paths(self):
        """An absolute path and a relative one must address the same document.

        Call sites build paths from config, and a deployment that resolved
        data/users.json to a second key would read an empty document and look
        exactly like data loss.
        """
        from backend.storage_pg import PgStore

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        assert PgStore._key_for("data/users.json") == PgStore._key_for(
            os.path.join(root, "data", "users.json")
        )
        assert PgStore._key_for("./data/users.json") == "data/users.json"


class TestDurability:
    def test_documents_survive_a_new_pool(self, store_factory):
        """Closest thing to a restart that a test can assert.

        The real question this migration answers is whether a write survives
        the process that made it. Dropping the pool and reconnecting is the
        same code path a redeployed instance takes.
        """
        import backend.storage_pg as storage_pg

        store = store_factory("durable")
        store.write({"written": "before the restart"})

        old = storage_pg._pool
        storage_pg._pool = None
        storage_pg._schema_ready = False
        try:
            assert type(store)(store.path).read() == {"written": "before the restart"}
        finally:
            if storage_pg._pool is not None:
                storage_pg._pool.close()
            storage_pg._pool = old
            storage_pg._schema_ready = True


class TestQueryList:
    """The filtering and projection that make the Postgres backend affordable.

    On the file backend `query_list` only saves memory, because the file is
    read either way. Here it is the difference between transferring every
    learner's attempts, with the full text of every question, and transferring
    the handful of summary rows a page displays. These assert the same
    behaviour `tests/test_attempt_queries.py` asserts of JsonStore.
    """

    @staticmethod
    def _rows():
        return [
            {"attempt_id": "a1", "user_id": "u1", "topic_id": "os", "question_results": [{"text": "q"}]},
            {"attempt_id": "a2", "user_id": "u2", "topic_id": "os", "question_results": [{"text": "q"}]},
            {"attempt_id": "a3", "user_id": "u1", "topic_id": "dbms", "question_results": [{"text": "q"}]},
            {"attempt_id": "a4", "user_id": "u1", "topic_id": "os", "question_results": [{"text": "q"}]},
        ]

    @pytest.fixture
    def store(self, store_factory):
        s = store_factory("attempts", default=list)
        s.write(self._rows())
        return s

    def test_filters_by_one_key(self, store):
        rows = store.query_list(match={"user_id": "u1"})
        assert [r["attempt_id"] for r in rows] == ["a1", "a3", "a4"]

    def test_filters_by_several_keys(self, store):
        rows = store.query_list(match={"user_id": "u1", "topic_id": "os"})
        assert [r["attempt_id"] for r in rows] == ["a1", "a4"]

    def test_preserves_document_order(self, store):
        """jsonb_agg makes no ordering promise on its own. Callers read the
        last element as the most recent attempt, so WITH ORDINALITY and the
        ORDER BY inside the aggregate are load-bearing, not decoration."""
        assert [r["attempt_id"] for r in store.query_list()] == ["a1", "a2", "a3", "a4"]

    def test_drops_named_keys(self, store):
        rows = store.query_list(match={"user_id": "u1"}, drop_keys=("question_results",))
        assert rows and all("question_results" not in r for r in rows)
        assert all("topic_id" in r for r in rows)

    def test_projection_does_not_change_what_is_stored(self, store):
        store.query_list(drop_keys=("question_results",))
        assert all("question_results" in r for r in store.read())

    def test_matches_are_compared_as_text(self, store_factory):
        """`->>` yields text, so an integer user_id in the document must still
        match the string the session holds, exactly as JsonStore does."""
        s = store_factory("typed", default=list)
        s.write([{"user_id": 7, "attempt_id": "a1"}])
        assert len(s.query_list(match={"user_id": "7"})) == 1
        assert len(s.query_list(match={"user_id": 7})) == 1

    def test_no_match_is_empty(self, store):
        assert store.query_list(match={"user_id": "nobody"}) == []

    def test_absent_document_is_empty(self, store_factory):
        assert store_factory("never-written", default=list).query_list() == []

    def test_map_shaped_document_yields_nothing(self, store_factory):
        """jsonb_array_elements raises on a non-array. The same table holds the
        users list, the progress map and the BKT state, so a map-shaped
        document must return empty rather than erroring."""
        s = store_factory("map", default=dict)
        s.write({"a": 1})
        assert s.query_list(match={"user_id": "u1"}) == []
        assert s.count_list() == 0


class TestCountList:
    @pytest.fixture
    def store(self, store_factory):
        s = store_factory("counts", default=list)
        s.write(TestQueryList._rows())
        return s

    def test_counts_matches(self, store):
        assert store.count_list(match={"user_id": "u1"}) == 3
        assert store.count_list(match={"user_id": "u1", "topic_id": "os"}) == 2

    def test_counts_everything_with_no_match(self, store):
        assert store.count_list() == 4

    def test_absent_is_zero(self, store):
        assert store.count_list(match={"user_id": "nobody"}) == 0


class TestMatchSemanticsAgainstPostgres:
    """The Postgres half of the contract in tests/test_attempt_queries.py.

    These are the cases the round 6 audit found disagreeing. `->>` renders a
    JSON boolean as lowercase "true", and compares against SQL NULL for an
    absent field, so neither `str(True)` nor `= 'None'` worked. Asserting the
    same expectations here and on JsonStore is the only way a disagreement
    shows up as a failure rather than as a production bug.
    """

    @pytest.fixture
    def store(self, store_factory):
        s = store_factory("match-semantics", default=list)
        s.write([
            {"id": "a", "flag": True, "n": 5},
            {"id": "b", "flag": False, "n": "5"},
            {"id": "c"},
        ])
        return s

    def test_true_matches_as_lowercase(self, store):
        assert [r["id"] for r in store.query_list(match={"flag": True})] == ["a"]

    def test_false_is_not_treated_as_absent(self, store):
        assert [r["id"] for r in store.query_list(match={"flag": False})] == ["b"]

    def test_none_means_absent_or_null(self, store):
        assert [r["id"] for r in store.query_list(match={"missing": None})] == ["a", "b", "c"]
        assert [r["id"] for r in store.query_list(match={"flag": None})] == ["c"]

    def test_numbers_compare_as_text_either_way(self, store):
        assert [r["id"] for r in store.query_list(match={"n": 5})] == ["a", "b"]
        assert [r["id"] for r in store.query_list(match={"n": "5"})] == ["a", "b"]

    def test_a_present_field_does_not_match_none(self, store):
        assert store.query_list(match={"id": None}) == []

    def test_count_list_agrees_with_query_list(self, store):
        for m in ({"flag": True}, {"flag": False}, {"missing": None}, {"n": 5}):
            assert store.count_list(match=m) == len(store.query_list(match=m)), m
