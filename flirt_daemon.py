import sys
import json
import random
import re
import time
import traceback
from collections import deque
from pathlib import Path
from helpers import (
    load_json,
    apply_redaction,
    log_event,
    write_to_file,
    atomic_write_json
)
from engine import build_specific_prompt, ask_openrouter


# =============================
# RATE LIMITING
# =============================

class GlobalRateLimiter:
    """Prevent API spam - max requests per minute"""
    def __init__(self, max_calls: int = 30, window: int = 60):
        self.max_calls = max_calls
        self.window = window
        self.calls = deque()
    
    def allow_request(self) -> tuple[bool, str]:
        now = time.time()
        # Remove old calls outside window
        while self.calls and self.calls[0] < now - self.window:
            self.calls.popleft()
        
        if len(self.calls) < self.max_calls:
            self.calls.append(now)
            return True, ""
        
        wait_time = int(self.calls[0] + self.window - now) + 1
        return False, f"Mai is catching her breath! Try again in {wait_time}s 💜"


class UserCooldownTracker:
    """Per-user cooldowns - prevent spam from single user"""
    def __init__(self, cooldown_file: Path = Path("data/user_cooldowns.json")):
        self.cooldown_file = cooldown_file
        self.cooldowns = self._load_cooldowns()
    
    def _load_cooldowns(self) -> dict:
        try:
            return load_json(self.cooldown_file, default={})
        except:
            return {}
    
    def _save_cooldowns(self):
        try:
            atomic_write_json(self.cooldown_file, self.cooldowns)
        except Exception as e:
            log_event("cooldown_save_error", {"error": str(e)}, "logs/errors/error_log.json")
    
    def check_cooldown(self, username: str, cooldown_seconds: int = 300) -> tuple[bool, int]:
        """Returns (can_request, seconds_remaining)"""
        now = time.time()
        last_request = self.cooldowns.get(username, 0)
        elapsed = now - last_request
        
        if elapsed >= cooldown_seconds:
            self.cooldowns[username] = now
            self._save_cooldowns()
            return True, 0
        
        remaining = int(cooldown_seconds - elapsed)
        return False, remaining


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
    """Returns (is_safe, reason)"""
    for pattern in UNSAFE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return False, "Content flagged by safety filter"
    return True, ""


# =============================
# FALLBACK RESPONSES
# =============================

FALLBACK_FLIRTS = [
    "Mai's servers are taking a coffee break... but you're still looking fine! ☕✨",
    "Technical difficulties, but the real magic is you being here! 💜",
    "OpenRouter is being shy, but Mai thinks you're adorable anyway! 🌙",
    "Mai's brain is buffering, but your vibe is already loaded! 🔮",
    "Error 418: I'm a teapot, but you're still brewing something special! 🫖💕"
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

    log_event("flirt_daemon_started", {"args": sys.argv}, "logs/calls/calls.json")

    # =============================
    # ARGUMENT PARSING
    # =============================
    
    if len(sys.argv) < 2:
        error_msg = "Usage: python flirt_daemon.py <command_string> [username]"
        print(error_msg)
        write_to_file("Mai needs parameters! Format: <theme> <tone> <spice> - Example: pagan sultry 5", "output/flirt_line.txt")
        sys.exit(1)

    command_str = sys.argv[1]
    username = sys.argv[2] if len(sys.argv) >= 3 else "Anonymous"
    
    # Load validation data
    themes = load_json("data/themes.json", default={})
    tones = load_json("data/tone.json", default={})
    spice_levels = load_json("data/spice.json", default={})
    
    # Parse command string for theme, tone, spice
    theme = None
    tone = None
    level = None
    
    for token in command_str.split():
        cleaned = token.strip().lower()
        if cleaned in themes and theme is None:
            theme = cleaned
        elif cleaned in tones and tone is None:
            tone = cleaned
        elif cleaned.isdigit() and cleaned in spice_levels and level is None:
            level = int(cleaned)
    
    # Apply defaults for missing params
    theme = theme or "general"
    tone = tone or "playful"
    level = level or 3
    
    # Validate level is in range
    if level not in range(1, 11):
        level = min(max(1, level), 10)
    
    # =============================
    # FREE EVENT CONFIGURATION
    # =============================
    
    event_config = load_json("configs/event_config.json", default={})
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
            }, "logs/events/spice_caps.json")
    
    # =============================
    # RATE LIMITING CHECKS
    # =============================
    
    # Global rate limit
    can_request, rate_message = global_limiter.allow_request()
    if not can_request:
        print(rate_message)
        write_to_file(rate_message, "output/flirt_line.txt")
        log_event("rate_limited", {
            "username": username,
            "reason": "global_limit",
            "message": rate_message
        }, "logs/errors/rate_limits.json")
        sys.exit(0)
    
    # User cooldown
    cooldown_seconds = event_config.get("free_event_cooldown_seconds", 300) if is_free_event else 300
    can_request, remaining = user_tracker.check_cooldown(username, cooldown_seconds)
    
    if not can_request:
        cooldown_msg = f"@{username} - Mai needs {remaining}s to recharge for you! 💜"
        print(cooldown_msg)
        write_to_file(cooldown_msg, "output/flirt_line.txt")
        log_event("user_cooldown", {
            "username": username,
            "remaining_seconds": remaining,
            "cooldown_duration": cooldown_seconds
        }, "logs/errors/rate_limits.json")
        sys.exit(0)
    
    # =============================
    # GENERATE FLIRT
    # =============================
    
    try:
        print(f"Generating flirt for @{username}: theme={theme}, tone={tone}, spice={level}")
        
        prompt = build_specific_prompt(theme, tone, level)
        flirt_line = ask_openrouter(prompt)
        
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
            write_to_file(error_msg, "output/flirt_line.txt")
            log_event("safety_violation", {
                "username": username,
                "theme": theme,
                "tone": tone,
                "level": level,
                "reason": safety_reason,
                "blocked_output": flirt_line
            }, "logs/errors/safety_log.json")
            sys.exit(0)
        
        # =============================
        # REDACTION
        # =============================
        
        redaction_data = load_json("data/redaction.json", default={}).get("redaction", {})
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
        }, "logs/history/flirt_history.json")
        
        # Log prompt for debugging
        log_event("prompt_made", {
            "username": username,
            "theme": theme,
            "tone": tone,
            "level": level,
            "prompt": prompt
        }, "logs/prompts/prompt_history.json")
        
        # Write output for Streamer.bot to read
        write_to_file(redacted_flirt_line, "output/flirt_line.txt")
        
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
        
        write_to_file(fallback, "output/flirt_line.txt")
        log_event("generation_error", error_details, "logs/errors/error_log.json")
        
        sys.exit(0)  # Exit gracefully even on error