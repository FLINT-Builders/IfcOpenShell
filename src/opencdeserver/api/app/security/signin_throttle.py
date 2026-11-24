# This file was generated with the assistance of an AI coding tool.
from __future__ import annotations

import ipaddress
import threading
import time

MAX_FAILURES = 5
FAILURE_WINDOW_SECONDS = 15 * 60
LOCKOUT_SECONDS = 15 * 60
MAX_LOCKOUT_SECONDS = 24 * 60 * 60
PURGE_INTERVAL_SECONDS = 60


class _Entry:
    __slots__ = ("failures", "pending", "lockouts", "locked_until", "last_failure")

    def __init__(self):
        self.failures = 0
        self.pending = 0
        self.lockouts = 0
        self.locked_until = 0.0
        self.last_failure = 0.0

    def refresh(self, now: float) -> None:
        if self.locked_until:
            if now < self.locked_until:
                return
            self.locked_until = 0.0
            self.failures = 0
        elif self.failures and now - self.last_failure >= FAILURE_WINDOW_SECONDS:
            self.failures = 0
        if self.lockouts and now - self.last_failure >= MAX_LOCKOUT_SECONDS:
            self.lockouts = 0

    def retry_after(self, now: float) -> float:
        if self.locked_until > now:
            return self.locked_until - now
        if self.failures + self.pending >= MAX_FAILURES:
            return 1.0
        return 0.0

    def is_idle(self) -> bool:
        return not (self.failures or self.pending or self.lockouts or self.locked_until)


class SignInThrottle:
    """Counts failed sign-ins per key and locks a key out after MAX_FAILURES.

    A slot is reserved before the password is checked, so concurrent attempts
    cannot exceed the limit. Lockouts double in length on each repeat, up to
    MAX_LOCKOUT_SECONDS. State is per process: the server runs one uvicorn
    process.
    """

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[tuple, _Entry] = {}
        self._last_purge = clock()

    def reserve(self, keys) -> float:
        """Reserve an attempt for every key, or return seconds until one is allowed."""
        with self._lock:
            now = self._clock()
            self._purge(now)
            retry_after = 0.0
            for key in keys:
                entry = self._entries.get(key)
                if entry is not None:
                    entry.refresh(now)
                    retry_after = max(retry_after, entry.retry_after(now))
            if retry_after:
                return retry_after
            for key in keys:
                self._entries.setdefault(key, _Entry()).pending += 1
            return 0.0

    def release(self, keys, failed: bool, reset_keys=()) -> None:
        """Finish a reserved attempt, counting it as a failure if ``failed``."""
        with self._lock:
            now = self._clock()
            for key in keys:
                entry = self._entries[key]
                entry.pending -= 1
                if failed:
                    entry.failures += 1
                    entry.last_failure = now
                    if entry.failures >= MAX_FAILURES and not entry.locked_until:
                        entry.locked_until = now + min(LOCKOUT_SECONDS * 2**entry.lockouts, MAX_LOCKOUT_SECONDS)
                        entry.lockouts += 1
                elif key in reset_keys:
                    entry.failures = 0
                    entry.lockouts = 0
                if entry.is_idle():
                    del self._entries[key]

    def _purge(self, now: float) -> None:
        if now - self._last_purge < PURGE_INTERVAL_SECONDS:
            return
        self._last_purge = now
        for key in list(self._entries):
            entry = self._entries[key]
            entry.refresh(now)
            if entry.pending or entry.locked_until:
                continue
            if entry.is_idle() or now - entry.last_failure >= MAX_LOCKOUT_SECONDS:
                del self._entries[key]


def address_key(host: str | None) -> tuple:
    # One IPv6 client usually controls a whole /64.
    try:
        address = ipaddress.ip_address(host or "")
    except ValueError:
        return ("address", host or "")
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return ("address", str(address.ipv4_mapped))
        return ("address", str(ipaddress.ip_network(f"{address}/64", strict=False)))
    return ("address", str(address))


def account_key(username: str) -> tuple:
    return ("account", username)


signin_throttle = SignInThrottle()
