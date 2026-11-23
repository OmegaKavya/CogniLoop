"""Rate limits and input validation on every endpoint that spends or writes.

Three distinct costs are being protected, and they are not the same thing:

  * Money. Generating a quiz and grading one each call a model, so an
    unlimited endpoint is unbounded spend on someone else's API key.
  * Availability. The deployment runs one synchronous worker, so any slow
    request blocks every other learner.
  * Integrity. Telemetry is the feature vector the clustering model uses, and
    the cluster chooses the bandit arm that picks the next difficulty. A
    learner who posts nonsense moves the centroids for everybody.

The route inventory test is the one that matters most: it fails when a NEW
endpoint is added without a limit, which is how this gap appeared in the first
place.
"""
import re

import pytest

from app import bounded_number


class TestBoundedNumber:
    def test_clamps_above_and_below(self):
        assert bounded_number(500, 0, 100) == 100
        assert bounded_number(-5, 0, 100) == 0

    def test_passes_values_in_range(self):
        assert bounded_number(42.5, 0, 100) == 42.5

    def test_strings_that_look_like_numbers_are_accepted(self):
        assert bounded_number("37", 0, 100) == 37

    def test_junk_becomes_the_default(self):
        for junk in ("abc", None, {}, [], object()):
            assert bounded_number(junk, 0, 100, default=7) == 7

    def test_nan_and_infinity_become_the_default(self):
        """NaN defeats comparison, so min/max would let it straight through
        into the clustering input."""
        assert bounded_number(float("nan"), 0, 100, default=3) == 3
        assert bounded_number(float("inf"), 0, 100, default=3) == 3
        assert bounded_number(float("-inf"), 0, 100, default=3) == 3

    def test_booleans_do_not_crash(self):
        assert bounded_number(True, 0, 100) == 1


class TestEveryWriteEndpointIsLimited:
    """The inventory check. A new POST without a limit fails here."""

    @staticmethod
    def _routes():
        src = open("app.py").read()
        pattern = re.compile(r"@app\.route\((.*?)\)(?:\s*@[^\n]*)*\s*\ndef (\w+)\(", re.S)
        found = []
        for match in pattern.finditer(src):
            decl = match.group(1).replace("\n", " ")
            start = match.end()
            nxt = src.find("@app.route", start)
            body = src[start: nxt if nxt != -1 else len(src)]
            found.append({
                "path": re.search(r"['\"]([^'\"]+)['\"]", decl).group(1),
                "post": "POST" in decl,
                "limited": "limiter.record" in body or "limiter.check" in body,
            })
        return found

    def test_every_post_route_has_a_rate_limit(self):
        unlimited = [r["path"] for r in self._routes() if r["post"] and not r["limited"]]
        assert unlimited == [], (
            "POST routes with no rate limit: " + ", ".join(unlimited) +
            " -- every state-changing endpoint needs one"
        )

    def test_the_expensive_reads_have_one_too(self):
        """Quiz generation calls a model; the cohort report reads everything."""
        by_path = {r["path"]: r for r in self._routes()}
        for path in ("/api/quiz-data/<topic_id>", "/api/research-analytics"):
            assert by_path[path]["limited"], f"{path} must be rate limited"

    def test_the_inventory_actually_found_routes(self):
        """Guards against the regex silently matching nothing, which would
        make every assertion above pass vacuously."""
        routes = self._routes()
        assert len(routes) > 15
        assert sum(1 for r in routes if r["post"]) >= 3



@pytest.fixture
def signed_in(client):
    """A genuinely signed-in client.

    Registering rather than writing the session directly, because the CSRF
    token is created and published as a cookie by a real response. A session
    forged with session_transaction has no token, so every authenticated POST
    comes back 403 and the test measures the CSRF guard instead of the thing
    it meant to measure.
    """
    client.post('/register', json={
        "name": "Hardening", "email": "hardening@test.com", "password": "pw12345"})
    response = client.post('/login', json={
        "email": "hardening@test.com", "password": "pw12345"})
    assert response.status_code == 200, "fixture could not sign in"
    with client.session_transaction() as sess:
        assert 'user_id' in sess
        sess['study_group'] = 'experimental'
    return client


