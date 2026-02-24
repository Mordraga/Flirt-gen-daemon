import random
import socket
import sys
import time
from pathlib import Path

# Add parent to path if needed
sys.path.insert(0, str(Path(__file__).parent))

from engine import ask_openrouter
from mai_personality import (
    detect_context,
    generate_contextual_response,
    get_contextual_fallback,
    is_mordraga,
    mordraga_chat,
)
from monitor import AutonomousRateLimiter, LiveMonitorConfig
from utils.helpers import atomic_write_json, load_config, load_json, load_keys, log_event, sanitize_path_component
from utils.irc_utils import parse_privmsg as _parse_privmsg_line
from utils.paths import Paths


class MaiMonitor:
    def __init__(self, oauth_token: str, bot_username: str, channel: str):
        self.oauth = oauth_token
        self.bot_username = bot_username.lower()
        self.channel = channel.lower()
        self.irc = None
        self.settings = LiveMonitorConfig()
        self.rate_limiter = AutonomousRateLimiter(self.settings.global_cooldown_seconds)
        self.connected = False
        self._last_registry_flush = 0.0
        self.user_history = {}
        self.user_aliases: dict[str, str] = {}
        self.user_history_dir = Path(Paths.USER_HISTORY_DIR)

    def connect(self):
        """Connect to Twitch IRC."""
        try:
            self.irc = socket.socket()
            self.irc.connect((self.settings.irc_server, self.settings.irc_port))

            self.irc.send(f"PASS {self.oauth}\r\n".encode("utf-8"))
            self.irc.send(f"NICK {self.bot_username}\r\n".encode("utf-8"))
            self.irc.send(b"CAP REQ :twitch.tv/tags twitch.tv/commands\r\n")
            self.irc.send(f"JOIN #{self.channel}\r\n".encode("utf-8"))

            self.connected = True
            print(f"[Mai Monitor] Connected to #{self.channel} as {self.bot_username}")
            print(f"[Mai Monitor] Trigger chance: {self.settings.response_chance_percent}%")
            print(f"[Mai Monitor] Global cooldown: {self.settings.global_cooldown_seconds}s")
            return True

        except Exception as e:
            print(f"[Mai Monitor] Connection error: {e}")
            log_event("monitor_connection_error", {"error": str(e)}, Paths.AUTONOMOUS_ERRORS)
            return False

    def _is_owner(self, username: str) -> bool:
        return is_mordraga(username, owner_username=self.settings.owner_username)

    def refresh_runtime_config(self):
        """Hot-reload runtime settings and apply dependent values."""
        if self.settings.reload():
            self.rate_limiter.cooldown = self.settings.global_cooldown_seconds

    def _canonical_username(self, username: str) -> str:
        cleaned = str(username).strip() or "unknown_user"
        key = cleaned.lower()
        existing = self.user_aliases.get(key)
        if existing:
            prefer_cleaned = cleaned != cleaned.lower() and existing == existing.lower()
            if prefer_cleaned:
                if existing in self.user_history and cleaned not in self.user_history:
                    self.user_history[cleaned] = self.user_history.pop(existing)
                self.user_aliases[key] = cleaned
                return cleaned
            return existing

        self.user_aliases[key] = cleaned
        return cleaned

    def _recent_messages_for_user(self, username: str, limit: int = 5) -> list[str]:
        user_bucket = self.user_history.get(username, {})
        messages = user_bucket.get("messages", []) if isinstance(user_bucket, dict) else []
        if not isinstance(messages, list):
            return []

        recent: list[str] = []
        for item in messages[-limit:]:
            if not isinstance(item, dict):
                continue
            text = str(item.get("message", "")).strip()
            if text:
                recent.append(text)
        return recent

    def _append_user_file_history(self, username: str, message: str, timestamp: float) -> None:
        safe_name = sanitize_path_component(username)
        user_file = self.user_history_dir / f"{safe_name}.json"

        payload = load_json(user_file, default={})
        if not isinstance(payload, dict):
            payload = {}

        entries = payload.get("messages", [])
        if not isinstance(entries, list):
            entries = []

        entries.append({"message": message, "timestamp": timestamp})
        max_messages = 500
        if len(entries) > max_messages:
            entries = entries[-max_messages:]

        payload["username"] = payload.get("username") or username
        payload["last_seen"] = timestamp
        payload["message_count"] = int(payload.get("message_count", 0)) + 1
        payload["messages"] = entries
        atomic_write_json(user_file, payload)

    def send_message(self, message: str):
        """Send message to chat."""
        if not self.connected or not self.irc:
            return

        try:
            sanitized = message.replace("\r", " ").replace("\n", " ").strip()
            if not sanitized:
                return
            self.irc.send(f"PRIVMSG #{self.channel} :{sanitized}\r\n".encode("utf-8"))
            print(f"[Mai -> Chat] {sanitized}")
        except Exception as e:
            print(f"[Mai Monitor] Send error: {e}")
            log_event(
                "monitor_send_error",
                {"error": str(e), "message": message},
                Paths.AUTONOMOUS_ERRORS,
            )

    def _parse_privmsg(self, line: str) -> tuple[str, str] | None:
        result = _parse_privmsg_line(line)
        if result is None:
            return None
        username, _, message = result
        return username, message

    def should_respond(self, username: str, message: str) -> bool:
        """Determine if Mai should respond to this message."""
        username_lower = username.lower()

        if username_lower == self.bot_username:
            return False

        if username_lower in self.settings.ignored_bot_usernames:
            return False

        if self.settings.ignore_command_messages and message.startswith("!"):
            return False

        if self.settings.respond_to_owner_always and self._is_owner(username):
            return True

        can_respond, _remaining = self.rate_limiter.can_respond()
        if not can_respond:
            return False

        if random.uniform(0.0, 100.0) > self.settings.response_chance_percent:
            return False

        return True

    def generate_response(self, username: str, message: str, recent_messages: list[str] | None = None) -> str:
        """Generate contextual response using personality engine."""
        try:
            context = detect_context(message)
            print(f"[Mai Context] {context}")

            if self._is_owner(username):
                response = mordraga_chat(
                    username=username,
                    message=message,
                    llm_backend=ask_openrouter,
                    owner_username=self.settings.owner_username,
                    recent_messages=recent_messages,
                )
            else:
                response = generate_contextual_response(
                    username=username,
                    message=message,
                    llm_backend=ask_openrouter,
                    owner_username=self.settings.owner_username,
                    recent_messages=recent_messages,
                )

            if response.startswith("WARNING:"):
                raise RuntimeError(response)

            return response

        except Exception as e:
            print(f"[Mai Monitor] Generation error: {e}")
            log_event(
                "monitor_generation_error",
                {
                    "username": username,
                    "message": message,
                    "error": str(e),
                },
                Paths.AUTONOMOUS_ERRORS,
            )

            context = detect_context(message)
            return get_contextual_fallback(context)

    def autonomous_response(self, username: str, trigger_message: str, recent_messages: list[str] | None = None):
        """Generate and send autonomous response."""
        print(f"[Mai Triggered] {username}: {trigger_message}")

        response = self.generate_response(username, trigger_message, recent_messages=recent_messages)
        self.send_message(response)

        if not self._is_owner(username):
            self.rate_limiter.mark_responded()

        log_event(
            "autonomous_response",
            {
                "username": username,
                "trigger_message": trigger_message,
                "response": response,
                "timestamp": time.time(),
            },
            Paths.AUTONOMOUS_HISTORY,
        )

    def listen(self):
        """Main loop: listen to chat and respond autonomously."""
        buffer = ""
        self._last_registry_flush = time.time()
        self.user_history = load_json(Paths.USER_REGISTRY, default={})
        if not isinstance(self.user_history, dict):
            self.user_history = {}
        self.user_aliases = {
            str(name).lower(): str(name)
            for name in self.user_history.keys()
            if str(name).strip()
        }

        while self.connected:
            try:
                self.refresh_runtime_config()

                data = self.irc.recv(self.settings.check_buffer_size).decode("utf-8", errors="ignore")
                if not data:
                    raise ConnectionError("Disconnected from Twitch IRC")

                buffer += data
                lines = buffer.split("\r\n")
                buffer = lines.pop()

                for line in lines:
                    if line.startswith("PING"):
                        pong_target = line.split()[1]
                        self.irc.send(f"PONG {pong_target}\r\n".encode("utf-8"))
                        continue

                    parsed = self._parse_privmsg(line)
                    if not parsed:
                        continue

                    raw_username, message = parsed
                    username = self._canonical_username(raw_username)
                    now = time.time()

                    log_event(
                        "chat_message",
                        {
                            "username": username,
                            "message": message,
                            "timestamp": now,
                        },
                        Paths.CHAT_LOG,
                    )

                    if username not in self.user_history:
                        self.user_history[username] = {
                            "messages": [],
                            "last_seen": now,
                            "message_count": 0,
                        }

                    self.user_history[username]["messages"].append(
                        {"message": message, "timestamp": now}
                    )
                    self.user_history[username]["last_seen"] = now
                    self.user_history[username]["message_count"] += 1

                    max_messages_per_user = 20
                    if len(self.user_history[username]["messages"]) > max_messages_per_user:
                        self.user_history[username]["messages"].pop(0)

                    try:
                        self._append_user_file_history(username, message, now)
                    except Exception as e:
                        log_event(
                            "user_history_file_error",
                            {"username": username, "error": str(e)},
                            Paths.AUTONOMOUS_ERRORS,
                        )

                    if self.should_respond(username, message):
                        recent_messages = self._recent_messages_for_user(username, limit=5)
                        self.autonomous_response(username, message, recent_messages=recent_messages)

                now = time.time()
                if now - self._last_registry_flush >= self.settings.registry_flush_seconds:
                    atomic_write_json(Paths.USER_REGISTRY, self.user_history)
                    self._last_registry_flush = now

            except KeyboardInterrupt:
                print("\n[Mai Monitor] Shutting down...")
                self.connected = False
                break

            except Exception as e:
                print(f"[Mai Monitor] Listen error: {e}")
                log_event("monitor_listen_error", {"error": str(e)}, Paths.AUTONOMOUS_ERRORS)
                time.sleep(5)

        atomic_write_json(Paths.USER_REGISTRY, self.user_history)


