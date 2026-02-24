"""
Simple cooldown tracker for autonomous chat responses.
"""

import time


class AutonomousRateLimiter:
    """Simple global cooldown for autonomous responses."""

    def __init__(self, cooldown_seconds: int = 5):
        self.cooldown = cooldown_seconds
        self.last_response = 0.0

    def can_respond(self) -> tuple[bool, int]:
        """Returns (can_respond, seconds_remaining)."""
        now = time.time()
        elapsed = now - self.last_response

        if elapsed >= self.cooldown:
            return True, 0

        remaining = int(self.cooldown - elapsed)
        return False, max(0, remaining)

    def mark_responded(self):
        """Record a successful autonomous response timestamp."""
        self.last_response = time.time()
