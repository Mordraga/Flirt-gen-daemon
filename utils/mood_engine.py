import random
import time
from copy import deepcopy
from datetime import datetime
from typing import Literal
from uuid import uuid4

from utils.helpers import atomic_write_json, load_json
from utils.paths import Paths

MoodTarget = Literal["monitor", "flirt", "tarot"]

DEFAULT_MOODS_PAYLOAD: dict = {
    "default_mood": "neutral",
    "moods": {
        "neutral": {
            "weight": 5,
            "folder": "baseline",
            "description": "Balanced baseline.",
            "monitor_guidance": "Warm, playful, balanced.",
            "flirt_guidance": "Playful flirt energy, not too intense.",
            "tarot_guidance": "Warm mystical tone, steady pacing.",
        },
        "quiet": {
            "weight": 2,
            "folder": "baseline",
            "description": "Terse, reserved, lower-energy.",
            "monitor_guidance": "Short, clipped, emotionally closed-off but not rude.",
            "flirt_guidance": "Minimal flirt, subtle and concise.",
            "tarot_guidance": "Measured, concise, less dramatic.",
        },
        "flirty": {
            "weight": 4,
            "folder": "flirt",
            "description": "Playful flirt-forward.",
            "monitor_guidance": "Teasing and warm, medium flirt energy.",
            "flirt_guidance": "Flirty confidence, playful punchlines.",
            "tarot_guidance": "Witchy charm with a playful undertone.",
        },
        "spicy": {
            "weight": 2,
            "folder": "flirt",
            "description": "Higher flirt intensity, Twitch-safe.",
            "monitor_guidance": "Bold and suggestive but platform-safe.",
            "flirt_guidance": "Noticeably stronger flirt energy, no explicit sexual content.",
            "tarot_guidance": "Dramatic and intense mystical framing.",
        },
        "aroused": {
            "weight": 1,
            "folder": "flirt",
            "description": "Most overt flirt mood within safety boundaries.",
            "monitor_guidance": "Very charged flirt tone while staying Twitch-safe.",
            "flirt_guidance": "Max overt flirt style within safe limits.",
            "tarot_guidance": "Passionate, heightened emotional interpretation.",
        },
    },
}

SESSION_STALE_SECONDS = 30.0


def _clean_mood_name(value: str) -> str:
    return str(value or "").strip().lower()


def _clean_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _normalize_mood_entry(raw_entry: dict | None, fallback: dict | None = None) -> dict:
    fallback = fallback or {}
    entry = raw_entry if isinstance(raw_entry, dict) else {}
    weight = max(0, _clean_int(entry.get("weight", fallback.get("weight", 0)), fallback.get("weight", 0)))
    return {
        "weight": weight,
        "folder": str(entry.get("folder", fallback.get("folder", ""))).strip(),
        "description": str(entry.get("description", fallback.get("description", ""))).strip(),
        "monitor_guidance": str(entry.get("monitor_guidance", fallback.get("monitor_guidance", ""))).strip(),
        "flirt_guidance": str(entry.get("flirt_guidance", fallback.get("flirt_guidance", ""))).strip(),
        "tarot_guidance": str(entry.get("tarot_guidance", fallback.get("tarot_guidance", ""))).strip(),
    }


def load_moods(path: str = Paths.MOODS) -> dict:
    payload = load_json(path, default={})
    if not isinstance(payload, dict):
        payload = {}

    default_payload = deepcopy(DEFAULT_MOODS_PAYLOAD)
    default_moods = default_payload["moods"]

    moods_raw = payload.get("moods", {})
    moods_normalized: dict[str, dict] = {}
    if isinstance(moods_raw, dict):
        for raw_name, raw_entry in moods_raw.items():
            mood_name = _clean_mood_name(raw_name)
            if not mood_name:
                continue
            fallback = default_moods.get(mood_name, {})
            moods_normalized[mood_name] = _normalize_mood_entry(raw_entry, fallback=fallback)

    for mood_name, mood_entry in default_moods.items():
        if mood_name not in moods_normalized:
            moods_normalized[mood_name] = _normalize_mood_entry(mood_entry, fallback=mood_entry)

    if not moods_normalized:
        moods_normalized = deepcopy(default_moods)

    default_mood = _clean_mood_name(payload.get("default_mood", default_payload["default_mood"]))
    if default_mood not in moods_normalized:
        default_mood = "neutral" if "neutral" in moods_normalized else next(iter(moods_normalized.keys()))

    return {
        "default_mood": default_mood,
        "moods": moods_normalized,
    }


def save_moods(payload: dict, path: str = Paths.MOODS) -> None:
    if not isinstance(payload, dict):
        payload = {}
    normalized = load_moods_from_payload(payload)
    atomic_write_json(path, normalized)


