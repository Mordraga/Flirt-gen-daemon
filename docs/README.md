# Flirt-gen-daemon
A LLM flirting engine that generates categorized output based on desired sensuality.

## Mai Control Panel (MVP)

`mai_control_panel.py` provides a local desktop UI to:
- Start/stop `mai_monitor.py`
- Edit monitor runtime config live
- Launch other Python scripts in this repo
- View process output logs

### Run UI

```bash
pip install -r requirements-ui.txt
python mai_control_panel.py
```

### Tray behavior

- If `pystray` + `pillow` are installed, minimizing/closing the window sends it to system tray.
- Without those packages, it falls back to normal taskbar minimize behavior.

### Build `.exe`

Use:

```powershell
.\build_mai_ui.ps1
```

Output:
- `dist/MaiControlPanel/MaiControlPanel.exe`

### Monitor runtime config

`mai_monitor.py` now reads `jsons/configs/config.json` -> `monitor` and hot-reloads it while running.
Example keys:
- `response_chance_percent`
- `global_cooldown_seconds`
- `ignored_bot_usernames`
- `respond_to_owner_always`
- `owner_username`
- `config_reload_seconds`

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

### OAuth Init Wizard

Use `oauth_init.py` to generate credentials and write them into `configs/keys.json`:

```bash
python oauth_init.py
```

Options:

```bash
python oauth_init.py --twitter --no-twitch
python oauth_init.py --twitch --no-twitter --twitch-redirect-uri http://localhost:8945/twitch/callback
python oauth_init.py --no-browser
```

Notes:
- Twitter flow exchanges API key + secret for an app bearer token.
- Twitch flow runs auth-code OAuth with a local callback and stores `twitch_oauth_token` + detected `twitch_bot_username`.

### Usage

Twitter thread:

```bash
python message_ingest.py twitter-thread --conversation-id 1234567890123456789 --pages 2
```

Twitch channel (live capture for 90 seconds):

```bash
python message_ingest.py twitch-chat --channel yourchannel --duration 90
```

Output format:
- Twitter: pretty JSON file, e.g. `logs/ingest/twitter_<conversation_id>.json`
  - top-level keys: `meta`, `Main`
  - `Main.replies` is an array of replies, or `null` when no replies exist
- Twitch: JSONL file, e.g. `logs/ingest/twitch_<channel>.jsonl`

Use `--out` to override output path.
