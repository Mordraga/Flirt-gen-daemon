import random
from pathlib import Path

from utils.helpers import atomic_write_json, load_json
from utils.paths import Paths

TOOL_COOLDOWN_KEYS = ("flirt", "tarot")

DEFAULT_TOOL_COOLDOWN_MESSAGES: dict[str, list[str]] = {
    "flirt": [
        "Give me {remaining}s to recharge for you!",
    ],
    "tarot": [
        "The cards need {remaining}s to reset for you!",
    ],
}


def _normalize_message_list(raw_value) -> list[str]:
    if not isinstance(raw_value, list):
        return []
    items: list[str] = []
    for item in raw_value:
        text = str(item).strip()
        if not text:
            continue
        items.append(text)
    return items


def _normalize_tool_name(tool_name: str) -> str:
    normalized = str(tool_name or "").strip().lower()
    return normalized if normalized in TOOL_COOLDOWN_KEYS else "flirt"


def load_tool_cooldown_map(cooldown_path: str | Path = Paths.COOLDOWN_MSGS) -> dict[str, list[str]]:
    payload = load_json(cooldown_path, default={})
    if not isinstance(payload, dict):
        payload = {}

    mapped: dict[str, list[str]] = {}
    raw_tool_cooldowns = payload.get("tool_cooldowns", {})
    if isinstance(raw_tool_cooldowns, dict):
        for raw_tool, raw_messages in raw_tool_cooldowns.items():
            tool = str(raw_tool or "").strip().lower()
            if tool not in TOOL_COOLDOWN_KEYS:
                continue
            mapped[tool] = _normalize_message_list(raw_messages)

    legacy_flirt = _normalize_message_list(payload.get("cooldown_messages", []))
    if legacy_flirt and not mapped.get("flirt"):
        mapped["flirt"] = legacy_flirt

    normalized: dict[str, list[str]] = {}
    for tool in TOOL_COOLDOWN_KEYS:
        messages = mapped.get(tool, [])
        normalized[tool] = messages or list(DEFAULT_TOOL_COOLDOWN_MESSAGES[tool])
    return normalized


def save_tool_cooldown_map(
    tool_cooldowns: dict[str, list[str]],
    cooldown_path: str | Path = Paths.COOLDOWN_MSGS,
) -> None:
    payload = {"tool_cooldowns": {}}
    for tool in TOOL_COOLDOWN_KEYS:
        values = _normalize_message_list(tool_cooldowns.get(tool, []))
        payload["tool_cooldowns"][tool] = values
    atomic_write_json(cooldown_path, payload)


def _load_cooldown_history_map(history_path: str | Path = Paths.COOLDOWN_HISTORY) -> dict[str, list[str]]:
    payload = load_json(history_path, default={})
    if not isinstance(payload, dict):
        payload = {}

    history_by_tool: dict[str, list[str]] = {}
    raw_by_tool = payload.get("last_used_by_tool", {})
    if isinstance(raw_by_tool, dict):
        for raw_tool, raw_messages in raw_by_tool.items():
            tool = str(raw_tool or "").strip().lower()
            if tool not in TOOL_COOLDOWN_KEYS:
                continue
            history_by_tool[tool] = _normalize_message_list(raw_messages)

    legacy_history = _normalize_message_list(payload.get("last_used", []))
    if legacy_history and not history_by_tool.get("flirt"):
        history_by_tool["flirt"] = legacy_history

    for tool in TOOL_COOLDOWN_KEYS:
        history_by_tool.setdefault(tool, [])
    return history_by_tool


def choose_tool_cooldown_template(
    tool_name: str,
    cooldown_path: str | Path = Paths.COOLDOWN_MSGS,
    history_path: str | Path = Paths.COOLDOWN_HISTORY,
    history_window: int = 3,
) -> str:
    tool = _normalize_tool_name(tool_name)
    templates = load_tool_cooldown_map(cooldown_path).get(tool) or list(DEFAULT_TOOL_COOLDOWN_MESSAGES[tool])

    history_by_tool = _load_cooldown_history_map(history_path)
    last_used = list(history_by_tool.get(tool, []))
    available = [msg for msg in templates if msg not in last_used]
    if not available:
        available = list(templates)
        last_used = []

    template = random.choice(available)
    last_used.append(template)
    if history_window > 0:
        last_used = last_used[-history_window:]
    else:
        last_used = []

    history_by_tool[tool] = last_used
    atomic_write_json(history_path, {"last_used_by_tool": history_by_tool})
    return template


def format_cooldown_template(template: str, remaining_seconds: int) -> str:
    raw_template = str(template or "").strip()
    if not raw_template:
        raw_template = "Please wait {remaining}s."
    try:
        return raw_template.format(remaining=remaining_seconds)
    except Exception:
        return raw_template.replace("{remaining}", str(remaining_seconds))
