import sys
import random
import re
import traceback
from pathlib import Path

# Add parent directory to path so we can import engine
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.helpers import (
    load_json,
    apply_redaction,
    log_event,
    parse_all_params,
    write_to_file,
    atomic_write_json,
)
from utils.paths import Paths
from utils.rate_limiter import GlobalRateLimiter, UserCooldownTracker
from engine import build_prompt_from_keyword, ask_openrouter


# Global instances
global_limiter = GlobalRateLimiter(max_calls=30, window=60)
user_tracker = UserCooldownTracker()


# =============================
# SAFETY CHECKS
# =============================

UNSAFE_PATTERNS = [
    r'\b(suicide|kill\s*yourself|kys|self.?harm)\b',
    r'\b(child|minor|underage|kid)\b',
    r'\b(rape|assault|molest)\b',
]

def safety_check(text: str) -> tuple[bool, str]:
    """Returns (is_safe, reason)."""
    for pattern in UNSAFE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return False, "Content flagged by safety filter"
    return True, ""


# =============================
# FALLBACK RESPONSES
# =============================

_fb_data = load_json(Paths.FALLBACK_FLIRTS, default={})
FALLBACK_FLIRTS: list[str] = _fb_data.get("fallback_flirts") or [
    "Mai's magic is resting, but you're worth the wait! 💜"
]


# =============================
# MAIN EXECUTION
# =============================

