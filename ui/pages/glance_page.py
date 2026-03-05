import json
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk

from utils.chat_analytics import load_chat_log
from utils.helpers import resolve_existing_path
from utils.mood_engine import read_mood_state
from utils.paths import Paths

def _format_glance_timestamp(self, ts: float | None) -> str:
    if ts is None:
        return "unknown"
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "unknown"

def _format_chat_message_timestamp(self, value) -> str:
    if isinstance(value, (int, float)):
        return self._format_glance_timestamp(float(value))
    raw = str(value or "").strip()
    if not raw:
        return "unknown"
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value)

def _chat_message_epoch_seconds(self, message: dict) -> float | None:
    raw = message.get("timestamp")
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw or "").strip()
    if not text:
        return None
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(normalized).timestamp()
    except Exception:
        return None

def _is_highlight_like_message(self, message: dict) -> bool:
    text = str(message.get("message", "")).lower()
    excitement_words = [
        "lol", "lmao", "omg", "wow", "holy", "insane",
        "crazy", "wtf", "amazing", "perfect", "clutch",
    ]
    return ("!" in text) or any(word in text for word in excitement_words)

def _insert_chatlog_rows(self, tree: ttk.Treeview | None, messages: list[dict], limit: int) -> None:
    if tree is None:
        return
    self._clear_treeview(tree)
    if not messages:
        return

    for msg in reversed(messages[-limit:]):
        username = str(msg.get("username", "")).strip() or "unknown"
        text = " ".join(str(msg.get("message", "")).split())
        timestamp = self._format_chat_message_timestamp(msg.get("timestamp"))
        tree.insert("", tk.END, values=(timestamp, username, text))

def _read_text_preview(self, file_path: Path, max_chars: int = 220) -> str:
    if not file_path.exists():
        return "[no output yet]"
    try:
        raw = file_path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception as e:
        return f"[read error: {e}]"
    if not raw:
        return "[empty]"
    raw = " ".join(raw.split())
    if len(raw) <= max_chars:
        return raw
    return "..." + raw[-max_chars:]

def _read_last_jsonl_record(self, file_path: Path) -> dict | None:
    if not file_path.exists():
        return None
    try:
        with file_path.open("r", encoding="utf-8", errors="replace") as handle:
            lines = [line.strip() for line in handle if line.strip()]
    except Exception:
        return None
    if not lines:
        return None
    try:
        payload = json.loads(lines[-1])
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None

def _format_age_short(self, seconds: float) -> str:
    sec = max(0, int(seconds))
    if sec < 60:
        return f"{sec}s"
    minutes, rem = divmod(sec, 60)
    if minutes < 60:
        return f"{minutes}m {rem}s"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins}m"

def _resolve_chip_color(self, key: str, severity: str) -> str:
    chip_colors = self.ui_settings.get("chip_colors", {})
    severity_colors = self.ui_settings.get("severity_colors", {})
    if severity == "ok":
        return str(chip_colors.get(key, "#22c55e"))
    return str(severity_colors.get(severity, "#9ca3af"))

def _set_glance_cue(self, key: str, text: str, severity: str) -> None:
    value_var = self.glance_status_text_vars.get(key)
    badge = self.glance_status_badges.get(key)
    if value_var is not None:
        value_var.set(text)
    if badge is not None:
        badge.configure(bg=self._resolve_chip_color(key, severity))

def _build_glance_cue(self, parent: ttk.Frame, column: int, key: str, title: str) -> None:
    frame = ttk.Frame(parent)
    frame.grid(row=0, column=column, sticky="ew", padx=6, pady=6)
    frame.columnconfigure(1, weight=1)

    badge = tk.Label(frame, text=" ", width=2, bg=self._resolve_chip_color(key, "idle"))
    badge.grid(row=0, column=0, rowspan=2, sticky="nsw", padx=(0, 8))

    value_var = tk.StringVar(value="waiting")
    ttk.Label(frame, text=title, font=("Segoe UI Semibold", 9)).grid(row=0, column=1, sticky="w")
    ttk.Label(frame, textvariable=value_var).grid(row=1, column=1, sticky="w")

    self.glance_status_badges[key] = badge
    self.glance_status_text_vars[key] = value_var

