import json
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import time
from typing import Any, Iterable, Mapping


# ============================
# Filesystem + data helpers
# ============================

def ensure_parent_dir(file_path: str | Path) -> Path:
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_json(file_path: str | Path, default: Any = None) -> Any:
    path = Path(file_path)
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(f"JSON file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def atomic_write_text(file_path: str | Path, text: str, encoding: str = "utf-8") -> None:
    path = ensure_parent_dir(file_path)
    with NamedTemporaryFile("w", encoding=encoding, dir=path.parent, delete=False) as tmp_file:
        tmp_file.write(text)
        tmp_name = tmp_file.name
    os.replace(tmp_name, path)


def atomic_write_json(
    file_path: str | Path,
    payload: Any,
    ensure_ascii: bool = False,
    indent: int = 2,
) -> None:
    serialized = json.dumps(payload, ensure_ascii=ensure_ascii, indent=indent)
    atomic_write_text(file_path, serialized + "\n")


def append_jsonl(file_path: str | Path, record: Mapping[str, Any], ensure_ascii: bool = False) -> None:
    path = ensure_parent_dir(file_path)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=ensure_ascii) + "\n")


def append_jsonl_many(
    file_path: str | Path,
    records: Iterable[Mapping[str, Any]],
    ensure_ascii: bool = False,
) -> None:
    path = ensure_parent_dir(file_path)
    with path.open("a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=ensure_ascii) + "\n")


def write_to_file(content: str, file_path: str | Path, append_newline: bool = True) -> None:
    text = content + ("\n" if append_newline else "")
    atomic_write_text(file_path, text)


def sanitize_path_component(value: str, replacement: str = "_") -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", replacement, str(value))


# ============================
# Time + secret helpers
# ============================

def utc_now_unix() -> int:
    return int(time())


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_secret(
    keys: Mapping[str, Any] | None,
    env_var: str,
    key_name: str,
    default: str | None = None,
) -> str | None:
    env_value = os.getenv(env_var)
    if env_value:
        return env_value
    if keys and key_name in keys and keys[key_name]:
        return str(keys[key_name])
    return default


# ============================
# Loaders
# ============================

def load_config() -> dict:
    return load_json("configs/config.json")


def load_keys() -> dict:
    return load_json("configs/keys.json")


# ============================
# Redaction
# ============================

def apply_redaction(text: str, level: int, redaction_data: dict, style: str | None = None) -> str:
    threshold = redaction_data.get("threshold") or 7
    max_replacements = redaction_data.get("max_replacements", 1)
    filler_words = set(redaction_data.get("ignored_words", []))

    if level < threshold:
        return text

    styles = redaction_data.get("styles", {})
    if not styles:
        return text

    if style is None:
        style = random.choice(list(styles.keys()))

    style_pool = styles.get(style, ["[REDACTED]"])
    if not style_pool:
        return text

    # Target longer words only (avoid breaking short syntax words)
    candidates = [
        word
        for word in re.findall(r"\b[A-Za-z]{5,}\b", text)
        if word.lower() not in filler_words
        and not word.lower().endswith("ly")  # skip adverbs
        and not word.lower().endswith("ing")  # skip gerunds
    ]
    if not candidates:
        return text

    targets = random.sample(candidates, min(max_replacements, len(candidates)))

    for word in targets:
        replacement_token = random.choice(style_pool)
        text = re.sub(rf"\b{re.escape(word)}\b", replacement_token, text, count=1)

    return text


# ============================
# Logging
# ============================

def write_to_log(entry: Mapping[str, Any], file_path: str | Path) -> None:
    append_jsonl(file_path, entry)


def log_event(event_type: str, payload: Mapping[str, Any], file_path: str | Path) -> None:
    entry = {
        **payload,
        "event": event_type,
        "timestamp": utc_now_unix(),
    }
    write_to_log(entry, file_path)


# ============================
# Parse Streamer.bot
# ============================

def parse_streamer_bot_command(command_str: str):
    themes = load_json("data/themes.json", default={})
    tones = load_json("data/tone.json", default={})
    spice_levels = load_json("data/spice.json", default={})

    args = command_str.split()
    for token in args:
        cleaned = token.strip().lower()
        if cleaned in themes:
            return "theme", cleaned
        if cleaned in tones:
            return "tone", cleaned
        if cleaned in spice_levels and cleaned.isdigit():
            return "spice", int(cleaned)

    return None, None
