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
    """Sliding-window rate limiter that persists across daemon processes."""

    def __init__(
        self,
        max_calls: int = 30,
        window: int = 60,
        state_file: Path = Path(Paths.GLOBAL_RATE_LIMIT_STATE),
    ):
        self.max_calls = max_calls
        self.window = window
        self.state_file = state_file
        self.calls: deque[float] = deque()
        self._reload_calls()

    def _normalize_calls(self, raw_calls) -> deque[float]:
        values: deque[float] = deque()
        if not isinstance(raw_calls, list):
            return values
        for item in raw_calls:
            try:
                values.append(float(item))
            except (TypeError, ValueError):
                continue
        return values

    def _reload_calls(self) -> None:
        try:
            payload = load_json(self.state_file, default={})
            raw_calls = payload.get("calls", []) if isinstance(payload, dict) else []
            self.calls = self._normalize_calls(raw_calls)
        except Exception:
            self.calls = deque()

    def _save_calls(self) -> None:
        try:
            atomic_write_json(self.state_file, {"calls": list(self.calls)})
        except Exception as e:
            log_event("global_rate_limit_save_error", {"error": str(e)}, Paths.ERROR_LOG)

    def _prune(self, now: float) -> None:
        while self.calls and self.calls[0] < now - self.window:
            self.calls.popleft()

    def allow_request(self) -> tuple[bool, str]:
        """Returns (allowed, message). Message is empty when allowed."""
        now = time.time()
        self._reload_calls()
        self._prune(now)

        if len(self.calls) < self.max_calls:
            self.calls.append(now)
            self._save_calls()
            return True, ""

        wait_time = int(self.calls[0] + self.window - now) + 1
        self._save_calls()
        return False, f"Mai is catching her breath! Try again in {wait_time}s."


class UserCooldownTracker:
    """Per-user cooldowns to prevent spam from a single user."""

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
        user_key = str(username or "").strip().lower() or "anonymous"
        now = time.time()
        last_request = self.cooldowns.get(user_key, 0)
        elapsed = now - last_request

        if elapsed >= cooldown_seconds:
            self.cooldowns[user_key] = now
            self._save_cooldowns()
            return True, 0

        remaining = int(cooldown_seconds - elapsed)
        return False, remaining
