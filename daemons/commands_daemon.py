import random
import sys
import traceback
from pathlib import Path

# Add parent directory to path so we can import engine and utils
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import ask_openrouter, build_prompt_from_keyword
from utils.helpers import load_json, log_event, write_to_file
from utils.paths import Paths

ROLE_ORDER = {
    "normal": 0,
    "vip": 1,
    "moderator": 2,
    "broadcaster": 3,
}

FALLBACK_RESPONSES = [
    "Mai had a command hiccup. Try that again in a moment.",
    "Command processing glitched. Please retry shortly.",
    "I missed that command timing. Run it again for me.",
]


class _SafeFormatDict(dict):
    def __missing__(self, key: str) -> str:
        return ""


def _normalize_level(value: str) -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "mod": "moderator",
        "mods": "moderator",
        "broadcaster": "broadcaster",
        "owner": "broadcaster",
        "vip": "vip",
        "normal": "normal",
        "user": "normal",
    }
    return aliases.get(raw, "normal")


def _normalize_username_set(value) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item).strip().lower() for item in value if str(item).strip()}


def _format_message(template: str, **payload) -> str:
    return str(template or "").format_map(_SafeFormatDict(payload)).strip()


def _get_broadcaster_username(config: dict) -> str:
    monitor_cfg = config.get("monitor", {}) if isinstance(config.get("monitor", {}), dict) else {}
    channel = (
        monitor_cfg.get("twitch_channel")
        or config.get("twitch_channel")
        or monitor_cfg.get("owner_username")
        or ""
    )
    return str(channel).strip().lower()


def resolve_user_level(username: str, access_data: dict, config_data: dict) -> str:
    user = str(username or "").strip().lower()
    if not user:
        return "normal"

    broadcaster = _get_broadcaster_username(config_data)
    if broadcaster and user == broadcaster:
        return "broadcaster"

    moderator_users = _normalize_username_set(access_data.get("moderator_users", []))
    if user in moderator_users:
        return "moderator"

    vip_users = _normalize_username_set(access_data.get("vip_users", []))
    if user in vip_users:
        return "vip"

    return "normal"


def parse_command(raw_input: str) -> tuple[str, str]:
    tokens = str(raw_input or "").strip().split()
    if not tokens:
        return "", ""

    first = tokens[0].strip()
    key = first[1:] if first.startswith("!") else first
    return key.lower(), " ".join(tokens[1:]).strip()


def resolve_command(command_key: str, commands_data: dict) -> tuple[str, dict] | tuple[None, None]:
    if command_key in commands_data and isinstance(commands_data[command_key], dict):
        return command_key, commands_data[command_key]

    lookup = command_key.lower()
    for key, payload in commands_data.items():
        if not isinstance(payload, dict):
            continue
        aliases = payload.get("aliases", [])
        alias_set = {str(a).strip().lower().lstrip("!") for a in aliases if str(a).strip()}
        if lookup in alias_set:
            return key, payload

    return None, None


def has_permission(user_level: str, min_level: str) -> bool:
    return ROLE_ORDER.get(user_level, 0) >= ROLE_ORDER.get(min_level, 0)


