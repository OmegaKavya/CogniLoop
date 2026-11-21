"""Server-side custody of an issued quiz and its answer key.

Why this module exists
----------------------
The answer key used to travel to the learner twice over.

It was in the response body: `/api/quiz-data/<topic_id>` returned the generated
quiz object wholesale, and every question in it carries an `answer` field. Any
learner could read the correct answers out of the browser's network tab.

It was also in the session. Flask's default session is a *signed* cookie, not
an *encrypted* one - the signature stops a learner from forging a session, but
it does nothing to stop them reading one. Putting the quiz in `session` handed
them the same key a second time, in a form they could decode offline with no
secret at all.

That mattered beyond cheating. Quiz scores drive the mastery update, which
drives the difficulty policy, so a learner reading answers does not merely
inflate their own score - they corrupt the signal the system adapts on, and
with it the data any analysis of that system would rest on.

The rule this module enforces is that the answer key never leaves the server.
The client is handed an opaque token and a `public_view` of the quiz with the
answers stripped; grading happens here, against the stored copy.

Design notes
------------
Tokens are keys, not identifiers. They come from `secrets.token_urlsafe` and
are compared with `secrets.compare_digest`, because a token that can be guessed
or recovered by timing is the same leak wearing a different hat.

Entries are keyed by token rather than by user, so two browser tabs each hold a
valid quiz. Keying by user made the second tab silently invalidate the first,
and submitting the first then graded its answers against the other tab's
questions.

Issuing is capped per learner and entries expire, so an abandoned or scripted
quiz cannot grow the store without bound. Reads and writes go through JsonStore,
so the whole read-modify-write runs under one lock.
"""

import secrets
import time

from backend import config
from backend.storage import open_store


def public_view(quiz):
    """The quiz as the client may see it: every answer key removed.

    Returns a copy. Mutating the caller's quiz in place would strip the answers
    from the very object we are about to persist, which would silently make
    grading impossible.
    """
    if not isinstance(quiz, dict):
        return quiz

    redacted = dict(quiz)
    questions = []
    for question in quiz.get("questions") or []:
        if isinstance(question, dict):
            # Drop every spelling of the key the generator or a model might use.
            questions.append({
                key: value for key, value in question.items()
                if key not in ("answer", "correct_answer", "correct", "correct_index")
            })
        else:
            questions.append(question)
    redacted["questions"] = questions
    return redacted


class ActiveQuizStore:
    """Issued quizzes awaiting submission, held server-side."""

    def __init__(self, file_path=None, ttl_seconds=None, max_per_user=None):
        self.file_path = file_path or config.ACTIVE_QUIZ_PATH
        self.ttl_seconds = (config.ACTIVE_QUIZ_TTL_SECONDS
                            if ttl_seconds is None else ttl_seconds)
        self.max_per_user = (config.ACTIVE_QUIZ_MAX_PER_USER
                             if max_per_user is None else max_per_user)
        self._store_cache = None
        # Deliberately no `ensure_exists()` here. This class is instantiated at
        # module import, and creating the file in the constructor would mean
        # `import app` writes to the data directory as a side effect - which
        # makes the import order matter, and makes a test suite that has not yet
        # redirected `file_path` touch real data. A missing file already reads
        # as empty, so the first write creates it.

    @property
    def _store(self):
        """Resolved from `file_path` on each access, not captured at init.

        Binding the store at construction would ignore later reassignment of
        `file_path`, which is how the tests redirect persistence to a temporary
        directory.
        """
        if self._store_cache is None or self._store_cache.path != self.file_path:
            self._store_cache = open_store(self.file_path)
        return self._store_cache

    def _prune(self, data, now):
        """Drop expired entries. Caller must hold the lock."""
        return {
            token: entry for token, entry in data.items()
            if isinstance(entry, dict)
            and now - entry.get("issued_at", 0) < self.ttl_seconds
        }

    def issue(self, user_id, quiz, now=None):
        """Store `quiz` and return the token the client should present."""
        now = time.time() if now is None else now
        token = secrets.token_urlsafe(32)

        def mutate(data):
            data = self._prune(data if isinstance(data, dict) else {}, now)

            # Evict this learner's oldest outstanding quizzes beyond the cap.
            mine = sorted(
                (t for t, e in data.items() if str(e.get("user_id")) == str(user_id)),
                key=lambda t: data[t].get("issued_at", 0),
            )
            for stale in mine[: max(0, len(mine) - (self.max_per_user - 1))]:
                data.pop(stale, None)

            data[token] = {
                "user_id": str(user_id),
                "issued_at": now,
                "quiz": quiz,
            }
            return data

        self._store.update_replacing(mutate, default=dict)
        return token

    def get(self, token, user_id, now=None):
        """The stored quiz for `token`, or None.

        Returns None unless the token exists, has not expired, and belongs to
        this learner - so one learner cannot grade against another's quiz.
        """
        now = time.time() if now is None else now
        if not token:
            return None

        data = self._store.read()
        if not isinstance(data, dict):
            return None

        # Constant-time lookup: compare against every key so a wrong token
        # cannot be distinguished from a right one by how long the miss took.
        entry = None
        for candidate, value in data.items():
            if secrets.compare_digest(str(candidate), str(token)):
                entry = value
        if not isinstance(entry, dict):
            return None

        if now - entry.get("issued_at", 0) >= self.ttl_seconds:
            return None
        if not secrets.compare_digest(str(entry.get("user_id")), str(user_id)):
            return None
        return entry.get("quiz")

    def consume(self, token, user_id, now=None):
        """Fetch the quiz and remove it, so a token grades exactly once.

        The removal is what stops a learner replaying one issued quiz to farm
        repeated mastery updates from a single set of questions.
        """
        quiz = self.get(token, user_id, now=now)
        if quiz is None:
            return None

        def mutate(data):
            data = data if isinstance(data, dict) else {}
            data.pop(token, None)
            return self._prune(data, time.time() if now is None else now)

        self._store.update_replacing(mutate, default=dict)
        return quiz


active_quiz_store = ActiveQuizStore()
