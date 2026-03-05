import re
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from utils.helpers import atomic_write_json, load_json
from utils.mood_engine import load_moods, lock_mood, manual_reroll, read_mood_state, unlock_mood
from utils.paths import Paths

def _is_valid_username(self, value: str) -> bool:
    return bool(re.fullmatch(r"[a-zA-Z0-9_]{2,25}", value or ""))

def _validate_monitor_event_inputs(self) -> list[str]:
    errors: list[str] = []
    try:
        chance = float(self.monitor_vars["response_chance_percent"].get().strip())
        if chance < 0 or chance > 100:
            errors.append("Response chance must be between 0 and 100.")
    except Exception:
        errors.append("Response chance must be a number.")

    try:
        cooldown = int(self.monitor_vars["global_cooldown_seconds"].get().strip())
        if cooldown < 0:
            errors.append("Global cooldown must be >= 0.")
    except Exception:
        errors.append("Global cooldown must be an integer.")

    try:
        buf = int(self.monitor_vars["check_buffer_size"].get().strip())
        if buf < 256:
            errors.append("IRC buffer size must be >= 256.")
    except Exception:
        errors.append("IRC buffer size must be an integer.")

    try:
        reload_s = float(self.monitor_vars["config_reload_seconds"].get().strip())
        if reload_s < 0.5:
            errors.append("Config reload interval must be >= 0.5.")
    except Exception:
        errors.append("Config reload interval must be numeric.")

    try:
        flush_s = int(self.monitor_vars["registry_flush_seconds"].get().strip())
        if flush_s < 5:
            errors.append("Registry flush interval must be >= 5.")
    except Exception:
        errors.append("Registry flush interval must be an integer.")

    try:
        mood_reroll = int(self.monitor_vars["mood_reroll_seconds"].get().strip())
        if mood_reroll < 30:
            errors.append("Mood reroll interval must be >= 30.")
    except Exception:
        errors.append("Mood reroll interval must be an integer.")

    try:
        port = int(self.monitor_vars["irc_port"].get().strip())
        if port < 1 or port > 65535:
            errors.append("IRC port must be between 1 and 65535.")
    except Exception:
        errors.append("IRC port must be an integer.")

    owner_username = self.monitor_vars["owner_username"].get().strip().lower()
    if owner_username and not self._is_valid_username(owner_username):
        errors.append("Owner username may contain only letters, numbers, and underscore (2-25 chars).")

    try:
        max_spice = int(self.event_vars["free_event_max_spice"].get().strip())
        if max_spice < 1 or max_spice > 10:
            errors.append("Event max spice must be between 1 and 10.")
    except Exception:
        errors.append("Event max spice must be an integer.")

    try:
        event_cd = int(self.event_vars["free_event_cooldown_seconds"].get().strip())
        if event_cd < 0:
            errors.append("Event cooldown must be >= 0.")
    except Exception:
        errors.append("Event cooldown must be an integer.")

    try:
        event_limit = int(self.event_vars["free_event_global_limit_per_minute"].get().strip())
        if event_limit < 1:
            errors.append("Event global limit/minute must be >= 1.")
    except Exception:
        errors.append("Event global limit/minute must be an integer.")

    return errors

def _refresh_monitor_meta_label(self):
    cfg = load_json(self.config_path, default={})
    ui_meta = cfg.get("ui_meta", {}) if isinstance(cfg.get("ui_meta", {}), dict) else {}
    ts = ui_meta.get("last_changed_monitor_event_at")
    self.monitor_last_changed_var.set(f"Last changed by UI: {self._format_meta_time(ts)}")

def _load_mood_names(self) -> list[str]:
    moods_payload = load_moods(Paths.MOODS)
    moods_map = moods_payload.get("moods", {})
    if not isinstance(moods_map, dict):
        return ["neutral"]
    names = sorted([str(name).strip().lower() for name in moods_map.keys() if str(name).strip()], key=str.lower)
    return names or ["neutral"]

