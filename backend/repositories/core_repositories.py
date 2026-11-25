"""
Domain repositories.

Every method that derives new state from existing state runs inside
`JsonStore.update`, which holds one exclusive lock across the read and the
write. Reading with `get_all()` and then calling `_write_data()` would reopen
the lock in between, so two concurrent callers would both read the same list
and the second write would discard the first -- losing a registration, a quiz
attempt or a progress update.
"""

import random
import secrets

from backend import config
from backend.repositories.base_repository import BaseJsonRepository


def _same_email(a, b):
    """Email addresses compare without case or surrounding space, so
    Name@x.com and name@x.com are one account rather than two."""
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    return a.strip().lower() == b.strip().lower()


class UserRepository(BaseJsonRepository):
    def __init__(self, file_path=None):
        super().__init__(file_path or config.USERS_PATH)

    def find_by_email(self, email):
        users = self.get_all()
        if not isinstance(users, list):
            return None
        for user in users:
            if _same_email(user.get("email"), email):
                return user
        return None

    def find_by_id(self, user_id):
        """The user with this id, or None. Filtered in the store, so against
        Postgres this reads one row rather than every account."""
        if user_id is None:
            return None
        rows = self._store.query_list(match={"id": str(user_id)})
        return rows[0] if rows else None

    def save(self, user_id, user_data):
        def mutate(users):
            for i, existing in enumerate(users):
                if existing.get("id") == user_id:
                    users[i] = user_data
                    return users
            users.append(user_data)
            return users

        self._store.update_replacing(mutate, default=list)

    def create(self, email, build_user):
        """Atomically allocate an id and append a new user.

        The duplicate-email check, the id allocation and the append all happen
        under one lock. Doing any of them outside it loses accounts: the id was
        previously derived from len(users) read before the write, so two
        simultaneous registrations computed the same id and the second silently
        replaced the first.

        `build_user(new_id, existing_users)` returns the record to store. The
        existing list is handed over so a caller can make an assignment that
        depends on who is already registered - cohort allocation does, and it
        has to happen inside this lock to be correct. Returns the created user,
        or None if the email is already registered.
        """
        created = {}

        def mutate(users):
            for existing in users:
                if _same_email(existing.get("email"), email):
                    return users
            # Random, not derived from existing ids. Counting reused an id
            # once an account was deleted; "highest + 1" still did whenever
            # the deleted account was the newest one, which handed a new
            # participant the id that any leftover rows or a still-valid
            # cookie of the old one pointed at. Random ids also cannot be
            # enumerated. Checked against every id ever stored, old numeric
            # ones included.
            taken = {str(existing.get("id")) for existing in users}
            new_id = secrets.token_hex(4)
            while new_id in taken:
                new_id = secrets.token_hex(4)
            user = build_user(new_id, users)
            created["user"] = user
            users.append(user)
            return users

        self._store.update_replacing(mutate, default=list)
        return created.get("user")


def assign_study_group(existing_users, groups=("control", "experimental"),
                       rng=None):
    """Put the next participant in whichever cohort is currently smaller.

    Assignment was `random.choice` per registration, which is unbiased in
    expectation and badly unbalanced in practice at the sizes that matter
    here: with ten participants a fair coin lands 7-3 or worse in 34.7% of
    runs, measured over 10,000 simulated allocations. A pilot that small
    cannot afford a one-in-three chance of losing a third of one arm.

    Counting the existing members and filling the smaller arm keeps the split
    even at every point, so stopping after any number of participants still
    leaves balanced cohorts - which matters when people drop out or simply
    never finish. Ties break randomly, so the sequence is not fully
    predictable from the outside.

    It runs inside the same lock that allocates the user id, so two
    simultaneous registrations cannot both read the same counts and pick the
    same arm.
    """
    rng = rng or random
    counts = {group: 0 for group in groups}
    for user in existing_users or []:
        group = user.get("study_group")
        if group in counts:
            counts[group] += 1

    fewest = min(counts.values())
    smallest = [group for group in groups if counts[group] == fewest]
    return rng.choice(smallest)


