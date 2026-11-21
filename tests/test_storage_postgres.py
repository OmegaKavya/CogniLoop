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

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip(),
    reason="DATABASE_URL is not set; Postgres integration tests are opt-in",
)


@pytest.fixture
def store_factory():
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