if __name__ == "__main__":
    # Avoid Windows cp1252 crashes when model output contains characters outside code page
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    log_event("flirt_daemon_started", {"args": sys.argv}, Paths.CALLS_LOG)

    # =============================
    # ARGUMENT PARSING
    # =============================

    if len(sys.argv) < 2:
        error_msg = "Usage: python flirt_daemon.py <command_string> [username]"
        print(error_msg)
        write_to_file("Mai needs parameters! Format: <theme> <tone> <spice> - Example: pagan sultry 5", Paths.FLIRT_OUTPUT)
        sys.exit(1)

    command_str = sys.argv[1]
    username = sys.argv[2] if len(sys.argv) >= 3 else "Anonymous"

    # Parse parameters — agnostic: use what's found, fall back on missing values
    params = parse_all_params(command_str)

    _themes_data = load_json(Paths.THEMES, default={})
    _tones_data = load_json(Paths.TONES, default={})
    _spice_data = load_json(Paths.SPICE, default={})
    theme = params.get("theme") or (random.choice(list(_themes_data.keys())) if _themes_data else "pagan")
    tone  = params.get("tone")  or (random.choice(list(_tones_data.keys()))  if _tones_data  else "sultry")
    level = params.get("spice") or 3

    # =============================
    # FREE EVENT CONFIGURATION
    # =============================

    # Primary source: config.json["event"]; fallback: standalone event_config.json
    _main_config = load_json(Paths.CONFIG, default={})
    event_config = _main_config.get("event") or load_json(Paths.EVENT_CONFIG, default={})
    is_free_event = event_config.get("free_event_active", False)

    if is_free_event:
        max_spice = event_config.get("free_event_max_spice", 5)
        if level > max_spice:
            original_level = level
            level = max_spice
            log_event("spice_capped", {
                "username": username,
                "requested": original_level,
                "capped_to": level,
                "reason": "free_event"
            }, Paths.SPICE_CAPS_LOG)

    # =============================
    # RATE LIMITING CHECKS
    # =============================

    # Global rate limit
    can_request, rate_message = global_limiter.allow_request()
    if not can_request:
        print(rate_message)
        write_to_file(rate_message, Paths.FLIRT_OUTPUT)
        log_event("rate_limited", {
            "username": username,
            "reason": "global_limit",
            "message": rate_message
        }, Paths.RATE_LIMITS_LOG)
        sys.exit(0)

    # User cooldown
    cooldown_seconds = event_config.get("free_event_cooldown_seconds", 300) if is_free_event else 300
    can_request, remaining = user_tracker.check_cooldown(username, cooldown_seconds)

    if not can_request:
        cooldown_data = load_json(Paths.COOLDOWN_MSGS, default={})
        cooldown_set = cooldown_data.get("cooldown_messages", [
            "Give me {remaining}s to recharge for you! 💜"
        ])

        # Load history to avoid repeats
        history_file = Path(Paths.COOLDOWN_HISTORY)
        if history_file.exists():
            history = load_json(history_file, default={})
            last_used = history.get("last_used", [])
        else:
            last_used = []

        # Filter out last 3 used messages
        available = [msg for msg in cooldown_set if msg not in last_used]

        # If exhausted all options, reset history
        if not available:
            available = cooldown_set
            last_used = []

        # Pick random from available
        template = random.choice(available)

        # Update history (keep last 3)
        last_used.append(template)
        if len(last_used) > 3:
            last_used.pop(0)

        # Save history
        atomic_write_json(history_file, {"last_used": last_used})

        # Format with username and remaining time
        cooldown_msg = f"@{username} - " + template.format(remaining=remaining)

        print(cooldown_msg)
        write_to_file(cooldown_msg, Paths.FLIRT_OUTPUT)
        log_event("user_cooldown", {
            "username": username,
            "remaining_seconds": remaining,
            "cooldown_duration": cooldown_seconds,
            "cooldown_message": template
        }, Paths.RATE_LIMITS_LOG)
        sys.exit(0)

    # =============================
    # GENERATE FLIRT
    # =============================

    try:
        print(f"Generating flirt for @{username}: theme={theme}, tone={tone}, spice={level}")

        theme_obj = _themes_data.get(theme, {})
        tone_obj = _tones_data.get(tone, {})
        spice_obj = _spice_data.get(str(level), {})

        prompt_context = {
            "theme": theme,
            "tone": tone,
            "level": level,
            "theme_desc": theme_obj.get("description") or "No description available.",
            "tone_desc": tone_obj.get("description") or "No description available.",
            "spice_desc": spice_obj.get("description") or "No description available.",
            "theme_anchors": theme_obj.get("anchors", []),
            "tone_anchors": tone_obj.get("anchors", []),
            "spice_anchors": spice_obj.get("anchors", []),
        }

        prompt = build_prompt_from_keyword("flirt", context=prompt_context)
        if prompt.startswith("WARNING:"):
            raise Exception(prompt)

        flirt_line = ask_openrouter(prompt, spicy=(level >= 7))

        # Check if OpenRouter returned an error
        if flirt_line.startswith("WARNING:"):
            raise Exception(flirt_line)

        # =============================
        # SAFETY CHECK
        # =============================

        is_safe, safety_reason = safety_check(flirt_line)
        if not is_safe:
            error_msg = "Mai detected unsafe content and blocked this flirt. Try different parameters! 🛡️"
            print(f"SAFETY VIOLATION: {safety_reason}")
            print(error_msg)
            write_to_file(error_msg, Paths.FLIRT_OUTPUT)
            log_event("safety_violation", {
                "username": username,
                "theme": theme,
                "tone": tone,
                "level": level,
                "reason": safety_reason,
                "blocked_output": flirt_line
            }, Paths.SAFETY_LOG)
            sys.exit(0)

        # =============================
        # REDACTION
        # =============================

        redaction_data = load_json(Paths.REDACTION, default={}).get("redaction", {})
        redacted_flirt_line = apply_redaction(flirt_line, level, redaction_data)

        # =============================
        # OUTPUT & LOGGING
        # =============================

        print(f"SUCCESS!")
        print(f"THEME: {theme}, TONE: {tone}, SPICE: {level}, USER: @{username}")
        print(f"RAW: {flirt_line}")
        print(f"FINAL: {redacted_flirt_line}")

        # Log successful generation
        log_event("flirt_generated", {
            "username": username,
            "theme": theme,
            "tone": tone,
            "level": level,
            "flirt_line": flirt_line,
            "redacted_flirt_line": redacted_flirt_line,
            "is_free_event": is_free_event
        }, Paths.FLIRT_HISTORY)

        # Log prompt for debugging
        log_event("prompt_made", {
            "username": username,
            "theme": theme,
            "tone": tone,
            "level": level,
            "prompt": prompt
        }, Paths.PROMPT_HISTORY)

        # Write output for Streamer.bot to read
        write_to_file(redacted_flirt_line, Paths.FLIRT_OUTPUT)

    except Exception as e:
        # =============================
        # GRACEFUL DEGRADATION
        # =============================

        fallback = random.choice(FALLBACK_FLIRTS)

        # Detailed error information
        error_details = {
            "username": username,
            "theme": theme,
            "tone": tone,
            "level": level,
            "error_type": type(e).__name__,
            "error_message": str(e),
            "error_traceback": traceback.format_exc(),
            "fallback_used": fallback
        }

        print(f"ERROR TYPE: {type(e).__name__}")
        print(f"ERROR MESSAGE: {e}")
        print(f"TRACEBACK:\n{traceback.format_exc()}")
        print(f"FALLBACK: {fallback}")

        write_to_file(fallback, Paths.FLIRT_OUTPUT)
        log_event("generation_error", error_details, Paths.ERROR_LOG)

        sys.exit(0)  # Exit gracefully even on error
