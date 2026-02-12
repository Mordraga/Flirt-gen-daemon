import json
import requests
import os
from pathlib import Path
import random

SPICE_FILE = Path("spice.json")
THEME_FILE = Path("themes.json")
CONFIG_FILE = Path("configs/config.json")
KEYS_FILE = Path("configs/keys.json")
REDACTION_FILE = Path("redaction.json")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# =============================
# Loaders
# =============================

def load_spice_levels():
    with open(SPICE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_themes():
    with open(THEME_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def clamp_level(level: int) -> int:
    return max(1, min(level, 10))


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_keys():
    with open(KEYS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)
    
def load_redaction():
    with open(REDACTION_FILE, "r", encoding="utf-8") as f:
        return json.load(f)
    
# =============================
# Random Theme Selection
# =============================



def is_vague_input(theme: str, style: str, level: int, theme_data: dict) -> bool:
    theme_key = theme.strip().lower()

    # If theme not in available themes
    if theme_key not in theme_data:
        return True

    # If user left defaults
    if theme_key == "general" and style == "clever" and level == 3:
        return True

    return False


def pick_random_theme(theme_data: dict, spice_data: dict):
    # Filter themes that allow low spice (<=5)
    low_spice_themes = []

    for theme, data in theme_data.items():
        if "spice_range" in data:
            if data["spice_range"][0] <= 5:
                low_spice_themes.append((theme, data))

    if not low_spice_themes:
        theme = random.choice(list(theme_data.keys()))
        return theme, "clever", 3

    theme, data = random.choice(low_spice_themes)

    min_spice, max_spice = data["spice_range"]
    level = random.randint(min_spice, min(5, max_spice))

    return theme, "clever", level


def build_specific_prompt(theme, style, level, spice_data, theme_data):
    return build_prompt(theme, style, level, spice_data, theme_data)



# =============================
# Prompt Builder
# =============================

def build_prompt(theme: str, style: str, level: int, spice_data: dict, theme_data: dict) -> str:
    lvl = str(clamp_level(level))
    spice_desc = spice_data.get(lvl, "playful and flirty energy")

    theme_key = theme.strip().lower()
    theme_entry = theme_data.get(theme_key, {})
    anchors = theme_entry.get("anchors", [])


    # Build context block if anchors exist
    context_block = ""
    if anchors:
        context_block = f"\n\nContext for {theme_key} theme:\n{', '.join(anchors[:5])}"  # Limit to 5 for brevity

    return f"""
You are MaidensAcquisistions.AI, or MA.AI, or Mai.
You generate sharp, punchy flirt lines for Twitch chat.

Rules:
- Maximum 15-20 words total
- One complete sentence only (no em-dashes, no multiple clauses)
- Capture the vibe and atmosphere of the theme naturally
- No asterisks, no italics, no formatting marks
- Twitch-safe language only
- Deliver the punchline fast

Style: {style}
Theme: {theme_key}
Energy: {spice_desc}{context_block}

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
        return f"WARNING: OpenRouter error: {e}"

import re

def apply_redaction(text: str, level: int, redaction_data: dict, style: str = "divine") -> str:
    threshold = redaction_data.get("threshold", 7)
    max_replacements = redaction_data.get("max_replacements", 1)

    if level < threshold:
        return text

    styles = redaction_data.get("styles", {})
    style_pool = styles.get(style, ["[REDACTED]"])

    if not style_pool:
        return text

    replacement_token = random.choice(style_pool)

    # Target longer words only (avoid breaking short syntax words)
    candidates = re.findall(r"\b\w{5,}\b", text)
    if not candidates:
        return text

    targets = random.sample(candidates, min(max_replacements, len(candidates)))

    for word in targets:
        text = re.sub(rf"\b{re.escape(word)}\b", replacement_token, text, count=1)

    return text
# =============================
# Unified Entry Point
# =============================

def ask_model(prompt: str, backend: str = "openrouter") -> str:
    if backend == "openrouter":
        return ask_openrouter(prompt)
    return "WARNING: No valid backend selected."