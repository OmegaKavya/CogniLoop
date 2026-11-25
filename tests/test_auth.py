"""
Tests for credential verification and account creation.

Regression tests for three real defects:

  * `verify_password` fell back to `password == stored_value` whenever the
    stored value was not in `salt:hash` form, so a plaintext-stored password
    authenticated.
  * That same branch was taken for an empty stored value, so an account whose
    password field was empty authenticated with an empty password.
  * Registration derived the new user id from `len(users)` read before the
    write, so simultaneous signups computed the same id and overwrote one
    another. Fifty concurrent registrations left five accounts.
"""
import threading

import pytest

from backend.auth.auth_service import (
    PBKDF2_ITERATIONS,
    hash_password,
    verify_password,
)
from backend.repositories.core_repositories import UserRepository


class TestPasswordVerification:
    @pytest.mark.parametrize("password,stored", [
        ("", ""),                    # empty stored value must not authenticate
        ("hunter2", "hunter2"),      # plaintext must not authenticate
        ("x", "abcdef"),             # no separator
        ("x", ":deadbeef"),          # empty salt
        ("x", "salt:"),              # empty hash
        ("x", "a:b:c"),              # malformed
        ("x", None),                 # missing value
        ("x", 12345),                # wrong type
    ])
    def test_malformed_stored_values_are_rejected(self, password, stored):
        assert verify_password(password, stored) is False

    def test_correct_password_verifies(self):
        stored = hash_password("correct horse battery staple")
        assert verify_password("correct horse battery staple", stored) is True

    def test_wrong_password_rejected(self):
        stored = hash_password("correct horse")
        assert verify_password("wrong horse", stored) is False

    def test_empty_password_rejected_against_a_real_hash(self):
        assert verify_password("", hash_password("something")) is False

    def test_hash_is_salted(self):
        """Equal passwords must not produce equal stored values."""
        assert hash_password("same") != hash_password("same")

    def test_iteration_count_meets_current_guidance(self):
        assert PBKDF2_ITERATIONS >= 600_000

    def test_stored_format_is_salt_and_hash(self):
        salt, digest = hash_password("pw").split(":")
        assert len(salt) == 32
        assert len(digest) == 64


class TestAccountCreation:
    def _build(self, email):
        return lambda new_id, users: {"id": new_id, "email": email, "name": "U"}

    def test_concurrent_registrations_do_not_overwrite_each_other(self, tmp_path):
        repo = UserRepository(str(tmp_path / "users.json"))

        def register(i):
            repo.create(f"user{i}@example.com", self._build(f"user{i}@example.com"))

        threads = [threading.Thread(target=register, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        users = repo.get_all()
        assert len(users) == 50
        assert len({u["id"] for u in users}) == 50

    def test_duplicate_email_is_rejected_atomically(self, tmp_path):
        repo = UserRepository(str(tmp_path / "users.json"))
        results = [None] * 20

        def register(i):
            results[i] = repo.create("same@example.com", self._build("same@example.com"))

        threads = [threading.Thread(target=register, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(repo.get_all()) == 1
        assert sum(1 for r in results if r is not None) == 1

    def test_duplicate_email_returns_none(self, tmp_path):
        repo = UserRepository(str(tmp_path / "users.json"))
        assert repo.create("a@example.com", self._build("a@example.com")) is not None
        assert repo.create("a@example.com", self._build("a@example.com")) is None

    def test_ids_are_not_reused_after_deletion(self, tmp_path):
        """Deleting the newest account must not hand its id to the next one.

        "highest + 1" passed a version of this test that deleted a middle
        account and failed this one: removing the newest made its id the next
        one allocated, merging a new participant with whatever of the old one
        remained (rows, or a cookie still within its seven days).
        """
        repo = UserRepository(str(tmp_path / "users.json"))
        ids = [repo.create(f"u{i}@example.com", self._build(f"u{i}@example.com"))["id"]
               for i in range(3)]
        newest = ids[-1]
        repo._store.update_replacing(lambda users: [u for u in users if u["id"] != newest],
                                     default=list)
        for i in range(50):
            created = repo.create(f"n{i}@example.com", self._build(f"n{i}@example.com"))
            assert created["id"] != newest
        assert len({u["id"] for u in repo.get_all()}) == 52

    def test_new_ids_avoid_existing_numeric_ids(self, tmp_path):
        repo = UserRepository(str(tmp_path / "users.json"))
        repo._store.write([{"id": "1", "email": "old@example.com"}])
        created = repo.create("new@example.com", self._build("new@example.com"))
        assert created["id"] != "1"

    def test_email_matching_ignores_case(self, tmp_path):
        repo = UserRepository(str(tmp_path / "users.json"))
        assert repo.create("Ana@Example.com", self._build("Ana@Example.com"))
        assert repo.create("ana@example.com", self._build("ana@example.com")) is None
        assert repo.find_by_email(" ANA@example.COM ") is not None
