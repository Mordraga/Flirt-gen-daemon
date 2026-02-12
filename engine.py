import json
import requests
import random
from pathlib import Path

SPICE_FILE = Path("spice.json")
THEME_FILE = Path("themes.json")
CONFIG_FILE = Path("configs/config.json")
KEYS_FILE = Path("configs/keys.json")

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


# =============================
# Smart Input Detection
# =============================

def is_vague_input(theme: str, style: str, level: int) -> bool:
    """Detect if user input is vague/requesting AI to decide"""
    vague_keywords = ["idk", "surprise", "random", "whatever", "anything", "dunno"]
    
    # Check if theme contains vague language
    if any(keyword in theme.lower() for keyword in vague_keywords):
        return True
    
    # If theme is empty or generic
    if not theme or theme.lower() in ["general", ""]:
        return True
    
    return False


def pick_random_theme(theme_data: dict) -> tuple:
    """Pick a random top-level theme with appropriate spice"""
    # Filter out themes with subtopics for simplicity in vague mode
    simple_themes = {k: v for k, v in theme_data.items() 
                     if "subtopics" not in v}
    
    if not simple_themes:
        simple_themes = theme_data
    
    theme_key = random.choice(list(simple_themes.keys()))
    theme_info = simple_themes[theme_key]
    
    # Pick spice level from theme's range
    spice_range = theme_info.get("spice_range", [3, 6])
    spice_level = random.randint(spice_range[0], spice_range[1])
    
    # Pick random style
    styles = ["clever", "playful", "bold", "sultry", "teasing"]
    style = random.choice(styles)
    
    return theme_key, style, spice_level


# =============================
# Prompt Builders
# =============================

def build_smart_prompt(user_input: str, theme_data: dict, spice_data: dict) -> str:
    """Build prompt for vague input - let LLM choose from metadata"""
    
    # Build metadata summary (top-level themes only, no subtopics)
    theme_summary = []
    for theme_key, theme_info in theme_data.items():
        category = theme_info.get("category", "general")
        spice_range = theme_info.get("spice_range", [3, 6])
        description = theme_info.get("description", "")
        theme_summary.append(
            f"- {theme_key} ({category}): {description} [spice {spice_range[0]}-{spice_range[1]}]"
        )
    
    themes_text = "\n".join(theme_summary)
    
    return f"""
You generate sharp, punchy flirt lines for an 18+ stream chat.

The user said: "{user_input}"

Available themes:
{themes_text}

Based on the user's vague request, pick an appropriate theme and spice level, then generate a flirt line.

Rules:
- Maximum 15-20 words total
- One complete sentence only (no em-dashes, no multiple clauses)
- No asterisks, no italics, no formatting marks
- Match the spice level authentically - don't sanitize
- Deliver the punchline fast

Output the flirt line only. No preamble, no explanation, no metadata.
""".strip()


def build_specific_prompt(theme: str, style: str, level: int, spice_data: dict, theme_data: dict) -> str:
    """Build prompt for specific input - user knows what they want"""
    lvl = str(clamp_level(level))
    spice_desc = spice_data.get(lvl, "playful and flirty energy")

    theme_key = theme.strip().lower()
    
    # Check if this is a subtopic (format: "theme.subtopic")
    if "." in theme_key:
        parent_theme, subtopic = theme_key.split(".", 1)
        theme_info = theme_data.get(parent_theme, {})
        
        if "subtopics" in theme_info and subtopic in theme_info["subtopics"]:
            subtopic_info = theme_info["subtopics"][subtopic]
            basics = subtopic_info.get("basics", "")
            anchors = subtopic_info.get("anchors", [])
            
            context_block = f"\n\nSubtopic: {subtopic}\nContext: {basics}"
            if anchors:
                context_block += f"\nExamples: {', '.join(anchors[:5])}"
        else:
            # Fallback if subtopic not found
            context_block = ""
    else:
        # Regular top-level theme
        theme_info = theme_data.get(theme_key, {})
        anchors = theme_info.get("anchors", [])
        
        context_block = ""
        if anchors:
            context_block = f"\n\nContext for {theme_key}:\n{', '.join(anchors[:5])}"

    return f"""
You generate sharp, punchy flirt lines for an 18+ stream chat.

Rules:
- Maximum 15-20 words total
- One complete sentence only (no em-dashes, no multiple clauses)
- Capture the vibe and atmosphere of the theme naturally
- No asterisks, no italics, no formatting marks
- Match the spice level authentically - don't sanitize
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


# =============================
# Unified Entry Point
# =============================

def ask_model(prompt: str, backend: str = "openrouter") -> str:
    if backend == "openrouter":
        return ask_openrouter(prompt)
    return "WARNING: No valid backend selected."