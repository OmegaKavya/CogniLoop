"""A temporary path must never become a database key.

This is the last line of defence against the failure that happened twice on
23 Nov 2026: a test or script running with DATABASE_URL set, writing what it
believed was a scratch file, and creating a document in the production
database keyed by a path under /tmp. Ninety such documents were created in
total, and both times it was noticed by accident rather than reported.

These do not need a database: `_key_for` is a pure function of the path.
"""
import os
import tempfile

import pytest

from backend.storage_pg import PgStore


class TestTemporaryPathsAreRefused:
    def test_a_tmp_path_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            with pytest.raises(ValueError, match="temporary path"):
                PgStore._key_for(os.path.join(directory, "users.json"))

    def test_pytest_tmp_path_raises(self, tmp_path):
        """The exact shape the suite produces, via the tmp_path fixture."""
        with pytest.raises(ValueError, match="temporary path"):
            PgStore._key_for(str(tmp_path / "attempts.json"))

    def test_the_message_says_what_to_do(self, tmp_path):
        with pytest.raises(ValueError) as caught:
            PgStore._key_for(str(tmp_path / "x.json"))
        message = str(caught.value)
        assert "DATABASE_URL" in message, "must name the variable to unset"
        assert str(tmp_path) in message, "must name the offending path"


class TestEveryTempRootIsCovered:
    """`gettempdir()` alone returns only the per-user $TMPDIR on macOS, so
    /tmp, /private/tmp and /var/tmp walked straight past the guard. Found by
    the round 6 audit."""

    @pytest.mark.parametrize("path", [
        "/tmp/users.json",
        "/private/tmp/users.json",
        "/var/tmp/users.json",
    ])
    def test_system_temp_roots_are_refused(self, path):
        with pytest.raises(ValueError, match="temporary path"):
            PgStore._key_for(path)

    def test_the_per_user_tmpdir_is_refused(self):
        with pytest.raises(ValueError, match="temporary path"):
            PgStore._key_for(os.path.join(tempfile.gettempdir(), "users.json"))


class TestLegitimatePathsStillWork:
    def test_project_relative_path(self):
        assert PgStore._key_for("data/users.json") == "data/users.json"

    def test_project_relative_path_is_normalised(self):
        assert PgStore._key_for("./data/users.json") == "data/users.json"

    def test_absolute_path_inside_the_project(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        assert PgStore._key_for(os.path.join(root, "data", "users.json")) == "data/users.json"

    def test_deliberate_absolute_path_outside_the_project(self):
        """config.py's data paths are env-overridable, so a deployment may put
        them somewhere deliberate. Only the temp case is never legitimate."""
        assert PgStore._key_for("/srv/cogniloop/users.json") == "/srv/cogniloop/users.json"

    def test_the_tests_own_namespace(self):
        """What the Postgres integration tests use; must not be refused."""
        assert PgStore._key_for("tests/_pg_abc123_store.json") == "tests/_pg_abc123_store.json"
