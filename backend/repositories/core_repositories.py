"""
Domain repositories.

Every method that derives new state from existing state runs inside
`JsonStore.update`, which holds one exclusive lock across the read and the
write. Reading with `get_all()` and then calling `_write_data()` would reopen
the lock in between, so two concurrent callers would both read the same list
and the second write would discard the first -- losing a registration, a quiz
attempt or a progress update.
"""

from backend import config
from backend.repositories.base_repository import BaseJsonRepository


class UserRepository(BaseJsonRepository):
    def __init__(self, file_path=None):
        super().__init__(file_path or config.USERS_PATH)

    def find_by_email(self, email):
        users = self.get_all()
        if not isinstance(users, list):
            return None
        for user in users:
            if user.get("email") == email:
                return user
        return None

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

        `build_user(new_id)` returns the record to store. Returns the created
        user, or None if the email is already registered.
        """
        created = {}

        def mutate(users):
            for existing in users:
                if existing.get("email") == email:
                    return users
            # Derived from the highest existing id rather than the count, so a
            # deleted account cannot cause an id to be reused.
            highest = 0
            for existing in users:
                try:
                    highest = max(highest, int(existing.get("id", 0)))
                except (TypeError, ValueError):
                    continue
            user = build_user(str(highest + 1))
            created["user"] = user
            users.append(user)
            return users

        self._store.update_replacing(mutate, default=list)
        return created.get("user")


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

    def get_user_attempts(self, user_id):
        attempts = self.get_all()
        if not isinstance(attempts, list):
            return []
        return [a for a in attempts if str(a.get("user_id")) == str(user_id)]

    def add_attempt(self, attempt_data):
        def mutate(attempts):
            attempts.append(attempt_data)
            return attempts

        self._store.update_replacing(mutate, default=list)


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
