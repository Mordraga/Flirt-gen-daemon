import argparse
import re
import socket
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

import requests

from helpers import (
    append_jsonl_many,
    get_secret,
    load_json,
    log_event,
    sanitize_path_component,
    utc_now_iso,
)


TWITTER_SEARCH_URL = "https://api.twitter.com/2/tweets/search/recent"


@dataclass
class IngestedMessage:
    platform: str
    scope: str
    message_id: str
    username: str
    user_id: str | None
    sent_at_utc: str
    captured_at_utc: str
    text: str

def normalize_twitch_oauth_token(token: str) -> str:
    if not token:
        return token
    if token.startswith("oauth:"):
        return token
    return f"oauth:{token}"

def fetch_twitter_thread_messages(
    conversation_id: str,
    bearer_token: str,
    max_results: int,
    pages: int,
    since_id: str | None,
    timeout: int,
) -> list[IngestedMessage]:
    headers = {"Authorization": f"Bearer {bearer_token}"}
    params = {
        "query": f"conversation_id:{conversation_id} -is:retweet",
        "tweet.fields": "id,author_id,created_at,text,conversation_id",
        "expansions": "author_id",
        "user.fields": "id,username",
        "max_results": max(10, min(max_results, 100)),
    }
    if since_id:
        params["since_id"] = since_id

    messages: list[IngestedMessage] = []
    next_token = None

    for _ in range(max(1, pages)):
        if next_token:
            params["next_token"] = next_token
        elif "next_token" in params:
            del params["next_token"]

        resp = requests.get(TWITTER_SEARCH_URL, headers=headers, params=params, timeout=timeout)
        if resp.status_code == 429:
            raise RuntimeError("Twitter rate limited request (HTTP 429).")
        resp.raise_for_status()

        payload = resp.json()
        includes = payload.get("includes", {})
        users = includes.get("users", [])
        users_by_id = {str(user.get("id")): user for user in users}

        for tweet in payload.get("data", []):
            author_id = str(tweet.get("author_id", ""))
            username = users_by_id.get(author_id, {}).get("username") or author_id or "unknown"

            messages.append(
                IngestedMessage(
                    platform="twitter",
                    scope=f"conversation_id:{conversation_id}",
                    message_id=str(tweet.get("id", "")),
                    username=username,
                    user_id=author_id or None,
                    sent_at_utc=tweet.get("created_at", utc_now_iso()),
                    captured_at_utc=utc_now_iso(),
                    text=tweet.get("text", "").strip(),
                )
            )

        next_token = payload.get("meta", {}).get("next_token")
        if not next_token:
            break

    messages.sort(key=lambda m: m.sent_at_utc)
    return messages


TWITCH_PRIVMSG_RE = re.compile(
    r"^(?:@(?P<tags>[^ ]+) )?:(?P<nick>[^!]+)![^ ]+ PRIVMSG #(?P<channel>[A-Za-z0-9_]+) :(?P<message>.*)$"
)


def parse_irc_tags(tag_text: str | None) -> dict:
    if not tag_text:
        return {}
    tags: dict[str, str] = {}
    for item in tag_text.split(";"):
        if "=" in item:
            key, value = item.split("=", 1)
            tags[key] = value
        else:
            tags[item] = ""
    return tags


