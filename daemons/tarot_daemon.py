import random
import re
import sys
import traceback
from pathlib import Path

# Add parent directory to path so we can import engine and utils
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import ask_openrouter
from utils.helpers import load_json, log_event, parse_all_params, write_to_file
from utils.paths import Paths
from utils.rate_limiter import GlobalRateLimiter, UserCooldownTracker


# =============================
# SAFETY CHECK
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

FALLBACK_READINGS = [
    "The cards are feeling shy tonight... but the stars still shine for you! 🌙",
    "The veil is thick today — but whatever's coming, your energy is ready for it. 🔮",
    "Even the cards need a moment sometimes. Trust the path, darling. 💜",
    "The mystical connection is buffering, but your fate isn't going anywhere! ✨",
    "The cards whisper secrets even when I can't translate them. Trust yourself. 🌿",
]


# =============================
# DECK UTILITIES
# =============================

def load_flat_deck(deck_path: str) -> list[dict]:
    """Flatten full_tarot_deck.json into a single list of card objects."""
    raw = load_json(deck_path, default={})
    cards: list[dict] = []
    for category_cards in raw.values():
        if isinstance(category_cards, list):
            cards.extend(category_cards)
    return cards


def build_tarot_prompt(question: str, spread_name: str, positions: list[str], drawn: list[tuple[dict, str]]) -> str:
    """Build the AI prompt for a tarot reading in Mai's voice.

    Args:
        question: The user's question (may be empty string).
        spread_name: Human-readable spread description.
        positions: List of position labels.
        drawn: List of (card_dict, orientation) tuples — one per position.
    """
    lines = [
        "You are Mai (MaidensAcquisitions.AI), a witchy, charismatic AI tarot reader for a Twitch stream.",
        "",
        "Rules:",
        "- 4 to 6 sentences total",
        "- Twitch-safe language only",
        "- Speak in Mai's voice: warm, mysterious, playful, a little dramatic",
        "- Reference the specific cards and their positions",
        "- If a question was asked, frame the reading around it",
        "- No asterisks, no markdown, plain text output only",
        "",
        f"Spread: {spread_name}",
    ]

    if question:
        lines.append(f"User's question: {question}")

    lines.append("")
    lines.append("Cards drawn:")
    for position, (card, orientation) in zip(positions, drawn):
        kw_key = "upright" if orientation == "upright" else "reversed"
        keywords = card.get("keywords", {}).get(kw_key, [])
        summary = ""
        llm_summaries = card.get("summary", {}).get("llm", [])
        if llm_summaries:
            summary = llm_summaries[0]
        keyword_str = ", ".join(keywords) if keywords else "no keywords"
        lines.append(
            f"  {position}: {card.get('name', 'Unknown')} ({orientation}) — {summary} | Keywords: {keyword_str}"
        )

    lines.append("")
    lines.append("Deliver the tarot reading now. Output the reading only. No preamble, no explanation.")
    return "\n".join(lines)


# =============================
# GLOBAL INSTANCES
# =============================

global_limiter = GlobalRateLimiter(max_calls=30, window=60)
user_tracker = UserCooldownTracker()