def _get_monitor_mood_reroll_settings(self) -> tuple[bool, int]:
    enabled_var = self.monitor_vars.get("mood_reroll_enabled")
    enabled = bool(enabled_var.get()) if isinstance(enabled_var, tk.BooleanVar) else True

    seconds = 1200
    seconds_var = self.monitor_vars.get("mood_reroll_seconds")
    if isinstance(seconds_var, tk.StringVar):
        try:
            seconds = int(seconds_var.get().strip() or 1200)
        except Exception:
            seconds = 1200
    return enabled, max(30, int(seconds))

def _has_active_monitor_mood_session(self, state: dict | None = None) -> bool:
    current = state if isinstance(state, dict) else read_mood_state(Paths.MOOD_STATE)
    if not bool(current.get("active", False)):
        return False
    heartbeat_raw = current.get("last_heartbeat_at", 0.0)
    try:
        heartbeat = float(heartbeat_raw)
    except Exception:
        return False
    if heartbeat <= 0:
        return False
    return (time.time() - heartbeat) <= 30.0

def _refresh_monitor_mood_state(self) -> None:
    state = read_mood_state(Paths.MOOD_STATE)
    mood_name = str(state.get("active_mood", "neutral")).strip() or "neutral"
    selected_by = str(state.get("selected_by", "fallback")).strip() or "fallback"
    session_active = self._has_active_monitor_mood_session(state)
    self.monitor_mood_name_var.set(mood_name)
    self.monitor_mood_source_var.set(selected_by)
    self.monitor_mood_status_var.set(f"Mood: {mood_name}")

    locked = str(state.get("locked_mood", "")).strip()
    if locked:
        self.monitor_mood_next_var.set("locked")
        self.monitor_mood_lock_var.set(locked)
        if self.monitor_mood_reroll_button is not None:
            self.monitor_mood_reroll_button.configure(state=tk.DISABLED)
    else:
        next_reroll = state.get("next_reroll_at", 0.0)
        if isinstance(next_reroll, (int, float)) and float(next_reroll) > 0:
            self.monitor_mood_next_var.set(self._format_glance_timestamp(float(next_reroll)))
        else:
            self.monitor_mood_next_var.set("n/a")
        if not self.monitor_mood_lock_var.get().strip():
            self.monitor_mood_lock_var.set(mood_name)
        if self.monitor_mood_reroll_button is not None:
            self.monitor_mood_reroll_button.configure(state=tk.NORMAL if session_active else tk.DISABLED)

    mood_names = self._load_mood_names()
    if self.monitor_mood_combo is not None:
        self.monitor_mood_combo["values"] = mood_names
        current = self.monitor_mood_lock_var.get().strip().lower()
        if current not in mood_names:
            self.monitor_mood_lock_var.set(mood_names[0] if mood_names else "neutral")

def _lock_selected_monitor_mood(self) -> None:
    mood_name = self.monitor_mood_lock_var.get().strip().lower()
    if not mood_name:
        messagebox.showwarning("Mood", "Select a mood to lock.", parent=self.root)
        return

    state = read_mood_state(Paths.MOOD_STATE)
    if not self._has_active_monitor_mood_session(state):
        messagebox.showinfo("Mood", "Start the monitor before locking the session mood.", parent=self.root)
        return
    lock_mood(state, mood_name, path=Paths.MOOD_STATE)
    self.log_queue.put(f"[mood] locked to '{mood_name}'")
    self._set_status(f"Mood locked: {mood_name}", "ok")
    self._refresh_monitor_mood_state()
    self._refresh_glance()

