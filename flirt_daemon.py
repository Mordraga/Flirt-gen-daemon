import sys
import re
from engine import load_spice_levels, build_prompt, ask_ollama, load_themes

MAX_SPICE = 7


def parse_input(text):
    theme = "general"
    style = "clever"
    level = 3

    if not text:
        return theme, style, level

    # split on commas or hyphens
    parts = re.split(r"[,\-]", text)

    if len(parts) >= 1 and parts[0].strip():
        theme = parts[0].strip().lower()

    if len(parts) >= 2 and parts[1].strip():
        style = parts[1].strip().lower()

    if len(parts) >= 3:
        try:
            level = int(parts[2].strip())
        except ValueError:
            pass

    level = max(1, min(level, MAX_SPICE))
    return theme, style, level


if __name__ == "__main__":
    raw_input = sys.argv[1] if len(sys.argv) > 1 else ""

    theme, style, level = parse_input(raw_input)

    spice_data = load_spice_levels()
    theme_data = load_themes()

    prompt = build_prompt(theme, style, level, spice_data, theme_data)

    result = ask_ollama(prompt, model="qwen2.5:3b")

    print(result.strip())
