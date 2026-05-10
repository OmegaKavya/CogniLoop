"""
Unit Tests: Base JSON Repository and Core Repositories
Covers: CRUD operations, file locking, corruption recovery, list-vs-dict storage.
"""
import os
import json
import tempfile
import pytest
from backend.repositories.base_repository import BaseJsonRepository
from backend.repositories.core_repositories import UserRepository, QuizAttemptRepository


@pytest.fixture
def repo(tmp_path):
    f = str(tmp_path / "test_data.json")
    # Write a dict-style store
    with open(f, "w") as fh:
        json.dump({}, fh)
    return BaseJsonRepository(f)


@pytest.fixture
def list_file(tmp_path):
    f = str(tmp_path / "users.json")
    with open(f, "w") as fh:
        json.dump([], fh)
    return f


class TestBaseRepository:
    def test_get_all_empty(self, repo):
        assert repo.get_all() == {}

    def test_save_and_get_by_id(self, repo):
        repo.save("u1", {"name": "Alice"})
        assert repo.get_by_id("u1") == {"name": "Alice"}

    def test_overwrite_existing(self, repo):
        repo.save("u1", {"name": "Alice"})
        repo.save("u1", {"name": "Bob"})
        assert repo.get_by_id("u1")["name"] == "Bob"

    def test_delete_existing(self, repo):
        repo.save("u1", {"name": "Alice"})
        repo.delete("u1")
        assert repo.get_by_id("u1") is None

    def test_delete_nonexistent_does_not_crash(self, repo):
        repo.delete("nonexistent_key")

    def test_get_by_id_missing_returns_none(self, repo):
        assert repo.get_by_id("does_not_exist") is None

    def test_corrupted_json_returns_empty(self, tmp_path):
        f = str(tmp_path / "corrupt.json")
        with open(f, "w") as fh:
            fh.write("{{{not valid json")
        repo = BaseJsonRepository(f)
        assert repo.get_all() == {}

    def test_file_created_if_missing(self, tmp_path):
        f = str(tmp_path / "newfile.json")
        assert not os.path.exists(f)
        BaseJsonRepository(f)
        assert os.path.exists(f)


class TestUserRepository:
    def test_add_and_find_by_email(self, list_file):
        repo = UserRepository(list_file)
        repo.save("1", {"id": "1", "email": "alice@test.com", "name": "Alice"})
        user = repo.find_by_email("alice@test.com")
        assert user is not None
        assert user["name"] == "Alice"

    def test_find_by_email_not_found(self, list_file):
        repo = UserRepository(list_file)
        assert repo.find_by_email("nope@test.com") is None

    def test_add_multiple_users(self, list_file):
        repo = UserRepository(list_file)
        repo.save("1", {"id": "1", "email": "a@test.com"})
        repo.save("2", {"id": "2", "email": "b@test.com"})
        assert len(repo.get_all()) == 2

    def test_update_existing_user(self, list_file):
        repo = UserRepository(list_file)
        repo.save("1", {"id": "1", "email": "x@test.com", "name": "Old"})
        repo.save("1", {"id": "1", "email": "x@test.com", "name": "New"})
        user = repo.find_by_email("x@test.com")
        assert user["name"] == "New"
        assert len(repo.get_all()) == 1  # Should not duplicate


class TestQuizAttemptRepository:
    def test_append_and_retrieve(self, list_file):
        repo = QuizAttemptRepository(list_file)
        repo.add_attempt({"attempt_id": "a1", "user_id": "u1", "score": 80})
        attempts = repo.get_user_attempts("u1")
        assert len(attempts) == 1
        assert attempts[0]["score"] == 80

    def test_multiple_users_isolated(self, list_file):
        repo = QuizAttemptRepository(list_file)
        repo.add_attempt({"attempt_id": "a1", "user_id": "u1", "score": 70})
        repo.add_attempt({"attempt_id": "a2", "user_id": "u2", "score": 90})
        assert len(repo.get_user_attempts("u1")) == 1
        assert len(repo.get_user_attempts("u2")) == 1

    def test_get_all_returns_all(self, list_file):
        repo = QuizAttemptRepository(list_file)
        repo.add_attempt({"attempt_id": "x1", "user_id": "ua", "score": 75})
        repo.add_attempt({"attempt_id": "x2", "user_id": "ub", "score": 55})
        all_attempts = repo.get_all()
        assert len(all_attempts) == 2

    def test_empty_user_returns_empty_list(self, list_file):
        repo = QuizAttemptRepository(list_file)
        assert repo.get_user_attempts("nobody") == []
