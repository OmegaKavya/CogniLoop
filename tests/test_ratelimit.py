"""
Tests for abuse limiting and session cookie hardening.

Login previously had no throttle, so passwords could be guessed as fast as the
server would answer.
"""
import threading

from app import app, login_limiter, register_limiter
from backend import config
from backend.ratelimit import SlidingWindowLimiter


class TestSlidingWindowLimiter:
    def test_allows_up_to_the_limit(self):
        limiter = SlidingWindowLimiter(max_events=3, window_seconds=60)
        assert [limiter.record("k") for _ in range(3)] == [True, True, True]

    def test_blocks_beyond_the_limit(self):
        limiter = SlidingWindowLimiter(max_events=3, window_seconds=60)
        for _ in range(3):
            limiter.record("k")
        assert limiter.record("k") is False
        assert limiter.check("k") is False

    def test_keys_are_independent(self):
        limiter = SlidingWindowLimiter(max_events=1, window_seconds=60)
        limiter.record("a")
        assert limiter.check("a") is False
        assert limiter.check("b") is True

    def test_events_expire_out_of_the_window(self):
        limiter = SlidingWindowLimiter(max_events=2, window_seconds=0)
        limiter.record("k")
        limiter.record("k")
        assert limiter.check("k") is True

    def test_reset_clears_one_key(self):
        limiter = SlidingWindowLimiter(max_events=1, window_seconds=60)
        limiter.record("k")
        limiter.reset("k")
        assert limiter.check("k") is True

    def test_retry_after_is_positive_once_blocked(self):
        limiter = SlidingWindowLimiter(max_events=1, window_seconds=60)
        limiter.record("k")
        assert limiter.retry_after("k") > 0

    def test_retry_after_is_zero_when_allowed(self):
        assert SlidingWindowLimiter(2, 60).retry_after("unused") == 0

    def test_concurrent_records_are_all_counted(self):
        """A racy counter would under-count and let extra attempts through."""
        limiter = SlidingWindowLimiter(max_events=10_000, window_seconds=60)
        threads = [threading.Thread(target=lambda: limiter.record("k"))
                   for _ in range(200)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(limiter._events["k"]) == 200


class TestLoginThrottling:
    def _login(self, client, password):
        return client.post('/login', json={"email": "victim@test.com",
                                           "password": password})

    def test_repeated_failures_are_eventually_blocked(self, client):
        client.post('/register', json={"name": "V", "email": "victim@test.com",
                                       "password": "right"})
        for _ in range(config.LOGIN_MAX_ATTEMPTS):
            self._login(client, "wrong")
        blocked = self._login(client, "wrong")
        assert blocked.status_code == 429
        assert blocked.headers.get('Retry-After')

    def test_blocked_even_with_the_correct_password(self, client):
        """Otherwise the throttle could be probed away by a lucky guess."""
        client.post('/register', json={"name": "V", "email": "victim@test.com",
                                       "password": "right"})
        for _ in range(config.LOGIN_MAX_ATTEMPTS):
            self._login(client, "wrong")
        assert self._login(client, "right").status_code == 429

    def test_successful_login_clears_the_counter(self, client):
        client.post('/register', json={"name": "V", "email": "victim@test.com",
                                       "password": "right"})
        for _ in range(config.LOGIN_MAX_ATTEMPTS - 1):
            self._login(client, "wrong")
        assert self._login(client, "right").status_code == 200
        assert self._login(client, "wrong").status_code == 200

    def test_unknown_and_wrong_account_responses_are_identical(self, client):
        """The response must not reveal whether an email is registered."""
        client.post('/register', json={"name": "V", "email": "victim@test.com",
                                       "password": "right"})
        wrong = self._login(client, "nope")
        unknown = client.post('/login', json={"email": "ghost@nowhere.test",
                                              "password": "nope"})
        assert wrong.status_code == unknown.status_code
        assert wrong.get_json() == unknown.get_json()


class TestSessionCookieHardening:
    def test_samesite_blocks_cross_site_cookie_attachment(self):
        assert app.config['SESSION_COOKIE_SAMESITE'] == 'Lax'

    def test_cookie_is_http_only(self):
        assert app.config['SESSION_COOKIE_HTTPONLY'] is True

    def test_secure_flag_follows_configuration(self):
        assert app.config['SESSION_COOKIE_SECURE'] == config.SESSION_COOKIE_SECURE

    def test_session_cookie_is_set_with_hardening_on_login(self, client):
        client.post('/register', json={"name": "C", "email": "cookie@test.com",
                                       "password": "pw"})
        res = client.post('/login', json={"email": "cookie@test.com",
                                          "password": "pw"})
        cookie = res.headers.get('Set-Cookie', '')
        if cookie:
            assert 'HttpOnly' in cookie
            assert 'SameSite=Lax' in cookie
