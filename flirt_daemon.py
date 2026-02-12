import sys
import re
from engine import (
    load_spice_levels, 
    load_themes, 
    is_vague_input,
    pick_random_theme,
    build_smart_prompt,
    build_specific_prompt,
    ask_openrouter
)


MAX_SPICE = 10  # Updated to match new spice.json


def parse_input(text):
    """Parse user input into theme, style, level"""
    theme = "general"
    style = "clever"
    level = 3

    if not text:
        return theme, style, level

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

    # HYBRID ROUTING
    if is_vague_input(theme, style, level):
        # User is being vague - pick random theme instead of meta commentary
        theme, style, level = pick_random_theme(theme_data)
        prompt = build_specific_prompt(theme, style, level, spice_data, theme_data)
        
    else:
        # User gave specifics - generate directly
        prompt = build_specific_prompt(theme, style, level, spice_data, theme_data)

    result = ask_openrouter(prompt).strip()

    # Write to file
    with open("flirt_output.txt", "w", encoding="utf-8") as f:
        f.write(result)