# =============================
# MAIN EXECUTION
# =============================

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    log_event("tarot_daemon_started", {"args": sys.argv}, Paths.CALLS_LOG)

    # =============================
    # ARGUMENT PARSING
    # =============================

    if len(sys.argv) < 2:
        error_msg = "Usage: python tarot_daemon.py <rawInput> [username]"
        print(error_msg)
        write_to_file("Mai needs a question or spread! Try: !tarot what is my fate 3-card", Paths.TAROT_OUTPUT)
        sys.exit(1)

    raw_input = sys.argv[1]
    username = sys.argv[2] if len(sys.argv) >= 3 else "Anonymous"

    params = parse_all_params(raw_input)
    spread_key = params.get("spread") or "3-card"
    question = params.get("question") or ""

    # =============================
    # LOAD SPREAD & DECK
    # =============================

    spreads_data = load_json(Paths.TAROT_SPREADS, default={})
    if spread_key not in spreads_data:
        spread_key = "3-card"

    spread_info = spreads_data[spread_key]
    positions: list[str] = spread_info.get("positions", ["Past", "Present", "Future"])
    spread_description: str = spread_info.get("description", spread_key)

    deck = load_flat_deck(Paths.TAROT_DECK)
    if len(deck) < len(positions):
        error_msg = "The tarot deck is empty — check full_tarot_deck.json! 🌙"
        print(error_msg)
        write_to_file(error_msg, Paths.TAROT_OUTPUT)
        sys.exit(1)

    # =============================
    # RATE LIMITING
    # =============================

    can_request, rate_message = global_limiter.allow_request()
    if not can_request:
        print(rate_message)
        write_to_file(rate_message, Paths.TAROT_OUTPUT)
        log_event("rate_limited", {
            "username": username,
            "reason": "global_limit",
            "message": rate_message,
        }, Paths.RATE_LIMITS_LOG)
        sys.exit(0)

    can_request, remaining = user_tracker.check_cooldown(username, 300)
    if not can_request:
        cooldown_msg = f"@{username} - The cards need {remaining}s to reset for you! 🔮"
        print(cooldown_msg)
        write_to_file(cooldown_msg, Paths.TAROT_OUTPUT)
        log_event("user_cooldown", {
            "username": username,
            "remaining_seconds": remaining,
        }, Paths.RATE_LIMITS_LOG)
        sys.exit(0)

    # =============================
    # DRAW CARDS & GENERATE
    # =============================

    try:
        print(f"Reading tarot for @{username}: spread={spread_key}, question={question!r}")

        sampled = random.sample(deck, len(positions))
        orientations = [random.choice(["upright", "reversed"]) for _ in positions]
        drawn = list(zip(sampled, orientations))

        prompt = build_tarot_prompt(question, spread_description, positions, drawn)
        reading = ask_openrouter(prompt)

        if reading.startswith("WARNING:"):
            raise Exception(reading)

        # =============================
        # SAFETY CHECK
        # =============================

        is_safe, safety_reason = safety_check(reading)
        if not is_safe:
            error_msg = "The cards sensed something dark and refused to speak. Try again! 🛡️"
            print(f"SAFETY VIOLATION: {safety_reason}")
            write_to_file(error_msg, Paths.TAROT_OUTPUT)
            log_event("safety_violation", {
                "username": username,
                "spread": spread_key,
                "reason": safety_reason,
                "blocked_output": reading,
            }, Paths.SAFETY_LOG)
            sys.exit(0)

        # =============================
        # OUTPUT & LOGGING
        # =============================

        print(f"SUCCESS!")
        print(f"SPREAD: {spread_key}, USER: @{username}")
        print(f"READING: {reading}")

        card_log = [
            {"position": pos, "card": card.get("name"), "ucid": card.get("UCID"), "orientation": ori}
            for pos, (card, ori) in zip(positions, drawn)
        ]
        log_event("tarot_generated", {
            "username": username,
            "spread": spread_key,
            "question": question,
            "cards": card_log,
            "reading": reading,
        }, Paths.TAROT_HISTORY)

        write_to_file(reading, Paths.TAROT_OUTPUT)

    except Exception as e:
        fallback = random.choice(FALLBACK_READINGS)

        print(f"ERROR TYPE: {type(e).__name__}")
        print(f"ERROR MESSAGE: {e}")
        print(f"TRACEBACK:\n{traceback.format_exc()}")
        print(f"FALLBACK: {fallback}")

        write_to_file(fallback, Paths.TAROT_OUTPUT)
        log_event("tarot_generation_error", {
            "username": username,
            "spread": spread_key,
            "question": question,
            "error_type": type(e).__name__,
            "error_message": str(e),
            "error_traceback": traceback.format_exc(),
            "fallback_used": fallback,
        }, Paths.ERROR_LOG)

        sys.exit(0)
