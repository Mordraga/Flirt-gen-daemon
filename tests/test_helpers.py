import json
import os
import tempfile
import unittest
from pathlib import Path

from helpers import (
    append_jsonl_many,
    atomic_write_json,
    get_secret,
    load_json,
    sanitize_path_component,
)


class HelpersTests(unittest.TestCase):
    def test_load_json_uses_default_when_file_missing(self):
        missing = Path("__definitely_missing__.json")
        value = load_json(missing, default={"ok": True})
        self.assertEqual(value, {"ok": True})

    def test_get_secret_prefers_env_then_keys_then_default(self):
        os.environ["TEST_SECRET_ENV"] = "from_env"
        self.assertEqual(
            get_secret({"my_secret_key": "from_key"}, "TEST_SECRET_ENV", "my_secret_key"),
            "from_env",
        )
        del os.environ["TEST_SECRET_ENV"]

        self.assertEqual(
            get_secret({"my_secret_key": "from_key"}, "TEST_SECRET_ENV", "my_secret_key"),
            "from_key",
        )
        self.assertEqual(
            get_secret({}, "TEST_SECRET_ENV", "my_secret_key", default="fallback"),
            "fallback",
        )

    def test_sanitize_path_component(self):
        self.assertEqual(sanitize_path_component("thread:id/123"), "thread_id_123")

    def test_atomic_write_json_and_append_jsonl_many(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            json_file = tmp_path / "a" / "payload.json"
            jsonl_file = tmp_path / "b" / "events.jsonl"

            atomic_write_json(json_file, {"x": 1})
            self.assertEqual(load_json(json_file), {"x": 1})

            append_jsonl_many(jsonl_file, [{"a": 1}, {"b": 2}])
            lines = jsonl_file.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(json.loads(lines[0]), {"a": 1})
            self.assertEqual(json.loads(lines[1]), {"b": 2})


if __name__ == "__main__":
    unittest.main()