class UserProgressRepository(BaseJsonRepository):
    def __init__(self, file_path=None):
        super().__init__(file_path or config.USER_PROGRESS_PATH)

    def get_progress(self, user_id, topic_id):
        data = self.get_all()
        if not isinstance(data, dict):
            return {}
        return data.get(str(user_id), {}).get(topic_id, {})

    def save_progress(self, user_id, topic_id, progress_data):
        def mutate(data):
            data.setdefault(str(user_id), {})[topic_id] = progress_data
            return data

        self._store.update_replacing(mutate, default=dict)


class QuizAttemptRepository(BaseJsonRepository):
    def __init__(self, file_path=None):
        super().__init__(file_path or config.QUIZ_ATTEMPTS_PATH)

    # The attempts document is the one that grows without bound: every learner
    # appends to the same array, and each entry carries the full text, options
    # and per-question feedback of the quiz that produced it. Reading it whole
    # to render one dashboard was fine against a local file and is not fine
    # against a database on another host.
    #
    # `RESPONSE_KEYS` names the heavy part. Only three places need it: the quiz
    # generator, which avoids repeating recent questions, and the two pages
    # that display a single attempt. Every other caller shows scores, mastery
    # and timestamps, so it asks for the rows without it.
    RESPONSE_KEYS = ("question_results",)

    def get_user_attempts(self, user_id, topic_id=None, include_responses=True):
        match = {"user_id": user_id}
        if topic_id is not None:
            match["topic_id"] = topic_id
        drop = () if include_responses else self.RESPONSE_KEYS
        return self._store.query_list(match=match, drop_keys=drop)

    def count_user_attempts(self, user_id, topic_id=None):
        """Only the number, so the rows themselves are never fetched."""
        match = {"user_id": user_id}
        if topic_id is not None:
            match["topic_id"] = topic_id
        return self._store.count_list(match=match)

    def get_attempt(self, user_id, attempt_id):
        """One attempt, complete, scoped to its owner.

        Scoped to the owner rather than looked up by id alone: attempt ids are
        handed out in URLs, and a bare id lookup would let a signed-in learner
        read somebody else's answers by changing the path.
        """
        rows = self._store.query_list(
            match={"user_id": user_id, "attempt_id": attempt_id})
        return rows[-1] if rows else None

    def latest_attempt(self, user_id):
        rows = self.get_user_attempts(user_id)
        return rows[-1] if rows else None

    def all_attempts(self, include_responses=True):
        """Every attempt, for the research analytics endpoint.

        That endpoint used to call get_user_attempts once per registered user,
        which read the whole document once per user. It reads it once instead
        and groups in memory.
        """
        drop = () if include_responses else self.RESPONSE_KEYS
        return self._store.query_list(drop_keys=drop)

    def add_attempt(self, attempt_data):
        def mutate(attempts):
            attempts.append(attempt_data)
            return attempts

        self._store.update_replacing(mutate, default=list)

    def set_insights(self, user_id, attempt_id, insights):
        """Replace one attempt's ai_insights, under the document lock.

        Written after the response has been sent, by the thread that produced
        the model version. It runs inside update_replacing for the usual
        reason: another learner may be appending an attempt at the same moment,
        and a read-then-write would drop whichever of the two landed first.

        Returns True if the attempt was found.
        """
        found = {"ok": False}

        def mutate(attempts):
            for attempt in attempts:
                if (str(attempt.get("user_id")) == str(user_id)
                        and attempt.get("attempt_id") == attempt_id):
                    attempt["ai_insights"] = insights
                    found["ok"] = True
                    break
            return attempts

        self._store.update_replacing(mutate, default=list)
        return found["ok"]


class VideoRepository(BaseJsonRepository):
    def __init__(self, file_path=None):
        super().__init__(file_path or config.VIDEOS_PATH)

    def get_all_videos(self):
        data = self.get_all()
        return data if isinstance(data, list) else []

    def get_by_id(self, video_id):
        for video in self.get_all_videos():
            if video.get("id") == video_id:
                return video
        return None


# Singleton instances for DI
user_repo = UserRepository()
progress_repo = UserProgressRepository()
quiz_repo = QuizAttemptRepository()
video_repo = VideoRepository()
