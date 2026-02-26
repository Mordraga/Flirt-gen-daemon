import tempfile
import unittest
from pathlib import Path

from utils.cooldown_messages import (
    DEFAULT_TOOL_COOLDOWN_MESSAGES,
    choose_tool_cooldown_template,
    load_tool_cooldown_map,
)
from utils.helpers import atomic_write_json, load_json


class CooldownMessagesTests(unittest.TestCase):
    def test_loads_new_tool_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            cooldown_file = Path(tmp) / "cooldown_msg.json"
            atomic_write_json(
                cooldown_file,
                {
                    "tool_cooldowns": {
                        "flirt": ["f1", "f2"],
                        "tarot": ["t1"],
                    }
                },
            )

            tool_map = load_tool_cooldown_map(cooldown_file)
            self.assertEqual(tool_map["flirt"], ["f1", "f2"])
            self.assertEqual(tool_map["tarot"], ["t1"])

    def test_legacy_cooldown_messages_map_to_flirt(self):
        with tempfile.TemporaryDirectory() as tmp:
            cooldown_file = Path(tmp) / "cooldown_msg.json"
            atomic_write_json(cooldown_file, {"cooldown_messages": ["legacy-1", "legacy-2"]})

            tool_map = load_tool_cooldown_map(cooldown_file)
            self.assertEqual(tool_map["flirt"], ["legacy-1", "legacy-2"])
            self.assertEqual(tool_map["tarot"], DEFAULT_TOOL_COOLDOWN_MESSAGES["tarot"])

    def test_missing_or_empty_tool_uses_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            cooldown_file = Path(tmp) / "cooldown_msg.json"
            atomic_write_json(cooldown_file, {"tool_cooldowns": {"flirt": [], "tarot": []}})

            tool_map = load_tool_cooldown_map(cooldown_file)
            self.assertEqual(tool_map["flirt"], DEFAULT_TOOL_COOLDOWN_MESSAGES["flirt"])
            self.assertEqual(tool_map["tarot"], DEFAULT_TOOL_COOLDOWN_MESSAGES["tarot"])

    def test_history_is_tracked_per_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            cooldown_file = Path(tmp) / "cooldown_msg.json"
            history_file = Path(tmp) / "cooldown_history.json"
            atomic_write_json(
                cooldown_file,
                {
                    "tool_cooldowns": {
                        "flirt": ["f1", "f2"],
                        "tarot": ["t1", "t2"],
                    }
                },
            )
            atomic_write_json(
                history_file,
                {
                    "last_used_by_tool": {
                        "flirt": ["f1"],
                        "tarot": ["t1"],
                    }
                },
            )

            chosen = choose_tool_cooldown_template(
                "flirt",
                cooldown_path=cooldown_file,
                history_path=history_file,
                history_window=3,
            )
            self.assertEqual(chosen, "f2")

            history = load_json(history_file, default={})
            by_tool = history.get("last_used_by_tool", {})
            self.assertEqual(by_tool.get("tarot"), ["t1"])
            self.assertEqual(by_tool.get("flirt"), ["f1", "f2"])

    def test_legacy_last_used_history_maps_to_flirt(self):
        with tempfile.TemporaryDirectory() as tmp:
            cooldown_file = Path(tmp) / "cooldown_msg.json"
            history_file = Path(tmp) / "cooldown_history.json"
            atomic_write_json(
                cooldown_file,
                {
                    "tool_cooldowns": {
                        "flirt": ["f1", "f2"],
                        "tarot": ["t1"],
                    }
                },
            )
            atomic_write_json(history_file, {"last_used": ["f1"]})

            chosen = choose_tool_cooldown_template(
                "flirt",
                cooldown_path=cooldown_file,
                history_path=history_file,
                history_window=3,
            )
            self.assertEqual(chosen, "f2")

            history = load_json(history_file, default={})
            by_tool = history.get("last_used_by_tool", {})
            self.assertEqual(by_tool.get("flirt"), ["f1", "f2"])
            self.assertEqual(by_tool.get("tarot"), [])


if __name__ == "__main__":
    unittest.main()