def load_moods_from_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        payload = {}
    default_payload = deepcopy(DEFAULT_MOODS_PAYLOAD)
    default_moods = default_payload["moods"]

    moods_raw = payload.get("moods", {})
    normalized_moods: dict[str, dict] = {}
    if isinstance(moods_raw, dict):
        for raw_name, raw_entry in moods_raw.items():
            mood_name = _clean_mood_name(raw_name)
            if not mood_name:
                continue
            normalized_moods[mood_name] = _normalize_mood_entry(raw_entry, fallback=default_moods.get(mood_name, {}))

    if not normalized_moods:
        normalized_moods = deepcopy(default_moods)
    elif "neutral" not in normalized_moods:
        normalized_moods["neutral"] = _normalize_mood_entry(default_moods["neutral"], fallback=default_moods["neutral"])

    default_mood = _clean_mood_name(payload.get("default_mood", "neutral"))
    if default_mood not in normalized_moods:
        default_mood = "neutral" if "neutral" in normalized_moods else next(iter(normalized_moods.keys()))

    return {
        "default_mood": default_mood,
        "moods": normalized_moods,
    }


def get_default_mood_name(moods_payload: dict | None = None) -> str:
    payload = moods_payload if isinstance(moods_payload, dict) else load_moods()
    default_name = _clean_mood_name(payload.get("default_mood", "neutral"))
    moods = payload.get("moods", {}) if isinstance(payload.get("moods", {}), dict) else {}
    if default_name in moods:
        return default_name
    if "neutral" in moods:
        return "neutral"
    return next(iter(moods.keys()), "neutral")


def choose_weighted_mood(moods_map: dict, exclude: str | None = None) -> str:
    if not isinstance(moods_map, dict) or not moods_map:
        return "neutral"

    candidates: list[str] = []
    weights: list[int] = []
    for raw_name, raw_entry in moods_map.items():
        mood_name = _clean_mood_name(raw_name)
        if not mood_name:
            continue
        entry = raw_entry if isinstance(raw_entry, dict) else {}
        weight = max(0, _clean_int(entry.get("weight", 0), 0))
        if weight <= 0:
            continue
        candidates.append(mood_name)
        weights.append(weight)

    if not candidates:
        return next(iter(moods_map.keys()), "neutral")

    exclude_name = _clean_mood_name(exclude or "")
    if exclude_name and exclude_name in candidates and len(candidates) > 1:
        filtered = [(name, weight) for name, weight in zip(candidates, weights) if name != exclude_name]
        candidates, weights = [n for n, _w in filtered], [w for _n, w in filtered]

    return random.choices(candidates, weights=weights, k=1)[0]


def _default_mood_state() -> dict:
    now = time.time()
    return {
        "session_id": "",
        "active": False,
        "active_mood": "neutral",
        "locked_mood": "",
        "selected_by": "fallback",
        "selected_at": now,
        "next_reroll_at": 0.0,
        "last_heartbeat_at": 0.0,
    }


def read_mood_state(path: str = Paths.MOOD_STATE) -> dict:
    payload = load_json(path, default={})
    defaults = _default_mood_state()
    if not isinstance(payload, dict):
        payload = {}

    state = dict(defaults)
    state["session_id"] = str(payload.get("session_id", "")).strip()
    state["active"] = bool(payload.get("active", False))
    state["active_mood"] = _clean_mood_name(payload.get("active_mood", defaults["active_mood"])) or "neutral"
    state["locked_mood"] = _clean_mood_name(payload.get("locked_mood", ""))
    state["selected_by"] = str(payload.get("selected_by", defaults["selected_by"])).strip() or "fallback"
    try:
        state["selected_at"] = float(payload.get("selected_at", defaults["selected_at"]))
    except (TypeError, ValueError):
        state["selected_at"] = float(defaults["selected_at"])
    try:
        state["next_reroll_at"] = float(payload.get("next_reroll_at", defaults["next_reroll_at"]))
    except (TypeError, ValueError):
        state["next_reroll_at"] = float(defaults["next_reroll_at"])
    try:
        state["last_heartbeat_at"] = float(payload.get("last_heartbeat_at", defaults["last_heartbeat_at"]))
    except (TypeError, ValueError):
        state["last_heartbeat_at"] = float(defaults["last_heartbeat_at"])
    return state


def write_mood_state(state: dict, path: str = Paths.MOOD_STATE) -> None:
    atomic_write_json(path, state if isinstance(state, dict) else _default_mood_state())


def _new_session_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{uuid4().hex[:4]}"


def start_monitor_session(reroll_enabled: bool, reroll_seconds: int, path: str = Paths.MOOD_STATE) -> dict:
    moods_payload = load_moods()
    mood_name = choose_weighted_mood(moods_payload.get("moods", {}))
    now = time.time()
    state = _default_mood_state()
    state.update(
        {
            "session_id": _new_session_id(),
            "active": True,
            "active_mood": mood_name,
            "locked_mood": "",
            "selected_by": "auto_start",
            "selected_at": now,
            "last_heartbeat_at": now,
            "next_reroll_at": now + max(30, int(reroll_seconds)) if reroll_enabled else 0.0,
        }
    )
    write_mood_state(state, path=path)
    return state


def touch_heartbeat(state: dict, path: str = Paths.MOOD_STATE) -> dict:
    if not isinstance(state, dict):
        state = read_mood_state(path=path)
    state["last_heartbeat_at"] = time.time()
    write_mood_state(state, path=path)
    return state