def parse_twitch_privmsg(line: str, expected_channel: str) -> IngestedMessage | None:
    match = TWITCH_PRIVMSG_RE.match(line.strip())
    if not match:
        return None

    channel = match.group("channel").lower()
    if channel != expected_channel.lower():
        return None

    tags = parse_irc_tags(match.group("tags"))
    nick = match.group("nick")
    text = match.group("message").strip()
    username = tags.get("display-name") or nick
    user_id = tags.get("user-id") or None
    sent_ts_ms = tags.get("tmi-sent-ts")

    if sent_ts_ms and sent_ts_ms.isdigit():
        sent_at = datetime.fromtimestamp(int(sent_ts_ms) / 1000, tz=timezone.utc)
        sent_at_utc = sent_at.isoformat().replace("+00:00", "Z")
    else:
        sent_at_utc = utc_now_iso()

    message_id = tags.get("id") or f"twitch-{channel}-{sent_ts_ms or int(time.time() * 1000)}-{nick}"

    return IngestedMessage(
        platform="twitch",
        scope=f"channel:{channel}",
        message_id=message_id,
        username=username,
        user_id=user_id,
        sent_at_utc=sent_at_utc,
        captured_at_utc=utc_now_iso(),
        text=text,
    )


def capture_twitch_chat_messages(
    channel: str,
    oauth_token: str,
    bot_username: str,
    duration_seconds: int,
    max_messages: int,
    socket_timeout: float,
) -> list[IngestedMessage]:
    channel = channel.lstrip("#").lower()
    oauth_token = normalize_twitch_oauth_token(oauth_token)
    messages: list[IngestedMessage] = []
    deadline = time.time() + max(1, duration_seconds)

    sock = socket.socket()
    sock.settimeout(socket_timeout)

    try:
        sock.connect(("irc.chat.twitch.tv", 6667))
        sock.sendall(f"PASS {oauth_token}\r\n".encode("utf-8"))
        sock.sendall(f"NICK {bot_username}\r\n".encode("utf-8"))
        sock.sendall(b"CAP REQ :twitch.tv/tags twitch.tv/commands\r\n")
        sock.sendall(f"JOIN #{channel}\r\n".encode("utf-8"))

        buffer = ""
        while time.time() < deadline and len(messages) < max_messages:
            try:
                chunk = sock.recv(4096).decode("utf-8", errors="ignore")
            except socket.timeout:
                continue

            if not chunk:
                continue

            buffer += chunk
            while "\r\n" in buffer:
                line, buffer = buffer.split("\r\n", 1)
                if not line:
                    continue

                if line.startswith("PING "):
                    server = line.split(" ", 1)[1]
                    sock.sendall(f"PONG {server}\r\n".encode("utf-8"))
                    continue

                msg = parse_twitch_privmsg(line, channel)
                if msg is not None:
                    messages.append(msg)

    finally:
        try:
            sock.close()
        except OSError:
            pass

    return messages


def build_output_path(platform: str, scope_id: str) -> Path:
    safe_scope = sanitize_path_component(scope_id)
    return Path("logs") / "ingest" / f"{platform}_{safe_scope}.jsonl"


def run_twitter_thread(args: argparse.Namespace, keys: dict) -> int:
    bearer_token = get_secret(keys, "TWITTER_BEARER_TOKEN", "twitter_bearer_token")
    if not bearer_token:
        print("Missing Twitter bearer token. Set TWITTER_BEARER_TOKEN or configs/keys.json.twitter_bearer_token")
        log_event(
            "ingest_failed",
            {"source": "twitter-thread", "reason": "missing_twitter_bearer_token"},
            "logs/calls/calls.json",
        )
        return 1

    log_event(
        "ingest_started",
        {"source": "twitter-thread", "conversation_id": args.conversation_id},
        "logs/calls/calls.json",
    )

    messages = fetch_twitter_thread_messages(
        conversation_id=args.conversation_id,
        bearer_token=bearer_token,
        max_results=args.max_results,
        pages=args.pages,
        since_id=args.since_id,
        timeout=args.timeout,
    )
    output_path = Path(args.out) if args.out else build_output_path("twitter", args.conversation_id)
    append_jsonl_many(output_path, [asdict(message) for message in messages], ensure_ascii=False)
    log_event(
        "ingest_completed",
        {
            "source": "twitter-thread",
            "conversation_id": args.conversation_id,
            "count": len(messages),
            "output_path": str(output_path),
        },
        "logs/calls/calls.json",
    )
    print(f"Ingested {len(messages)} twitter messages into {output_path}")
    return 0


