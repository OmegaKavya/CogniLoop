"""Helpers shared by test modules.

Kept out of conftest.py: importing conftest from a test module can execute
its body a second time, and its body decides which database the run uses.
"""
from app import user_repo


def set_study_group(user_id, group):
    """Put a registered test user in a specific cohort.

    The cohort is read from the stored user on every request, so writing it
    into the session does nothing - which is the fix for H-01. A test that
    exercises one arm has to set it where the application reads it from.
    """
    user = user_repo.find_by_id(user_id)
    assert user is not None, f"no stored user {user_id}"
    user['study_group'] = group
    user_repo.save(user['id'], user)