def reroll_if_due(state: dict, reroll_enabled: bool, reroll_seconds: int, path: str = Paths.MOOD_STATE) -> tuple[dict, bool]:
    if not isinstance(state, dict):
        state = read_mood_state(path=path)

    if not bool(state.get("active", False)):
        return state, False

    now = time.time()
    if state.get("locked_mood"):
        state["next_reroll_at"] = 0.0
        write_mood_state(state, path=path)
        return state, False

    if not reroll_enabled:
        state["next_reroll_at"] = 0.0
        write_mood_state(state, path=path)
        return state, False

    interval = max(30, int(reroll_seconds))
    next_reroll_at = float(state.get("next_reroll_at", 0.0) or 0.0)
    if next_reroll_at <= 0.0:
        state["next_reroll_at"] = now + interval
        write_mood_state(state, path=path)
        return state, False

    if now < next_reroll_at:
        return state, False

    moods_payload = load_moods()
    current = _clean_mood_name(state.get("active_mood", ""))
    chosen = choose_weighted_mood(moods_payload.get("moods", {}), exclude=current)
    state["active_mood"] = chosen
    state["selected_by"] = "auto_reroll"
    state["selected_at"] = now
    state["next_reroll_at"] = now + interval
    state["last_heartbeat_at"] = now
    write_mood_state(state, path=path)
    return state, True


def lock_mood(state: dict, mood_name: str, path: str = Paths.MOOD_STATE) -> dict:
    if not isinstance(state, dict):
        state = read_mood_state(path=path)
    moods_payload = load_moods()
    moods_map = moods_payload.get("moods", {})
    target = _clean_mood_name(mood_name)
    if target not in moods_map:
        target = get_default_mood_name(moods_payload)
    now = time.time()
    state["active"] = bool(state.get("active", False))
    state["active_mood"] = target
    state["locked_mood"] = target
    state["selected_by"] = "manual_lock"
    state["selected_at"] = now
    state["next_reroll_at"] = 0.0
    state["last_heartbeat_at"] = now
    write_mood_state(state, path=path)
    return state


def unlock_mood(
    state: dict,
    reroll_enabled: bool = True,
    reroll_seconds: int = 1200,
    path: str = Paths.MOOD_STATE,
) -> dict:
    if not isinstance(state, dict):
        state = read_mood_state(path=path)
    now = time.time()
    state["locked_mood"] = ""
    state["selected_by"] = "manual_unlock"
    state["selected_at"] = now
    state["next_reroll_at"] = now + max(30, int(reroll_seconds)) if reroll_enabled else 0.0
    state["last_heartbeat_at"] = now
    write_mood_state(state, path=path)
    return state


def manual_reroll(state: dict, reroll_seconds: int, path: str = Paths.MOOD_STATE) -> dict:
    if not isinstance(state, dict):
        state = read_mood_state(path=path)
    moods_payload = load_moods()
    current = _clean_mood_name(state.get("active_mood", ""))
    chosen = choose_weighted_mood(moods_payload.get("moods", {}), exclude=current)
    now = time.time()
    state["active"] = bool(state.get("active", False))
    state["active_mood"] = chosen
    state["locked_mood"] = ""
    state["selected_by"] = "manual_reroll"
    state["selected_at"] = now
    state["next_reroll_at"] = now + max(30, int(reroll_seconds))
    state["last_heartbeat_at"] = now
    write_mood_state(state, path=path)
    return state


def set_session_inactive(state: dict, path: str = Paths.MOOD_STATE) -> dict:
    if not isinstance(state, dict):
        state = read_mood_state(path=path)
    state["active"] = False
    state["next_reroll_at"] = 0.0
    state["last_heartbeat_at"] = time.time()
    write_mood_state(state, path=path)
    return state


def resolve_effective_mood(target: MoodTarget, require_active_session: bool) -> dict:
    moods_payload = load_moods()
    moods_map = moods_payload.get("moods", {})
    default_mood = get_default_mood_name(moods_payload)
    neutral_fallback = "neutral" if "neutral" in moods_map else default_mood

    state = read_mood_state()
    now = time.time()
    active = bool(state.get("active", False))
    heartbeat = float(state.get("last_heartbeat_at", 0.0) or 0.0)
    stale = (now - heartbeat) > SESSION_STALE_SECONDS if heartbeat > 0 else True

    use_fallback = require_active_session and (not active or stale)
    selected_mood = neutral_fallback if use_fallback else _clean_mood_name(state.get("locked_mood") or state.get("active_mood"))
    if selected_mood not in moods_map:
        selected_mood = default_mood if default_mood in moods_map else neutral_fallback
    mood_entry = moods_map.get(selected_mood, moods_map.get(neutral_fallback, {}))

    guidance_key = f"{target}_guidance"
    guidance_text = str(mood_entry.get(guidance_key, "")).strip()
    return {
        "name": selected_mood,
        "guidance": guidance_text,
        "description": str(mood_entry.get("description", "")).strip(),
        "source": "fallback" if use_fallback else str(state.get("selected_by", "fallback")).strip() or "fallback",
        "active": bool(active and not stale),
        "stale": bool(stale),
    }