def _unlock_monitor_mood(self) -> None:
    state = read_mood_state(Paths.MOOD_STATE)
    if not self._has_active_monitor_mood_session(state):
        messagebox.showinfo("Mood", "No active monitor mood session to unlock.", parent=self.root)
        return
    reroll_enabled, reroll_seconds = self._get_monitor_mood_reroll_settings()
    unlock_mood(
        state,
        reroll_enabled=reroll_enabled,
        reroll_seconds=reroll_seconds,
        path=Paths.MOOD_STATE,
    )
    self.log_queue.put("[mood] unlocked")
    self._set_status("Mood unlocked.", "ok")
    self._refresh_monitor_mood_state()
    self._refresh_glance()

def _reroll_monitor_mood(self) -> None:
    state = read_mood_state(Paths.MOOD_STATE)
    if not self._has_active_monitor_mood_session(state):
        messagebox.showinfo("Mood", "Start the monitor before rerolling mood.", parent=self.root)
        return
    if str(state.get("locked_mood", "")).strip():
        messagebox.showinfo("Mood", "Mood is locked. Unlock before rerolling.", parent=self.root)
        return
    _enabled, reroll_seconds = self._get_monitor_mood_reroll_settings()
    manual_reroll(state, reroll_seconds=reroll_seconds, path=Paths.MOOD_STATE)
    updated = read_mood_state(Paths.MOOD_STATE)
    mood_name = str(updated.get("active_mood", "neutral")).strip() or "neutral"
    self.log_queue.put(f"[mood] rerolled -> {mood_name}")
    self._set_status(f"Mood rerolled: {mood_name}", "ok")
    self._refresh_monitor_mood_state()
    self._refresh_glance()

