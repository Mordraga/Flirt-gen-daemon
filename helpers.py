import json
import random
import re
import sys
from time import time
import token

#============================
# Loaders
#============================

def load_json(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_config():
    return load_json("configs/config.json")

def load_keys():
    return load_json("configs/keys.json")

#============================
# Redaction
#============================

def apply_redaction(text: str, level: int, redaction_data: dict, style: str | None = None) -> str:

    threshold = redaction_data.get("threshold") or 7
    max_replacements = redaction_data.get("max_replacements")
    filler_words = set(redaction_data.get("ignored_words", []))
    print(max_replacements)

    if level < threshold:
        return text

    styles = redaction_data.get("styles", {})

    if not styles:
        return text

    if style is None:
        style = random.choice(list(styles.keys()))

    style_pool = styles.get(style, ["[REDACTED]"])

    if not style_pool:
        return text


    # Target longer words only (avoid breaking short syntax words)
    candidates = [
    word for word in re.findall(r"\b[A-Za-z]{5,}\b", text)
    if word.lower() not in filler_words
    and not word.lower().endswith("ly")  # skip adverbs
    and not word.lower().endswith("ing")  # skip gerunds
    ]
    if not candidates:
        return text

    targets = random.sample(candidates, min(max_replacements, len(candidates)))

    for word in targets:
        replacement_token = random.choice(style_pool)
        text = re.sub(rf"\b{re.escape(word)}\b", replacement_token, text, count=1)

    return text
    
#============================
# Logging
#============================
def write_to_log(entry, file_path):
    with open(file_path, "a", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=4)
        f.write("\n\n")

def log_event(event_type, payload, file_path):
    entry = {
        **payload,
        "event": event_type,
        "timestamp": int(time())
    }
    write_to_log(entry, file_path)

def write_to_file(content, file_path):
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content + "\n")

#============================
#Parse Streamer.bot
#============================

def parse_streamer_bot_command(command_str):

    themes = load_json("data/themes.json")
    tones = load_json("data/tones.json")
    spice_levels = load_json("data/spice_levels.json")

    args = command_str.split()
    for token in args:
            token = token.strip().lower()
            if token in themes:
                return "theme", token
            if token in tones:
                return "tone", token
            if token in spice_levels:
                return "spice", int(token)
        
    return None, None
