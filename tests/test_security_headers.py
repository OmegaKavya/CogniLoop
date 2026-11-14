"""
Tests for baseline HTTP security headers.

These are easy to lose in a refactor and produce no visible symptom when they
go missing, so they are asserted explicitly.
"""


class TestSecurityHeaders:
    def test_nosniff_is_set(self, client):
        assert client.get('/login').headers['X-Content-Type-Options'] == 'nosniff'

    def test_framing_is_denied(self, client):
        """Both the legacy header and the CSP directive that supersedes it."""
        res = client.get('/login')
        assert res.headers['X-Frame-Options'] == 'DENY'
        assert "frame-ancestors 'none'" in res.headers['Content-Security-Policy']

    def test_referrer_policy_is_restrictive(self, client):
        assert client.get('/login').headers['Referrer-Policy'] == \
            'strict-origin-when-cross-origin'

    def test_permissions_policy_disables_unused_capabilities(self, client):
        policy = client.get('/login').headers['Permissions-Policy']
        for capability in ('geolocation', 'microphone', 'camera'):
            assert f'{capability}=()' in policy

    def test_headers_are_present_on_static_assets_too(self, client):
        assert 'X-Content-Type-Options' in client.get('/static/css/style.css').headers


class TestContentSecurityPolicy:
    def _csp(self, client):
        return client.get('/login').headers['Content-Security-Policy']

    def test_default_src_is_self(self, client):
        assert "default-src 'self'" in self._csp(client)

    def test_youtube_player_is_allowed(self, client):
        """The player is loaded from youtube.com and pulls its widget script
        from s.ytimg.com; blocking either breaks video playback."""
        csp = self._csp(client)
        assert 'https://www.youtube.com' in csp
        assert 'https://s.ytimg.com' in csp
        assert 'frame-src https://www.youtube.com' in csp

    def test_google_fonts_are_allowed(self, client):
        csp = self._csp(client)
        assert 'https://fonts.googleapis.com' in csp
        assert 'https://fonts.gstatic.com' in csp

    def test_form_submissions_restricted_to_own_origin(self, client):
        assert "form-action 'self'" in self._csp(client)

    def test_inline_is_permitted_deliberately(self, client):
        """The templates carry inline scripts and style attributes, so a policy
        without 'unsafe-inline' would break the application. Asserted so that
        tightening it is a deliberate decision rather than an accident."""
        assert "'unsafe-inline'" in self._csp(client)


class TestStrictTransportSecurity:
    def test_not_sent_over_plain_http(self, client):
        """Over HTTP it does nothing, and in local development it would pin
        localhost to HTTPS and make the app unreachable."""
        assert 'Strict-Transport-Security' not in client.get('/login').headers

    def test_sent_when_the_proxy_reports_https(self, client):
        """Render terminates TLS and forwards X-Forwarded-Proto."""
        res = client.get('/login', headers={'X-Forwarded-Proto': 'https'})
        hsts = res.headers['Strict-Transport-Security']
        assert 'max-age=31536000' in hsts
        assert 'includeSubDomains' in hsts