def _build_monitor_tab(self, parent: ttk.Frame):
    controls = ttk.LabelFrame(parent, text="Mai Monitor")
    controls.pack(fill=tk.X, padx=12, pady=12)
    controls.columnconfigure(6, weight=1)

    ttk.Label(controls, text="Status:").grid(row=0, column=0, sticky="w", padx=8, pady=8)
    ttk.Label(controls, textvariable=self.monitor_status_var).grid(row=0, column=1, sticky="w", padx=8, pady=8)

    ttk.Button(controls, text="Start Monitor", command=self.start_monitor).grid(row=0, column=2, padx=8, pady=8)
    ttk.Button(controls, text="Stop Monitor",  command=self.stop_monitor).grid(row=0, column=3, padx=8, pady=8)
    ttk.Button(controls, text="Reload Config", command=self._load_monitor_config_into_form).grid(row=0, column=4, padx=8, pady=8)

    ttk.Label(controls, text="Current mood:").grid(row=1, column=0, sticky="w", padx=8, pady=(0, 6))
    ttk.Label(controls, textvariable=self.monitor_mood_name_var).grid(row=1, column=1, sticky="w", padx=8, pady=(0, 6))
    ttk.Label(controls, text="Selected by:").grid(row=1, column=2, sticky="w", padx=8, pady=(0, 6))
    ttk.Label(controls, textvariable=self.monitor_mood_source_var).grid(row=1, column=3, sticky="w", padx=8, pady=(0, 6))
    ttk.Label(controls, text="Next reroll:").grid(row=1, column=4, sticky="w", padx=8, pady=(0, 6))
    ttk.Label(controls, textvariable=self.monitor_mood_next_var).grid(row=1, column=5, sticky="w", padx=8, pady=(0, 6))

    ttk.Label(controls, text="Lock to mood").grid(row=2, column=0, sticky="w", padx=8, pady=(0, 8))
    self.monitor_mood_combo = ttk.Combobox(
        controls,
        textvariable=self.monitor_mood_lock_var,
        values=self._load_mood_names(),
        state="readonly",
        width=20,
    )
    self.monitor_mood_combo.grid(row=2, column=1, sticky="w", padx=8, pady=(0, 8))
    ttk.Button(controls, text="Lock Selected", command=self._lock_selected_monitor_mood).grid(
        row=2, column=2, padx=8, pady=(0, 8)
    )
    ttk.Button(controls, text="Unlock", command=self._unlock_monitor_mood).grid(
        row=2, column=3, padx=8, pady=(0, 8)
    )
    self.monitor_mood_reroll_button = ttk.Button(controls, text="Reroll Now", command=self._reroll_monitor_mood)
    self.monitor_mood_reroll_button.grid(row=2, column=4, padx=8, pady=(0, 8))

    _form_section, form = self._build_collapsible_section(
        parent,
        title="Monitor Runtime Config (live-reloadable)",
        expanded=True,
        state_key="monitor_runtime",
    )

    fields = [
        ("twitch_channel",          "Twitch channel",                  "str"),
        ("owner_username",           "Owner username",                   "str"),
        ("response_chance_percent",  "Response chance %",                "float"),
        ("global_cooldown_seconds",  "Global cooldown (s)",              "int"),
        ("check_buffer_size",        "IRC buffer size",                  "int"),
        ("ignored_bot_usernames",    "Ignored bots (comma separated)",   "str"),
        ("config_reload_seconds",    "Config reload interval (s)",       "float"),
        ("registry_flush_seconds",   "Registry flush interval (s)",      "int"),
        ("mood_reroll_seconds",      "Mood reroll interval (s)",         "int"),
        ("irc_server",               "IRC server",                       "str"),
        ("irc_port",                 "IRC port",                         "int"),
    ]
    bool_fields = [
        ("respond_to_owner_always",  "Always respond to owner"),
        ("ignore_command_messages",  "Ignore command messages (!foo)"),
        ("mood_reroll_enabled",      "Enable mood auto-reroll"),
    ]

    for i, (key, label, _) in enumerate(fields):
        ttk.Label(form, text=label).grid(row=i, column=0, sticky="w", padx=8, pady=5)
        var = tk.StringVar()
        ttk.Entry(form, textvariable=var, width=48).grid(row=i, column=1, sticky="w", padx=8, pady=5)
        self.monitor_vars[key] = var
        self._bind_dirty_var("monitor", var)

    base_row = len(fields)
    for i, (key, label) in enumerate(bool_fields):
        var = tk.BooleanVar(value=False)
        ttk.Checkbutton(form, text=label, variable=var).grid(
            row=base_row + i, column=0, columnspan=2, sticky="w", padx=8, pady=4
        )
        self.monitor_vars[key] = var
        self._bind_dirty_var("monitor", var)

    action_row = base_row + len(bool_fields)
    ttk.Button(form, text="Save Config (Monitor + Event)", command=self.save_monitor_config).grid(
        row=action_row, column=0, padx=8, pady=10, sticky="w"
    )
    ttk.Label(
        form,
        text="Monitor changes apply to running monitor automatically within the configured reload interval.",
    ).grid(row=action_row, column=1, sticky="w", padx=8, pady=10)
    ttk.Label(form, textvariable=self.monitor_last_changed_var, foreground=self.theme_palette["text_subtle"]).grid(
        row=action_row + 1, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 6)
    )

    _event_section, event_form = self._build_collapsible_section(
        parent,
        title="Flirt Event Config",
        expanded=True,
        state_key="event_config",
    )

    event_fields = [
        ("free_event_name", "Event name", "str"),
        ("free_event_max_spice", "Max spice", "int"),
        ("free_event_cooldown_seconds", "Cooldown (s)", "int"),
        ("free_event_global_limit_per_minute", "Global limit / minute", "int"),
        ("announcement_message", "Announcement", "str"),
    ]

    for i, (key, label, _kind) in enumerate(event_fields):
        ttk.Label(event_form, text=label).grid(row=i, column=0, sticky="w", padx=8, pady=5)
        var = tk.StringVar()
        width = 72 if key == "announcement_message" else 48
        ttk.Entry(event_form, textvariable=var, width=width).grid(
            row=i, column=1, sticky="w", padx=8, pady=5
        )
        self.event_vars[key] = var
        self._bind_dirty_var("monitor", var)

    free_event_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(
        event_form,
        text="Free event active",
        variable=free_event_var,
    ).grid(row=len(event_fields), column=0, columnspan=2, sticky="w", padx=8, pady=4)
    self.event_vars["free_event_active"] = free_event_var
    self._bind_dirty_var("monitor", free_event_var)

    ttk.Button(event_form, text="Save Config (Monitor + Event)", command=self.save_monitor_config).grid(
        row=len(event_fields) + 1, column=0, padx=8, pady=10, sticky="w"
    )
    ttk.Label(
        event_form,
        text="These values drive flirt event caps, cooldowns, and limiter behavior.",
    ).grid(row=len(event_fields) + 1, column=1, sticky="w", padx=8, pady=10)
    ttk.Label(
        event_form,
        textvariable=self.monitor_last_changed_var,
        foreground=self.theme_palette["text_subtle"],
    ).grid(row=len(event_fields) + 2, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 6))

