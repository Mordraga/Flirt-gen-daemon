"""
Shared rate-limiting utilities for all daemons.

Both flirt_daemon and tarot_daemon import from here to prevent duplication.
"""

import time
from collections import deque
from pathlib import Path

from utils.helpers import atomic_write_json, load_json, log_event
from utils.paths import Paths


class GlobalRateLimiter:
    """Sliding-window rate limiter — prevents API spam across all requests."""

    def __init__(self, max_calls: int = 30, window: int = 60):
        self.max_calls = max_calls
        self.window = window
        self.calls: deque = deque()

    def allow_request(self) -> tuple[bool, str]:
        """Returns (allowed, message). Message is empty when allowed."""
        now = time.time()
        while self.calls and self.calls[0] < now - self.window:
            self.calls.popleft()

        if len(self.calls) < self.max_calls:
            self.calls.append(now)
            return True, ""

        wait_time = int(self.calls[0] + self.window - now) + 1
        return False, f"Mai is catching her breath! Try again in {wait_time}s 💜"


class UserCooldownTracker:
    """Per-user cooldowns — prevents spam from a single user."""

    def __init__(self, cooldown_file: Path = Path(Paths.USER_COOLDOWNS)):
        self.cooldown_file = cooldown_file
        self.cooldowns = self._load_cooldowns()

    def _load_cooldowns(self) -> dict:
        try:
            return load_json(self.cooldown_file, default={})
        except Exception:
            return {}

    def _save_cooldowns(self):
        try:
            atomic_write_json(self.cooldown_file, self.cooldowns)
        except Exception as e:
            log_event("cooldown_save_error", {"error": str(e)}, Paths.ERROR_LOG)

    def check_cooldown(self, username: str, cooldown_seconds: int = 300) -> tuple[bool, int]:
        """Returns (can_request, seconds_remaining)."""
        now = time.time()
        last_request = self.cooldowns.get(username, 0)
        elapsed = now - last_request

        if elapsed >= cooldown_seconds:
            self.cooldowns[username] = now
            self._save_cooldowns()
            return True, 0

        remaining = int(cooldown_seconds - elapsed)
        return False, remaining
