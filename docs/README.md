# Flirt-gen-daemon
A LLM flirting engine that generates categorized output based on desired sensuality.

## Message Ingestion MVP

`message_ingest.py` captures scoped messages from:
- `twitter-thread`: one conversation/thread by `conversation_id`
- `twitch-chat`: one channel over a bounded duration

Each captured row is written as JSONL with:
- `username`
- `sent_at_utc` (time/date)
- `text`
- plus IDs and platform/scope metadata

### Setup

Populate `configs/keys.json` or env vars:
- `twitter_bearer_token` or `TWITTER_BEARER_TOKEN`
- `twitch_oauth_token` or `TWITCH_OAUTH_TOKEN`
- `twitch_bot_username` or `TWITCH_BOT_USERNAME`

Use `configs/keys.example.json` as the template.

### Usage

Twitter thread:

```bash
python message_ingest.py twitter-thread --conversation-id 1234567890123456789 --pages 2
```

Twitch channel (live capture for 90 seconds):

```bash
python message_ingest.py twitch-chat --channel yourchannel --duration 90
```

By default outputs go to `logs/ingest/*.jsonl`. Use `--out` to override.
