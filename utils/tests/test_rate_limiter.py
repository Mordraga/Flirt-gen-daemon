import tempfile
import unittest
from pathlib import Path

from utils.rate_limiter import GlobalRateLimiter, UserCooldownTracker


class RateLimiterTests(unittest.TestCase):
    def test_user_cooldown_normalizes_username_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            cooldown_file = Path(tmp) / "user_cooldowns.json"
            tracker = UserCooldownTracker(cooldown_file=cooldown_file)

            allowed_first, _ = tracker.check_cooldown("TestUser", cooldown_seconds=300)
            allowed_second, remaining = tracker.check_cooldown("testuser", cooldown_seconds=300)

            self.assertTrue(allowed_first)
            self.assertFalse(allowed_second)
            self.assertGreaterEqual(remaining, 0)

    def test_global_rate_limiter_persists_state_between_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "global_rate_limit.json"
            limiter_one = GlobalRateLimiter(max_calls=1, window=60, state_file=state_file)
            limiter_two = GlobalRateLimiter(max_calls=1, window=60, state_file=state_file)

            allowed_first, _ = limiter_one.allow_request()
            allowed_second, _ = limiter_two.allow_request()

            self.assertTrue(allowed_first)
            self.assertFalse(allowed_second)


if __name__ == "__main__":
    unittest.main()