def main():
    print("=" * 60)
    print("MAI AUTONOMOUS MONITOR")
    print("=" * 60)

    try:
        keys = load_keys()
        config = load_config()
    except Exception as e:
        print(f"[ERROR] Failed to load config: {e}")
        return

    oauth_token = keys.get("twitch_oauth_token")
    bot_username = keys.get("twitch_bot_username", "maidensacquisitionsai")

    monitor_cfg = config.get("monitor", {}) if isinstance(config.get("monitor", {}), dict) else {}
    channel = (
        monitor_cfg.get("twitch_channel")
        or config.get("twitch_channel")
        or monitor_cfg.get("owner_username")
        or "mordraga0"
    )

    if not oauth_token:
        print("[ERROR] Missing 'twitch_oauth_token' in jsons/configs/keys.json")
        print("[INFO] Generate token at: https://twitchapps.com/tmi/")
        return

    monitor = MaiMonitor(oauth_token, bot_username, channel)

    if monitor.connect():
        print("\n[Mai Monitor] Now monitoring chat autonomously...")
        print("[Mai Monitor] Press Ctrl+C to stop\n")

        try:
            monitor.listen()
        except KeyboardInterrupt:
            print("\n[Mai Monitor] Stopped by user")
        finally:
            if monitor.irc:
                monitor.irc.close()
            print("[Mai Monitor] Disconnected")
    else:
        print("[ERROR] Failed to connect to Twitch IRC")


if __name__ == "__main__":
    main()