def _signed_in_user_id(client):
    with client.session_transaction() as sess:
        return str(sess['user_id'])


class TestVideoTrackValidation:
    """Through real requests, not just the helper in isolation.

    `test_topic` is the only video seeded by the test_data_dir fixture.
    """

    def test_rejects_an_unknown_topic(self, signed_in):
        assert signed_in.post('/api/video-track',
                              json={'topic_id': 'no_such_topic'}).status_code == 404

    def test_rejects_a_missing_topic_id(self, signed_in):
        assert signed_in.post('/api/video-track', json={}).status_code == 400

    def test_rejects_a_non_object_payload(self, signed_in):
        assert signed_in.post('/api/video-track', json=[1, 2, 3]).status_code == 400

    def test_requires_a_session(self, client):
        assert client.post('/api/video-track',
                           json={'topic_id': 'test_topic'}).status_code == 401

    def test_clamps_absurd_telemetry_before_it_is_stored(self, signed_in):
        """These values would otherwise become the feature vector the
        clustering model sees, and the cluster picks the bandit arm."""
        response = signed_in.post('/api/video-track', json={
            'topic_id': 'test_topic',
            'watch_percentage': 99999,
            'skip_ratio': -4,
            'pause_count': 1e12,
            'last_time': float('inf'),
        })
        assert response.status_code == 200

        from backend.repositories.core_repositories import progress_repo
        stored = progress_repo.get_progress(_signed_in_user_id(signed_in), 'test_topic')
        assert 0 <= stored['watch_percentage'] <= 100
        assert 0 <= stored['last_position'] <= 86400

    def test_is_rate_limited(self, signed_in, monkeypatch):
        from app import video_track_limiter
        monkeypatch.setattr(video_track_limiter, 'max_events', 3)
        codes = [signed_in.post('/api/video-track',
                                json={'topic_id': 'test_topic'}).status_code
                 for _ in range(5)]
        assert 429 in codes, f"expected a 429 once over the limit, got {codes}"


class TestSemaphoreIsNotLeaked:
    """The slot is taken before the thread exists, so a failure to start one
    must give it back. Four leaks would disable refinement for the whole
    process until restart, and thread creation fails on exactly the small
    container this cap exists for. Found by the round 7 audit."""

    def test_a_thread_that_cannot_start_releases_its_slot(self, monkeypatch):
        import app as app_module
        from backend import config

        def refuse(*args, **kwargs):
            raise RuntimeError("can't start new thread")

        monkeypatch.setattr(app_module.threading, 'Thread', refuse)
        for _ in range(config.INSIGHT_REFINE_MAX_INFLIGHT + 2):
            app_module.refine_insights_in_background(
                '1', 'a1', 'OS', 40, 0.4, [{'is_correct': False}])

        # Every permit must still be available.
        taken = []
        try:
            for _ in range(config.INSIGHT_REFINE_MAX_INFLIGHT):
                assert app_module._insight_slots.acquire(blocking=False), \
                    "a permit was leaked by a thread that never started"
                taken.append(True)
        finally:
            for _ in taken:
                app_module._insight_slots.release()


class TestClientAddress:
    """The address limiter keys on this, so the entry chosen decides whether a
    caller can rotate the header for a fresh bucket."""

    def test_uses_the_rightmost_forwarded_entry(self, client):
        from app import _client_address
        with client.application.test_request_context(
                headers={'X-Forwarded-For': '1.1.1.1, 2.2.2.2, 9.9.9.9'}):
            assert _client_address() == '9.9.9.9'

    def test_a_single_entry_still_works(self, client):
        from app import _client_address
        with client.application.test_request_context(
                headers={'X-Forwarded-For': '9.9.9.9'}):
            assert _client_address() == '9.9.9.9'

    def test_falls_back_to_the_peer_address(self, client):
        from app import _client_address
        with client.application.test_request_context():
            assert _client_address() is not None
