"""
Central path constants for all jsons/ file references.

Import Paths from here instead of hardcoding strings inline.
"""


class Paths:
    # ---- Configs -------------------------------------------------------
    CONFIG           = "jsons/configs/config.json"
    KEYS             = "jsons/configs/keys.json"
    REGISTRY         = "jsons/configs/registry.json"
    EVENT_CONFIG     = "jsons/configs/event_config.json"

    # ---- Data ----------------------------------------------------------
    THEMES           = "jsons/data/themes.json"
    TONES            = "jsons/data/tone.json"
    SPICE            = "jsons/data/spice.json"
    COOLDOWN_MSGS    = "jsons/data/cooldown_msg.json"
    COOLDOWN_HISTORY = "jsons/data/cooldown_history.json"
    USER_COOLDOWNS   = "jsons/data/user_cooldowns.json"
    REDACTION        = "jsons/data/redaction.json"
    PERSONALITY      = "jsons/data/personality.json"
    TAROT_DECK       = "jsons/data/full_tarot_deck.json"
    TAROT_SPREADS    = "jsons/data/tarot_spreads.json"
    FALLBACK_FLIRTS  = "jsons/data/fallback_flirts.json"
    PROMPT_TEMPLATES = "jsons/data/Prompt_Templates.json"
    COMMANDS         = "jsons/data/commands.json"
    COMMAND_ACCESS   = "jsons/data/command_access.json"

    # ---- Calls / routing -----------------------------------------------
    CALLS_LOG        = "jsons/calls/calls.json"
    ROUTING_LOG      = "jsons/calls/routing_log.json"

    # ---- History -------------------------------------------------------
    CHAT_LOG           = "jsons/logs/history/chat_log.json"
    FLIRT_HISTORY      = "jsons/logs/history/flirt_history.json"
    TAROT_HISTORY      = "jsons/logs/history/tarot_history.json"
    COMMAND_HISTORY    = "jsons/logs/history/command_history.json"
    AUTONOMOUS_HISTORY = "jsons/logs/history/autonomous_history.json"
    USER_REGISTRY      = "jsons/logs/history/user_registry.json"
    USER_HISTORY_DIR   = "jsons/logs/history/users"

    # ---- Errors --------------------------------------------------------
    ERROR_LOG        = "jsons/logs/errors/error_log.json"
    ROUTING_ERRORS   = "jsons/logs/errors/routing_errors.json"
    AUTONOMOUS_ERRORS= "jsons/logs/errors/autonomous_errors.json"
    SAFETY_LOG       = "jsons/logs/errors/safety_log.json"
    RATE_LIMITS_LOG  = "jsons/logs/errors/rate_limits.json"

    # ---- Events --------------------------------------------------------
    SPICE_CAPS_LOG   = "jsons/logs/events/spice_caps.json"

    # ---- Prompts -------------------------------------------------------
    PROMPT_HISTORY   = "jsons/logs/prompts/prompt_history.json"

    # ---- Output --------------------------------------------------------
    FLIRT_OUTPUT     = "jsons/output/flirt_line.txt"
    TAROT_OUTPUT     = "jsons/output/tarot_reading.txt"
    COMMAND_OUTPUT   = "jsons/output/command_response.txt"
