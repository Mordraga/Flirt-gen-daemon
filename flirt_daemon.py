import sys
import json
import requests
from helpers import load_json, apply_redaction, log_event, write_to_file
from engine import build_specific_prompt, ask_openrouter

if __name__ == "__main__":

    log_event("flirt_daemon_started", {"args": sys.argv}, "logs/calls/calls.json")

    if len(sys.argv) != 4:
        print("Usage: python flirt_daemon.py <theme> <tone> <spice_level>")
        sys.exit(1)

    theme = sys.argv[1]
    tone = sys.argv[2]
    try:
        level = int(sys.argv[3])
    except ValueError:
        print("Spice level must be an integer.")
        sys.exit(1)

    prompt = build_specific_prompt(theme, tone, level)
    flirt_line = ask_openrouter(prompt)

    redacted_flirt_line = apply_redaction(flirt_line, level, load_json("data/redaction.json").get("redaction", {}))

    print(f"THEME: {theme}, TONE: {tone}, SPICE LEVEL: {level}\n"
          f"THEME DESC: {load_json('data/themes.json').get(theme, {}).get('description', 'N/A')}\n"
          f"TONE DESC: {load_json('data/tone.json').get(tone, {}).get('description', 'N/A')}\n"
          f"SPICE DESC: {load_json('data/spice.json').get(str(level), {}).get('description', 'N/A')}\n"
          f"FLIRT LINE: {flirt_line} \n"
          f"REDACTED FLIRT LINE: {redacted_flirt_line}")
    
    redaction_data = load_json("data/redaction.json").get("max_replacements", {})

    log_event("flirt_generated", {
        "theme": theme,
        "tone": tone,
        "level": level,
        "flirt_line": flirt_line,
        "redacted_flirt_line": redacted_flirt_line
    }, "logs/history/flirt_history.json")

    log_event("prompt_made", {
        "theme": theme,
        "tone": tone,
        "level": level,
        "prompt": prompt
    }, "logs/prompts/prompt_history.json")    

    write_to_file(redacted_flirt_line, "output/flirt_line.txt")