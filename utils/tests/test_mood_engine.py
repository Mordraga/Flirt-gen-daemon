import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.helpers import atomic_write_json, load_json
from utils.mood_engine import (
    choose_weighted_mood,
    lock_mood,
    load_moods,
    load_moods_from_payload,
    manual_reroll,
    read_mood_state,
    reroll_if_due,
    resolve_effective_mood,
    start_monitor_session,
    unlock_mood,
)


class MoodEngineTests(unittest.TestCase):
    def test_loads_defaults_when_moods_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing_moods.json"
            payload = load_moods(path=missing)
            self.assertIn("neutral", payload["moods"])
            self.assertEqual(payload["default_mood"], "neutral")

    def test_weighted_choice_and_exclude_behavior(self):
        self.assertEqual(
            choose_weighted_mood(
                {"quiet": {"weight": 0}, "flirty": {"weight": 3}},
            ),
            "flirty",
        )
        self.assertEqual(
            choose_weighted_mood(
                {"neutral": {"weight": 5}, "spicy": {"weight": 1}},
                exclude="neutral",
            ),
            "spicy",
        )

    def test_payload_normalization_preserves_folder(self):
        normalized = load_moods_from_payload(
            {
                "default_mood": "flirty",
                "moods": {
                    "flirty": {
                        "weight": 2,
                        "folder": "high-energy",
                    }
                },
            }
        )
        self.assertEqual(normalized["moods"]["flirty"]["folder"], "high-energy")
        self.assertIn("folder", normalized["moods"]["neutral"])

    @patch("utils.mood_engine.load_moods")
    def test_start_monitor_session_writes_valid_state(self, mock_load_moods):
        mock_load_moods.return_value = {
            "default_mood": "neutral",
            "moods": {"flirty": {"weight": 1}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "session_mood.json"
            state = start_monitor_session(True, 120, path=state_path)
            self.assertTrue(state["active"])
            self.assertEqual(state["selected_by"], "auto_start")
            self.assertEqual(state["active_mood"], "flirty")
            self.assertGreater(state["next_reroll_at"], state["selected_at"])

            on_disk = read_mood_state(path=state_path)
            self.assertEqual(on_disk["session_id"], state["session_id"])
            self.assertTrue(on_disk["active"])

    @patch("utils.mood_engine.load_moods")
    @patch("utils.mood_engine.choose_weighted_mood")
    def test_reroll_if_due_changes_mood_when_unlocked(self, mock_choose, mock_load_moods):
        mock_load_moods.return_value = {
            "default_mood": "neutral",
            "moods": {"neutral": {"weight": 1}, "flirty": {"weight": 1}},
        }
        mock_choose.return_value = "flirty"
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "session_mood.json"
            initial = {
                "session_id": "s1",
                "active": True,
                "active_mood": "neutral",
                "locked_mood": "",
                "selected_by": "auto_start",
                "selected_at": time.time() - 500,
                "next_reroll_at": time.time() - 1,
                "last_heartbeat_at": time.time(),
            }
            atomic_write_json(state_path, initial)
            state, changed = reroll_if_due(initial, True, 120, path=state_path)
            self.assertTrue(changed)
            self.assertEqual(state["active_mood"], "flirty")
            self.assertEqual(state["selected_by"], "auto_reroll")
            self.assertGreater(state["next_reroll_at"], time.time())

    @patch("utils.mood_engine.choose_weighted_mood")
    def test_lock_prevents_timed_reroll(self, mock_choose):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "session_mood.json"
            initial = {
                "session_id": "s2",
                "active": True,
                "active_mood": "quiet",
                "locked_mood": "quiet",
                "selected_by": "manual_lock",
                "selected_at": time.time() - 60,
                "next_reroll_at": time.time() - 1,
                "last_heartbeat_at": time.time(),
            }
            atomic_write_json(state_path, initial)
            state, changed = reroll_if_due(initial, True, 120, path=state_path)
            self.assertFalse(changed)
            self.assertEqual(state["active_mood"], "quiet")
            self.assertEqual(state["next_reroll_at"], 0.0)
            mock_choose.assert_not_called()

    @patch("utils.mood_engine.time.time")
    @patch("utils.mood_engine.read_mood_state")
    @patch("utils.mood_engine.load_moods")
    def test_stale_or_inactive_session_falls_back_to_neutral(
        self,
        mock_load_moods,
        mock_read_state,
        mock_time,
    ):
        now = 1_900_000_000.0
        mock_time.return_value = now
        mock_load_moods.return_value = {
            "default_mood": "neutral",
            "moods": {
                "neutral": {"description": "n", "flirt_guidance": "neutral-flirt"},
                "flirty": {"description": "f", "flirt_guidance": "flirty-flirt"},
            },
        }
        mock_read_state.return_value = {
            "active": True,
            "active_mood": "flirty",
            "locked_mood": "",
            "selected_by": "auto_start",
            "last_heartbeat_at": now - 60,
        }

        mood = resolve_effective_mood("flirt", require_active_session=True)
        self.assertEqual(mood["name"], "neutral")
        self.assertEqual(mood["source"], "fallback")
        self.assertFalse(mood["active"])
        self.assertTrue(mood["stale"])

    @patch("utils.mood_engine.load_moods")
    @patch("utils.mood_engine.choose_weighted_mood")
    def test_manual_lock_unlock_reroll_transitions(self, mock_choose, mock_load_moods):
        mock_choose.return_value = "neutral"
        mock_load_moods.return_value = {
            "default_mood": "neutral",
            "moods": {
                "neutral": {"weight": 1},
                "flirty": {"weight": 1},
            },
        }

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "session_mood.json"
            active_state = {
                "session_id": "s3",
                "active": True,
                "active_mood": "neutral",
                "locked_mood": "",
                "selected_by": "auto_start",
                "selected_at": time.time(),
                "next_reroll_at": time.time() + 120,
                "last_heartbeat_at": time.time(),
            }
            atomic_write_json(state_path, active_state)

            locked = lock_mood(active_state, "flirty", path=state_path)
            self.assertTrue(locked["active"])
            self.assertEqual(locked["locked_mood"], "flirty")
            self.assertEqual(locked["selected_by"], "manual_lock")

            unlocked = unlock_mood(locked, reroll_enabled=True, reroll_seconds=120, path=state_path)
            self.assertEqual(unlocked["locked_mood"], "")
            self.assertEqual(unlocked["selected_by"], "manual_unlock")
            self.assertGreater(unlocked["next_reroll_at"], 0)

            rerolled = manual_reroll(unlocked, reroll_seconds=120, path=state_path)
            self.assertEqual(rerolled["selected_by"], "manual_reroll")
            self.assertEqual(rerolled["locked_mood"], "")
            self.assertEqual(rerolled["active_mood"], "neutral")

            on_disk = load_json(state_path, default={})
            self.assertEqual(on_disk.get("selected_by"), "manual_reroll")


if __name__ == "__main__":
    unittest.main()