def _load_monitor_config_into_form(self):
    try:
        cfg = load_json(self.config_path)
    except Exception as e:
        messagebox.showerror("Config", f"Failed to load config: {e}")
        self.log_queue.put(f"[ui] failed to load config: {e}")
        self._set_status(f"Monitor config load failed: {e}", "error")
        return

    monitor = cfg.get("monitor", {}) if isinstance(cfg.get("monitor", {}), dict) else {}
    event_cfg = cfg.get("event", {}) if isinstance(cfg.get("event", {}), dict) else {}
    if not event_cfg and isinstance(cfg.get("Event", {}), dict):
        event_cfg = cfg.get("Event", {})

    defaults = {
        "twitch_channel":           "mordraga0",
        "owner_username":            "mordraga0",
        "response_chance_percent":   35,
        "global_cooldown_seconds":   5,
        "check_buffer_size":         2048,
        "ignored_bot_usernames":     "nightbot,streamelements,streamlabs,moobot,fossabot",
        "respond_to_owner_always":   True,
        "ignore_command_messages":   True,
        "config_reload_seconds":     2,
        "registry_flush_seconds":    30,
        "mood_reroll_enabled":       True,
        "mood_reroll_seconds":       1200,
        "irc_server":                "irc.chat.twitch.tv",
        "irc_port":                  6667,
    }

    for key, default in defaults.items():
        value = monitor.get(key, default)
        var   = self.monitor_vars[key]
        if isinstance(var, tk.BooleanVar):
            var.set(bool(value))
        else:
            if key == "ignored_bot_usernames" and isinstance(value, list):
                var.set(",".join(str(v).strip() for v in value if str(v).strip()))
            else:
                var.set(str(value))

    event_defaults = {
        "free_event_active": False,
        "free_event_name": "Free Flirts Event",
        "free_event_max_spice": 5,
        "free_event_cooldown_seconds": 300,
        "free_event_global_limit_per_minute": 30,
        "announcement_message": "",
    }
    for key, default in event_defaults.items():
        var = self.event_vars.get(key)
        if var is None:
            continue
        value = event_cfg.get(key, default)
        if isinstance(var, tk.BooleanVar):
            if isinstance(value, str):
                var.set(value.strip().lower() in {"1", "true", "yes", "on"})
            else:
                var.set(bool(value))
        else:
            var.set(str(value))

    self._refresh_monitor_meta_label()
    self._refresh_monitor_mood_state()
    self._mark_dirty("monitor", False)
    self.log_queue.put("[ui] monitor config loaded")
    self._set_status("Monitor config loaded.", "ok")