def _build_glance_output_card(
    self,
    parent: ttk.Frame,
    row: int,
    title: str,
    key: str,
    file_path: Path,
) -> None:
    card = ttk.LabelFrame(parent, text=title)
    card.grid(row=row, column=0, sticky="ew", padx=8, pady=6)
    card.columnconfigure(0, weight=1)

    stamp_var = tk.StringVar(value="Last updated: unknown")
    self.glance_output_stamp_vars[key] = stamp_var

    ttk.Label(card, textvariable=stamp_var).grid(row=0, column=0, sticky="w", padx=8, pady=(6, 2))
    ttk.Label(card, text=str(file_path)).grid(row=0, column=1, sticky="e", padx=8, pady=(6, 2))

    output = tk.Text(card, wrap=tk.WORD, height=2, state=tk.DISABLED)
    output.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=(2, 8))
    self.glance_output_widgets[key] = output
    self._register_text_widget(output)

def _build_glance_tab(self, parent: ttk.Frame):
    container = ttk.Frame(parent)
    container.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
    container.columnconfigure(0, weight=3)
    container.columnconfigure(1, weight=2)
    container.rowconfigure(2, weight=1)

    system = ttk.LabelFrame(container, text="System")
    system.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
    system.columnconfigure(4, weight=1)

    ttk.Label(system, text="Monitor status").grid(row=0, column=0, sticky="w", padx=8, pady=8)
    ttk.Label(system, textvariable=self.monitor_status_var).grid(row=0, column=1, sticky="w", padx=8, pady=8)
    ttk.Button(system, text="Start Monitor", command=self.start_monitor).grid(row=0, column=2, padx=8, pady=8)
    ttk.Button(system, text="Stop Monitor", command=self.stop_monitor).grid(row=0, column=3, padx=8, pady=8)
    ttk.Button(system, text="Refresh", command=self._refresh_glance).grid(row=0, column=4, sticky="e", padx=8, pady=8)

    ttk.Label(system, text="Last refresh").grid(row=1, column=0, sticky="w", padx=8, pady=(0, 8))
    ttk.Label(system, textvariable=self.glance_last_refresh_var).grid(row=1, column=1, sticky="w", padx=8, pady=(0, 8))
    ttk.Label(system, text="Last routed call").grid(row=1, column=2, sticky="w", padx=8, pady=(0, 8))
    ttk.Label(system, textvariable=self.glance_last_route_var).grid(
        row=1, column=3, columnspan=2, sticky="w", padx=8, pady=(0, 8)
    )
    ttk.Label(system, textvariable=self.glance_mood_var).grid(
        row=2, column=0, columnspan=5, sticky="w", padx=8, pady=(0, 8)
    )

    cues = ttk.LabelFrame(container, text="Health Cues")
    cues.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
    for col in range(5):
        cues.columnconfigure(col, weight=1)
    self._build_glance_cue(cues, 0, "monitor", "Monitor")
    self._build_glance_cue(cues, 1, "routing", "Routing")
    self._build_glance_cue(cues, 2, "flirt", "Flirt Output")
    self._build_glance_cue(cues, 3, "tarot", "Tarot Output")
    self._build_glance_cue(cues, 4, "commands", "Command Output")

    outputs = ttk.LabelFrame(container, text="Latest Daemon Outputs")
    outputs.grid(row=2, column=0, sticky="nsew", padx=(0, 8))
    outputs.columnconfigure(0, weight=1)

    self.glance_output_paths = {
        "flirt": resolve_existing_path(Paths.FLIRT_OUTPUT),
        "tarot": resolve_existing_path(Paths.TAROT_OUTPUT),
        "commands": resolve_existing_path(Paths.COMMAND_OUTPUT),
    }
    self._build_glance_output_card(outputs, row=0, title="Flirt", key="flirt", file_path=self.glance_output_paths["flirt"])
    self._build_glance_output_card(outputs, row=1, title="Tarot", key="tarot", file_path=self.glance_output_paths["tarot"])
    self._build_glance_output_card(outputs, row=2, title="Commands", key="commands", file_path=self.glance_output_paths["commands"])

    chat = ttk.LabelFrame(container, text="Recent Chat Log")
    chat.grid(row=2, column=1, sticky="nsew")
    chat.columnconfigure(0, weight=1)
    chat.rowconfigure(0, weight=1)

    glance_chat = ttk.Treeview(
        chat,
        columns=("time", "username", "message"),
        show="headings",
        height=12,
    )
    glance_chat.heading("time", text="Time")
    glance_chat.heading("username", text="Username")
    glance_chat.heading("message", text="Message")
    glance_chat.column("time", width=150, anchor="w")
    glance_chat.column("username", width=130, anchor="w")
    glance_chat.column("message", width=520, anchor="w")
    glance_chat.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)

    glance_scroll = ttk.Scrollbar(chat, orient=tk.VERTICAL, command=glance_chat.yview)
    glance_scroll.grid(row=0, column=1, sticky="ns", padx=(0, 8), pady=8)
    glance_chat.configure(yscrollcommand=glance_scroll.set)
    self.glance_chatlog_tree = glance_chat

    self._refresh_glance()

