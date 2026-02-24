import requests
from utils.helpers import load_json, load_config, load_keys, log_event
from utils.paths import Paths

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


# =============================
# Prompt Builder
# =============================

def build_prompt(theme: str, tone: str, level: int) -> str:
    theme_data = load_json(Paths.THEMES, default={})
    tone_data = load_json(Paths.TONES, default={})
    spice_data = load_json(Paths.SPICE, default={})

    theme_obj = theme_data.get(theme, {})
    tone_obj = tone_data.get(tone, {})
    spice_obj = spice_data.get(str(level), {})

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

def ask_openrouter(prompt: str, spicy: bool = False) -> str:
    config = load_config()
    keys = load_keys()

    mai_config = config.get("Mai-config", config)

    api_key = keys.get("openrouter_api_key")
    if not api_key:
        return f"WARNING: Missing OpenRouter API key in {Paths.KEYS}"

    model = mai_config.get("model", "mistralai/mistral-7b-instruct")
    max_tokens = mai_config.get("max_tokens", 60)
    temp_key = "temperature_spicy" if spicy else "temperature_normal"
    temperature = mai_config.get(temp_key, mai_config.get("temperature_normal", 0.85))
    timeout = mai_config.get("timeout", 30)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "FlirtDaemon",
    }

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    try:
        r = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"].strip()

    except requests.RequestException as e:
        log_event("openrouter_error", {"error": str(e)}, Paths.ERROR_LOG)
        return f"WARNING: OpenRouter error: {e}"


# =============================
# Unified Entry Point
# =============================

def ask_model(prompt: str, backend: str = "openrouter", spicy: bool = False) -> str:
    if backend == "openrouter":
        return ask_openrouter(prompt, spicy=spicy)
    return "WARNING: No valid backend selected."
