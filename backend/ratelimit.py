"""
In-process sliding-window rate limiting.

Why this exists
---------------
Login had no throttle at all, so passwords could be guessed as fast as the
server would answer. Raising the PBKDF2 iteration count slows each attempt, but
slowing a guess is not the same as limiting how many are allowed.

Scope and honesty about it
--------------------------
Counters live in the process, so each worker enforces the limit separately: with
N workers an attacker gets up to N times the configured attempts. That is a real
weakening, but still a hard bound rather than none, and it needs no external
store. A deployment that runs many workers, or that wants limits shared across
instances, should move these counters to Redis rather than raise the numbers.

Keying
------
Attempts are counted per identity being targeted, not only per source address.
An attacker chooses their own address and can rotate it; they cannot change
which account they are trying to break into, so the account is the more
meaningful key. Source address is limited separately to slow broad sweeps.
"""

import threading
import time
from collections import deque


class SlidingWindowLimiter:
    """Allows at most `max_events` per key within `window_seconds`."""

    def __init__(self, max_events, window_seconds):
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._events = {}
        self._lock = threading.Lock()

    def _prune(self, key, now):
        events = self._events.get(key)
        if events is None:
            return None
        cutoff = now - self.window_seconds
        while events and events[0] <= cutoff:
            events.popleft()
        if not events:
            self._events.pop(key, None)
            return None
        return events

    def check(self, key):
        """Return True if `key` is currently within its limit, without recording."""
        with self._lock:
            events = self._prune(key, time.monotonic())
            return len(events) < self.max_events if events else True

    def record(self, key):
        """Record one event. Returns True if still within the limit afterwards."""
        now = time.monotonic()
        with self._lock:
            events = self._events.setdefault(key, deque())
            cutoff = now - self.window_seconds
            while events and events[0] <= cutoff:
                events.popleft()
            events.append(now)
            return len(events) <= self.max_events

    def retry_after(self, key):
        """Seconds until the oldest recorded event leaves the window."""
        with self._lock:
            events = self._prune(key, time.monotonic())
            if not events or len(events) < self.max_events:
                return 0
            return max(0, int(self.window_seconds - (time.monotonic() - events[0])) + 1)

    def reset(self, key):
        """Clear a key, e.g. after a successful login."""
        with self._lock:
            self._events.pop(key, None)

    def clear(self):
        """Forget every key. Used to isolate tests from one another."""
        with self._lock:
            self._events.clear()