def run_twitch_chat(args: argparse.Namespace, keys: dict) -> int:
    oauth_token = get_secret(keys, "TWITCH_OAUTH_TOKEN", "twitch_oauth_token")
    bot_username = get_secret(keys, "TWITCH_BOT_USERNAME", "twitch_bot_username")

    if not oauth_token:
        print("Missing Twitch OAuth token. Set TWITCH_OAUTH_TOKEN or configs/keys.json.twitch_oauth_token")
        log_event(
            "ingest_failed",
            {"source": "twitch-chat", "reason": "missing_twitch_oauth_token"},
            "logs/calls/calls.json",
        )
        return 1
    if not bot_username:
        print("Missing Twitch bot username. Set TWITCH_BOT_USERNAME or configs/keys.json.twitch_bot_username")
        log_event(
            "ingest_failed",
            {"source": "twitch-chat", "reason": "missing_twitch_bot_username"},
            "logs/calls/calls.json",
        )
        return 1

    log_event(
        "ingest_started",
        {"source": "twitch-chat", "channel": args.channel, "duration": args.duration},
        "logs/calls/calls.json",
    )

    messages = capture_twitch_chat_messages(
        channel=args.channel,
        oauth_token=oauth_token,
        bot_username=bot_username,
        duration_seconds=args.duration,
        max_messages=args.max_messages,
        socket_timeout=args.socket_timeout,
    )
    output_path = Path(args.out) if args.out else build_output_path("twitch", args.channel)
    append_jsonl_many(output_path, [asdict(message) for message in messages], ensure_ascii=False)
    log_event(
        "ingest_completed",
        {
            "source": "twitch-chat",
            "channel": args.channel,
            "duration": args.duration,
            "count": len(messages),
            "output_path": str(output_path),
        },
        "logs/calls/calls.json",
    )
    print(f"Ingested {len(messages)} twitch messages into {output_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scoped message ingestion MVP for Twitter threads and Twitch chat."
    )
    parser.add_argument("--keys-file", default="configs/keys.json", help="Path to keys JSON file")

    subparsers = parser.add_subparsers(dest="source", required=True)

    twitter_parser = subparsers.add_parser("twitter-thread", help="Ingest messages from one Twitter thread")
    twitter_parser.add_argument("--conversation-id", required=True, help="Root tweet ID / conversation_id")
    twitter_parser.add_argument("--since-id", default=None, help="Optional: only fetch tweets newer than this ID")
    twitter_parser.add_argument("--max-results", type=int, default=100, help="Tweets per API page (10-100)")
    twitter_parser.add_argument("--pages", type=int, default=1, help="How many API pages to fetch")
    twitter_parser.add_argument("--timeout", type=int, default=20, help="Twitter API timeout seconds")
    twitter_parser.add_argument("--out", default=None, help="JSONL output path")
    twitter_parser.set_defaults(handler=run_twitter_thread)

    twitch_parser = subparsers.add_parser("twitch-chat", help="Capture live Twitch chat for one channel")
    twitch_parser.add_argument("--channel", required=True, help="Twitch channel name")
    twitch_parser.add_argument("--duration", type=int, default=60, help="Capture duration in seconds")
    twitch_parser.add_argument("--max-messages", type=int, default=500, help="Upper bound on captured messages")
    twitch_parser.add_argument("--socket-timeout", type=float, default=2.0, help="Socket timeout in seconds")
    twitch_parser.add_argument("--out", default=None, help="JSONL output path")
    twitch_parser.set_defaults(handler=run_twitch_chat)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    keys = load_json(args.keys_file, default={}) if args.keys_file else {}
    try:
        return args.handler(args, keys)
    except Exception as exc:
        log_event(
            "ingest_error",
            {"source": args.source, "error": str(exc)},
            "logs/calls/calls.json",
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