def save_monitor_config(self):
    try:
        errors = self._validate_monitor_event_inputs()
        if errors:
            messagebox.showwarning("Validation", "\n".join(f"- {e}" for e in errors), parent=self.root)
            self._set_status("Monitor config validation failed.", "warn")
            return

        cfg     = load_json(self.config_path)
        monitor = cfg.get("monitor", {}) if isinstance(cfg.get("monitor", {}), dict) else {}

        monitor["twitch_channel"]         = self.monitor_vars["twitch_channel"].get().strip()
        monitor["owner_username"]          = self.monitor_vars["owner_username"].get().strip().lower()
        monitor["response_chance_percent"] = float(self.monitor_vars["response_chance_percent"].get().strip() or 35)
        monitor["global_cooldown_seconds"] = int(self.monitor_vars["global_cooldown_seconds"].get().strip() or 5)
        monitor["check_buffer_size"]       = int(self.monitor_vars["check_buffer_size"].get().strip() or 2048)
        monitor["ignored_bot_usernames"]   = [
            t.strip().lower()
            for t in self.monitor_vars["ignored_bot_usernames"].get().split(",")
            if t.strip()
        ]
        monitor["respond_to_owner_always"] = bool(self.monitor_vars["respond_to_owner_always"].get())
        monitor["ignore_command_messages"] = bool(self.monitor_vars["ignore_command_messages"].get())
        monitor["config_reload_seconds"]   = float(self.monitor_vars["config_reload_seconds"].get().strip() or 2)
        monitor["registry_flush_seconds"]  = int(self.monitor_vars["registry_flush_seconds"].get().strip() or 30)
        monitor["mood_reroll_enabled"]    = bool(self.monitor_vars["mood_reroll_enabled"].get())
        monitor["mood_reroll_seconds"]    = int(self.monitor_vars["mood_reroll_seconds"].get().strip() or 1200)
        monitor["irc_server"]              = self.monitor_vars["irc_server"].get().strip() or "irc.chat.twitch.tv"
        monitor["irc_port"]                = int(self.monitor_vars["irc_port"].get().strip() or 6667)

        event_cfg = cfg.get("event", {}) if isinstance(cfg.get("event", {}), dict) else {}
        if not event_cfg and isinstance(cfg.get("Event", {}), dict):
            event_cfg = cfg.get("Event", {})
        if not isinstance(event_cfg, dict):
            event_cfg = {}

        event_cfg["free_event_active"] = bool(self.event_vars["free_event_active"].get())
        event_cfg["free_event_name"] = self.event_vars["free_event_name"].get().strip() or "Free Flirts Event"
        event_cfg["free_event_max_spice"] = int(self.event_vars["free_event_max_spice"].get().strip() or 5)
        event_cfg["free_event_cooldown_seconds"] = int(
            self.event_vars["free_event_cooldown_seconds"].get().strip() or 300
        )
        event_cfg["free_event_global_limit_per_minute"] = int(
            self.event_vars["free_event_global_limit_per_minute"].get().strip() or 30
        )
        event_cfg["announcement_message"] = self.event_vars["announcement_message"].get().strip()

        cfg["monitor"]        = monitor
        cfg["twitch_channel"] = monitor["twitch_channel"]
        cfg["event"] = event_cfg
        cfg["Event"] = event_cfg
        ui_meta = cfg.get("ui_meta", {}) if isinstance(cfg.get("ui_meta", {}), dict) else {}
        ui_meta["last_changed_monitor_event_at"] = datetime.now().isoformat()
        cfg["ui_meta"] = ui_meta

        atomic_write_json(self.config_path, cfg)
        self._refresh_monitor_meta_label()
        self._mark_dirty("monitor", False)
        self.log_queue.put("[ui] monitor + event config saved")
        self._set_status("Monitor/Event config saved.", "ok")
        messagebox.showinfo("Config", "Monitor and event config saved. Running monitor will auto-reload monitor values.")
    except Exception as e:
        messagebox.showerror("Config", f"Failed to save config: {e}")
        self.log_queue.put(f"[ui] failed to save config: {e}")
        self._set_status(f"Monitor config save failed: {e}", "error")
