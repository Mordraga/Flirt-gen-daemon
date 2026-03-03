# Mai — MaidensAcquisitions.AI

AI-powered Twitch stream assistant. Generates flirts, tarot readings, and chat command responses via an LLM backend (OpenRouter), and autonomously watches chat as a Twitch IRC bot.

---

## What's in the box

| Component | File | What it does |
|-----------|------|--------------|
| Control Panel | `mai_control_panel.py` | Desktop UI — start/stop the monitor, edit config, view logs |
| Router | `main.py` | CLI entry point — routes a keyword to the right daemon subprocess |
| Flirt daemon | `daemons/flirt_daemon.py` | Generates a themed flirt line |
| Tarot daemon | `daemons/tarot_daemon.py` | Deals and reads tarot cards |
| Commands daemon | `daemons/commands_daemon.py` | Handles Twitch chat commands (`!discord`, `!social`, etc.) |
| Monitor | `mai_monitor.py` | Autonomous IRC listener — Mai replies to chat on her own |
| Engine | `engine.py` | OpenRouter API wrapper + prompt template system |

---

## Setup

### 1. Clone & create a virtual environment

```bash
git clone https://github.com/yourname/Flirt-gen-daemon.git
cd Flirt-gen-daemon
python -m venv .venv
```

Activate it:
- Windows: `.venv\Scripts\activate`
- Mac/Linux: `source .venv/bin/activate`

### 2. Install dependencies

Core (daemons + monitor):
```bash
pip install -r requirements.txt
```

Control panel + build tools:
```bash
pip install -r requirements-ui.txt
```

### 3. Set up API credentials

Copy the example keys file and fill it in:

```bash
cp jsons/configs/keys.example.json jsons/configs/keys.json
```

Edit `jsons/configs/keys.json`:

```json
{
  "openrouter_api_key": "sk-or-v1-...",
  "twitch_oauth_token": "oauth:...",
  "twitch_bot_username": "your_bot_username",
  "twitch_client_id": "...",
  "twitch_refresh_token": "..."
}
```

- **OpenRouter key** — required for all LLM features. Get one at [openrouter.ai](https://openrouter.ai).
- **Twitch credentials** — required for the autonomous monitor. Use `python utils/oauth_init.py` to generate these (see [OAuth wizard](#oauth-wizard) below).
- Twitter keys are only needed if you use `message_ingest.py` for Twitter thread ingestion.

### 4. Configure the channel

Edit `jsons/configs/config.json` and set your channel:

```json
{
  "Mai-config": {
    "model": "gryphe/mythomax-l2-13b"
  },
  "monitor": {
    "twitch_channel": "yourchannel",
    "owner_username": "yourchannel"
  }
}
```

Key monitor settings:

| Key | Default | What it does |
|-----|---------|--------------|
| `twitch_channel` | — | Channel to join (required) |
| `owner_username` | — | Your username — Mai always responds to you |
| `response_chance_percent` | 35.0 | How often Mai replies to random chat messages |
| `global_cooldown_seconds` | 5 | Minimum seconds between any two autonomous responses |
| `mood_reroll_seconds` | 1200 | How often Mai's session mood changes (seconds) |

### 5. Configure commands

Edit `jsons/data/commands.json` and replace the placeholder URLs:

```json
{
  "discord": {
    "url": "discord.gg/your-actual-invite"
  },
  "social": {
    "url": "discord.gg/... | x.com/... | youtube.com/@..."
  }
}
```

Commands work like this: the LLM writes Mai's personality-flavored response, then the `url` value is appended verbatim at the end — so links are always exact, never hallucinated.

---

## Running

### Control Panel (recommended)

```bash
python mai_control_panel.py
```

The UI lets you start/stop the monitor, edit all config and data files, and view live logs. Minimizing sends it to the system tray if `pystray` and `pillow` are installed.

### CLI — invoke a daemon directly

```bash
python main.py <keyword> "<params>" [username]
```

Examples:

```bash
# Generate a flirt
python main.py flirt "witchy playful 3" StreamViewer

# Pull a tarot spread
python main.py tarot "3-card" StreamViewer

# Handle a chat command
python main.py commands "!discord" StreamViewer
```

Output is written both to stdout and to the corresponding file in `jsons/`:
- Flirts → `jsons/data/flirt_output.txt`
- Tarot → `jsons/data/tarot_output.txt`
- Commands → `jsons/data/command_output.txt`

### Monitor only

```bash
python mai_monitor.py
```

Connects to Twitch IRC and autonomously responds to chat. Config hot-reloads from `jsons/configs/config.json` every 2 seconds while running.

---

## OAuth Wizard

Generates Twitch credentials and writes them to `jsons/configs/keys.json`:

```bash
python utils/oauth_init.py
```

Options:

```bash
python utils/oauth_init.py --twitch --no-twitter
python utils/oauth_init.py --twitter --no-twitch
python utils/oauth_init.py --no-browser   # print URL instead of auto-opening
```

---

## Build a standalone `.exe`

Requires `pyinstaller` (included in `requirements-ui.txt`).

```powershell
.\build_mai_ui.ps1
```

Output: `dist/MaiControlPanel/MaiControlPanel.exe`

---

## File structure

```
jsons/
  configs/
    keys.json          ← API credentials (gitignored)
    keys.example.json  ← Template to copy from
    config.json        ← Runtime config (model, monitor settings, events)
    registry.json      ← Maps keywords to daemon files
  data/
    commands.json      ← Chat commands + hardcoded URLs
    Prompt_Templates.json ← LLM prompt templates
    moods.json         ← Session mood definitions
    tarot_spreads.json ← Spread layouts
    personality.json   ← Mai's personality traits + context patterns
  logs/                ← Runtime logs (history, errors, calls)

daemons/               ← Subprocess workers
utils/                 ← Shared helpers, rate limiters, path constants
monitor/               ← Hot-reloadable monitor config + rate limiter
```

---

## Personality & prompts

Mai's personality lives in `jsons/data/personality.json` — edit it to tune her identity, context patterns, fallback responses, and sass triggers without touching Python code.

Prompt templates for each daemon live in `jsons/data/Prompt_Templates.json`.
