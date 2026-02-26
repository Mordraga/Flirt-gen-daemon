"""
Hot-reloadable monitor configuration.

Reads the ``monitor`` section of jsons/configs/config.json and exposes it
as a plain attribute bag. Reloads automatically when the file changes on disk.
"""

import time
from pathlib import Path

from mai_personality import WITCH_USERNAME
from utils.helpers import load_config, log_event
from utils.paths import Paths


DEFAULT_MONITOR_CONFIG: dict = {
    "irc_server": "irc.chat.twitch.tv",
    "irc_port": 6667,
    "response_chance_percent": 35.0,
    "global_cooldown_seconds": 5,
    "check_buffer_size": 2048,
    "ignored_bot_usernames": ["nightbot", "streamelements", "streamlabs", "moobot", "fossabot"],
    "respond_to_owner_always": True,
    "ignore_command_messages": True,
    "owner_username": WITCH_USERNAME,
    "config_reload_seconds": 2.0,
    "registry_flush_seconds": 30,
    "mood_reroll_enabled": True,
    "mood_reroll_seconds": 1200,
}


class LiveMonitorConfig:
    """Hot-reloadable monitor configuration sourced from jsons/configs/config.json."""

    def __init__(self, config_path: str = Paths.CONFIG):
        self.config_path = Path(config_path)
        self._last_mtime = 0.0
        self._last_check = 0.0
        self._last_log_error_at = 0.0

        # Initialize with defaults
        self.irc_server = DEFAULT_MONITOR_CONFIG["irc_server"]
        self.irc_port = DEFAULT_MONITOR_CONFIG["irc_port"]
        self.response_chance_percent = DEFAULT_MONITOR_CONFIG["response_chance_percent"]
        self.global_cooldown_seconds = DEFAULT_MONITOR_CONFIG["global_cooldown_seconds"]
        self.check_buffer_size = DEFAULT_MONITOR_CONFIG["check_buffer_size"]
        self.ignored_bot_usernames = set(DEFAULT_MONITOR_CONFIG["ignored_bot_usernames"])
        self.respond_to_owner_always = DEFAULT_MONITOR_CONFIG["respond_to_owner_always"]
        self.ignore_command_messages = DEFAULT_MONITOR_CONFIG["ignore_command_messages"]
        self.owner_username = DEFAULT_MONITOR_CONFIG["owner_username"]
        self.config_reload_seconds = DEFAULT_MONITOR_CONFIG["config_reload_seconds"]
        self.registry_flush_seconds = DEFAULT_MONITOR_CONFIG["registry_flush_seconds"]
        self.mood_reroll_enabled = DEFAULT_MONITOR_CONFIG["mood_reroll_enabled"]
        self.mood_reroll_seconds = DEFAULT_MONITOR_CONFIG["mood_reroll_seconds"]

        self.reload(force=True)

    # ------------------------------------------------------------------
    # Type coercions
    # ------------------------------------------------------------------

    @staticmethod
    def _as_float(value, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _as_int(value, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    @staticmethod
    def _as_bool(value, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off"}:
                return False
        return bool(default)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _throttled_reload_error(self, error: Exception):
        now = time.time()
        if now - self._last_log_error_at >= 30:
            self._last_log_error_at = now
            print(f"[Mai Monitor] Config reload warning: {error}")
            log_event(
                "monitor_config_reload_error",
                {"error": str(error)},
                Paths.AUTONOMOUS_ERRORS,
            )

    def _apply(self, monitor_config: dict):
        self.irc_server = (
            str(monitor_config.get("irc_server", self.irc_server)).strip()
            or DEFAULT_MONITOR_CONFIG["irc_server"]
        )

        irc_port = self._as_int(
            monitor_config.get("irc_port", self.irc_port),
            DEFAULT_MONITOR_CONFIG["irc_port"],
        )
        self.irc_port = max(1, min(65535, irc_port))

        response_percent = self._as_float(
            monitor_config.get("response_chance_percent", self.response_chance_percent),
            DEFAULT_MONITOR_CONFIG["response_chance_percent"],
        )
        self.response_chance_percent = max(0.0, min(100.0, response_percent))

        cooldown = self._as_int(
            monitor_config.get("global_cooldown_seconds", self.global_cooldown_seconds),
            DEFAULT_MONITOR_CONFIG["global_cooldown_seconds"],
        )
        self.global_cooldown_seconds = max(0, cooldown)

        buffer_size = self._as_int(
            monitor_config.get("check_buffer_size", self.check_buffer_size),
            DEFAULT_MONITOR_CONFIG["check_buffer_size"],
        )
        self.check_buffer_size = max(256, buffer_size)

        ignored_raw = monitor_config.get("ignored_bot_usernames", list(self.ignored_bot_usernames))
        if isinstance(ignored_raw, str):
            ignored_list = [name.strip() for name in ignored_raw.split(",") if name.strip()]
        elif isinstance(ignored_raw, list):
            ignored_list = [str(name).strip() for name in ignored_raw if str(name).strip()]
        else:
            ignored_list = list(DEFAULT_MONITOR_CONFIG["ignored_bot_usernames"])
        self.ignored_bot_usernames = {name.lower() for name in ignored_list}

        self.respond_to_owner_always = self._as_bool(
            monitor_config.get("respond_to_owner_always", self.respond_to_owner_always),
            DEFAULT_MONITOR_CONFIG["respond_to_owner_always"],
        )

        self.ignore_command_messages = self._as_bool(
            monitor_config.get("ignore_command_messages", self.ignore_command_messages),
            DEFAULT_MONITOR_CONFIG["ignore_command_messages"],
        )

        owner = str(monitor_config.get("owner_username", self.owner_username)).strip().lower()
        self.owner_username = owner or WITCH_USERNAME

        reload_seconds = self._as_float(
            monitor_config.get("config_reload_seconds", self.config_reload_seconds),
            DEFAULT_MONITOR_CONFIG["config_reload_seconds"],
        )
        self.config_reload_seconds = max(0.5, reload_seconds)

        flush_seconds = self._as_int(
            monitor_config.get("registry_flush_seconds", self.registry_flush_seconds),
            DEFAULT_MONITOR_CONFIG["registry_flush_seconds"],
        )
        self.registry_flush_seconds = max(5, flush_seconds)

        self.mood_reroll_enabled = self._as_bool(
            monitor_config.get("mood_reroll_enabled", self.mood_reroll_enabled),
            DEFAULT_MONITOR_CONFIG["mood_reroll_enabled"],
        )
        mood_reroll_seconds = self._as_int(
            monitor_config.get("mood_reroll_seconds", self.mood_reroll_seconds),
            DEFAULT_MONITOR_CONFIG["mood_reroll_seconds"],
        )
        self.mood_reroll_seconds = max(30, mood_reroll_seconds)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reload(self, force: bool = False) -> bool:
        """Reload config if the file has changed. Returns True if reloaded."""
        now = time.time()
        if not force and now - self._last_check < self.config_reload_seconds:
            return False

        self._last_check = now

        try:
            mtime = self.config_path.stat().st_mtime
        except Exception as e:
            self._throttled_reload_error(e)
            return False

        if not force and mtime <= self._last_mtime:
            return False

        try:
            full_config = load_config()
            monitor_config = full_config.get("monitor", {})
            if not isinstance(monitor_config, dict):
                monitor_config = {}

            self._apply(monitor_config)
            self._last_mtime = mtime
            print(
                f"[Mai Monitor] Config reloaded | chance={self.response_chance_percent}% "
                f"cooldown={self.global_cooldown_seconds}s owner={self.owner_username} "
                f"mood_reroll={'on' if self.mood_reroll_enabled else 'off'}({self.mood_reroll_seconds}s)"
            )
            return True

        except Exception as e:
            self._throttled_reload_error(e)
            return False