def build_command_prompt(
    command_key: str,
    command_args: str,
    raw_input: str,
    username: str,
    user_level: str,
    min_level: str,
    command_data: dict,
) -> str:
    context = {
        "command": command_key,
        "username": username,
        "user_level": user_level,
        "min_level": min_level,
        "command_description": command_data.get("description", ""),
        "command_context": command_data.get("context", ""),
        "command_usage": command_data.get("usage", f"!{command_key}"),
        "response_data": command_data.get("response_data", ""),
        "command_args": command_args,
        "raw_input": raw_input,
    }
    return build_prompt_from_keyword("commands", context=context)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    log_event("commands_daemon_started", {"args": sys.argv}, Paths.CALLS_LOG)

    if len(sys.argv) < 2:
        msg = "Usage: python commands_daemon.py <rawInput> [username]"
        print(msg)
        write_to_file("Mai needs a chat command like !social.", Paths.COMMAND_OUTPUT)
        sys.exit(1)

    raw_input = sys.argv[1]
    username = sys.argv[2] if len(sys.argv) >= 3 else "Anonymous"

    command_key, command_args = parse_command(raw_input)

    access_data = load_json(Paths.COMMAND_ACCESS, default={})
    commands_data = load_json(Paths.COMMANDS, default={})
    config_data = load_json(Paths.CONFIG, default={})

    invalid_input_message = access_data.get(
        "invalid_input_message",
        "@{username} - use a command like !social, !discord, or !about.",
    )
    unknown_command_message = access_data.get(
        "unknown_command_message",
        "@{username} - I do not have !{command} configured yet.",
    )
    permission_denied_message = access_data.get(
        "permission_denied_message",
        "@{username} - !{command} requires {min_level} access.",
    )

    if not command_key:
        output = _format_message(invalid_input_message, username=username)
        print(output)
        write_to_file(output, Paths.COMMAND_OUTPUT)
        log_event(
            "command_invalid_input",
            {"username": username, "raw_input": raw_input, "output": output},
            Paths.COMMAND_HISTORY,
        )
        sys.exit(0)

    resolved_key, command_cfg = resolve_command(command_key, commands_data)
    if not resolved_key or not command_cfg:
        output = _format_message(unknown_command_message, username=username, command=command_key)
        print(output)
        write_to_file(output, Paths.COMMAND_OUTPUT)
        log_event(
            "command_unknown",
            {"username": username, "raw_input": raw_input, "command": command_key, "output": output},
            Paths.COMMAND_HISTORY,
        )
        sys.exit(0)

    user_level = resolve_user_level(username, access_data, config_data)
    min_level = _normalize_level(command_cfg.get("min_level", "normal"))

    if not has_permission(user_level, min_level):
        output = _format_message(
            permission_denied_message,
            username=username,
            command=resolved_key,
            min_level=min_level,
            user_level=user_level,
        )
        print(output)
        write_to_file(output, Paths.COMMAND_OUTPUT)
        log_event(
            "command_permission_denied",
            {
                "username": username,
                "command": resolved_key,
                "raw_input": raw_input,
                "user_level": user_level,
                "required_level": min_level,
                "output": output,
            },
            Paths.COMMAND_HISTORY,
        )
        sys.exit(0)

    try:
        prompt = build_command_prompt(
            command_key=resolved_key,
            command_args=command_args,
            raw_input=raw_input,
            username=username,
            user_level=user_level,
            min_level=min_level,
            command_data=command_cfg,
        )
        if prompt.startswith("WARNING:"):
            raise RuntimeError(prompt)

        response = ask_openrouter(prompt, spicy=False)
        if response.startswith("WARNING:"):
            raise RuntimeError(response)

        print(response)
        write_to_file(response, Paths.COMMAND_OUTPUT)
        log_event(
            "command_generated",
            {
                "username": username,
                "command": resolved_key,
                "raw_input": raw_input,
                "args": command_args,
                "user_level": user_level,
                "required_level": min_level,
                "prompt": prompt,
                "response": response,
            },
            Paths.COMMAND_HISTORY,
        )
        sys.exit(0)

    except Exception as e:
        fallback = random.choice(FALLBACK_RESPONSES)
        print(fallback)
        write_to_file(fallback, Paths.COMMAND_OUTPUT)
        log_event(
            "command_generation_error",
            {
                "username": username,
                "command": resolved_key,
                "raw_input": raw_input,
                "args": command_args,
                "user_level": user_level,
                "required_level": min_level,
                "error_type": type(e).__name__,
                "error_message": str(e),
                "error_traceback": traceback.format_exc(),
                "fallback_used": fallback,
            },
            Paths.ERROR_LOG,
        )
        sys.exit(0)
