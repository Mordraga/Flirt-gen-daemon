import requests
from helpers import (
    load_json,
    load_config,
    load_keys,
    log_event
)
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def build_specific_prompt(theme, tone, level):
    return build_prompt(theme, tone, level)

# =============================
# Prompt Builder
# =============================
theme_data = load_json("data/themes.json")
tone_data = load_json("data/tone.json")
spice_data = load_json("data/spice.json")

def build_prompt(theme: str, tone: str, level: int) -> str:
    # Extract relevant data
    theme_obj = theme_data.get(theme, {})
    tone_obj = tone_data.get(tone, {})
    spice_obj = spice_data.get(str(level), {})

# Extract Description and Anchors
    theme_desc = theme_obj.get("description") or "No description available."
    theme_anchors = theme_obj.get("anchors", [])

    tone_desc = tone_obj.get("description") or "No description available."
    tone_anchors = tone_obj.get("anchors", [])

    spice_desc = spice_obj.get("description") or "No description available."
    spice_anchors = spice_obj.get("anchors", [])
    
    return f"""
You are MaidensAcquisistions.AI, or Mai for short.
You generate sharp, punchy flirt lines for a Twitch chat.

Rules:
- Maximum 15-20 words total
- One complete sentence only (no em-dashes, no multiple clauses)
- Capture the vibe and atmosphere of the theme naturally
- Natural Language Only
- Ensure proper grammar and spelling
- Twitch-safe language only
- Deliver the punchline fast

Theme:{theme} - {theme_desc}
Tone:{tone} - {tone_desc}
Spice Level:{level} - {spice_desc}

Use the following anchors as inspiration, but do not force them in. Be creative and natural.
Theme Anchors: {', '.join(theme_anchors)}
Tone Anchors: {', '.join(tone_anchors)}
Spice Anchors: {', '.join(spice_anchors)}

Output the flirt line only. No preamble, no explanation.
""".strip()

# =============================
# OpenRouter Backend
# =============================

def ask_openrouter(prompt: str) -> str:
    config = load_config()
    keys = load_keys()

    api_key = keys["openrouter_api_key"]
    model = config["model"]
    max_tokens = config["max_tokens"]
    temperature = config["temperature_normal"]
    timeout = config["timeout"]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "FlirtDaemon"
    }

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature
    }

    try:
        r = requests.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
            timeout=timeout
        )
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"].strip()

    except requests.RequestException as e:
        log_event("openrouter_error", {"error": str(e)}, "logs/errors/error_log.json")
        return f"WARNING: OpenRouter error: {e}"

# =============================
# Unified Entry Point
# =============================

def ask_model(prompt: str, backend: str = "openrouter") -> str:
    if backend == "openrouter":
        return ask_openrouter(prompt)
    return "WARNING: No valid backend selected."
