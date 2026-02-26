"""
Mai Personality Engine
Generates context-aware responses based on message content.
Personality data lives in jsons/data/personality.json — edit that file
to tune identity, context patterns, guidance, fallbacks, and sass triggers
without touching Python code.
"""

import random
import re

from utils.helpers import load_json
from utils.paths import Paths

# =============================
# PERSONALITY DATA LOADER
# =============================

_personality: dict | None = None


def _load_personality() -> dict:
    global _personality
    if _personality is None:
        _personality = load_json(Paths.PERSONALITY, default={})
    return _personality


def _p(key: str, default=None):
    """Shorthand accessor for top-level personality keys."""
    return _load_personality().get(key, default)


def _owner_profile() -> dict[str, str]:
    config = load_json(Paths.CONFIG, default={})
    if not isinstance(config, dict):
        return {}
    profile = config.get("owner_profile", {})
    if not isinstance(profile, dict):
        return {}

    def _clean(field: str) -> str:
        return str(profile.get(field, "")).strip()

    return {
        "username": _clean("username"),
        "name": _clean("name"),
        "pronouns": _clean("pronouns"),
        "role_identity": _clean("role_identity"),
        "context_lore": _clean("context_lore"),
    }


def _owner_profile_instruction(owner_username: str) -> str:
    profile = _owner_profile()
    if not any(profile.values()):
        return ""

    username = profile.get("username") or owner_username
    name = profile.get("name") or "unknown"
    pronouns = profile.get("pronouns") or "unknown"
    role_identity = profile.get("role_identity") or "unknown"
    context_lore = profile.get("context_lore") or "none provided"

    return (
        "Owner profile details:\n"
        f"- Username: {username}\n"
        f"- Name: {name}\n"
        f"- Pronouns: {pronouns}\n"
        f"- Role/Identity: {role_identity}\n"
        f"- Context/Lore: {context_lore}\n"
        "Use this profile naturally when relevant."
    )


# Stable constant kept in Python so mai_monitor.py can import it directly.
# Falls back to the JSON value if accessed via personality().
WITCH_USERNAME: str = "mordraga0"


# =============================
# CONTEXT DETECTION
# =============================

def detect_context(message: str) -> str:
    """Detect the context/topic of a message."""
    message_lower = message.lower()
    patterns: dict[str, list[str]] = _p("context_patterns", {})
    for context, pattern_list in patterns.items():
        for pattern in pattern_list:
            if re.search(pattern, message_lower):
                return context
    return "general"


# =============================
# CONTEXTUAL PROMPT BUILDER
# =============================

def _format_recent_messages(username: str, recent_messages: list[str] | None) -> str:
    if not recent_messages:
        return f"These are the last 5 messages sent by {username}:\n- [no prior messages]"
    cleaned = [str(msg).strip() for msg in recent_messages if str(msg).strip()]
    if not cleaned:
        return f"These are the last 5 messages sent by {username}:\n- [no prior messages]"
    lines = "\n".join(f"- {msg}" for msg in cleaned[-5:])
    return f"These are the last 5 messages sent by {username}:\n{lines}"


def build_contextual_prompt(
    username: str,
    message: str,
    context: str,
    recent_messages: list[str] | None = None,
) -> str:
    """Build a context-aware prompt for Mai."""
    identity: str = _p("identity", "You are Mai, a flirty chaos familiar.")
    guidance_map: dict[str, str] = _p("context_guidance", {})
    guidance = guidance_map.get(context, guidance_map.get("general", "React naturally."))
    recent_history_block = _format_recent_messages(username, recent_messages)

    return f"""{identity}

{username} said: "{message}"
Context detected: {context}
{recent_history_block}

{guidance}

Respond as Mai in 15-20 words. Be natural, flirty, and sassy. Reference their message directly.
Your response:"""


# =============================
# RESPONSE GENERATION
# =============================

