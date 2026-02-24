"""
Shared Twitch IRC parsing utilities.

Both mai_monitor.py and message_ingest.py use these; keeping one copy here
prevents the two from drifting apart.
"""

import re

# Matches an optional tag block, nick!host, PRIVMSG #channel, and the message body.
PRIVMSG_RE = re.compile(
    r"^(?:@(?P<tags>[^ ]+) )?:(?P<nick>[^!]+)![^ ]+ PRIVMSG #(?P<channel>[A-Za-z0-9_]+) :(?P<message>.*)$"
)


def parse_irc_tags(tag_text: str | None) -> dict[str, str]:
    """Parse a Twitch IRCv3 tag string into a plain dict.

    Example input:  ``"display-name=SomeUser;color=#FF0000"``
    Example output: ``{"display-name": "SomeUser", "color": "#FF0000"}``
    """
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


def parse_privmsg(line: str) -> tuple[str, str, str] | None:
    """Parse a raw IRC PRIVMSG line.

    Returns ``(username, channel, message)`` on success, ``None`` otherwise.
    ``username`` prefers the ``display-name`` tag over the nick.
    """
    match = PRIVMSG_RE.match(line.strip())
    if not match:
        return None
    tags = parse_irc_tags(match.group("tags"))
    username = tags.get("display-name") or match.group("nick")
    channel = match.group("channel").lower()
    message = match.group("message")
    return username, channel, message