def _refresh_glance(self):
    now = datetime.now().timestamp()
    monitor_running = bool(
        "monitor" in self.processes
        and self.processes["monitor"].poll() is None
        and self.monitor_status_var.get().lower() == "running"
    )
    if monitor_running:
        self._set_glance_cue("monitor", "running", "ok")
    else:
        self._set_glance_cue("monitor", "stopped", "bad")

    routed = self._read_last_jsonl_record(resolve_existing_path(Paths.ROUTING_LOG))
    if routed:
        keyword = str(routed.get("keyword", "unknown"))
        username = str(routed.get("username", "unknown"))
        ts = routed.get("timestamp")
        ts_value = float(ts) if isinstance(ts, (int, float)) else None
        ts_text = self._format_glance_timestamp(ts_value)
        self.glance_last_route_var.set(f"{keyword} by @{username} at {ts_text}")
        if ts_value is not None:
            route_age = now - ts_value
            if route_age <= 60:
                self._set_glance_cue("routing", f"fresh ({self._format_age_short(route_age)})", "ok")
            elif route_age <= 300:
                self._set_glance_cue("routing", f"aging ({self._format_age_short(route_age)})", "warn")
            else:
                self._set_glance_cue("routing", f"stale ({self._format_age_short(route_age)})", "bad")
        else:
            self._set_glance_cue("routing", "unknown timestamp", "warn")
    else:
        self.glance_last_route_var.set("No routed calls yet.")
        self._set_glance_cue("routing", "no activity yet", "warn")

    mood_state = read_mood_state(Paths.MOOD_STATE)
    mood_name = str(mood_state.get("active_mood", "neutral")).strip() or "neutral"
    mood_source = str(mood_state.get("selected_by", "fallback")).strip() or "fallback"
    locked_mood = str(mood_state.get("locked_mood", "")).strip()
    mood_suffix = " (locked)" if locked_mood else ""
    self.glance_mood_var.set(f"Current mood: {mood_name}{mood_suffix} [{mood_source}]")
    self._refresh_monitor_mood_state()

    for key, file_path in self.glance_output_paths.items():
        preview = self._read_text_preview(file_path)
        widget = self.glance_output_widgets.get(key)
        stamp_var = self.glance_output_stamp_vars.get(key)
        if widget is not None:
            self._set_text_widget_content(widget, preview)
        if stamp_var is not None:
            stamp = file_path.stat().st_mtime if file_path.exists() else None
            stamp_var.set(f"Last updated: {self._format_glance_timestamp(stamp)}")
        if not file_path.exists():
            self._set_glance_cue(key, "missing", "bad")
            continue
        age = now - file_path.stat().st_mtime
        if age <= 60:
            self._set_glance_cue(key, f"fresh ({self._format_age_short(age)})", "ok")
        elif age <= 300:
            self._set_glance_cue(key, f"aging ({self._format_age_short(age)})", "warn")
        else:
            self._set_glance_cue(key, f"stale ({self._format_age_short(age)})", "bad")

    chat_messages = load_chat_log(str(resolve_existing_path(Paths.CHAT_LOG)))
    self._insert_chatlog_rows(self.glance_chatlog_tree, chat_messages, limit=30)

    self.glance_last_refresh_var.set(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    if self._glance_refresh_after_id is not None:
        try:
            self.root.after_cancel(self._glance_refresh_after_id)
        except Exception:
            pass
    self._glance_refresh_after_id = self.root.after(5000, self._refresh_glance)