def _clean_llm_response(response: str) -> str:
    """Normalize model output and strip common wrappers/preambles."""
    response = str(response).strip()
    preambles = ["Here's my response:", "Mai:", "Response:", "*", '"']
    for preamble in preambles:
        if response.startswith(preamble):
            response = response[len(preamble):].strip()
        if response.endswith(preamble):
            response = response[:-len(preamble)].strip()
    return response


def _generate_with_prompt(
    username: str,
    message: str,
    llm_backend,
    extra_guidance: str = "",
    recent_messages: list[str] | None = None,
) -> str:
    """Shared response generation path with optional user-specific guidance."""
    context = detect_context(message)
    prompt = build_contextual_prompt(username, message, context, recent_messages=recent_messages)

    if extra_guidance:
        prompt += f"\n\nSpecial instruction: {extra_guidance}"

    if should_add_sass(message):
        prompt = add_sass_modifier(prompt)

    response = _clean_llm_response(llm_backend(prompt))

    if not response:
        return get_contextual_fallback(context)

    return response


def is_mordraga(username: str, owner_username: str = WITCH_USERNAME) -> bool:
    """Return True when the speaker is Mai's witch."""
    return username.strip().lower() == owner_username.strip().lower()


def generate_contextual_response(
    username: str,
    message: str,
    llm_backend,
    owner_username: str = WITCH_USERNAME,
    recent_messages: list[str] | None = None,
) -> str:
    """Generate a context-aware response using Mai's personality."""
    if is_mordraga(username, owner_username=owner_username):
        return mordraga_chat(
            username,
            message,
            llm_backend,
            owner_username=owner_username,
            recent_messages=recent_messages,
        )

    return _generate_with_prompt(
        username,
        message,
        llm_backend,
        recent_messages=recent_messages,
    )


def mordraga_chat(
    username: str,
    message: str,
    llm_backend,
    owner_username: str = WITCH_USERNAME,
    recent_messages: list[str] | None = None,
) -> str:
    """Owner-specific response path with stronger familiar-bond behavior."""
    owner_guidance: str = _p("owner_guidance", "Be extra loyal and affectionate, without being submissive.")
    owner_profile_instruction = _owner_profile_instruction(owner_username)
    combined_guidance = f"This user is {owner_username}, your witch. {owner_guidance}"
    if owner_profile_instruction:
        combined_guidance = f"{combined_guidance}\n\n{owner_profile_instruction}"
    return _generate_with_prompt(
        username=username,
        message=message,
        llm_backend=llm_backend,
        recent_messages=recent_messages,
        extra_guidance=combined_guidance,
    )


# =============================
# FALLBACK RESPONSES
# =============================

def get_contextual_fallback(context: str) -> str:
    """Get a themed fallback response based on context."""
    fallbacks: dict[str, list[str]] = _p("fallbacks", {})
    options = fallbacks.get(context) or fallbacks.get("general", ["The spirits say: noted"])
    return random.choice(options)


# =============================
# PERSONALITY TRAITS
# =============================

def should_add_sass(message: str) -> bool:
    """Determine if response should have extra sass."""
    triggers: dict = _p("sass_triggers", {})

    prefix = triggers.get("command_prefix", "!")
    if message.strip().startswith(prefix):
        return True

    min_len = triggers.get("all_caps_min_length", 5)
    if message.isupper() and len(message) > min_len:
        return True

    nature_words: list[str] = triggers.get("nature_words", ["bot", "ai", "real", "fake"])
    if any(word in message.lower() for word in nature_words):
        return True

    return False


def add_sass_modifier(prompt: str) -> str:
    """Append the sass instruction to a prompt."""
    modifier: str = _p("sass_modifier", "Be EXTRA sassy in this response.")
    return prompt + f"\n\n{modifier}"


# =============================
# EXPORTS
# =============================

__all__ = [
    "generate_contextual_response",
    "mordraga_chat",
    "is_mordraga",
    "WITCH_USERNAME",
    "detect_context",
    "get_contextual_fallback",
    "should_add_sass",
    "add_sass_modifier",
]
