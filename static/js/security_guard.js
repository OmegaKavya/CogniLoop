/**
 * CogniLoop client security.
 *
 * This file attaches the CSRF token to state-changing requests, using the
 * double-submit cookie pattern: the server sets a readable `csrf_token`
 * cookie and keeps the authoritative copy in the session, this code echoes
 * the cookie back in an `X-CSRF-Token` header, and the server compares the
 * two. An attacker's page can cause the browser to send the cookie but
 * cannot read it, so it cannot produce the matching header.
 *
 * Patching fetch here rather than editing each call site means every request
 * the application makes is covered, including ones added later.
 *
 * ---------------------------------------------------------------------------
 * What this file used to do, and why it no longer does it
 * ---------------------------------------------------------------------------
 * It previously blocked right-click, F12, Ctrl+Shift+I/J/C, Ctrl+U and
 * Ctrl+S, and ran an anti-debugging trap. That was removed for three reasons.
 *
 * It did not work. Any of it can be bypassed by disabling JavaScript, using
 * the browser's menu, or viewing the page source over the network. Anything
 * the browser has received is already in the user's hands; the only way to
 * keep a secret from a client is not to send it. While this file was blocking
 * F12, the quiz answer key was being served in the response body and in the
 * session cookie - so it guarded the window while the door stood open.
 *
 * The anti-debugging trap was an outright bug. It measured how long a
 * `debugger` statement took and set `document.body.style.display = 'none'`
 * when that exceeded 100ms. A slow frame on a modest laptop exceeds 100ms, so
 * it could blank the page for an ordinary learner who had done nothing. It
 * also ran a timer every second for the whole session.
 *
 * It was hostile to legitimate use. Ctrl+S saves a page, Ctrl+U views source,
 * and the context menu is how people copy text, open links in new tabs and
 * reach their browser's accessibility tools. Screen-reader and keyboard users
 * were the ones paying for it.
 */

(function () {
    'use strict';

    var SAFE_METHODS = ['GET', 'HEAD', 'OPTIONS', 'TRACE'];

    function readCookie(name) {
        var prefix = name + '=';
        var parts = (document.cookie || '').split(';');
        for (var i = 0; i < parts.length; i++) {
            var part = parts[i].trim();
            if (part.indexOf(prefix) === 0) {
                return decodeURIComponent(part.substring(prefix.length));
            }
        }
        return null;
    }

    function isSameOrigin(url) {
        // Never attach the token to a third-party request: that would leak it
        // to whoever is being called.
        try {
            return new URL(url, window.location.href).origin === window.location.origin;
        } catch (err) {
            return false;
        }
    }

    var nativeFetch = window.fetch;
    if (typeof nativeFetch !== 'function') {
        return;
    }

    window.fetch = function (input, init) {
        init = init || {};
        var method = (init.method || (input && input.method) || 'GET').toUpperCase();
        var url = typeof input === 'string' ? input : (input && input.url) || '';

        if (SAFE_METHODS.indexOf(method) === -1 && isSameOrigin(url)) {
            var token = readCookie('csrf_token');
            if (token) {
                var headers = new Headers(init.headers || (input && input.headers) || {});
                headers.set('X-CSRF-Token', token);
                init = Object.assign({}, init, { headers: headers });
            }
        }

        return nativeFetch.call(window, input, init);
    };
})();
