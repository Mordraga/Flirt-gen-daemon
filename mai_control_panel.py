import queue
import json
import re
import shutil
import os
import runpy
import shlex
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from pathlib import Path
from tkinter import colorchooser, messagebox, simpledialog, ttk

from utils.chat_analytics import analyze_activity, find_highlights, load_chat_log
from utils.cooldown_messages import load_tool_cooldown_map, save_tool_cooldown_map
from utils.helpers import atomic_write_json, load_json, resolve_existing_path
from utils.mood_engine import (
    load_moods,
    load_moods_from_payload,
    lock_mood,
    manual_reroll,
    read_mood_state,
    set_session_inactive,
    unlock_mood,
)
from utils.paths import Paths

try:
    import pystray
    from PIL import Image, ImageDraw
except Exception:
    pystray = None
    Image = None
    ImageDraw = None


REPO_ROOT = Path(__file__).parent


COLORBLIND_PRESETS: dict[str, dict] = {
    "standard": {
        "chip_colors": {
            "monitor": "#22c55e",
            "routing": "#0ea5e9",
            "flirt": "#f97316",
            "tarot": "#a855f7",
            "commands": "#14b8a6",
        },
        "severity_colors": {
            "warn": "#f59e0b",
            "bad": "#ef4444",
            "idle": "#9ca3af",
        },
    },
    "protanomaly": {
        "chip_colors": {
            "monitor": "#0072b2",
            "routing": "#56b4e9",
            "flirt": "#e69f00",
            "tarot": "#cc79a7",
            "commands": "#009e73",
        },
        "severity_colors": {
            "warn": "#f0e442",
            "bad": "#d81b60",
            "idle": "#9aa0a6",
        },
    },
    "deutranomaly": {
        "chip_colors": {
            "monitor": "#1f77b4",
            "routing": "#17becf",
            "flirt": "#ff7f0e",
            "tarot": "#9467bd",
            "commands": "#bcbd22",
        },
        "severity_colors": {
            "warn": "#ffd166",
            "bad": "#ef476f",
            "idle": "#8d99ae",
        },
    },
    "tritanomaly": {
        "chip_colors": {
            "monitor": "#2ca02c",
            "routing": "#d62728",
            "flirt": "#8c564b",
            "tarot": "#e377c2",
            "commands": "#7f7f7f",
        },
        "severity_colors": {
            "warn": "#ff9f1c",
            "bad": "#c1121f",
            "idle": "#adb5bd",
        },
    },
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _scrolled_listbox(parent) -> tuple[tk.Listbox, ttk.Scrollbar]:
    """Return (listbox, scrollbar) packed into parent."""
    sb = ttk.Scrollbar(parent, orient=tk.VERTICAL)
    lb = tk.Listbox(
        parent,
        yscrollcommand=sb.set,
        selectmode=tk.SINGLE,
        width=60,
        font=("Segoe UI", 10),
        activestyle="none",
        borderwidth=0,
        highlightthickness=1,
        relief=tk.FLAT,
    )
    sb.config(command=lb.yview)
    lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    sb.pack(side=tk.RIGHT, fill=tk.Y)
    return lb, sb


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------

class MaiControlPanel:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Mai Control Panel")
        self.window_min_width = 980
        self.window_min_height = 680
        self.root.geometry("1100x780")
        self.root.minsize(self.window_min_width, self.window_min_height)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.processes: dict[str, subprocess.Popen] = {}

        self.tray_icon = None
        self.tray_thread = None

        self.config_path = REPO_ROOT / "jsons" / "configs" / "config.json"
        self.ui_settings_path = REPO_ROOT / "jsons" / "configs" / "ui_settings.json"
        self.ui_profiles_path = REPO_ROOT / "jsons" / "configs" / "ui_profiles.json"
        self.ui_state_path = REPO_ROOT / "jsons" / "configs" / "ui_state.json"
        self._themed_text_widgets: list[tk.Text] = []
        self._tab_scroll_canvases: list[tk.Canvas] = []
        self.ui_settings = self._load_ui_settings()
        self.ui_profiles = self._load_ui_profiles(self.ui_settings)
        active_profile = str(self.ui_profiles.get("active_profile", "default"))
        self.ui_settings = dict(self.ui_profiles.get("profiles", {}).get(active_profile, self.ui_settings))
        self.ui_state = self._load_ui_state()
        self.theme_palette = self._get_theme_palette()
        self.main_notebook: ttk.Notebook | None = None
        self._main_tab_containers: dict[str, ttk.Frame] = {}
        self._main_tab_content_frames: dict[str, ttk.Frame] = {}
        self._main_tab_ids: list[str] = []
        self._main_tab_keys: list[str] = []
        self._main_tab_labels: dict[str, str] = {}
        self._previous_tab_index: int = 0
        self._suspend_tab_change_guard = False
        self._section_expansion_state: dict[str, bool] = {}
        self._dirty_flags: dict[str, bool] = {}
        self.status_var = tk.StringVar(value="Ready")
        self.status_message_kind = "info"
        self._status_label: ttk.Label | None = None

        self.monitor_status_var = tk.StringVar(value="Stopped")
        self.script_status_var = tk.StringVar(value="Idle")

        self.monitor_vars: dict[str, tk.Variable] = {}
        self.event_vars: dict[str, tk.Variable] = {}
        self.monitor_last_changed_var = tk.StringVar(value="Last changed by UI: unknown")
        self.monitor_mood_name_var = tk.StringVar(value="neutral")
        self.monitor_mood_source_var = tk.StringVar(value="fallback")
        self.monitor_mood_next_var = tk.StringVar(value="n/a")
        self.monitor_mood_lock_var = tk.StringVar(value="")
        self.monitor_mood_status_var = tk.StringVar(value="Mood: neutral")
        self.monitor_mood_combo: ttk.Combobox | None = None
        self.monitor_mood_reroll_button: ttk.Button | None = None
        self.owner_last_changed_var = tk.StringVar(value="Last changed by UI: unknown")
        self.glance_last_refresh_var = tk.StringVar(value="Never")
        self.glance_last_route_var = tk.StringVar(value="No routed calls yet.")
        self.glance_mood_var = tk.StringVar(value="Current mood: neutral")
        self.glance_output_stamp_vars: dict[str, tk.StringVar] = {}
        self.glance_output_widgets: dict[str, tk.Text] = {}
        self.glance_status_text_vars: dict[str, tk.StringVar] = {}
        self.glance_status_badges: dict[str, tk.Label] = {}
        self.glance_output_paths: dict[str, Path] = {}
        self._glance_refresh_after_id: str | None = None
        self.settings_dark_mode_var: tk.BooleanVar | None = None
        self.settings_colorblind_mode_var: tk.StringVar | None = None
        self.settings_font_scale_var: tk.StringVar | None = None
        self.settings_density_var: tk.StringVar | None = None
        self.settings_ui_profile_var: tk.StringVar | None = None
        self.settings_profile_combo: ttk.Combobox | None = None
        self.settings_chip_color_vars: dict[str, tk.StringVar] = {}
        self.settings_severity_color_vars: dict[str, tk.StringVar] = {}
        self.settings_snapshot_listbox: tk.Listbox | None = None
        self.settings_snapshot_name_to_path: dict[str, Path] = {}
        self.settings_full_backup_listbox: tk.Listbox | None = None
        self.settings_full_backup_name_to_path: dict[str, Path] = {}
        self.settings_backup_root_var = tk.StringVar(value="")
        self.settings_section_var: tk.StringVar | None = None
        self.settings_section_backup_listbox: tk.Listbox | None = None
        self.settings_section_backup_name_to_path: dict[str, Path] = {}
        self.analytics_total_var = tk.StringVar(value="-")
        self.analytics_unique_var = tk.StringVar(value="-")
        self.analytics_first_var = tk.StringVar(value="-")
        self.analytics_last_var = tk.StringVar(value="-")
        self.analytics_log_path_var = tk.StringVar(value=str(resolve_existing_path(Paths.CHAT_LOG)))
        self.analytics_username_filter_var = tk.StringVar(value="")
        self.analytics_keyword_filter_var = tk.StringVar(value="")
        self.analytics_time_window_var = tk.StringVar(value="All")
        self.analytics_highlights_only_var = tk.BooleanVar(value=False)
        self.analytics_users_tree: ttk.Treeview | None = None
        self.analytics_highlights_tree: ttk.Treeview | None = None
        self.analytics_chatlog_tree: ttk.Treeview | None = None
        self.glance_chatlog_tree: ttk.Treeview | None = None
        self.analytics_chat_messages_cache: list[dict] = []
        self.analytics_username_filter_entry: ttk.Entry | None = None
        self.log_text: tk.Text | None = None
        self.log_pause_var = tk.BooleanVar(value=False)
        self.log_filter_var = tk.StringVar(value="All")
        self.log_search_var = tk.StringVar(value="")
        self.log_buffer: list[str] = []
        self.log_search_entry: ttk.Entry | None = None
        self._owner_profile_editor_vars: dict[str, object] = {}
        self._owner_profile_editor_lore_widget: tk.Text | None = None

        self.script_var = tk.StringVar()
        self.script_args_var = tk.StringVar()
        self._drag_ghost: tk.Toplevel | None = None
        self._drag_ghost_label: ttk.Label | None = None

        # Quick-test vars
        self.qt_keyword_var = tk.StringVar(value="flirt")
        self.qt_username_var = tk.StringVar(value="TestUser")
        # flirt fields
        self.qt_theme_var = tk.StringVar()
        self.qt_tone_var = tk.StringVar()
        self.qt_spice_var = tk.IntVar(value=5)
        # tarot fields
        self.qt_question_var = tk.StringVar()
        self.qt_spread_var = tk.StringVar(value="3-card")
        # commands fields
        self.qt_command_input_var = tk.StringVar(value="!social")

        self._apply_ui_style()
        self._build_ui()
        self._load_monitor_config_into_form()

        self.root.after(150, self._drain_log_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close_request)
        self.root.bind("<Unmap>", self._on_window_minimize)

    # -----------------------------------------------------------------------
    # UI layout
    # -----------------------------------------------------------------------

    @staticmethod
    def _default_ui_settings() -> dict:
        preset = COLORBLIND_PRESETS["standard"]
        return {
            "dark_mode": False,
            "colorblind_mode": "standard",
            "chip_colors": dict(preset["chip_colors"]),
            "severity_colors": dict(preset["severity_colors"]),
            "font_scale": "100%",
            "density": "comfortable",
        }

    @staticmethod
    def _is_hex_color(value: str) -> bool:
        raw = str(value or "").strip()
        if len(raw) != 7 or not raw.startswith("#"):
            return False
        try:
            int(raw[1:], 16)
            return True
        except ValueError:
            return False

    def _merge_ui_settings(self, payload: dict | None) -> dict:
        defaults = self._default_ui_settings()
        if not isinstance(payload, dict):
            return defaults

        mode = str(payload.get("colorblind_mode", "standard")).strip().lower()
        if mode not in COLORBLIND_PRESETS:
            mode = "standard"
        preset = COLORBLIND_PRESETS[mode]

        dark_mode = bool(payload.get("dark_mode", defaults["dark_mode"]))
        font_scale = str(payload.get("font_scale", defaults["font_scale"])).strip()
        if font_scale not in {"90%", "100%", "115%"}:
            font_scale = "100%"
        density = str(payload.get("density", defaults["density"])).strip().lower()
        if density not in {"compact", "comfortable"}:
            density = "comfortable"

        chip_colors = dict(preset["chip_colors"])
        incoming_chip = payload.get("chip_colors", {})
        if isinstance(incoming_chip, dict):
            for key in chip_colors.keys():
                value = str(incoming_chip.get(key, chip_colors[key])).strip().lower()
                if self._is_hex_color(value):
                    chip_colors[key] = value

        severity_colors = dict(preset["severity_colors"])
        incoming_severity = payload.get("severity_colors", {})
        if isinstance(incoming_severity, dict):
            for key in severity_colors.keys():
                value = str(incoming_severity.get(key, severity_colors[key])).strip().lower()
                if self._is_hex_color(value):
                    severity_colors[key] = value

        return {
            "dark_mode": dark_mode,
            "colorblind_mode": mode,
            "chip_colors": chip_colors,
            "severity_colors": severity_colors,
            "font_scale": font_scale,
            "density": density,
        }

    def _load_ui_settings(self) -> dict:
        payload = load_json(self.ui_settings_path, default={})
        return self._merge_ui_settings(payload)

    def _save_ui_settings(self) -> None:
        atomic_write_json(self.ui_settings_path, self.ui_settings)

    def _default_ui_profiles(self) -> dict:
        return {
            "active_profile": "default",
            "profiles": {
                "default": self._default_ui_settings(),
            },
        }

    def _merge_ui_profiles(self, payload: dict | None) -> dict:
        default_payload = self._default_ui_profiles()
        if not isinstance(payload, dict):
            return default_payload

        incoming_profiles = payload.get("profiles", {})
        merged_profiles: dict[str, dict] = {}
        if isinstance(incoming_profiles, dict):
            for raw_name, raw_profile in incoming_profiles.items():
                name = str(raw_name or "").strip()
                if not name:
                    continue
                merged_profiles[name] = self._merge_ui_settings(raw_profile if isinstance(raw_profile, dict) else {})

        if not merged_profiles:
            merged_profiles = dict(default_payload["profiles"])

        active_profile = str(payload.get("active_profile", "")).strip()
        if active_profile not in merged_profiles:
            active_profile = next(iter(merged_profiles.keys()))

        return {
            "active_profile": active_profile,
            "profiles": merged_profiles,
        }

    def _load_ui_profiles(self, legacy_settings: dict | None = None) -> dict:
        payload = load_json(self.ui_profiles_path, default={})
        merged = self._merge_ui_profiles(payload)

        # One-time migration: seed the default profile from legacy ui_settings.json.
        if not isinstance(payload, dict) or "profiles" not in payload:
            merged["profiles"]["default"] = self._merge_ui_settings(legacy_settings if isinstance(legacy_settings, dict) else {})
            merged["active_profile"] = "default"
            atomic_write_json(self.ui_profiles_path, merged)
        return merged

    def _save_ui_profiles(self) -> None:
        atomic_write_json(self.ui_profiles_path, self.ui_profiles)

    @staticmethod
    def _default_ui_state() -> dict:
        return {
            "window_geometry": "",
            "active_tab_key": "glance",
            "collapsed_sections": {},
            "tree_open_state": {},
            "filters": {
                "analytics_log_path": Paths.CHAT_LOG,
                "analytics_username": "",
                "analytics_keyword": "",
                "analytics_time_window": "All",
                "analytics_highlights_only": False,
                "log_search": "",
                "log_filter": "All",
            },
            "onboarding_seen": False,
        }

    def _merge_ui_state(self, payload: dict | None) -> dict:
        state = self._default_ui_state()
        if not isinstance(payload, dict):
            return state

        geometry = str(payload.get("window_geometry", "")).strip()
        if geometry:
            state["window_geometry"] = geometry

        tab_key = str(payload.get("active_tab_key", "glance")).strip()
        state["active_tab_key"] = tab_key or "glance"

        collapsed = payload.get("collapsed_sections", {})
        if isinstance(collapsed, dict):
            state["collapsed_sections"] = {str(k): bool(v) for k, v in collapsed.items()}

        tree_open_state = payload.get("tree_open_state", {})
        if isinstance(tree_open_state, dict):
            normalized: dict[str, dict[str, bool]] = {}
            for scope_key, raw_map in tree_open_state.items():
                if not isinstance(raw_map, dict):
                    continue
                normalized[str(scope_key)] = {str(group): bool(is_open) for group, is_open in raw_map.items()}
            state["tree_open_state"] = normalized

        filters = payload.get("filters", {})
        if isinstance(filters, dict):
            target = state["filters"]
            for key in target.keys():
                if key in filters:
                    target[key] = filters[key]

        state["onboarding_seen"] = bool(payload.get("onboarding_seen", False))
        return state

    def _load_ui_state(self) -> dict:
        payload = load_json(self.ui_state_path, default={})
        return self._merge_ui_state(payload)

    def _save_ui_state(self) -> None:
        try:
            self.ui_state["window_geometry"] = self.root.winfo_geometry()
        except Exception:
            pass
        if self.main_notebook is not None:
            try:
                idx = int(self.main_notebook.index("current"))
                if 0 <= idx < len(self._main_tab_keys):
                    self.ui_state["active_tab_key"] = self._main_tab_keys[idx]
            except Exception:
                pass
        filters = self.ui_state.setdefault("filters", {})
        filters["analytics_log_path"] = str(self.analytics_log_path_var.get() or "")
        filters["analytics_username"] = str(self.analytics_username_filter_var.get() or "")
        filters["analytics_keyword"] = str(self.analytics_keyword_filter_var.get() or "")
        filters["analytics_time_window"] = str(self.analytics_time_window_var.get() or "All")
        filters["analytics_highlights_only"] = bool(self.analytics_highlights_only_var.get())
        filters["log_search"] = str(self.log_search_var.get() or "")
        filters["log_filter"] = str(self.log_filter_var.get() or "All")
        atomic_write_json(self.ui_state_path, self.ui_state)

    def _set_status(self, message: str, kind: str = "info") -> None:
        self.status_var.set(str(message))
        self.status_message_kind = kind
        if self._status_label is None:
            return
        colors = {
            "info": self.theme_palette["text_subtle"],
            "ok": self.ui_settings.get("chip_colors", {}).get("monitor", self.theme_palette["text_subtle"]),
            "warn": self.ui_settings.get("severity_colors", {}).get("warn", self.theme_palette["text_subtle"]),
            "error": self.ui_settings.get("severity_colors", {}).get("bad", self.theme_palette["text_subtle"]),
        }
        self._status_label.configure(foreground=colors.get(kind, self.theme_palette["text_subtle"]))

    def _mark_dirty(self, section: str, dirty: bool = True) -> None:
        self._dirty_flags[section] = dirty
        self._refresh_tab_dirty_indicators()

    def _has_unsaved_changes(self) -> bool:
        return any(bool(value) for value in self._dirty_flags.values())

    def _refresh_tab_dirty_indicators(self) -> None:
        if self.main_notebook is None:
            return
        dirty_map = {
            "monitor": bool(self._dirty_flags.get("monitor")),
            "data": bool(self._dirty_flags.get("data")),
            "settings": bool(self._dirty_flags.get("settings")),
            "scripts": False,
            "glance": False,
            "analytics": False,
        }
        for index, tab_key in enumerate(self._main_tab_keys):
            base = self._main_tab_labels.get(tab_key, tab_key.title())
            if dirty_map.get(tab_key):
                self.main_notebook.tab(index, text=f"{base} *")
            else:
                self.main_notebook.tab(index, text=base)

    def _confirm_discard_unsaved(self, context: str) -> bool:
        if not self._has_unsaved_changes():
            return True
        result = messagebox.askyesno(
            "Unsaved Changes",
            f"There are unsaved changes. Discard them and continue to {context}?",
            parent=self.root,
        )
        return bool(result)

    def _bind_dirty_var(self, section: str, variable: tk.Variable) -> None:
        variable.trace_add("write", lambda *_args: self._mark_dirty(section, True))

    def _get_theme_palette(self) -> dict[str, str]:
        dark_mode = bool(self.ui_settings.get("dark_mode", False))
        if dark_mode:
            return {
                "root_bg": "#111827",
                "surface": "#1f2937",
                "surface_alt": "#111827",
                "text": "#e5e7eb",
                "text_subtle": "#9ca3af",
                "field_bg": "#0f172a",
                "field_text": "#e5e7eb",
                "tab_selected": "#1f2937",
                "tab_active": "#273449",
            }
        return {
            "root_bg": "#f3f5f8",
            "surface": "#f3f5f8",
            "surface_alt": "#e5e7eb",
            "text": "#1f2937",
            "text_subtle": "#6b7280",
            "field_bg": "#ffffff",
            "field_text": "#111827",
            "tab_selected": "#ffffff",
            "tab_active": "#f9fafb",
        }

    def _register_text_widget(self, widget: tk.Text) -> None:
        self._themed_text_widgets.append(widget)
        self._apply_text_widget_theme()

    def _apply_text_widget_theme(self) -> None:
        for widget in list(self._themed_text_widgets):
            try:
                widget.configure(
                    bg=self.theme_palette["field_bg"],
                    fg=self.theme_palette["field_text"],
                    insertbackground=self.theme_palette["field_text"],
                )
            except Exception:
                continue
        for canvas in list(self._tab_scroll_canvases):
            try:
                canvas.configure(background=self.theme_palette["surface"])
            except Exception:
                continue

    def _create_scrollable_tab_container(self, notebook: ttk.Notebook) -> tuple[ttk.Frame, ttk.Frame]:
        outer = ttk.Frame(notebook)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        canvas = tk.Canvas(
            outer,
            highlightthickness=0,
            borderwidth=0,
            background=self.theme_palette["surface"],
        )
        self._tab_scroll_canvases.append(canvas)
        scrollbar = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        content = ttk.Frame(canvas)
        content.columnconfigure(0, weight=1)
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")

        def _on_content_configure(_event=None):
            try:
                canvas.configure(scrollregion=canvas.bbox("all"))
            except Exception:
                pass

        def _on_canvas_configure(event):
            try:
                canvas.itemconfigure(window_id, width=event.width)
            except Exception:
                pass

        def _on_mouse_wheel(event):
            try:
                if event.delta != 0:
                    canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
                return "break"
            except Exception:
                return None

        def _on_button4(_event):
            try:
                canvas.yview_scroll(-3, "units")
            except Exception:
                pass
            return "break"

        def _on_button5(_event):
            try:
                canvas.yview_scroll(3, "units")
            except Exception:
                pass
            return "break"

        content.bind("<Configure>", _on_content_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        for widget in (canvas, content):
            widget.bind("<MouseWheel>", _on_mouse_wheel, add="+")
            widget.bind("<Button-4>", _on_button4, add="+")
            widget.bind("<Button-5>", _on_button5, add="+")
        return outer, content

    def _fit_window_to_active_tab(self) -> None:
        if self.main_notebook is None:
            return
        try:
            if self.root.state() in {"zoomed", "iconic"}:
                return
        except Exception:
            pass

        try:
            idx = int(self.main_notebook.index("current"))
        except Exception:
            return
        if idx < 0 or idx >= len(self._main_tab_keys):
            return
        key = self._main_tab_keys[idx]
        outer = self._main_tab_containers.get(key)
        content = self._main_tab_content_frames.get(key)
        if outer is None or content is None:
            return

        try:
            self.root.update_idletasks()
            chrome_w = max(0, self.root.winfo_width() - outer.winfo_width())
            chrome_h = max(0, self.root.winfo_height() - outer.winfo_height())
            desired_w = int(content.winfo_reqwidth() + chrome_w + 24)
            desired_h = int(content.winfo_reqheight() + chrome_h + 24)
            max_w = max(self.window_min_width, self.root.winfo_screenwidth() - 80)
            max_h = max(self.window_min_height, self.root.winfo_screenheight() - 80)
            target_w = min(max(desired_w, self.window_min_width), max_w)
            target_h = min(max(desired_h, self.window_min_height), max_h)
            x = self.root.winfo_x()
            y = self.root.winfo_y()
            self.root.geometry(f"{target_w}x{target_h}+{x}+{y}")
        except Exception:
            return

    def _apply_ui_style(self):
        self.theme_palette = self._get_theme_palette()
        scale_map = {"90%": 0.9, "100%": 1.0, "115%": 1.15}
        scale = scale_map.get(str(self.ui_settings.get("font_scale", "100%")), 1.0)
        density = str(self.ui_settings.get("density", "comfortable")).lower()
        rowheight = 24 if density == "compact" else 30
        pad_y = 4 if density == "compact" else 6
        base_font = max(9, int(round(10 * scale)))
        heading_font = max(10, int(round(10 * scale)))
        combo_font = max(10, int(round(11 * scale)))
        # Configure Tk named fonts directly to avoid Tcl parsing issues with
        # family names that contain spaces (e.g. "Segoe UI").
        try:
            tkfont.nametofont("TkDefaultFont").configure(family="Segoe UI", size=base_font)
            tkfont.nametofont("TkTextFont").configure(family="Segoe UI", size=base_font)
            tkfont.nametofont("TkMenuFont").configure(family="Segoe UI", size=base_font)
            tkfont.nametofont("TkHeadingFont").configure(family="Segoe UI", size=heading_font, weight="bold")
        except Exception:
            pass
        # Ensure combobox dropdown list rows have enough line-height so
        # descenders (g, p, q, y) are not clipped.
        self.root.option_add("*TCombobox*Listbox.font", f"{{Segoe UI}} {combo_font}")
        self.root.configure(background=self.theme_palette["root_bg"])

        style = ttk.Style()
        for theme_name in ("clam", "vista", "xpnative", "default"):
            if theme_name in style.theme_names():
                style.theme_use(theme_name)
                break

        style.configure(".", background=self.theme_palette["surface"], foreground=self.theme_palette["text"])
        style.configure("TFrame", background=self.theme_palette["surface"])
        style.configure("TLabel", background=self.theme_palette["surface"], foreground=self.theme_palette["text"])
        style.configure("TLabelframe", background=self.theme_palette["surface"], borderwidth=1, relief="solid")
        style.configure(
            "TLabelframe.Label",
            background=self.theme_palette["surface"],
            foreground=self.theme_palette["text"],
            font=("Segoe UI Semibold", heading_font),
        )
        style.configure("TNotebook", background=self.theme_palette["surface_alt"], tabmargins=(6, 6, 6, 0))
        style.configure("TNotebook.Tab", padding=(12, pad_y), font=("Segoe UI Semibold", heading_font))
        style.map(
            "TNotebook.Tab",
            background=[("selected", self.theme_palette["tab_selected"]), ("active", self.theme_palette["tab_active"])],
            foreground=[("selected", self.theme_palette["text"]), ("active", self.theme_palette["text"])],
        )
        style.configure("TButton", padding=(10, pad_y), font=("Segoe UI Semibold", base_font))
        style.configure("TEntry", fieldbackground=self.theme_palette["field_bg"], foreground=self.theme_palette["field_text"])
        style.configure(
            "TCombobox",
            fieldbackground=self.theme_palette["field_bg"],
            foreground=self.theme_palette["field_text"],
            padding=(8, 4, 8, 4),
            font=("Segoe UI", combo_font),
        )
        style.configure(
            "Treeview",
            rowheight=rowheight,
            font=("Segoe UI", combo_font),
            background=self.theme_palette["field_bg"],
            fieldbackground=self.theme_palette["field_bg"],
            foreground=self.theme_palette["field_text"],
        )
        style.configure(
            "Treeview.Heading",
            font=("Segoe UI Semibold", heading_font),
            background=self.theme_palette["surface_alt"],
            foreground=self.theme_palette["text"],
        )
        self._apply_text_widget_theme()
        self._set_status(self.status_var.get(), self.status_message_kind)

    def _build_ui(self):
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True)
        self.main_notebook = notebook

        glance_outer, glance_tab = self._create_scrollable_tab_container(notebook)
        monitor_outer, monitor_tab = self._create_scrollable_tab_container(notebook)
        scripts_outer, scripts_tab = self._create_scrollable_tab_container(notebook)
        analytics_outer, analytics_tab = self._create_scrollable_tab_container(notebook)
        data_outer, data_tab = self._create_scrollable_tab_container(notebook)
        settings_outer, settings_tab = self._create_scrollable_tab_container(notebook)

        tabs = [
            ("glance", "At a Glance", glance_outer),
            ("monitor", "Monitor", monitor_outer),
            ("scripts", "Scripts", scripts_outer),
            ("analytics", "Chat Analytics", analytics_outer),
            ("data", "Data Editor", data_outer),
            ("settings", "Settings", settings_outer),
        ]
        for key, label, frame in tabs:
            notebook.add(frame, text=label)
            self._main_tab_keys.append(key)
            self._main_tab_labels[key] = label
        self._main_tab_containers = {
            "glance": glance_outer,
            "monitor": monitor_outer,
            "scripts": scripts_outer,
            "analytics": analytics_outer,
            "data": data_outer,
            "settings": settings_outer,
        }
        self._main_tab_content_frames = {
            "glance": glance_tab,
            "monitor": monitor_tab,
            "scripts": scripts_tab,
            "analytics": analytics_tab,
            "data": data_tab,
            "settings": settings_tab,
        }

        self._build_glance_tab(glance_tab)
        self._build_monitor_tab(monitor_tab)
        self._build_scripts_tab(scripts_tab)
        self._build_chat_analytics_tab(analytics_tab)
        self._build_data_editor_tab(data_tab)
        self._build_settings_tab(settings_tab)

        self._main_tab_ids = list(notebook.tabs())
        self._bind_global_shortcuts()
        notebook.bind("<<NotebookTabChanged>>", self._on_main_tab_changed)

        status_bar = ttk.Frame(self.root)
        status_bar.pack(fill=tk.X, padx=8, pady=(0, 8))
        self._status_label = ttk.Label(status_bar, textvariable=self.status_var, anchor="w")
        self._status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(status_bar, text="Help", width=8, command=self._show_help_drawer).pack(side=tk.RIGHT)

        self._restore_ui_state()
        self._refresh_tab_dirty_indicators()
        self.root.after(120, self._fit_window_to_active_tab)

    def _show_help_drawer(self):
        messagebox.showinfo(
            "Quick Help",
            "Where to go:\n"
            "- At a Glance: monitor state + latest outputs + recent chat.\n"
            "- Monitor: runtime monitor/event config.\n"
            "- Scripts: quick command tests + runtime logs.\n"
            "- Chat Analytics: activity, highlights, filterable chat log.\n"
            "- Data Editor: tones/themes/commands/users/owner profile.\n"
            "- Settings: dark mode, color profiles, chip colors, backups/profiles.",
            parent=self.root,
        )
        self.ui_state["onboarding_seen"] = True
        self._save_ui_state()

    def _restore_ui_state(self) -> None:
        geom = str(self.ui_state.get("window_geometry", "")).strip()
        if geom:
            try:
                self.root.geometry(geom)
            except Exception:
                pass

        filters = self.ui_state.get("filters", {})
        if isinstance(filters, dict):
            self.analytics_log_path_var.set(str(filters.get("analytics_log_path", self.analytics_log_path_var.get())))
            self.analytics_username_filter_var.set(str(filters.get("analytics_username", "")))
            self.analytics_keyword_filter_var.set(str(filters.get("analytics_keyword", "")))
            self.analytics_time_window_var.set(str(filters.get("analytics_time_window", "All")))
            self.analytics_highlights_only_var.set(bool(filters.get("analytics_highlights_only", False)))
            self.log_search_var.set(str(filters.get("log_search", "")))
            self.log_filter_var.set(str(filters.get("log_filter", "All")))
            self._rerender_logs()
            self._refresh_chat_analytics()

        if self.main_notebook is not None:
            active_key = str(self.ui_state.get("active_tab_key", "glance"))
            if active_key in self._main_tab_keys:
                idx = self._main_tab_keys.index(active_key)
                self._suspend_tab_change_guard = True
                self.main_notebook.select(idx)
                self._previous_tab_index = idx
                self._suspend_tab_change_guard = False

        if not bool(self.ui_state.get("onboarding_seen", False)):
            self.root.after(600, self._show_help_drawer)

    def _on_main_tab_changed(self, _event=None):
        if self.main_notebook is None or self._suspend_tab_change_guard:
            return
        current_idx = self.main_notebook.index("current")
        if current_idx == self._previous_tab_index:
            return

        previous_key = self._main_tab_keys[self._previous_tab_index] if self._previous_tab_index < len(self._main_tab_keys) else ""
        guarded_tabs = {"monitor", "data", "settings"}
        if previous_key in guarded_tabs and self._dirty_flags.get(previous_key):
            if not self._confirm_discard_unsaved("switching tabs"):
                self._suspend_tab_change_guard = True
                self.main_notebook.select(self._previous_tab_index)
                self._suspend_tab_change_guard = False
                return
            self._mark_dirty(previous_key, False)

        self._previous_tab_index = current_idx
        if current_idx < len(self._main_tab_keys):
            self.ui_state["active_tab_key"] = self._main_tab_keys[current_idx]
            self._save_ui_state()
        self.root.after_idle(self._fit_window_to_active_tab)

    def _bind_global_shortcuts(self):
        self.root.bind_all("<Control-s>", self._on_shortcut_save, add="+")
        self.root.bind_all("<Control-r>", self._on_shortcut_refresh, add="+")
        self.root.bind_all("<Control-f>", self._on_shortcut_focus_filter, add="+")

    def _on_shortcut_save(self, _event=None):
        current_key = self._main_tab_keys[self._previous_tab_index] if self._previous_tab_index < len(self._main_tab_keys) else ""
        if current_key == "monitor":
            self.save_monitor_config()
            return "break"
        if current_key == "settings":
            self._apply_ui_settings_from_controls(save=True)
            return "break"
        if current_key == "data":
            self._set_status("Use per-editor Save buttons in Data Editor.", "warn")
            return "break"
        self._set_status("Nothing to save on this tab.", "info")
        return "break"

    def _on_shortcut_refresh(self, _event=None):
        current_key = self._main_tab_keys[self._previous_tab_index] if self._previous_tab_index < len(self._main_tab_keys) else ""
        if current_key == "glance":
            self._refresh_glance()
        elif current_key == "analytics":
            self._refresh_chat_analytics()
        elif current_key == "monitor":
            self._load_monitor_config_into_form()
        else:
            self._set_status("Refresh not available for this tab.", "info")
        return "break"

    def _on_shortcut_focus_filter(self, _event=None):
        current_key = self._main_tab_keys[self._previous_tab_index] if self._previous_tab_index < len(self._main_tab_keys) else ""
        if current_key == "analytics" and self.analytics_username_filter_entry is not None:
            self.analytics_username_filter_entry.focus_set()
            return "break"
        if current_key == "scripts" and self.log_search_entry is not None:
            self.log_search_entry.focus_set()
            return "break"
        self._set_status("No filter input on this tab.", "info")
        return "break"

    def _editor_meta_path(self) -> Path:
        return REPO_ROOT / "jsons" / "data" / "editor_meta.json"

    def _load_editor_meta(self) -> dict:
        payload = load_json(self._editor_meta_path(), default={})
        return payload if isinstance(payload, dict) else {}

    def _save_editor_meta(self, payload: dict) -> None:
        atomic_write_json(self._editor_meta_path(), payload)

    def _load_command_access(self) -> dict:
        payload = load_json(Paths.COMMAND_ACCESS, default={})
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("normal_users", [])
        payload.setdefault("vip_users", [])
        payload.setdefault("moderator_users", [])
        return payload

    def _save_command_access(self, payload: dict) -> None:
        atomic_write_json(Paths.COMMAND_ACCESS, payload)

    def _load_command_access_list(self, key: str) -> list[str]:
        payload = self._load_command_access()
        values = payload.get(key, [])
        if not isinstance(values, list):
            return []
        return [str(item).strip() for item in values if str(item).strip()]

    def _save_command_access_list(self, key: str, items: list[str]) -> None:
        payload = self._load_command_access()
        seen: set[str] = set()
        cleaned: list[str] = []
        for item in items:
            value = str(item).strip()
            if not value:
                continue
            canon = value.lower()
            if canon in seen:
                continue
            seen.add(canon)
            cleaned.append(value)
        payload[key] = cleaned
        self._save_command_access(payload)

    def _show_drag_ghost(self, text: str, x_root: int, y_root: int):
        if self._drag_ghost is None or self._drag_ghost_label is None:
            ghost = tk.Toplevel(self.root)
            ghost.overrideredirect(True)
            ghost.transient(self.root)
            try:
                ghost.attributes("-alpha", 0.92)
                ghost.attributes("-topmost", True)
            except Exception:
                pass

            frame = ttk.Frame(ghost, padding=(8, 4, 8, 4), style="TLabelframe")
            frame.pack(fill=tk.BOTH, expand=True)
            label = ttk.Label(frame, text="", font=("Segoe UI", 10))
            label.pack()

            self._drag_ghost = ghost
            self._drag_ghost_label = label

        assert self._drag_ghost is not None
        assert self._drag_ghost_label is not None
        self._drag_ghost_label.configure(text=text)
        self._drag_ghost.geometry(f"+{x_root + 16}+{y_root + 20}")
        self._drag_ghost.deiconify()

    def _hide_drag_ghost(self):
        if self._drag_ghost is not None:
            self._drag_ghost.withdraw()

    def _build_collapsible_section(
        self,
        parent: ttk.Frame,
        title: str,
        expanded: bool = True,
        state_key: str | None = None,
        fill: str = tk.X,
        expand: bool = False,
    ) -> tuple[ttk.LabelFrame, ttk.Frame]:
        expanded_state = expanded
        if state_key:
            stored = self.ui_state.get("collapsed_sections", {}).get(state_key)
            if isinstance(stored, bool):
                expanded_state = stored

        section = ttk.LabelFrame(parent, text=title)
        section.pack(fill=fill, expand=expand, padx=12, pady=8)
        section.columnconfigure(0, weight=1)

        header = ttk.Frame(section)
        header.grid(row=0, column=0, sticky="ew", padx=8, pady=(4, 0))
        header.columnconfigure(0, weight=1)

        toggle_text = tk.StringVar(value="Collapse" if expanded_state else "Expand")
        content = ttk.Frame(section)
        content.columnconfigure(1, weight=1)

        def _toggle():
            if content.winfo_ismapped():
                content.grid_remove()
                toggle_text.set("Expand")
                if state_key:
                    self.ui_state.setdefault("collapsed_sections", {})[state_key] = False
                    self._save_ui_state()
            else:
                content.grid(row=1, column=0, sticky="ew", padx=8, pady=(4, 8))
                toggle_text.set("Collapse")
                if state_key:
                    self.ui_state.setdefault("collapsed_sections", {})[state_key] = True
                    self._save_ui_state()
            self.root.after_idle(self._fit_window_to_active_tab)

        ttk.Button(header, textvariable=toggle_text, width=10, command=_toggle).grid(
            row=0, column=1, sticky="e", pady=2
        )

        if expanded_state:
            content.grid(row=1, column=0, sticky="ew", padx=8, pady=(4, 8))

        return section, content

    @staticmethod
    def _format_meta_time(value: str | int | float | None) -> str:
        if value is None:
            return "unknown"
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value)).strftime("%Y-%m-%d %H:%M:%S")
        raw = str(value).strip()
        if not raw:
            return "unknown"
        normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        try:
            dt = datetime.fromisoformat(normalized)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return raw

    @staticmethod
    def _is_valid_username(value: str) -> bool:
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

    def _refresh_owner_meta_label(self):
        cfg = load_json(self.config_path, default={})
        ui_meta = cfg.get("ui_meta", {}) if isinstance(cfg.get("ui_meta", {}), dict) else {}
        ts = ui_meta.get("last_changed_owner_profile_at")
        self.owner_last_changed_var.set(f"Last changed by UI: {self._format_meta_time(ts)}")

    def _load_owner_profile_into_editor(self) -> None:
        if not self._owner_profile_editor_vars:
            return
        cfg = load_json(self.config_path, default={})
        if not isinstance(cfg, dict):
            cfg = {}

        monitor_cfg = cfg.get("monitor", {}) if isinstance(cfg.get("monitor", {}), dict) else {}
        profile = cfg.get("owner_profile", {}) if isinstance(cfg.get("owner_profile", {}), dict) else {}
        owner_username = str(profile.get("username") or monitor_cfg.get("owner_username") or "").strip().lower()
        owner_name = str(profile.get("name") or "").strip()
        owner_pronouns = str(profile.get("pronouns") or "").strip()
        owner_role = str(profile.get("role_identity") or "").strip()
        owner_lore = str(profile.get("context_lore") or "").strip()

        username_var = self._owner_profile_editor_vars.get("username")
        name_var = self._owner_profile_editor_vars.get("name")
        pronouns_var = self._owner_profile_editor_vars.get("pronouns")
        role_var = self._owner_profile_editor_vars.get("role_identity")
        if isinstance(username_var, tk.StringVar):
            username_var.set(owner_username)
        if isinstance(name_var, tk.StringVar):
            name_var.set(owner_name)
        if isinstance(pronouns_var, tk.StringVar):
            pronouns_var.set(owner_pronouns)
        if isinstance(role_var, tk.StringVar):
            role_var.set(owner_role)

        if self._owner_profile_editor_lore_widget is not None:
            self._owner_profile_editor_lore_widget.delete("1.0", tk.END)
            self._owner_profile_editor_lore_widget.insert("1.0", owner_lore)

        self._refresh_owner_meta_label()
        self._mark_dirty("data", False)

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

    # ---- Monitor tab -------------------------------------------------------

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

    # ---- Scripts tab -------------------------------------------------------

    def _build_scripts_tab(self, parent: ttk.Frame):
        # Quick Test section
        qt_frame = ttk.LabelFrame(parent, text="Quick Test via Router")
        qt_frame.pack(fill=tk.X, padx=12, pady=12)

        ttk.Label(qt_frame, text="Command").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        cmd_cb = ttk.Combobox(
            qt_frame, textvariable=self.qt_keyword_var,
            values=["flirt", "tarot", "commands"], state="readonly", width=12
        )
        cmd_cb.grid(row=0, column=1, sticky="w", padx=8, pady=6)
        cmd_cb.bind("<<ComboboxSelected>>", self._on_qt_keyword_change)
        self._bind_enter_to_quick_test(cmd_cb)

        ttk.Label(qt_frame, text="Username").grid(row=0, column=2, sticky="w", padx=8, pady=6)
        username_entry = ttk.Entry(qt_frame, textvariable=self.qt_username_var, width=20)
        username_entry.grid(row=0, column=3, sticky="w", padx=8, pady=6)
        self._bind_enter_to_quick_test(username_entry)

        # Dynamic fields frame (swapped on keyword change)
        self._qt_fields_frame = ttk.Frame(qt_frame)
        self._qt_fields_frame.grid(row=1, column=0, columnspan=4, sticky="w", padx=4, pady=4)
        self._build_qt_flirt_fields(self._qt_fields_frame)

        ttk.Button(qt_frame, text="Fire Command", command=self._fire_quick_test).grid(
            row=2, column=0, columnspan=4, padx=8, pady=8, sticky="w"
        )

        logs = ttk.LabelFrame(parent, text="Runtime Logs")
        logs.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 12))
        self._build_logs_tab(logs)

    def _bind_enter_to_quick_test(self, widget) -> None:
        widget.bind("<Return>", lambda _event: self._fire_quick_test())
        widget.bind("<KP_Enter>", lambda _event: self._fire_quick_test())

    def _build_qt_flirt_fields(self, parent: ttk.Frame):
        for w in parent.winfo_children():
            w.destroy()
        ttk.Label(parent, text="Theme").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        theme_entry = ttk.Entry(parent, textvariable=self.qt_theme_var, width=18)
        theme_entry.grid(row=0, column=1, sticky="w", padx=4, pady=4)
        self._bind_enter_to_quick_test(theme_entry)
        ttk.Label(parent, text="Tone").grid(row=0, column=2, sticky="w", padx=8, pady=4)
        tone_entry = ttk.Entry(parent, textvariable=self.qt_tone_var, width=18)
        tone_entry.grid(row=0, column=3, sticky="w", padx=4, pady=4)
        self._bind_enter_to_quick_test(tone_entry)
        ttk.Label(parent, text="Spice (1-10)").grid(row=0, column=4, sticky="w", padx=8, pady=4)
        spice_spinbox = ttk.Spinbox(parent, from_=1, to=10, textvariable=self.qt_spice_var, width=5)
        spice_spinbox.grid(
            row=0, column=5, sticky="w", padx=4, pady=4
        )
        self._bind_enter_to_quick_test(spice_spinbox)

    def _build_qt_tarot_fields(self, parent: ttk.Frame):
        for w in parent.winfo_children():
            w.destroy()
        ttk.Label(parent, text="Question").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        question_entry = ttk.Entry(parent, textvariable=self.qt_question_var, width=40)
        question_entry.grid(row=0, column=1, sticky="w", padx=4, pady=4)
        self._bind_enter_to_quick_test(question_entry)
        ttk.Label(parent, text="Spread").grid(row=0, column=2, sticky="w", padx=8, pady=4)
        spread_combo = ttk.Combobox(
            parent, textvariable=self.qt_spread_var,
            values=["single", "3-card", "horseshoe", "celtic-cross"],
            state="readonly", width=14
        )
        spread_combo.grid(row=0, column=3, sticky="w", padx=4, pady=4)
        self._bind_enter_to_quick_test(spread_combo)

    def _build_qt_commands_fields(self, parent: ttk.Frame):
        for w in parent.winfo_children():
            w.destroy()
        ttk.Label(parent, text="Command Input").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        command_entry = ttk.Entry(parent, textvariable=self.qt_command_input_var, width=40)
        command_entry.grid(
            row=0, column=1, sticky="w", padx=4, pady=4
        )
        self._bind_enter_to_quick_test(command_entry)
        ttk.Label(parent, text="Example: !social").grid(row=0, column=2, sticky="w", padx=8, pady=4)

    def _on_qt_keyword_change(self, _event=None):
        keyword = self.qt_keyword_var.get()
        if keyword == "flirt":
            self._build_qt_flirt_fields(self._qt_fields_frame)
        elif keyword == "tarot":
            self._build_qt_tarot_fields(self._qt_fields_frame)
        else:
            self._build_qt_commands_fields(self._qt_fields_frame)

    def _fire_quick_test(self):
        keyword  = self.qt_keyword_var.get()
        username = self.qt_username_var.get().strip() or "TestUser"

        if keyword == "flirt":
            theme = self.qt_theme_var.get().strip()
            tone  = self.qt_tone_var.get().strip()
            spice = str(self.qt_spice_var.get())
            raw_input = " ".join(filter(None, [theme, tone, spice]))
            if not raw_input.strip():
                messagebox.showwarning("Quick Test", "Enter at least one flirt parameter.")
                return
        elif keyword == "tarot":
            question  = self.qt_question_var.get().strip()
            spread    = self.qt_spread_var.get().strip()
            raw_input = " ".join(filter(None, [question, spread]))
            if not raw_input.strip():
                messagebox.showwarning("Quick Test", "Enter a question or spread type.")
                return
        else:
            raw_input = self.qt_command_input_var.get().strip()
            if not raw_input.strip():
                messagebox.showwarning("Quick Test", "Enter a command like !social.")
                return

        command = self._build_python_script_command("main.py", [keyword, raw_input, username])
        self._spawn_process(f"test:{keyword}", command)

    # ---- Logs tab ----------------------------------------------------------

    def _build_logs_tab(self, parent: ttk.Frame):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        controls = ttk.Frame(frame)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        controls.columnconfigure(3, weight=1)
        ttk.Checkbutton(controls, text="Pause Auto-Scroll", variable=self.log_pause_var).grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        ttk.Label(controls, text="Level").grid(row=0, column=1, sticky="w", padx=(0, 6))
        level_combo = ttk.Combobox(
            controls,
            textvariable=self.log_filter_var,
            values=["All", "Error", "Warn", "Info"],
            state="readonly",
            width=10,
        )
        level_combo.grid(row=0, column=2, sticky="w", padx=(0, 8))
        level_combo.bind("<<ComboboxSelected>>", lambda _event: self._rerender_logs())

        ttk.Label(controls, text="Search").grid(row=0, column=3, sticky="e", padx=(0, 6))
        self.log_search_entry = ttk.Entry(controls, textvariable=self.log_search_var, width=28)
        self.log_search_entry.grid(row=0, column=4, sticky="e", padx=(0, 8))
        self.log_search_entry.bind("<KeyRelease>", lambda _event: self._rerender_logs())
        ttk.Button(controls, text="Clear", command=self._clear_logs).grid(row=0, column=5, sticky="e")

        log_container = ttk.Frame(frame)
        log_container.grid(row=1, column=0, sticky="nsew")
        log_container.columnconfigure(0, weight=1)
        log_container.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_container, wrap=tk.WORD, height=30)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self._register_text_widget(self.log_text)

        scrollbar = ttk.Scrollbar(log_container, orient=tk.VERTICAL, command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.config(yscrollcommand=scrollbar.set)

    def _clear_logs(self):
        self.log_buffer.clear()
        self._rerender_logs()
        self._set_status("Runtime logs cleared.", "info")

    def _log_matches_filter(self, message: str) -> bool:
        raw = str(message)
        level = self.log_filter_var.get().strip().lower()
        if level == "error":
            if "error" not in raw.lower() and "traceback" not in raw.lower() and "failed" not in raw.lower():
                return False
        elif level == "warn":
            if "warn" not in raw.lower() and "warning" not in raw.lower():
                return False
        elif level == "info":
            lowered = raw.lower()
            if any(token in lowered for token in ("error", "warn", "warning", "failed", "traceback")):
                return False

        needle = self.log_search_var.get().strip().lower()
        if needle and needle not in raw.lower():
            return False
        return True

    def _rerender_logs(self):
        if self.log_text is None:
            return
        filters = self.ui_state.setdefault("filters", {})
        filters["log_search"] = str(self.log_search_var.get() or "")
        filters["log_filter"] = str(self.log_filter_var.get() or "All")
        self.log_text.delete("1.0", tk.END)
        for line in self.log_buffer:
            if self._log_matches_filter(line):
                self.log_text.insert(tk.END, line + "\n")
        if not self.log_pause_var.get():
            self.log_text.see(tk.END)

    @staticmethod
    def _format_glance_timestamp(ts: float | None) -> str:
        if ts is None:
            return "unknown"
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return "unknown"

    @staticmethod
    def _format_chat_message_timestamp(value) -> str:
        if isinstance(value, (int, float)):
            return MaiControlPanel._format_glance_timestamp(float(value))
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

    @staticmethod
    def _chat_message_epoch_seconds(message: dict) -> float | None:
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

    @staticmethod
    def _is_highlight_like_message(message: dict) -> bool:
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

    @staticmethod
    def _read_text_preview(file_path: Path, max_chars: int = 220) -> str:
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

    @staticmethod
    def _read_last_jsonl_record(file_path: Path) -> dict | None:
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

    @staticmethod
    def _set_text_widget_content(widget: tk.Text, text: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)
        widget.configure(state=tk.DISABLED)

    @staticmethod
    def _format_age_short(seconds: float) -> str:
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

    def _refresh_analytics_chatlog_view(self):
        if self.analytics_chatlog_tree is None:
            return

        username_filter_raw = str(self.analytics_username_filter_var.get() or "").strip()
        keyword_filter_raw = str(self.analytics_keyword_filter_var.get() or "").strip()
        username_filter = username_filter_raw.lower()
        keyword_filter = keyword_filter_raw.lower()
        time_window = str(self.analytics_time_window_var.get() or "All").strip()
        highlights_only = bool(self.analytics_highlights_only_var.get())

        window_seconds = {
            "15m": 15 * 60,
            "1h": 60 * 60,
            "6h": 6 * 60 * 60,
            "24h": 24 * 60 * 60,
        }.get(time_window)
        now = datetime.now().timestamp()

        filtered: list[dict] = []
        for msg in self.analytics_chat_messages_cache:
            if username_filter and username_filter not in str(msg.get("username", "")).strip().lower():
                continue
            text = str(msg.get("message", "")).strip()
            if keyword_filter and keyword_filter not in text.lower():
                continue
            if highlights_only and not self._is_highlight_like_message(msg):
                continue
            if window_seconds is not None:
                epoch = self._chat_message_epoch_seconds(msg)
                if epoch is None or (now - epoch) > window_seconds:
                    continue
            filtered.append(msg)

        self.ui_state.setdefault("filters", {})["analytics_username"] = username_filter_raw
        self.ui_state.setdefault("filters", {})["analytics_keyword"] = keyword_filter_raw
        self.ui_state.setdefault("filters", {})["analytics_time_window"] = time_window
        self.ui_state.setdefault("filters", {})["analytics_highlights_only"] = highlights_only

        self._insert_chatlog_rows(self.analytics_chatlog_tree, filtered, limit=250)

    def _select_color_for_var(self, target_var: tk.StringVar, title: str) -> None:
        initial = target_var.get().strip() or "#ffffff"
        _rgb, hex_value = colorchooser.askcolor(initialcolor=initial, title=title, parent=self.root)
        if not hex_value:
            return
        target_var.set(str(hex_value).lower())

    def _apply_colorblind_preset_to_controls(self, mode: str) -> None:
        preset = COLORBLIND_PRESETS.get(str(mode or "").strip().lower())
        if not preset:
            return
        for key, color in preset["chip_colors"].items():
            var = self.settings_chip_color_vars.get(key)
            if var is not None:
                var.set(color)
        for key, color in preset["severity_colors"].items():
            var = self.settings_severity_color_vars.get(key)
            if var is not None:
                var.set(color)

    @staticmethod
    def _is_valid_profile_name(value: str) -> bool:
        return bool(re.fullmatch(r"[A-Za-z0-9 _.\-]{1,40}", value or ""))

    def _refresh_settings_profile_controls(self) -> None:
        if self.settings_ui_profile_var is None or self.settings_profile_combo is None:
            return
        profiles = self.ui_profiles.get("profiles", {}) if isinstance(self.ui_profiles, dict) else {}
        names = sorted([str(name) for name in profiles.keys() if str(name).strip()], key=str.lower)
        if not names:
            names = ["default"]
            self.ui_profiles = self._default_ui_profiles()
            self._save_ui_profiles()
        current = str(self.settings_ui_profile_var.get() or self.ui_profiles.get("active_profile", names[0])).strip()
        if current not in names:
            current = str(self.ui_profiles.get("active_profile", names[0]))
        if current not in names:
            current = names[0]
        self.settings_profile_combo["values"] = names
        self.settings_ui_profile_var.set(current)
        self.ui_profiles["active_profile"] = current

    def _load_ui_profile_into_controls(self, profile_name: str, persist_active: bool = True) -> None:
        profiles = self.ui_profiles.get("profiles", {}) if isinstance(self.ui_profiles, dict) else {}
        selected = profiles.get(profile_name)
        if not isinstance(selected, dict):
            self._set_status(f"UI profile not found: {profile_name}", "warn")
            return
        if persist_active:
            self.ui_profiles["active_profile"] = profile_name
        self.ui_settings = self._merge_ui_settings(selected)
        self._sync_settings_controls_from_ui_settings()
        self._apply_ui_style()
        self._refresh_glance()
        self._mark_dirty("settings", False)
        if persist_active:
            self.ui_profiles.setdefault("profiles", {})[profile_name] = dict(self.ui_settings)
            self._save_ui_profiles()
            self._save_ui_settings()
            self._refresh_settings_profile_controls()
        self._set_status(f"Loaded UI profile '{profile_name}'.", "ok")

    def _on_settings_profile_selected(self, _event=None) -> None:
        if self.settings_ui_profile_var is None:
            return
        selected = str(self.settings_ui_profile_var.get() or "").strip()
        if not selected:
            return
        self._load_ui_profile_into_controls(selected, persist_active=True)

    def _save_as_new_ui_profile(self) -> None:
        initial = ""
        if self.settings_ui_profile_var is not None:
            initial = str(self.settings_ui_profile_var.get() or "").strip()
        requested = simpledialog.askstring(
            "Save UI Profile",
            "Profile name (letters/numbers/space/._-):",
            initialvalue=initial,
            parent=self.root,
        )
        if requested is None:
            return
        name = str(requested).strip()
        if not self._is_valid_profile_name(name):
            messagebox.showwarning("Profile", "Use 1-40 chars: letters, numbers, space, dot, dash, underscore.", parent=self.root)
            return
        profiles = self.ui_profiles.setdefault("profiles", {})
        if name in profiles:
            if not messagebox.askyesno("Profile Exists", f"Overwrite existing profile '{name}'?", parent=self.root):
                return
        self.ui_settings = self._collect_ui_settings_from_controls()
        profiles[name] = dict(self.ui_settings)
        self.ui_profiles["active_profile"] = name
        self._save_ui_profiles()
        self._save_ui_settings()
        self._refresh_settings_profile_controls()
        self._mark_dirty("settings", False)
        self._set_status(f"Saved UI profile '{name}'.", "ok")

    def _rename_selected_ui_profile(self) -> None:
        if self.settings_ui_profile_var is None:
            return
        old_name = str(self.settings_ui_profile_var.get() or "").strip()
        if not old_name:
            messagebox.showwarning("Profile", "Select a profile first.", parent=self.root)
            return
        profiles = self.ui_profiles.get("profiles", {}) if isinstance(self.ui_profiles, dict) else {}
        if old_name not in profiles:
            messagebox.showwarning("Profile", f"Profile not found: {old_name}", parent=self.root)
            return
        requested = simpledialog.askstring(
            "Rename UI Profile",
            "New profile name:",
            initialvalue=old_name,
            parent=self.root,
        )
        if requested is None:
            return
        new_name = str(requested).strip()
        if new_name == old_name:
            return
        if not self._is_valid_profile_name(new_name):
            messagebox.showwarning("Profile", "Use 1-40 chars: letters, numbers, space, dot, dash, underscore.", parent=self.root)
            return
        if new_name in profiles:
            messagebox.showwarning("Profile", f"A profile named '{new_name}' already exists.", parent=self.root)
            return
        profiles[new_name] = profiles.pop(old_name)
        if str(self.ui_profiles.get("active_profile", "")) == old_name:
            self.ui_profiles["active_profile"] = new_name
        self._save_ui_profiles()
        self._refresh_settings_profile_controls()
        self._set_status(f"Renamed profile '{old_name}' to '{new_name}'.", "ok")

    def _delete_selected_ui_profile(self) -> None:
        if self.settings_ui_profile_var is None:
            return
        target = str(self.settings_ui_profile_var.get() or "").strip()
        if not target:
            messagebox.showwarning("Profile", "Select a profile first.", parent=self.root)
            return
        profiles = self.ui_profiles.get("profiles", {}) if isinstance(self.ui_profiles, dict) else {}
        if target not in profiles:
            messagebox.showwarning("Profile", f"Profile not found: {target}", parent=self.root)
            return
        if len(profiles) <= 1:
            messagebox.showwarning("Profile", "At least one UI profile must remain.", parent=self.root)
            return
        if not messagebox.askyesno("Delete Profile", f"Delete UI profile '{target}'?", parent=self.root):
            return
        profiles.pop(target, None)
        next_name = sorted(profiles.keys(), key=str.lower)[0]
        self.ui_profiles["active_profile"] = next_name
        self._save_ui_profiles()
        self._refresh_settings_profile_controls()
        self._load_ui_profile_into_controls(next_name, persist_active=True)
        self._set_status(f"Deleted profile '{target}'.", "ok")

    def _collect_ui_settings_from_controls(self) -> dict:
        if (
            self.settings_dark_mode_var is None
            or self.settings_colorblind_mode_var is None
            or self.settings_font_scale_var is None
            or self.settings_density_var is None
        ):
            return dict(self.ui_settings)

        mode = str(self.settings_colorblind_mode_var.get() or "standard").strip().lower()
        if mode not in COLORBLIND_PRESETS:
            mode = "standard"
        font_scale = str(self.settings_font_scale_var.get() or "100%").strip()
        if font_scale not in {"90%", "100%", "115%"}:
            font_scale = "100%"
        density = str(self.settings_density_var.get() or "comfortable").strip().lower()
        if density not in {"compact", "comfortable"}:
            density = "comfortable"

        payload = {
            "dark_mode": bool(self.settings_dark_mode_var.get()),
            "colorblind_mode": mode,
            "chip_colors": {},
            "severity_colors": {},
            "font_scale": font_scale,
            "density": density,
        }

        preset = COLORBLIND_PRESETS[mode]
        for key, default in preset["chip_colors"].items():
            var = self.settings_chip_color_vars.get(key)
            raw = str(var.get()).strip().lower() if var is not None else default
            payload["chip_colors"][key] = raw if self._is_hex_color(raw) else default

        for key, default in preset["severity_colors"].items():
            var = self.settings_severity_color_vars.get(key)
            raw = str(var.get()).strip().lower() if var is not None else default
            payload["severity_colors"][key] = raw if self._is_hex_color(raw) else default

        return self._merge_ui_settings(payload)

    def _apply_ui_settings_from_controls(self, save: bool) -> None:
        self.ui_settings = self._collect_ui_settings_from_controls()
        self._apply_ui_style()
        self._refresh_glance()
        if save:
            active_profile = str(self.ui_profiles.get("active_profile", "default")).strip() or "default"
            if self.settings_ui_profile_var is not None:
                selected = str(self.settings_ui_profile_var.get() or "").strip()
                if selected:
                    active_profile = selected
            self.ui_profiles.setdefault("profiles", {})[active_profile] = dict(self.ui_settings)
            self.ui_profiles["active_profile"] = active_profile
            self._save_ui_profiles()
            self._save_ui_settings()
            self._refresh_settings_profile_controls()
            self.log_queue.put("[settings] UI settings saved")
            self._set_status(f"Settings saved to profile '{active_profile}'.", "ok")
            self._mark_dirty("settings", False)
            messagebox.showinfo("Settings", "Accessibility settings saved.", parent=self.root)
        else:
            self.log_queue.put("[settings] UI settings applied")
            self._set_status("Settings applied.", "ok")

    def _sync_settings_controls_from_ui_settings(self) -> None:
        if self.settings_ui_profile_var is not None:
            self.settings_ui_profile_var.set(str(self.ui_profiles.get("active_profile", "default")))
        if self.settings_dark_mode_var is not None:
            self.settings_dark_mode_var.set(bool(self.ui_settings.get("dark_mode", False)))
        if self.settings_colorblind_mode_var is not None:
            self.settings_colorblind_mode_var.set(str(self.ui_settings.get("colorblind_mode", "standard")))
        if self.settings_font_scale_var is not None:
            self.settings_font_scale_var.set(str(self.ui_settings.get("font_scale", "100%")))
        if self.settings_density_var is not None:
            self.settings_density_var.set(str(self.ui_settings.get("density", "comfortable")))

        chip_colors = self.ui_settings.get("chip_colors", {})
        for key, var in self.settings_chip_color_vars.items():
            var.set(str(chip_colors.get(key, var.get())))
        severity_colors = self.ui_settings.get("severity_colors", {})
        for key, var in self.settings_severity_color_vars.items():
            var.set(str(severity_colors.get(key, var.get())))

    def _snapshot_root(self) -> Path:
        return REPO_ROOT / "jsons" / "configs" / "snapshots"

    def _snapshot_target_files(self) -> list[Path]:
        return [self.config_path, self.ui_settings_path, self.ui_profiles_path, self.ui_state_path]

    def _list_config_snapshots(self) -> list[Path]:
        root = self._snapshot_root()
        if not root.exists():
            return []
        items = [path for path in root.iterdir() if path.is_dir()]
        return sorted(items, key=lambda item: item.name, reverse=True)

    def _refresh_snapshot_list(self) -> None:
        if self.settings_snapshot_listbox is None:
            return
        self.settings_snapshot_name_to_path.clear()
        self.settings_snapshot_listbox.delete(0, tk.END)
        for snap in self._list_config_snapshots():
            name = snap.name
            self.settings_snapshot_name_to_path[name] = snap
            self.settings_snapshot_listbox.insert(tk.END, name)

    def _create_config_snapshot(self) -> None:
        try:
            root = self._snapshot_root()
            root.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            snapshot_dir = root / stamp
            suffix = 1
            while snapshot_dir.exists():
                snapshot_dir = root / f"{stamp}_{suffix}"
                suffix += 1
            snapshot_dir.mkdir(parents=True, exist_ok=False)

            copied = 0
            for src in self._snapshot_target_files():
                if not src.exists():
                    continue
                shutil.copy2(src, snapshot_dir / src.name)
                copied += 1

            self._refresh_snapshot_list()
            self._set_status(f"Created snapshot {snapshot_dir.name} ({copied} files).", "ok")
            self.log_queue.put(f"[settings] created snapshot {snapshot_dir}")
        except Exception as e:
            self._set_status(f"Snapshot creation failed: {e}", "error")
            messagebox.showerror("Snapshot", f"Failed to create snapshot: {e}", parent=self.root)

    def _restore_selected_snapshot(self) -> None:
        if self.settings_snapshot_listbox is None:
            return
        selection = self.settings_snapshot_listbox.curselection()
        if not selection:
            messagebox.showwarning("Snapshot", "Select a snapshot to restore.", parent=self.root)
            return
        name = str(self.settings_snapshot_listbox.get(selection[0]))
        snap_path = self.settings_snapshot_name_to_path.get(name)
        if snap_path is None or not snap_path.exists():
            messagebox.showerror("Snapshot", f"Snapshot not found: {name}", parent=self.root)
            self._refresh_snapshot_list()
            return
        if not self._confirm_discard_unsaved("restoring a snapshot"):
            return
        if not messagebox.askyesno(
            "Restore Snapshot",
            f"Restore snapshot '{name}'?\nThis overwrites current config and UI settings files.",
            parent=self.root,
        ):
            return
        try:
            for dst in self._snapshot_target_files():
                src = snap_path / dst.name
                if src.exists():
                    shutil.copy2(src, dst)
            self.ui_profiles = self._load_ui_profiles(self._load_ui_settings())
            active_name = str(self.ui_profiles.get("active_profile", "default"))
            self.ui_settings = dict(self.ui_profiles.get("profiles", {}).get(active_name, self._default_ui_settings()))
            self.ui_state = self._load_ui_state()
            self._refresh_settings_profile_controls()
            self._sync_settings_controls_from_ui_settings()
            self._apply_ui_style()
            self._load_monitor_config_into_form()
            self._load_owner_profile_into_editor()
            self._refresh_glance()
            self._refresh_chat_analytics()
            self._mark_dirty("settings", False)
            self._mark_dirty("data", False)
            self._set_status(f"Restored snapshot {name}.", "ok")
            self.log_queue.put(f"[settings] restored snapshot {snap_path}")
        except Exception as e:
            self._set_status(f"Snapshot restore failed: {e}", "error")
            messagebox.showerror("Snapshot", f"Failed to restore snapshot: {e}", parent=self.root)

    def _persistent_backup_base_root(self) -> Path:
        candidates: list[Path] = []
        local_appdata = str(os.getenv("LOCALAPPDATA") or "").strip()
        appdata = str(os.getenv("APPDATA") or "").strip()
        if local_appdata:
            candidates.append(Path(local_appdata) / "MaiControlPanel" / "backups")
        if appdata:
            candidates.append(Path(appdata) / "MaiControlPanel" / "backups")
        candidates.append(Path.home() / ".mai_control_panel" / "backups")
        candidates.append(REPO_ROOT / "backups")

        for root in candidates:
            try:
                root.mkdir(parents=True, exist_ok=True)
                return root
            except Exception:
                continue
        return REPO_ROOT / "backups"

    def _update_backup_root_label(self) -> None:
        base = self._persistent_backup_base_root()
        self.settings_backup_root_var.set(str(base))

    def _open_backup_folder(self) -> None:
        root = self._persistent_backup_base_root()
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(root))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(root)], cwd=REPO_ROOT)
            else:
                subprocess.Popen(["xdg-open", str(root)], cwd=REPO_ROOT)
            self._set_status(f"Opened backup folder: {root}", "ok")
        except Exception as e:
            self._set_status(f"Could not open backup folder: {e}", "error")
            messagebox.showerror("Backup Folder", f"Failed to open backup folder:\n{root}\n\n{e}", parent=self.root)

    def _full_backup_root(self) -> Path:
        return self._persistent_backup_base_root() / "full_data"

    def _list_full_backups(self) -> list[Path]:
        root = self._full_backup_root()
        if not root.exists():
            return []
        candidates = [item for item in root.iterdir() if item.is_dir()]
        return sorted(candidates, key=lambda item: item.name, reverse=True)

    def _refresh_full_backup_list(self) -> None:
        self._update_backup_root_label()
        if self.settings_full_backup_listbox is None:
            return
        self.settings_full_backup_name_to_path.clear()
        self.settings_full_backup_listbox.delete(0, tk.END)
        for item in self._list_full_backups():
            name = item.name
            self.settings_full_backup_name_to_path[name] = item
            self.settings_full_backup_listbox.insert(tk.END, name)

    def _create_full_backup_folder(self, name_prefix: str = "all_data") -> Path:
        root = self._full_backup_root()
        root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = root / f"{name_prefix}_{stamp}"
        suffix = 1
        while backup_dir.exists():
            backup_dir = root / f"{name_prefix}_{stamp}_{suffix}"
            suffix += 1
        backup_dir.mkdir(parents=True, exist_ok=False)

        source_jsons = REPO_ROOT / "jsons"
        target_jsons = backup_dir / "jsons"
        if source_jsons.exists():
            shutil.copytree(source_jsons, target_jsons)
        else:
            target_jsons.mkdir(parents=True, exist_ok=True)
        return backup_dir

    def _create_full_data_backup(self) -> None:
        try:
            backup_dir = self._create_full_backup_folder(name_prefix="all_data")
            self._refresh_full_backup_list()
            self.log_queue.put(f"[settings] full data backup created: {backup_dir}")
            self._set_status(f"Full data backup created: {backup_dir}", "ok")
        except Exception as e:
            self._set_status(f"Full data backup failed: {e}", "error")
            messagebox.showerror("Backup", f"Failed to create full data backup: {e}", parent=self.root)

    def _restore_selected_full_backup(self) -> None:
        if self.settings_full_backup_listbox is None:
            return
        selection = self.settings_full_backup_listbox.curselection()
        if not selection:
            messagebox.showwarning("Backup", "Select a backup to restore.", parent=self.root)
            return
        name = str(self.settings_full_backup_listbox.get(selection[0]))
        backup_path = self.settings_full_backup_name_to_path.get(name)
        if backup_path is None or not backup_path.exists():
            messagebox.showerror("Backup", f"Backup not found: {name}", parent=self.root)
            self._refresh_full_backup_list()
            return
        source_jsons = backup_path / "jsons"
        if not source_jsons.exists():
            messagebox.showerror("Backup", f"Backup is missing jsons/: {name}", parent=self.root)
            return
        if not self._confirm_discard_unsaved("restoring a full data backup"):
            return
        if not messagebox.askyesno(
            "Restore Full Data Backup",
            f"Restore backup '{name}'?\nThis overwrites all files under jsons/.",
            parent=self.root,
        ):
            return

        try:
            current_jsons = REPO_ROOT / "jsons"
            self._create_full_backup_folder(name_prefix="pre_restore")
            if current_jsons.exists():
                shutil.rmtree(current_jsons)
            shutil.copytree(source_jsons, current_jsons)

            self.ui_profiles = self._load_ui_profiles(self._load_ui_settings())
            active_name = str(self.ui_profiles.get("active_profile", "default"))
            self.ui_settings = dict(self.ui_profiles.get("profiles", {}).get(active_name, self._default_ui_settings()))
            self.ui_state = self._load_ui_state()
            self._sync_settings_controls_from_ui_settings()
            self._refresh_settings_profile_controls()
            self._apply_ui_style()
            self._load_monitor_config_into_form()
            self._load_owner_profile_into_editor()
            self._refresh_chat_analytics()
            self._refresh_glance()
            self._refresh_snapshot_list()
            self._refresh_full_backup_list()
            self._mark_dirty("settings", False)
            self._mark_dirty("data", False)
            self.log_queue.put(f"[settings] restored full data backup: {backup_path}")
            self._set_status(f"Restored full data backup: {name}", "ok")
        except Exception as e:
            self._set_status(f"Full data restore failed: {e}", "error")
            messagebox.showerror("Backup", f"Failed to restore full data backup: {e}", parent=self.root)

    def _rename_selected_full_backup(self) -> None:
        if self.settings_full_backup_listbox is None:
            return
        selection = self.settings_full_backup_listbox.curselection()
        if not selection:
            messagebox.showwarning("Backup", "Select a backup first.", parent=self.root)
            return
        old_name = str(self.settings_full_backup_listbox.get(selection[0]))
        backup_path = self.settings_full_backup_name_to_path.get(old_name)
        if backup_path is None or not backup_path.exists():
            self._refresh_full_backup_list()
            messagebox.showerror("Backup", f"Backup not found: {old_name}", parent=self.root)
            return
        requested = simpledialog.askstring("Rename Backup", "New backup name:", initialvalue=old_name, parent=self.root)
        if requested is None:
            return
        new_name = str(requested).strip()
        if not self._is_valid_profile_name(new_name):
            messagebox.showwarning("Backup", "Use 1-40 chars: letters, numbers, space, dot, dash, underscore.", parent=self.root)
            return
        target = backup_path.parent / new_name
        if target.exists():
            messagebox.showwarning("Backup", f"A backup named '{new_name}' already exists.", parent=self.root)
            return
        try:
            backup_path.rename(target)
            self._refresh_full_backup_list()
            self._set_status(f"Renamed backup '{old_name}' to '{new_name}'.", "ok")
        except Exception as e:
            self._set_status(f"Backup rename failed: {e}", "error")
            messagebox.showerror("Backup", f"Failed to rename backup: {e}", parent=self.root)

    def _delete_selected_full_backup(self) -> None:
        if self.settings_full_backup_listbox is None:
            return
        selection = self.settings_full_backup_listbox.curselection()
        if not selection:
            messagebox.showwarning("Backup", "Select a backup first.", parent=self.root)
            return
        name = str(self.settings_full_backup_listbox.get(selection[0]))
        backup_path = self.settings_full_backup_name_to_path.get(name)
        if backup_path is None or not backup_path.exists():
            self._refresh_full_backup_list()
            messagebox.showerror("Backup", f"Backup not found: {name}", parent=self.root)
            return
        if not messagebox.askyesno("Delete Backup", f"Delete backup '{name}'?", parent=self.root):
            return
        try:
            shutil.rmtree(backup_path)
            self._refresh_full_backup_list()
            self._set_status(f"Deleted backup '{name}'.", "ok")
        except Exception as e:
            self._set_status(f"Backup delete failed: {e}", "error")
            messagebox.showerror("Backup", f"Failed to delete backup: {e}", parent=self.root)

    def _json_section_sources(self) -> dict[str, Path]:
        base = REPO_ROOT / "jsons"
        return {
            "configs": base / "configs",
            "data": base / "data",
            "calls": base / "calls",
        }

    def _section_backup_root(self) -> Path:
        return self._persistent_backup_base_root() / "sections"

    def _list_section_backups(self, section: str) -> list[Path]:
        root = self._section_backup_root() / section
        if not root.exists():
            return []
        return sorted([item for item in root.iterdir() if item.is_dir()], key=lambda item: item.name, reverse=True)

    def _refresh_section_backup_list(self) -> None:
        if self.settings_section_backup_listbox is None or self.settings_section_var is None:
            return
        section = str(self.settings_section_var.get() or "configs").strip().lower()
        self.settings_section_backup_name_to_path.clear()
        self.settings_section_backup_listbox.delete(0, tk.END)
        for item in self._list_section_backups(section):
            name = item.name
            self.settings_section_backup_name_to_path[name] = item
            self.settings_section_backup_listbox.insert(tk.END, name)

    def _on_section_changed(self, _event=None) -> None:
        self._refresh_section_backup_list()

    def _create_section_backup(self) -> None:
        if self.settings_section_var is None:
            return
        section = str(self.settings_section_var.get() or "").strip().lower()
        source = self._json_section_sources().get(section)
        if source is None:
            messagebox.showwarning("Section Backup", "Select a valid section.", parent=self.root)
            return
        try:
            root = self._section_backup_root() / section
            root.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = root / f"{section}_{stamp}"
            suffix = 1
            while backup_dir.exists():
                backup_dir = root / f"{section}_{stamp}_{suffix}"
                suffix += 1
            if source.exists():
                shutil.copytree(source, backup_dir)
            else:
                backup_dir.mkdir(parents=True, exist_ok=False)
            self._refresh_section_backup_list()
            self._set_status(f"Created {section} backup: {backup_dir.name}", "ok")
        except Exception as e:
            self._set_status(f"Section backup failed: {e}", "error")
            messagebox.showerror("Section Backup", f"Failed to create section backup: {e}", parent=self.root)

    def _restore_selected_section_backup(self) -> None:
        if self.settings_section_backup_listbox is None or self.settings_section_var is None:
            return
        section = str(self.settings_section_var.get() or "").strip().lower()
        source_dir = self._json_section_sources().get(section)
        if source_dir is None:
            messagebox.showwarning("Section Backup", "Select a valid section.", parent=self.root)
            return
        selection = self.settings_section_backup_listbox.curselection()
        if not selection:
            messagebox.showwarning("Section Backup", "Select a section backup to restore.", parent=self.root)
            return
        name = str(self.settings_section_backup_listbox.get(selection[0]))
        backup_path = self.settings_section_backup_name_to_path.get(name)
        if backup_path is None or not backup_path.exists():
            self._refresh_section_backup_list()
            messagebox.showerror("Section Backup", f"Backup not found: {name}", parent=self.root)
            return
        if not self._confirm_discard_unsaved(f"restoring {section} backup"):
            return
        if not messagebox.askyesno(
            "Restore Section Backup",
            f"Restore '{name}' into jsons/{section}?\nThis overwrites that section.",
            parent=self.root,
        ):
            return
        try:
            pre_root = self._section_backup_root() / section
            pre_root.mkdir(parents=True, exist_ok=True)
            pre_name = f"pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            pre_path = pre_root / pre_name
            suffix = 1
            while pre_path.exists():
                pre_path = pre_root / f"{pre_name}_{suffix}"
                suffix += 1
            if source_dir.exists():
                shutil.copytree(source_dir, pre_path)
                shutil.rmtree(source_dir)
            shutil.copytree(backup_path, source_dir)

            if section == "configs":
                self.ui_profiles = self._load_ui_profiles(self._load_ui_settings())
                active_name = str(self.ui_profiles.get("active_profile", "default"))
                self.ui_settings = dict(
                    self.ui_profiles.get("profiles", {}).get(active_name, self._default_ui_settings())
                )
                self.ui_state = self._load_ui_state()
                self._refresh_settings_profile_controls()
                self._sync_settings_controls_from_ui_settings()
                self._apply_ui_style()
            self._load_monitor_config_into_form()
            self._load_owner_profile_into_editor()
            self._refresh_chat_analytics()
            self._refresh_glance()
            self._refresh_snapshot_list()
            self._refresh_full_backup_list()
            self._refresh_section_backup_list()
            self._mark_dirty("settings", False)
            self._mark_dirty("data", False)
            self._set_status(f"Restored {section} backup '{name}'.", "ok")
        except Exception as e:
            self._set_status(f"Section restore failed: {e}", "error")
            messagebox.showerror("Section Backup", f"Failed to restore section backup: {e}", parent=self.root)

    def _rename_selected_section_backup(self) -> None:
        if self.settings_section_backup_listbox is None:
            return
        selection = self.settings_section_backup_listbox.curselection()
        if not selection:
            messagebox.showwarning("Section Backup", "Select a section backup first.", parent=self.root)
            return
        old_name = str(self.settings_section_backup_listbox.get(selection[0]))
        backup_path = self.settings_section_backup_name_to_path.get(old_name)
        if backup_path is None or not backup_path.exists():
            self._refresh_section_backup_list()
            messagebox.showerror("Section Backup", f"Backup not found: {old_name}", parent=self.root)
            return
        requested = simpledialog.askstring(
            "Rename Section Backup",
            "New backup name:",
            initialvalue=old_name,
            parent=self.root,
        )
        if requested is None:
            return
        new_name = str(requested).strip()
        if not self._is_valid_profile_name(new_name):
            messagebox.showwarning("Section Backup", "Use 1-40 chars: letters, numbers, space, dot, dash, underscore.", parent=self.root)
            return
        target = backup_path.parent / new_name
        if target.exists():
            messagebox.showwarning("Section Backup", f"A backup named '{new_name}' already exists.", parent=self.root)
            return
        try:
            backup_path.rename(target)
            self._refresh_section_backup_list()
            self._set_status(f"Renamed section backup '{old_name}' to '{new_name}'.", "ok")
        except Exception as e:
            self._set_status(f"Section backup rename failed: {e}", "error")
            messagebox.showerror("Section Backup", f"Failed to rename section backup: {e}", parent=self.root)

    def _delete_selected_section_backup(self) -> None:
        if self.settings_section_backup_listbox is None:
            return
        selection = self.settings_section_backup_listbox.curselection()
        if not selection:
            messagebox.showwarning("Section Backup", "Select a section backup first.", parent=self.root)
            return
        name = str(self.settings_section_backup_listbox.get(selection[0]))
        backup_path = self.settings_section_backup_name_to_path.get(name)
        if backup_path is None or not backup_path.exists():
            self._refresh_section_backup_list()
            messagebox.showerror("Section Backup", f"Backup not found: {name}", parent=self.root)
            return
        if not messagebox.askyesno("Delete Section Backup", f"Delete section backup '{name}'?", parent=self.root):
            return
        try:
            shutil.rmtree(backup_path)
            self._refresh_section_backup_list()
            self._set_status(f"Deleted section backup '{name}'.", "ok")
        except Exception as e:
            self._set_status(f"Section backup delete failed: {e}", "error")
            messagebox.showerror("Section Backup", f"Failed to delete section backup: {e}", parent=self.root)

    def _wipe_jsons_contents(self) -> None:
        if not messagebox.askyesno(
            "Wipe jsons",
            "Delete all files/folders inside jsons/? A safety full backup will be created first.",
            parent=self.root,
        ):
            return
        token = simpledialog.askstring(
            "Confirm Wipe",
            "Type WIPE to continue:",
            parent=self.root,
        )
        if str(token or "").strip().upper() != "WIPE":
            self._set_status("Wipe cancelled.", "warn")
            return
        try:
            self._create_full_backup_folder(name_prefix="pre_wipe")
            jsons_root = REPO_ROOT / "jsons"
            jsons_root.mkdir(parents=True, exist_ok=True)
            for child in list(jsons_root.iterdir()):
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()

            for folder in ("configs", "data", "calls"):
                (jsons_root / folder).mkdir(parents=True, exist_ok=True)

            self.ui_settings = self._default_ui_settings()
            self.ui_profiles = self._default_ui_profiles()
            self.ui_state = self._default_ui_state()
            self._save_ui_profiles()
            self._save_ui_settings()
            self._save_ui_state()
            self._sync_settings_controls_from_ui_settings()
            self._refresh_settings_profile_controls()
            self._apply_ui_style()
            self._refresh_snapshot_list()
            self._refresh_full_backup_list()
            self._refresh_section_backup_list()
            self._load_monitor_config_into_form()
            self._load_owner_profile_into_editor()
            self._refresh_chat_analytics()
            self._refresh_glance()
            self._mark_dirty("settings", False)
            self._mark_dirty("data", False)
            self._set_status("Wiped jsons contents. You can now build custom JSON data from scratch.", "ok")
            self.log_queue.put("[settings] wiped jsons contents")
        except Exception as e:
            self._set_status(f"Wipe failed: {e}", "error")
            messagebox.showerror("Wipe jsons", f"Failed to wipe jsons contents: {e}", parent=self.root)

    def _build_settings_tab(self, parent: ttk.Frame):
        container = ttk.Frame(parent)
        container.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        container.columnconfigure(0, weight=1)

        appearance = ttk.LabelFrame(container, text="Appearance")
        appearance.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        appearance.columnconfigure(1, weight=1)
        appearance.columnconfigure(2, weight=1)

        self.settings_dark_mode_var = tk.BooleanVar(value=bool(self.ui_settings.get("dark_mode", False)))
        self.settings_colorblind_mode_var = tk.StringVar(value=str(self.ui_settings.get("colorblind_mode", "standard")))
        self.settings_font_scale_var = tk.StringVar(value=str(self.ui_settings.get("font_scale", "100%")))
        self.settings_density_var = tk.StringVar(value=str(self.ui_settings.get("density", "comfortable")))
        self.settings_ui_profile_var = tk.StringVar(value=str(self.ui_profiles.get("active_profile", "default")))

        ttk.Checkbutton(appearance, text="Dark mode", variable=self.settings_dark_mode_var).grid(
            row=0, column=0, sticky="w", padx=8, pady=8
        )
        ttk.Label(appearance, text="Vision preset").grid(row=1, column=0, sticky="w", padx=8, pady=8)
        preset_combo = ttk.Combobox(
            appearance,
            textvariable=self.settings_colorblind_mode_var,
            values=["standard", "protanomaly", "deutranomaly", "tritanomaly"],
            state="readonly",
            width=18,
        )
        preset_combo.grid(row=1, column=1, sticky="w", padx=8, pady=8)
        preset_combo.bind(
            "<<ComboboxSelected>>",
            lambda _event: self._apply_colorblind_preset_to_controls(self.settings_colorblind_mode_var.get()),
        )
        ttk.Label(
            appearance,
            text="Pick a profile, then tweak colors if needed.",
        ).grid(row=1, column=2, sticky="w", padx=8, pady=8)

        ttk.Label(appearance, text="Font scale").grid(row=2, column=0, sticky="w", padx=8, pady=8)
        ttk.Combobox(
            appearance,
            textvariable=self.settings_font_scale_var,
            values=["90%", "100%", "115%"],
            state="readonly",
            width=10,
        ).grid(row=2, column=1, sticky="w", padx=8, pady=8)

        ttk.Label(appearance, text="Density").grid(row=3, column=0, sticky="w", padx=8, pady=8)
        ttk.Combobox(
            appearance,
            textvariable=self.settings_density_var,
            values=["comfortable", "compact"],
            state="readonly",
            width=14,
        ).grid(row=3, column=1, sticky="w", padx=8, pady=8)

        ttk.Label(appearance, text="UI profile").grid(row=4, column=0, sticky="w", padx=8, pady=8)
        profile_combo = ttk.Combobox(
            appearance,
            textvariable=self.settings_ui_profile_var,
            state="readonly",
            width=22,
        )
        profile_combo.grid(row=4, column=1, sticky="w", padx=8, pady=8)
        profile_combo.bind("<<ComboboxSelected>>", self._on_settings_profile_selected)
        self.settings_profile_combo = profile_combo

        profile_actions = ttk.Frame(appearance)
        profile_actions.grid(row=4, column=2, sticky="w", padx=8, pady=8)
        ttk.Button(profile_actions, text="Save As New", command=self._save_as_new_ui_profile).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(profile_actions, text="Rename", command=self._rename_selected_ui_profile).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(profile_actions, text="Delete", command=self._delete_selected_ui_profile).pack(side=tk.LEFT)

        appearance_actions = ttk.Frame(appearance)
        appearance_actions.grid(row=0, column=3, rowspan=5, sticky="ne", padx=8, pady=8)
        ttk.Button(
            appearance_actions,
            text="Save Settings",
            command=lambda: self._apply_ui_settings_from_controls(save=True),
        ).pack(side=tk.TOP, fill=tk.X, pady=(0, 6))
        ttk.Button(
            appearance_actions,
            text="Apply",
            command=lambda: self._apply_ui_settings_from_controls(save=False),
        ).pack(side=tk.TOP, fill=tk.X, pady=(0, 6))
        ttk.Button(
            appearance_actions,
            text="Reset To Profile",
            command=lambda: self._apply_colorblind_preset_to_controls(self.settings_colorblind_mode_var.get()),
        ).pack(side=tk.TOP, fill=tk.X, pady=(0, 6))
        ttk.Button(
            appearance_actions,
            text="Backup All Data",
            command=self._create_full_data_backup,
        ).pack(side=tk.TOP, fill=tk.X)

        chips = ttk.LabelFrame(container, text="Monitor Chip Colors")
        chips.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        chips.columnconfigure(1, weight=1)

        chip_colors = self.ui_settings.get("chip_colors", {})
        chip_labels = {
            "monitor": "Monitor",
            "routing": "Routing",
            "flirt": "Flirt Output",
            "tarot": "Tarot Output",
            "commands": "Command Output",
        }
        for row, (key, label) in enumerate(chip_labels.items()):
            ttk.Label(chips, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=6)
            var = tk.StringVar(value=str(chip_colors.get(key, "#22c55e")))
            self.settings_chip_color_vars[key] = var
            ttk.Entry(chips, textvariable=var, width=14).grid(row=row, column=1, sticky="w", padx=8, pady=6)
            ttk.Button(
                chips,
                text="Pick...",
                command=lambda v=var, l=label: self._select_color_for_var(v, f"{l} Color"),
            ).grid(row=row, column=2, sticky="w", padx=8, pady=6)
            self._bind_dirty_var("settings", var)

        severity = ttk.LabelFrame(container, text="Shared Status Colors")
        severity.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        severity.columnconfigure(1, weight=1)

        severity_colors = self.ui_settings.get("severity_colors", {})
        severity_labels = {
            "warn": "Warning",
            "bad": "Error",
            "idle": "Idle",
        }
        for row, (key, label) in enumerate(severity_labels.items()):
            ttk.Label(severity, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=6)
            var = tk.StringVar(value=str(severity_colors.get(key, "#9ca3af")))
            self.settings_severity_color_vars[key] = var
            ttk.Entry(severity, textvariable=var, width=14).grid(row=row, column=1, sticky="w", padx=8, pady=6)
            ttk.Button(
                severity,
                text="Pick...",
                command=lambda v=var, l=label: self._select_color_for_var(v, f"{l} Color"),
            ).grid(row=row, column=2, sticky="w", padx=8, pady=6)
            self._bind_dirty_var("settings", var)

        full_backups = ttk.LabelFrame(container, text="Full Data Backups (all jsons/*)")
        full_backups.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        full_backups.columnconfigure(0, weight=1)

        full_backup_meta = ttk.Frame(full_backups)
        full_backup_meta.pack(fill=tk.X, padx=8, pady=(8, 0))
        ttk.Label(full_backup_meta, text="Stored at").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Label(full_backup_meta, textvariable=self.settings_backup_root_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(full_backup_meta, text="Open Folder", command=self._open_backup_folder).pack(side=tk.RIGHT)

        full_backup_box = ttk.Frame(full_backups)
        full_backup_box.pack(fill=tk.X, padx=8, pady=8)
        full_backup_list, _full_backup_scroll = _scrolled_listbox(full_backup_box)
        full_backup_list.configure(height=6)
        self.settings_full_backup_listbox = full_backup_list

        full_backup_actions = ttk.Frame(full_backups)
        full_backup_actions.pack(anchor="w", padx=8, pady=(0, 8))
        ttk.Button(full_backup_actions, text="Create Full Backup", command=self._create_full_data_backup).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(full_backup_actions, text="Restore Selected", command=self._restore_selected_full_backup).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(full_backup_actions, text="Rename Selected", command=self._rename_selected_full_backup).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(full_backup_actions, text="Delete Selected", command=self._delete_selected_full_backup).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(full_backup_actions, text="Refresh List", command=self._refresh_full_backup_list).pack(side=tk.LEFT)

        section_backups = ttk.LabelFrame(container, text="Section Backups (configs/data/calls)")
        section_backups.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        section_backups.columnconfigure(0, weight=1)

        section_controls = ttk.Frame(section_backups)
        section_controls.pack(fill=tk.X, padx=8, pady=(8, 4))
        self.settings_section_var = tk.StringVar(value="configs")
        ttk.Label(section_controls, text="Section").pack(side=tk.LEFT, padx=(0, 8))
        section_combo = ttk.Combobox(
            section_controls,
            textvariable=self.settings_section_var,
            values=["configs", "data", "calls"],
            state="readonly",
            width=12,
        )
        section_combo.pack(side=tk.LEFT, padx=(0, 8))
        section_combo.bind("<<ComboboxSelected>>", self._on_section_changed)

        section_list_frame = ttk.Frame(section_backups)
        section_list_frame.pack(fill=tk.X, padx=8, pady=4)
        section_backup_list, _section_backup_scroll = _scrolled_listbox(section_list_frame)
        section_backup_list.configure(height=6)
        self.settings_section_backup_listbox = section_backup_list

        section_actions = ttk.Frame(section_backups)
        section_actions.pack(anchor="w", padx=8, pady=(0, 8))
        ttk.Button(section_actions, text="Create Backup", command=self._create_section_backup).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(section_actions, text="Restore Selected", command=self._restore_selected_section_backup).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(section_actions, text="Rename Selected", command=self._rename_selected_section_backup).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(section_actions, text="Delete Selected", command=self._delete_selected_section_backup).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(section_actions, text="Refresh List", command=self._refresh_section_backup_list).pack(side=tk.LEFT)

        dangerous = ttk.LabelFrame(container, text="Danger Zone")
        dangerous.grid(row=5, column=0, sticky="ew", pady=(0, 8))
        dangerous.columnconfigure(1, weight=1)
        ttk.Label(
            dangerous,
            text="Wipe all contents under jsons/ (keeps empty folders and UI config defaults).",
            foreground=self.theme_palette["text_subtle"],
        ).grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ttk.Button(dangerous, text="Wipe jsons Contents", command=self._wipe_jsons_contents).grid(
            row=0, column=1, sticky="e", padx=8, pady=8
        )

        self._bind_dirty_var("settings", self.settings_dark_mode_var)
        self._bind_dirty_var("settings", self.settings_colorblind_mode_var)
        self._bind_dirty_var("settings", self.settings_font_scale_var)
        self._bind_dirty_var("settings", self.settings_density_var)
        self._bind_dirty_var("settings", self.settings_ui_profile_var)
        self._refresh_settings_profile_controls()
        self._refresh_full_backup_list()
        self._refresh_section_backup_list()
        self._mark_dirty("settings", False)

    def _clear_treeview(self, tree: ttk.Treeview | None) -> None:
        if tree is None:
            return
        for item in tree.get_children():
            tree.delete(item)

    @staticmethod
    def _format_analytics_time(value) -> str:
        if value is None:
            return "-"
        if hasattr(value, "strftime"):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return str(value)

    def _build_chat_analytics_tab(self, parent: ttk.Frame):
        container = ttk.Frame(parent)
        container.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(2, weight=1)
        container.rowconfigure(3, weight=1)

        controls = ttk.LabelFrame(container, text="Source")
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        controls.columnconfigure(1, weight=1)

        ttk.Label(controls, text="Chat log file").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(controls, textvariable=self.analytics_log_path_var).grid(
            row=0, column=1, sticky="ew", padx=8, pady=8
        )
        ttk.Button(controls, text="Refresh Analytics", command=self._refresh_chat_analytics).grid(
            row=0, column=2, sticky="e", padx=8, pady=8
        )
        ttk.Label(controls, text="Username filter").grid(row=1, column=0, sticky="w", padx=8, pady=8)
        username_filter = ttk.Entry(controls, textvariable=self.analytics_username_filter_var)
        username_filter.grid(row=1, column=1, sticky="ew", padx=8, pady=8)
        username_filter.bind("<KeyRelease>", lambda _event: self._refresh_analytics_chatlog_view())
        self.analytics_username_filter_entry = username_filter
        ttk.Button(controls, text="Apply Filter", command=self._refresh_analytics_chatlog_view).grid(
            row=1, column=2, sticky="e", padx=8, pady=8
        )
        ttk.Label(controls, text="Keyword").grid(row=2, column=0, sticky="w", padx=8, pady=8)
        keyword_entry = ttk.Entry(controls, textvariable=self.analytics_keyword_filter_var)
        keyword_entry.grid(row=2, column=1, sticky="ew", padx=8, pady=8)
        keyword_entry.bind("<KeyRelease>", lambda _event: self._refresh_analytics_chatlog_view())
        ttk.Button(controls, text="Apply", command=self._refresh_analytics_chatlog_view).grid(
            row=2, column=2, sticky="e", padx=8, pady=8
        )
        ttk.Label(controls, text="Time window").grid(row=3, column=0, sticky="w", padx=8, pady=8)
        window_combo = ttk.Combobox(
            controls,
            textvariable=self.analytics_time_window_var,
            values=["All", "15m", "1h", "6h", "24h"],
            state="readonly",
            width=10,
        )
        window_combo.grid(row=3, column=1, sticky="w", padx=8, pady=8)
        window_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_analytics_chatlog_view())
        ttk.Checkbutton(
            controls,
            text="Highlights only",
            variable=self.analytics_highlights_only_var,
            command=self._refresh_analytics_chatlog_view,
        ).grid(row=3, column=2, sticky="e", padx=8, pady=8)

        summary = ttk.LabelFrame(container, text="Summary")
        summary.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        for idx in range(4):
            summary.columnconfigure(idx, weight=1)

        ttk.Label(summary, text="Total messages").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Label(summary, textvariable=self.analytics_total_var).grid(row=1, column=0, sticky="w", padx=8, pady=6)
        ttk.Label(summary, text="Unique users").grid(row=0, column=1, sticky="w", padx=8, pady=6)
        ttk.Label(summary, textvariable=self.analytics_unique_var).grid(row=1, column=1, sticky="w", padx=8, pady=6)
        ttk.Label(summary, text="First message").grid(row=0, column=2, sticky="w", padx=8, pady=6)
        ttk.Label(summary, textvariable=self.analytics_first_var).grid(row=1, column=2, sticky="w", padx=8, pady=6)
        ttk.Label(summary, text="Last message").grid(row=0, column=3, sticky="w", padx=8, pady=6)
        ttk.Label(summary, textvariable=self.analytics_last_var).grid(row=1, column=3, sticky="w", padx=8, pady=6)

        detail_frame = ttk.Frame(container)
        detail_frame.grid(row=2, column=0, sticky="nsew")
        detail_frame.columnconfigure(0, weight=1)
        detail_frame.columnconfigure(1, weight=2)
        detail_frame.rowconfigure(0, weight=1)

        users_frame = ttk.LabelFrame(detail_frame, text="Most Active Users")
        users_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        users_frame.rowconfigure(0, weight=1)
        users_frame.columnconfigure(0, weight=1)

        users_tree = ttk.Treeview(
            users_frame,
            columns=("username", "count"),
            show="headings",
            height=16,
        )
        users_tree.heading("username", text="Username")
        users_tree.heading("count", text="Messages")
        users_tree.column("username", width=180, anchor="w")
        users_tree.column("count", width=100, anchor="center")
        users_tree.grid(row=0, column=0, sticky="nsew")

        users_scroll = ttk.Scrollbar(users_frame, orient=tk.VERTICAL, command=users_tree.yview)
        users_scroll.grid(row=0, column=1, sticky="ns")
        users_tree.configure(yscrollcommand=users_scroll.set)
        self.analytics_users_tree = users_tree

        highlights_frame = ttk.LabelFrame(detail_frame, text="Highlights")
        highlights_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        highlights_frame.rowconfigure(0, weight=1)
        highlights_frame.columnconfigure(0, weight=1)

        highlights_tree = ttk.Treeview(
            highlights_frame,
            columns=("time", "username", "score", "message"),
            show="headings",
            height=16,
        )
        highlights_tree.heading("time", text="Time")
        highlights_tree.heading("username", text="Username")
        highlights_tree.heading("score", text="Score")
        highlights_tree.heading("message", text="Message")
        highlights_tree.column("time", width=150, anchor="w")
        highlights_tree.column("username", width=130, anchor="w")
        highlights_tree.column("score", width=80, anchor="center")
        highlights_tree.column("message", width=560, anchor="w")
        highlights_tree.grid(row=0, column=0, sticky="nsew")

        highlights_scroll = ttk.Scrollbar(highlights_frame, orient=tk.VERTICAL, command=highlights_tree.yview)
        highlights_scroll.grid(row=0, column=1, sticky="ns")
        highlights_tree.configure(yscrollcommand=highlights_scroll.set)
        self.analytics_highlights_tree = highlights_tree

        chatlog_frame = ttk.LabelFrame(container, text="Chat Log")
        chatlog_frame.grid(row=3, column=0, sticky="nsew", pady=(8, 0))
        chatlog_frame.columnconfigure(0, weight=1)
        chatlog_frame.rowconfigure(0, weight=1)

        chatlog_tree = ttk.Treeview(
            chatlog_frame,
            columns=("time", "username", "message"),
            show="headings",
            height=14,
        )
        chatlog_tree.heading("time", text="Time")
        chatlog_tree.heading("username", text="Username")
        chatlog_tree.heading("message", text="Message")
        chatlog_tree.column("time", width=150, anchor="w")
        chatlog_tree.column("username", width=140, anchor="w")
        chatlog_tree.column("message", width=860, anchor="w")
        chatlog_tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)

        chatlog_scroll = ttk.Scrollbar(chatlog_frame, orient=tk.VERTICAL, command=chatlog_tree.yview)
        chatlog_scroll.grid(row=0, column=1, sticky="ns", padx=(0, 8), pady=8)
        chatlog_tree.configure(yscrollcommand=chatlog_scroll.set)
        self.analytics_chatlog_tree = chatlog_tree

        self._refresh_chat_analytics()

    def _refresh_chat_analytics(self):
        path_text = self.analytics_log_path_var.get().strip() or Paths.CHAT_LOG
        resolved_path = resolve_existing_path(path_text)
        self.analytics_log_path_var.set(str(resolved_path))
        self.ui_state.setdefault("filters", {})["analytics_log_path"] = str(resolved_path)

        try:
            messages = load_chat_log(str(resolved_path))
            self._clear_treeview(self.analytics_users_tree)
            self._clear_treeview(self.analytics_highlights_tree)
            self.analytics_chat_messages_cache = messages if isinstance(messages, list) else []

            if not messages:
                self.analytics_total_var.set("0")
                self.analytics_unique_var.set("0")
                self.analytics_first_var.set("-")
                self.analytics_last_var.set("-")
                self._clear_treeview(self.analytics_chatlog_tree)
                self.log_queue.put(f"[analytics] no chat data found at {resolved_path}")
                self._set_status("No chat analytics data found.", "warn")
                return

            stats = analyze_activity(messages)
            highlights = find_highlights(messages)

            self.analytics_total_var.set(str(stats.get("total_messages", 0)))
            self.analytics_unique_var.set(str(stats.get("unique_users", 0)))
            self.analytics_first_var.set(self._format_analytics_time(stats.get("first_message")))
            self.analytics_last_var.set(self._format_analytics_time(stats.get("last_message")))

            for username, count in stats.get("most_active", []):
                if self.analytics_users_tree is not None:
                    self.analytics_users_tree.insert("", tk.END, values=(username, count))

            for item in highlights:
                timestamp = self._format_analytics_time(item.get("time"))
                username = item.get("username", "")
                score = item.get("excitement_score", 0)
                message = str(item.get("message", "")).replace("\n", " ").strip()
                if self.analytics_highlights_tree is not None:
                    self.analytics_highlights_tree.insert(
                        "",
                        tk.END,
                        values=(timestamp, username, score, message),
                    )

            self._refresh_analytics_chatlog_view()
            self.log_queue.put(
                f"[analytics] loaded {len(messages)} messages, {len(highlights)} highlights from {resolved_path}"
            )
            self._set_status("Chat analytics refreshed.", "ok")
        except Exception as e:
            self.analytics_total_var.set("error")
            self.analytics_unique_var.set("error")
            self.analytics_first_var.set("-")
            self.analytics_last_var.set("-")
            self._clear_treeview(self.analytics_users_tree)
            self._clear_treeview(self.analytics_highlights_tree)
            self._clear_treeview(self.analytics_chatlog_tree)
            self.log_queue.put(f"[analytics] refresh failed: {e}")
            self._set_status(f"Chat analytics refresh failed: {e}", "error")
            messagebox.showerror("Chat Analytics", f"Failed to load analytics: {e}")

    # ---- Data Editor tab ---------------------------------------------------

    def _build_data_editor_tab(self, parent: ttk.Frame):
        inner = ttk.Notebook(parent)
        inner.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        messages_tab = ttk.Frame(inner)
        commands_tab = ttk.Frame(inner)
        users_tab = ttk.Frame(inner)
        data_tab = ttk.Frame(inner)

        inner.add(messages_tab, text="Messages")
        inner.add(commands_tab, text="Commands")
        inner.add(users_tab, text="Users")
        inner.add(data_tab, text="Data")

        # Messages sub-tabs
        messages_inner = ttk.Notebook(messages_tab)
        messages_inner.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        cooldown_tab = ttk.Frame(messages_inner)
        fallback_tab = ttk.Frame(messages_inner)
        command_messages_tab = ttk.Frame(messages_inner)
        messages_inner.add(cooldown_tab, text="Cooldown")
        messages_inner.add(fallback_tab, text="Fallback Flirts")
        messages_inner.add(command_messages_tab, text="Command Fallbacks")

        # Data sub-tabs
        data_inner = ttk.Notebook(data_tab)
        data_inner.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        themes_tab = ttk.Frame(data_inner)
        tones_tab = ttk.Frame(data_inner)
        moods_tab = ttk.Frame(data_inner)
        data_inner.add(themes_tab, text="Themes")
        data_inner.add(tones_tab, text="Tones")
        data_inner.add(moods_tab, text="Moods")

        # Users sub-tabs
        users_note = ttk.LabelFrame(
            users_tab,
            text="Tier Resolution",
        )
        users_note.pack(fill=tk.X, padx=12, pady=(12, 6))
        ttk.Label(
            users_note,
            text=(
                "Broadcaster is automatic from config monitor.twitch_channel.\n"
                "Define only Normal, VIP, and Moderator users here."
            ),
            justify=tk.LEFT,
        ).pack(anchor="w", padx=10, pady=8)

        users_inner = ttk.Notebook(users_tab)
        users_inner.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        normal_users_tab = ttk.Frame(users_inner)
        vip_users_tab = ttk.Frame(users_inner)
        moderator_users_tab = ttk.Frame(users_inner)
        owner_tab = ttk.Frame(users_inner)
        users_inner.add(normal_users_tab, text="Normal")
        users_inner.add(vip_users_tab, text="VIP")
        users_inner.add(moderator_users_tab, text="Moderators")
        users_inner.add(owner_tab, text="Owner")

        self._build_tool_cooldown_editor(cooldown_tab)
        self._build_list_editor(
            fallback_tab,
            load_fn=lambda: load_json(Paths.FALLBACK_FLIRTS, default={}).get("fallback_flirts", []),
            save_fn=lambda items: atomic_write_json(Paths.FALLBACK_FLIRTS, {"fallback_flirts": items}),
            source_path=Paths.FALLBACK_FLIRTS,
            item_label="Fallback Flirt",
        )
        self._build_kv_editor(
            themes_tab,
            path=Paths.THEMES,
            fields=[
                ("Key", "key"),
                ("Folder", "category"),
                ("Tags (comma separated)", "tags"),
                ("Description", "description"),
            ],
            anchors_field="anchors",
            group_field="category",
            group_label="Folder",
            tags_field="tags",
            tags_label="Tag",
            list_fields={"tags"},
            grouped_tree=True,
        )
        self._build_kv_editor(
            tones_tab,
            path=Paths.TONES,
            fields=[
                ("Key", "key"),
                ("Folder", "category"),
                ("Tags (comma separated)", "tags"),
                ("Description", "description"),
            ],
            anchors_field="anchors",
            group_field="category",
            group_label="Folder",
            tags_field="tags",
            tags_label="Tag",
            list_fields={"tags"},
            grouped_tree=True,
        )
        self._build_moods_editor(moods_tab)
        self._build_kv_editor(
            commands_tab,
            path=Paths.COMMANDS,
            fields=[
                ("Key", "key"),
                ("URL", "url"),
                ("Minimum Tier", "min_level"),
                ("Description", "description"),
                ("Context", "context"),
                ("Usage", "usage"),
                ("Response Data", "response_data"),
            ],
            anchors_field="aliases",
            anchors_label="Aliases",
            group_field="min_level",
            group_label="Minimum Tier",
            grouped_tree=True,
        )
        self._build_list_editor(
            normal_users_tab,
            load_fn=lambda: self._load_command_access_list("normal_users"),
            save_fn=lambda items: self._save_command_access_list("normal_users", items),
            hint="Users listed here are explicitly marked normal. Users not in VIP/Moderator default to normal anyway.",
            source_path=f"{Paths.COMMAND_ACCESS}#normal_users",
            item_label="Username",
        )
        self._build_list_editor(
            vip_users_tab,
            load_fn=lambda: self._load_command_access_list("vip_users"),
            save_fn=lambda items: self._save_command_access_list("vip_users", items),
            hint="Any username listed here receives VIP command permissions.",
            source_path=f"{Paths.COMMAND_ACCESS}#vip_users",
            item_label="Username",
        )
        self._build_list_editor(
            moderator_users_tab,
            load_fn=lambda: self._load_command_access_list("moderator_users"),
            save_fn=lambda items: self._save_command_access_list("moderator_users", items),
            hint="Any username listed here receives Moderator command permissions.",
            source_path=f"{Paths.COMMAND_ACCESS}#moderator_users",
            item_label="Username",
        )
        self._build_owner_profile_editor(owner_tab)

        messages_frame = ttk.LabelFrame(command_messages_tab, text="Command Fallback Messages")
        messages_frame.pack(fill=tk.X, padx=12, pady=12)
        messages_frame.columnconfigure(1, weight=1)

        defaults = {
            "permission_denied_message": "@{username} - !{command} requires {min_level} access.",
            "unknown_command_message": "@{username} - I do not have !{command} configured yet.",
            "invalid_input_message": "@{username} - use a command like !social, !discord, or !about.",
        }

        message_vars = {
            "permission_denied_message": tk.StringVar(value=""),
            "unknown_command_message": tk.StringVar(value=""),
            "invalid_input_message": tk.StringVar(value=""),
        }

        labels = [
            ("Permission denied", "permission_denied_message"),
            ("Unknown command", "unknown_command_message"),
            ("Invalid input", "invalid_input_message"),
        ]
        for row_i, (label, key) in enumerate(labels):
            ttk.Label(messages_frame, text=label).grid(row=row_i, column=0, sticky="w", padx=8, pady=6)
            ttk.Entry(messages_frame, textvariable=message_vars[key], width=96).grid(
                row=row_i, column=1, sticky="we", padx=8, pady=6
            )

        ttk.Label(
            messages_frame,
            text="Available placeholders: {username}, {command}, {min_level}, {user_level}",
            foreground="gray",
        ).grid(row=len(labels), column=0, columnspan=2, sticky="w", padx=8, pady=(4, 8))

        def _load_command_messages():
            payload = self._load_command_access()
            for key, default_value in defaults.items():
                message_vars[key].set(str(payload.get(key, default_value)))

        def _save_command_messages():
            payload = self._load_command_access()
            for key, default_value in defaults.items():
                payload[key] = message_vars[key].get().strip() or default_value
            self._save_command_access(payload)
            self.log_queue.put("[data editor] saved command fallback messages")
            messagebox.showinfo("Saved", "Command messages saved.", parent=self.root)

        actions = ttk.Frame(command_messages_tab)
        actions.pack(anchor="w", padx=12, pady=(0, 12))
        ttk.Button(actions, text="Reload", command=_load_command_messages).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(actions, text="Save", command=_save_command_messages).pack(side=tk.LEFT)

        _load_command_messages()

    def _build_moods_editor(self, parent: ttk.Frame):
        payload_store: dict = {"default_mood": "neutral", "moods": {}}
        visible_keys: list[str] = []
        key_to_node: dict[str, str] = {}
        folder_node_to_name: dict[str, str] = {}
        group_open_state: dict[str, bool] = {}
        suspend_dirty: dict[str, bool] = {"value": False}

        container = ttk.Frame(parent)
        container.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)

        top = ttk.LabelFrame(container, text="Mood Defaults")
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        top.columnconfigure(1, weight=1)

        default_mood_var = tk.StringVar(value="neutral")
        ttk.Label(top, text="Default mood").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        default_mood_combo = ttk.Combobox(top, textvariable=default_mood_var, state="readonly", width=24)
        default_mood_combo.grid(row=0, column=1, sticky="w", padx=8, pady=8)
        ttk.Label(
            top,
            text="This mood is used as safe fallback when no active session mood is available.",
            foreground=self.theme_palette["text_subtle"],
        ).grid(row=0, column=2, sticky="w", padx=8, pady=8)

        pane = ttk.PanedWindow(container, orient=tk.HORIZONTAL)
        pane.grid(row=1, column=0, sticky="nsew")

        left = ttk.Frame(pane)
        pane.add(left, weight=1)
        right = ttk.Frame(pane)
        pane.add(right, weight=2)

        filter_frame = ttk.LabelFrame(left, text="Filter")
        filter_frame.pack(fill=tk.X, padx=4, pady=(4, 2))
        filter_frame.columnconfigure(1, weight=1)
        search_var = tk.StringVar(value="")
        ttk.Label(filter_frame, text="Search").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(filter_frame, textvariable=search_var, width=24).grid(row=0, column=1, sticky="we", padx=8, pady=4)

        folder_var = tk.StringVar(value="All")
        ttk.Label(filter_frame, text="Folder").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        folder_combo = ttk.Combobox(filter_frame, textvariable=folder_var, values=["All"], state="readonly", width=24)
        folder_combo.grid(row=1, column=1, sticky="we", padx=8, pady=4)

        grouped_view_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            filter_frame,
            text="Group moods by folder (collapsible)",
            variable=grouped_view_var,
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=8, pady=(2, 2))

        stats_var = tk.StringVar(value="0 moods")
        ttk.Label(filter_frame, textvariable=stats_var, foreground="gray").grid(
            row=3, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 4)
        )

        keys_frame = ttk.LabelFrame(left, text="Mood Keys")
        keys_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        tree_container = ttk.Frame(keys_frame)
        tree_container.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        tree = ttk.Treeview(tree_container, show="tree", selectmode="browse", height=18)
        tree_scroll = ttk.Scrollbar(tree_container, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=tree_scroll.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        form = ttk.LabelFrame(right, text="Edit Mood")
        form.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        form.columnconfigure(1, weight=1)
        form.rowconfigure(4, weight=1)
        form.rowconfigure(5, weight=1)
        form.rowconfigure(6, weight=1)

        key_var = tk.StringVar(value="")
        folder_edit_var = tk.StringVar(value="")
        weight_var = tk.StringVar(value="1")
        description_var = tk.StringVar(value="")

        ttk.Label(form, text="Mood key").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(form, textvariable=key_var, width=30).grid(row=0, column=1, sticky="we", padx=8, pady=4)

        ttk.Label(form, text="Folder").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        folder_edit_combo = ttk.Combobox(form, textvariable=folder_edit_var, width=30)
        folder_edit_combo.grid(row=1, column=1, sticky="w", padx=8, pady=4)

        ttk.Label(form, text="Weight").grid(row=2, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(form, textvariable=weight_var, width=12).grid(row=2, column=1, sticky="w", padx=8, pady=4)

        ttk.Label(form, text="Description").grid(row=3, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(form, textvariable=description_var, width=72).grid(row=3, column=1, sticky="we", padx=8, pady=4)

        ttk.Label(form, text="Monitor guidance").grid(row=4, column=0, sticky="nw", padx=8, pady=4)
        monitor_guidance_text = tk.Text(form, wrap=tk.WORD, height=5)
        monitor_guidance_text.grid(row=4, column=1, sticky="nsew", padx=8, pady=4)
        self._register_text_widget(monitor_guidance_text)

        ttk.Label(form, text="Flirt guidance").grid(row=5, column=0, sticky="nw", padx=8, pady=4)
        flirt_guidance_text = tk.Text(form, wrap=tk.WORD, height=5)
        flirt_guidance_text.grid(row=5, column=1, sticky="nsew", padx=8, pady=4)
        self._register_text_widget(flirt_guidance_text)

        ttk.Label(form, text="Tarot guidance").grid(row=6, column=0, sticky="nw", padx=8, pady=4)
        tarot_guidance_text = tk.Text(form, wrap=tk.WORD, height=5)
        tarot_guidance_text.grid(row=6, column=1, sticky="nsew", padx=8, pady=4)
        self._register_text_widget(tarot_guidance_text)

        selected_key_state: dict[str, str] = {"value": ""}

        def _extract_guidance(widget: tk.Text) -> str:
            return widget.get("1.0", tk.END).strip()

        def _set_guidance(widget: tk.Text, value: str) -> None:
            widget.delete("1.0", tk.END)
            widget.insert("1.0", str(value or ""))

        def _validate_payload(data: dict) -> tuple[bool, str]:
            moods = data.get("moods", {})
            if not isinstance(moods, dict) or not moods:
                return False, "At least one mood must exist."
            default_mood = str(data.get("default_mood", "")).strip().lower()
            if default_mood not in moods:
                return False, "Default mood must exist in moods."
            has_positive_weight = False
            for key, entry in moods.items():
                if not str(key).strip():
                    return False, "Mood key cannot be empty."
                if not isinstance(entry, dict):
                    return False, f"Mood '{key}' must be an object."
                try:
                    weight = int(entry.get("weight", 0))
                except Exception:
                    return False, f"Mood '{key}' has invalid weight."
                if weight < 0:
                    return False, f"Mood '{key}' weight must be >= 0."
                if weight > 0:
                    has_positive_weight = True
            if not has_positive_weight:
                return False, "At least one mood must have weight > 0."
            return True, ""

        def _persist(show_dialog: bool = False) -> bool:
            normalized = load_moods_from_payload(payload_store)
            ok, error_message = _validate_payload(normalized)
            if not ok:
                messagebox.showwarning("Validation", error_message, parent=self.root)
                self._set_status(f"Moods validation failed: {error_message}", "warn")
                return False
            atomic_write_json(Paths.MOODS, normalized)
            payload_store["default_mood"] = normalized["default_mood"]
            payload_store["moods"] = normalized["moods"]
            self.log_queue.put("[data editor] moods saved")
            self._set_status("Moods saved.", "ok")
            self._mark_dirty("data", False)
            if show_dialog:
                messagebox.showinfo("Saved", "Moods saved.", parent=self.root)
            return True

        def _set_dirty_tracking(active: bool) -> None:
            suspend_dirty["value"] = bool(active)

        def _set_form_fields(
            key_value: str,
            folder_value: str,
            weight_value: str,
            description_value: str,
            monitor_guidance: str,
            flirt_guidance: str,
            tarot_guidance: str,
        ) -> None:
            _set_dirty_tracking(True)
            try:
                key_var.set(key_value)
                folder_edit_var.set(folder_value)
                weight_var.set(weight_value)
                description_var.set(description_value)
                _set_guidance(monitor_guidance_text, monitor_guidance)
                _set_guidance(flirt_guidance_text, flirt_guidance)
                _set_guidance(tarot_guidance_text, tarot_guidance)
            finally:
                _set_dirty_tracking(False)

        def _update_default_combo():
            mood_keys = sorted(payload_store.get("moods", {}).keys(), key=str.lower)
            default_mood_combo["values"] = mood_keys
            current_default = str(payload_store.get("default_mood", "neutral")).strip().lower()
            if current_default not in mood_keys and mood_keys:
                current_default = mood_keys[0]
            if not current_default:
                current_default = "neutral"
            _set_dirty_tracking(True)
            try:
                default_mood_var.set(current_default)
            finally:
                _set_dirty_tracking(False)
            payload_store["default_mood"] = current_default

        def _update_folder_options():
            folders: set[str] = set()
            has_unfiled = False
            for entry in payload_store.get("moods", {}).values():
                mood_entry = entry if isinstance(entry, dict) else {}
                folder_name = str(mood_entry.get("folder", "")).strip()
                if folder_name:
                    folders.add(folder_name)
                else:
                    has_unfiled = True

            sorted_folders = sorted(folders, key=str.lower)
            folder_values = ["All", *sorted_folders]
            if has_unfiled:
                folder_values.append("(Unfiled)")
            if folder_var.get().strip() not in folder_values:
                folder_var.set("All")
            folder_combo["values"] = folder_values
            folder_edit_combo["values"] = sorted_folders

        def _selected_key() -> str:
            selected = tree.selection()
            if not selected:
                return ""
            node_id = selected[0]
            return next((k for k, node in key_to_node.items() if node == node_id), "")

        def _remember_group_open_state():
            for node_id, folder_name in list(folder_node_to_name.items()):
                if tree.exists(node_id):
                    group_open_state[folder_name] = bool(tree.item(node_id, "open"))

        def _refresh_keys(select_key: str | None = None):
            query = search_var.get().strip().lower()
            selected_folder = folder_var.get().strip()
            grouped = bool(grouped_view_var.get() and selected_folder == "All")
            _remember_group_open_state()
            tree.delete(*tree.get_children())
            key_to_node.clear()
            folder_node_to_name.clear()
            visible_keys.clear()
            grouped_map: dict[str, list[str]] = {}

            for key in sorted(payload_store.get("moods", {}).keys(), key=str.lower):
                entry = payload_store.get("moods", {}).get(key, {})
                folder_name = str(entry.get("folder", "")).strip()
                description = str(entry.get("description", "")).strip()
                haystack = f"{key} {folder_name} {description}".lower()
                if query and query not in haystack:
                    continue
                if selected_folder == "(Unfiled)" and folder_name:
                    continue
                if selected_folder not in {"All", "(Unfiled)"} and folder_name.lower() != selected_folder.lower():
                    continue
                visible_keys.append(key)
                if grouped:
                    group_name = folder_name or "(Unfiled)"
                    grouped_map.setdefault(group_name, []).append(key)
                else:
                    node = tree.insert("", tk.END, text=f"\u2022  {key}")
                    key_to_node[key] = node

            if grouped:
                for folder_name in sorted(grouped_map.keys(), key=str.lower):
                    keys = sorted(grouped_map[folder_name], key=str.lower)
                    parent_id = tree.insert(
                        "",
                        tk.END,
                        text=f"\U0001F4C1  {folder_name} ({len(keys)})",
                        open=group_open_state.get(folder_name, True),
                    )
                    folder_node_to_name[parent_id] = folder_name
                    for key in keys:
                        node = tree.insert(parent_id, tk.END, text=f"    {key}")
                        key_to_node[key] = node

            total = len(payload_store.get("moods", {}))
            if grouped:
                stats_var.set(f"{len(visible_keys)} shown in {len(grouped_map)} folders / {total} total")
            else:
                stats_var.set(f"{len(visible_keys)} shown / {total} total")
            target = select_key or selected_key_state["value"]
            if target and target in key_to_node:
                node = key_to_node[target]
                tree.selection_set(node)
                tree.focus(node)
                tree.see(node)

        def _load():
            payload = load_moods(Paths.MOODS)
            payload_store["default_mood"] = payload.get("default_mood", "neutral")
            payload_store["moods"] = payload.get("moods", {})
            selected_key_state["value"] = ""
            _update_default_combo()
            _update_folder_options()
            _refresh_keys()
            _new()
            self._mark_dirty("data", False)

        def _on_select(_event=None):
            key = _selected_key()
            if not key:
                return
            selected_key_state["value"] = key
            entry = payload_store.get("moods", {}).get(key, {})
            _set_form_fields(
                key,
                str(entry.get("folder", "")).strip(),
                str(entry.get("weight", 0)),
                str(entry.get("description", "")),
                str(entry.get("monitor_guidance", "")),
                str(entry.get("flirt_guidance", "")),
                str(entry.get("tarot_guidance", "")),
            )

        def _new():
            tree.selection_remove(tree.selection())
            selected_key_state["value"] = ""
            selected_folder = folder_var.get().strip()
            folder_value = "" if selected_folder in {"All", "(Unfiled)"} else selected_folder
            _set_form_fields("", folder_value, "1", "", "", "", "")

        def _save_selected():
            raw_key = key_var.get().strip().lower()
            if not raw_key:
                messagebox.showwarning("Save", "Mood key cannot be empty.", parent=self.root)
                return
            try:
                weight = int(weight_var.get().strip() or "0")
            except Exception:
                messagebox.showwarning("Save", "Weight must be an integer.", parent=self.root)
                return
            if weight < 0:
                messagebox.showwarning("Save", "Weight must be >= 0.", parent=self.root)
                return

            old_key = selected_key_state["value"]
            moods = payload_store.get("moods", {})
            if old_key and old_key != raw_key:
                moods.pop(old_key, None)
                if payload_store.get("default_mood", "") == old_key:
                    payload_store["default_mood"] = raw_key

            moods[raw_key] = {
                "weight": weight,
                "folder": folder_edit_var.get().strip(),
                "description": description_var.get().strip(),
                "monitor_guidance": _extract_guidance(monitor_guidance_text),
                "flirt_guidance": _extract_guidance(flirt_guidance_text),
                "tarot_guidance": _extract_guidance(tarot_guidance_text),
            }
            payload_store["moods"] = moods
            selected_key_state["value"] = raw_key
            if not default_mood_var.get().strip():
                payload_store["default_mood"] = raw_key
            _update_default_combo()
            if not _persist(show_dialog=False):
                return
            _update_folder_options()
            _refresh_keys(select_key=raw_key)

        def _delete_selected():
            key = selected_key_state["value"]
            if not key:
                return
            if not messagebox.askyesno("Delete", f"Delete mood '{key}'?", parent=self.root):
                return
            moods = payload_store.get("moods", {})
            moods.pop(key, None)
            payload_store["moods"] = moods
            selected_key_state["value"] = ""
            if payload_store.get("default_mood", "") == key:
                remaining = sorted(moods.keys(), key=str.lower)
                payload_store["default_mood"] = remaining[0] if remaining else ""
            _update_default_combo()
            if not _persist(show_dialog=False):
                return
            _update_folder_options()
            _new()
            _refresh_keys()

        def _save_all():
            payload_store["default_mood"] = default_mood_var.get().strip().lower()
            if _persist(show_dialog=True):
                _update_default_combo()
                _update_folder_options()
                _refresh_keys(select_key=selected_key_state["value"] or None)

        def _on_default_change(_event=None):
            payload_store["default_mood"] = default_mood_var.get().strip().lower()
            if suspend_dirty["value"]:
                return
            self._mark_dirty("data", True)

        def _on_tree_open_close(_event=None):
            node_id = tree.focus()
            folder_name = folder_node_to_name.get(node_id)
            if folder_name is None:
                return
            group_open_state[folder_name] = bool(tree.item(node_id, "open"))

        tree.bind("<<TreeviewSelect>>", _on_select)
        tree.bind("<<TreeviewOpen>>", _on_tree_open_close)
        tree.bind("<<TreeviewClose>>", _on_tree_open_close)
        search_var.trace_add("write", lambda *_args: _refresh_keys())
        folder_combo.bind("<<ComboboxSelected>>", lambda _event: _refresh_keys())
        grouped_view_var.trace_add("write", lambda *_args: _refresh_keys())
        default_mood_combo.bind("<<ComboboxSelected>>", _on_default_change)
        for var in (key_var, folder_edit_var, weight_var, description_var):
            var.trace_add("write", lambda *_args: (None if suspend_dirty["value"] else self._mark_dirty("data", True)))
        for widget in (monitor_guidance_text, flirt_guidance_text, tarot_guidance_text):
            widget.bind("<KeyRelease>", lambda _event: self._mark_dirty("data", True))

        actions = ttk.Frame(right)
        actions.pack(anchor="w", padx=4, pady=4)
        ttk.Button(actions, text="Reload", command=_load).pack(side=tk.LEFT, padx=4)
        ttk.Button(actions, text="New", command=_new).pack(side=tk.LEFT, padx=4)
        ttk.Button(actions, text="Save Selected", command=_save_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(actions, text="Delete Selected", command=_delete_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(actions, text="Save All to File", command=_save_all).pack(side=tk.LEFT, padx=12)

        _load()

    def _build_owner_profile_editor(self, parent: ttk.Frame):
        frame = ttk.LabelFrame(parent, text="Owner Profile Context")
        frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(4, weight=1)

        owner_username_var = tk.StringVar()
        owner_name_var = tk.StringVar()
        owner_pronouns_var = tk.StringVar()
        owner_role_var = tk.StringVar()

        ttk.Label(frame, text="Username").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(frame, textvariable=owner_username_var, width=40).grid(row=0, column=1, sticky="we", padx=8, pady=6)

        ttk.Label(frame, text="Name").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(frame, textvariable=owner_name_var, width=40).grid(row=1, column=1, sticky="we", padx=8, pady=6)

        ttk.Label(frame, text="Pronouns").grid(row=2, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(frame, textvariable=owner_pronouns_var, width=40).grid(row=2, column=1, sticky="we", padx=8, pady=6)

        ttk.Label(frame, text="Role / Identity").grid(row=3, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(frame, textvariable=owner_role_var, width=40).grid(row=3, column=1, sticky="we", padx=8, pady=6)

        ttk.Label(frame, text="Context / Lore").grid(row=4, column=0, sticky="nw", padx=8, pady=6)
        lore_text = tk.Text(frame, wrap=tk.WORD, height=10)
        lore_text.grid(row=4, column=1, sticky="nsew", padx=8, pady=6)
        self._register_text_widget(lore_text)

        ttk.Label(
            frame,
            text=(
                "Context/Lore can include nicknames, recurring jokes, boundaries, vibe, and anything "
                "Mai should remember for owner-specific replies."
            ),
            foreground=self.theme_palette["text_subtle"],
            justify=tk.LEFT,
        ).grid(row=5, column=0, columnspan=2, sticky="w", padx=8, pady=(2, 8))
        ttk.Label(frame, textvariable=self.owner_last_changed_var, foreground=self.theme_palette["text_subtle"]).grid(
            row=6, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8)
        )

        self._owner_profile_editor_vars = {
            "username": owner_username_var,
            "name": owner_name_var,
            "pronouns": owner_pronouns_var,
            "role_identity": owner_role_var,
        }
        self._owner_profile_editor_lore_widget = lore_text
        for var in (owner_username_var, owner_name_var, owner_pronouns_var, owner_role_var):
            self._bind_dirty_var("data", var)
        lore_text.bind("<KeyRelease>", lambda _event: self._mark_dirty("data", True))

        def _load_owner_profile():
            self._load_owner_profile_into_editor()
            self._set_status("Owner profile loaded.", "ok")

        def _save_owner_profile():
            try:
                cfg = load_json(self.config_path, default={})
                if not isinstance(cfg, dict):
                    cfg = {}

                monitor_cfg = cfg.get("monitor", {}) if isinstance(cfg.get("monitor", {}), dict) else {}
                owner_username = owner_username_var.get().strip().lower()
                if owner_username and not self._is_valid_username(owner_username):
                    messagebox.showwarning(
                        "Validation",
                        "Username may contain only letters, numbers, and underscore (2-25 chars).",
                        parent=self.root,
                    )
                    self._set_status("Owner profile validation failed.", "warn")
                    return
                if owner_username:
                    monitor_cfg["owner_username"] = owner_username
                cfg["monitor"] = monitor_cfg

                owner_profile = {
                    "username": owner_username,
                    "name": owner_name_var.get().strip(),
                    "pronouns": owner_pronouns_var.get().strip(),
                    "role_identity": owner_role_var.get().strip(),
                    "context_lore": lore_text.get("1.0", tk.END).strip(),
                }
                cfg["owner_profile"] = owner_profile
                ui_meta = cfg.get("ui_meta", {}) if isinstance(cfg.get("ui_meta", {}), dict) else {}
                ui_meta["last_changed_owner_profile_at"] = datetime.now().isoformat()
                cfg["ui_meta"] = ui_meta
                atomic_write_json(self.config_path, cfg)

                monitor_owner_var = self.monitor_vars.get("owner_username")
                if isinstance(monitor_owner_var, tk.StringVar):
                    monitor_owner_var.set(owner_username)
                    self._mark_dirty("monitor", False)

                self._load_owner_profile_into_editor()
                self._mark_dirty("data", False)
                self.log_queue.put("[data editor] owner profile saved")
                self._set_status("Owner profile saved.", "ok")
                messagebox.showinfo("Saved", "Owner profile saved.", parent=self.root)
            except Exception as e:
                self.log_queue.put(f"[data editor] owner profile save failed: {e}")
                self._set_status(f"Owner profile save failed: {e}", "error")
                messagebox.showerror("Save Failed", f"Could not save owner profile: {e}", parent=self.root)

        actions = ttk.Frame(parent)
        actions.pack(anchor="w", padx=12, pady=(0, 12))
        ttk.Button(actions, text="Reload", command=_load_owner_profile).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(actions, text="Save", command=_save_owner_profile).pack(side=tk.LEFT)

        self._load_owner_profile_into_editor()

    def _build_tool_cooldown_editor(self, parent: ttk.Frame):
        tools = ("flirt", "tarot")
        records: list[dict[str, str]] = []
        node_to_index: dict[str, int] = {}
        folder_node_to_name: dict[str, str] = {}
        scope_open_key = "list::tool_cooldowns::folder_open"
        raw_open_state = self.ui_state.setdefault("tree_open_state", {}).get(scope_open_key, {})
        group_open_state: dict[str, bool] = (
            {str(name): bool(is_open) for name, is_open in raw_open_state.items()}
            if isinstance(raw_open_state, dict)
            else {}
        )

        pane = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        left = ttk.Frame(pane)
        pane.add(left, weight=1)

        filter_frame = ttk.LabelFrame(left, text="Filter")
        filter_frame.pack(fill=tk.X, padx=4, pady=(4, 2))
        filter_frame.columnconfigure(1, weight=1)

        ttk.Label(
            filter_frame,
            text="{remaining} is replaced with cooldown seconds at runtime. Set Folder before adding new lines.",
            foreground="gray",
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 2))

        search_var = tk.StringVar(value="")
        folder_var = tk.StringVar(value="All")
        grouped_view_var = tk.BooleanVar(value=True)
        stats_var = tk.StringVar(value="0 shown / 0 total")

        ttk.Label(filter_frame, text="Search").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(filter_frame, textvariable=search_var, width=24).grid(row=1, column=1, sticky="we", padx=8, pady=4)

        ttk.Label(filter_frame, text="Folder").grid(row=2, column=0, sticky="w", padx=8, pady=4)
        folder_combo = ttk.Combobox(
            filter_frame,
            textvariable=folder_var,
            values=["All", "flirt", "tarot"],
            state="readonly",
            width=24,
        )
        folder_combo.grid(row=2, column=1, sticky="we", padx=8, pady=4)

        ttk.Checkbutton(
            filter_frame,
            text="Group items by folder (collapsible)",
            variable=grouped_view_var,
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=8, pady=(2, 4))

        ttk.Label(filter_frame, textvariable=stats_var, foreground="gray").grid(
            row=4, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 4)
        )

        list_frame = ttk.LabelFrame(left, text="Cooldown Messages")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        tree_actions = ttk.Frame(list_frame)
        tree_actions.pack(side=tk.TOP, fill=tk.X, padx=4, pady=(2, 4))
        expand_btn = ttk.Button(tree_actions, text="Expand All", width=12)
        collapse_btn = ttk.Button(tree_actions, text="Collapse All", width=12)
        expand_btn.pack(side=tk.LEFT, padx=(0, 6))
        collapse_btn.pack(side=tk.LEFT)

        list_inner = ttk.Frame(list_frame)
        list_inner.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        tree = ttk.Treeview(list_inner, show="tree", selectmode="browse", height=18)
        tree_scroll = ttk.Scrollbar(list_inner, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=tree_scroll.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        right = ttk.Frame(pane)
        pane.add(right, weight=2)

        form_frame = ttk.LabelFrame(right, text="Edit Entry")
        form_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        form_frame.columnconfigure(1, weight=1)
        form_frame.rowconfigure(0, weight=1)

        ttk.Label(form_frame, text="Cooldown Message").grid(row=0, column=0, sticky="nw", padx=8, pady=4)
        message_text = tk.Text(form_frame, width=56, height=8, wrap=tk.WORD)
        message_text.grid(row=0, column=1, sticky="nsew", padx=8, pady=4)
        self._register_text_widget(message_text)

        folder_value_var = tk.StringVar(value="flirt")
        ttk.Label(form_frame, text="Folder (tool, fixed)").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        folder_combo = ttk.Combobox(
            form_frame,
            textvariable=folder_value_var,
            values=["flirt", "tarot"],
            state="readonly",
            width=24,
        )
        folder_combo.grid(row=1, column=1, sticky="w", padx=8, pady=4)

        selected_index: dict[str, int | None] = {"value": None}

        def _persist_group_open_state():
            self.ui_state.setdefault("tree_open_state", {})[scope_open_key] = dict(group_open_state)
            try:
                self._save_ui_state()
            except Exception:
                pass

        def _remember_group_open_state():
            for node_id, folder_name in list(folder_node_to_name.items()):
                if tree.exists(node_id):
                    group_open_state[folder_name] = bool(tree.item(node_id, "open"))

        def _selected_row_index() -> int | None:
            selected = tree.selection()
            if not selected:
                return None
            return node_to_index.get(selected[0])

        def _set_group_open(is_open: bool):
            for node in tree.get_children(""):
                tree.item(node, open=is_open)
                folder_name = folder_node_to_name.get(node)
                if folder_name is not None:
                    group_open_state[folder_name] = bool(is_open)
            _persist_group_open_state()

        def _refresh(selected_idx: int | None = None):
            query = search_var.get().strip().lower()
            selected_folder = folder_var.get().strip()
            if selected_folder not in {"All", *tools}:
                selected_folder = "All"
                folder_var.set("All")
            grouped = bool(grouped_view_var.get() and selected_folder == "All")

            _remember_group_open_state()
            tree.delete(*tree.get_children())
            node_to_index.clear()
            folder_node_to_name.clear()

            visible_indices: list[int] = []
            grouped_map: dict[str, list[int]] = {}
            for idx, rec in enumerate(records):
                tool = str(rec.get("tool", "")).strip().lower()
                text = str(rec.get("text", "")).strip()
                if tool not in tools or not text:
                    continue
                if selected_folder != "All" and tool != selected_folder:
                    continue
                haystack = f"{tool} {text}".lower()
                if query and query not in haystack:
                    continue
                visible_indices.append(idx)
                if grouped:
                    grouped_map.setdefault(tool, []).append(idx)

            if grouped:
                for folder_name in sorted(grouped_map.keys(), key=str.lower):
                    ids = grouped_map[folder_name]
                    parent_id = tree.insert(
                        "",
                        tk.END,
                        text=f"\U0001F4C1  {folder_name} ({len(ids)})",
                        open=group_open_state.get(folder_name, True),
                    )
                    folder_node_to_name[parent_id] = folder_name
                    for idx in ids:
                        text_value = str(records[idx].get("text", "")).strip().replace("\n", " ")
                        preview = text_value if len(text_value) <= 96 else text_value[:93] + "..."
                        node_id = tree.insert(parent_id, tk.END, text=f"    {preview}")
                        node_to_index[node_id] = idx
            else:
                for idx in visible_indices:
                    text_value = str(records[idx].get("text", "")).strip().replace("\n", " ")
                    preview = text_value if len(text_value) <= 96 else text_value[:93] + "..."
                    node_id = tree.insert("", tk.END, text=f"\u2022  {preview}")
                    node_to_index[node_id] = idx

            if grouped:
                stats_var.set(f"{len(visible_indices)} shown in {len(grouped_map)} folders / {len(records)} total")
            else:
                stats_var.set(f"{len(visible_indices)} shown / {len(records)} total")

            target_idx = selected_idx if selected_idx is not None else selected_index["value"]
            if target_idx is not None:
                for node_id, idx in node_to_index.items():
                    if idx == target_idx:
                        tree.selection_set(node_id)
                        tree.focus(node_id)
                        tree.see(node_id)
                        break

            state = tk.NORMAL if grouped else tk.DISABLED
            expand_btn.configure(state=state)
            collapse_btn.configure(state=state)

        def _persist(show_dialog: bool = False) -> bool:
            try:
                payload = {tool: [] for tool in tools}
                for rec in records:
                    tool = str(rec.get("tool", "")).strip().lower()
                    text = str(rec.get("text", "")).strip()
                    if tool in payload and text:
                        payload[tool].append(text)

                save_tool_cooldown_map(payload, Paths.COOLDOWN_MSGS)
                self.log_queue.put("[data editor] saved tool cooldown messages")
                self._mark_dirty("data", False)
                if show_dialog:
                    messagebox.showinfo("Saved", "Cooldown messages saved.", parent=self.root)
                return True
            except Exception as e:
                messagebox.showerror("Save Error", str(e), parent=self.root)
                self._set_status(f"Cooldown save failed: {e}", "error")
                return False

        def _load():
            mapping = load_tool_cooldown_map(Paths.COOLDOWN_MSGS)
            records.clear()
            for tool in tools:
                for message in mapping.get(tool, []):
                    text = str(message).strip()
                    if text:
                        records.append({"tool": tool, "text": text})

            selected_index["value"] = None
            message_text.delete("1.0", tk.END)
            selected_folder = folder_var.get().strip().lower()
            folder_value_var.set(selected_folder if selected_folder in tools else "flirt")
            _refresh()

        def _on_select(_event=None):
            idx = _selected_row_index()
            selected_index["value"] = idx
            if idx is None:
                return
            rec = records[idx]
            message_text.delete("1.0", tk.END)
            message_text.insert(tk.END, str(rec.get("text", "")))
            folder_value_var.set(str(rec.get("tool", "flirt")))

        def _new():
            tree.selection_remove(tree.selection())
            selected_index["value"] = None
            message_text.delete("1.0", tk.END)
            selected_folder = folder_var.get().strip().lower()
            folder_value_var.set(selected_folder if selected_folder in tools else "flirt")

        def _save_selected():
            text = message_text.get("1.0", tk.END).strip()
            if not text:
                messagebox.showwarning("Save", "Cooldown message cannot be empty.", parent=self.root)
                return

            idx = selected_index.get("value")
            if idx is None:
                selected_folder = folder_var.get().strip().lower()
                tool = selected_folder if selected_folder in tools else "flirt"
                records.append({"tool": tool, "text": text})
                idx = len(records) - 1
            else:
                records[idx]["text"] = text

            if not _persist(show_dialog=False):
                return
            _refresh(selected_idx=idx)

        def _delete_selected():
            idx = selected_index.get("value")
            if idx is None:
                return
            if not messagebox.askyesno("Delete", "Delete selected cooldown message?", parent=self.root):
                return
            records.pop(idx)
            selected_index["value"] = None
            if not _persist(show_dialog=False):
                return
            message_text.delete("1.0", tk.END)
            selected_folder = folder_var.get().strip().lower()
            folder_value_var.set(selected_folder if selected_folder in tools else "flirt")
            _refresh()

        def _on_tree_open_close(_event=None):
            node_id = tree.focus()
            folder_name = folder_node_to_name.get(node_id)
            if folder_name is None:
                return
            group_open_state[folder_name] = bool(tree.item(node_id, "open"))
            _persist_group_open_state()

        tree.bind("<<TreeviewSelect>>", _on_select)
        search_var.trace_add("write", lambda *_args: _refresh())
        folder_combo.bind("<<ComboboxSelected>>", lambda _event: _refresh())
        grouped_view_var.trace_add("write", lambda *_args: _refresh())
        tree.bind("<<TreeviewOpen>>", _on_tree_open_close)
        tree.bind("<<TreeviewClose>>", _on_tree_open_close)
        expand_btn.configure(command=lambda: _set_group_open(True))
        collapse_btn.configure(command=lambda: _set_group_open(False))
        message_text.bind("<KeyRelease>", lambda _event: self._mark_dirty("data", True))

        actions = ttk.Frame(right)
        actions.pack(anchor="w", padx=4, pady=4)
        ttk.Button(actions, text="Reload", command=_load).pack(side=tk.LEFT, padx=4)
        ttk.Button(actions, text="New", command=_new).pack(side=tk.LEFT, padx=4)
        ttk.Button(actions, text="Save Selected", command=_save_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(actions, text="Delete Selected", command=_delete_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(actions, text="Save All to File", command=lambda: _persist(show_dialog=True)).pack(
            side=tk.LEFT, padx=12
        )

        _load()

    def _build_list_editor(
        self,
        parent: ttk.Frame,
        load_fn,
        save_fn,
        hint: str = "",
        source_path: str | None = None,
        item_label: str = "Message",
    ):
        pane = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        left = ttk.Frame(pane)
        pane.add(left, weight=1)

        filter_frame = ttk.LabelFrame(left, text="Filter")
        filter_frame.pack(fill=tk.X, padx=4, pady=(4, 2))
        filter_frame.columnconfigure(1, weight=1)

        if hint:
            ttk.Label(filter_frame, text=hint, foreground="gray").grid(
                row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 2)
            )
            row_i = 1
        else:
            row_i = 0

        search_var = tk.StringVar()
        ttk.Label(filter_frame, text="Search").grid(row=row_i, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(filter_frame, textvariable=search_var, width=24).grid(row=row_i, column=1, sticky="we", padx=8, pady=4)
        row_i += 1

        folder_var = tk.StringVar(value="All")
        ttk.Label(filter_frame, text="Folder").grid(row=row_i, column=0, sticky="w", padx=8, pady=4)
        folder_combo = ttk.Combobox(
            filter_frame,
            textvariable=folder_var,
            values=["All"],
            state="readonly",
            width=30,
        )
        folder_combo.grid(row=row_i, column=1, sticky="we", padx=8, pady=4)
        row_i += 1

        tag_var = tk.StringVar(value="All")
        ttk.Label(filter_frame, text="Tag").grid(row=row_i, column=0, sticky="w", padx=8, pady=4)
        tag_combo = ttk.Combobox(
            filter_frame,
            textvariable=tag_var,
            values=["All"],
            state="readonly",
            width=30,
        )
        tag_combo.grid(row=row_i, column=1, sticky="we", padx=8, pady=4)
        row_i += 1

        grouped_view_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            filter_frame,
            text="Group items by folder (collapsible)",
            variable=grouped_view_var,
        ).grid(row=row_i, column=0, columnspan=2, sticky="w", padx=8, pady=(2, 4))
        row_i += 1

        stats_var = tk.StringVar(value="0 shown / 0 total")
        ttk.Label(filter_frame, textvariable=stats_var, foreground="gray").grid(
            row=row_i, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 4)
        )

        keys_frame = ttk.LabelFrame(left, text="Items")
        keys_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=4, pady=4)

        tree_actions = ttk.Frame(keys_frame)
        tree_actions.pack(side=tk.TOP, fill=tk.X, padx=4, pady=(2, 4))
        expand_btn = ttk.Button(tree_actions, text="Expand All", width=12)
        collapse_btn = ttk.Button(tree_actions, text="Collapse All", width=12)
        expand_btn.pack(side=tk.LEFT, padx=(0, 6))
        collapse_btn.pack(side=tk.LEFT)

        tree_container = ttk.Frame(keys_frame)
        tree_container.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        tree = ttk.Treeview(tree_container, show="tree", selectmode="browse", height=18)
        tree_scroll = ttk.Scrollbar(tree_container, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=tree_scroll.set)
        tree.tag_configure("drop_target", background="#dbeafe")
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        right = ttk.Frame(pane)
        pane.add(right, weight=2)
        form_frame = ttk.LabelFrame(right, text="Edit Entry")
        form_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        form_frame.columnconfigure(1, weight=1)
        form_frame.rowconfigure(0, weight=1)

        ttk.Label(form_frame, text=item_label).grid(row=0, column=0, sticky="nw", padx=8, pady=4)
        message_text = tk.Text(form_frame, width=56, height=8, wrap=tk.WORD)
        message_text.grid(row=0, column=1, sticky="nsew", padx=8, pady=4)

        folder_edit_var = tk.StringVar()
        ttk.Label(form_frame, text="Folder").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        folder_edit_combo = ttk.Combobox(form_frame, textvariable=folder_edit_var, width=54)
        folder_edit_combo.grid(row=1, column=1, sticky="we", padx=8, pady=4)

        tags_edit_var = tk.StringVar()
        ttk.Label(form_frame, text="Tags (comma separated)").grid(row=2, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(form_frame, textvariable=tags_edit_var, width=48).grid(row=2, column=1, sticky="we", padx=8, pady=4)

        scope_key = f"list::{source_path or item_label.lower()}"
        scope_open_key = f"{scope_key}::folder_open"
        raw_open_state = self.ui_state.setdefault("tree_open_state", {}).get(scope_open_key, {})
        group_open_state: dict[str, bool] = (
            {str(name): bool(is_open) for name, is_open in raw_open_state.items()}
            if isinstance(raw_open_state, dict)
            else {}
        )
        records: list[dict] = []
        node_to_index: dict[str, int] = {}
        folder_node_to_name: dict[str, str] = {}
        drag_state: dict[str, object] = {"index": None, "dragging": False, "target_node": None}

        def _persist_group_open_state():
            self.ui_state.setdefault("tree_open_state", {})[scope_open_key] = dict(group_open_state)
            try:
                self._save_ui_state()
            except Exception:
                pass

        def _normalize_tags(value) -> list[str]:
            if isinstance(value, list):
                return [str(v).strip().lower() for v in value if str(v).strip()]
            if isinstance(value, str):
                return [p.strip().lower() for p in value.split(",") if p.strip()]
            return []

        def _record_folder(rec: dict) -> str:
            return str(rec.get("folder", "")).strip()

        def _record_tags(rec: dict) -> list[str]:
            return _normalize_tags(rec.get("tags", []))

        def _set_drop_target(node_id: str | None):
            current = drag_state.get("target_node")
            if current and tree.exists(current):
                tree.item(current, tags=())
            drag_state["target_node"] = node_id
            if node_id and tree.exists(node_id):
                tree.item(node_id, tags=("drop_target",))

        def _nearest_folder_node(y: int) -> str | None:
            node = tree.identify_row(y)
            if node:
                if node in folder_node_to_name:
                    return node
                parent_id = tree.parent(node)
                if parent_id in folder_node_to_name:
                    return parent_id

            nearest = None
            nearest_distance = None
            for folder_node in tree.get_children(""):
                bbox = tree.bbox(folder_node)
                if not bbox:
                    continue
                _x, row_y, _w, row_h = bbox
                center = row_y + (row_h // 2)
                dist = abs(y - center)
                if nearest_distance is None or dist < nearest_distance:
                    nearest_distance = dist
                    nearest = folder_node
            return nearest

        def _persist(show_dialog: bool = False) -> bool:
            try:
                save_fn([str(rec.get("text", "")) for rec in records])
                meta = self._load_editor_meta()
                list_meta = meta.get("list_meta", {})
                if not isinstance(list_meta, dict):
                    list_meta = {}

                scope_meta: dict[str, dict] = {}
                for rec in records:
                    text_value = str(rec.get("text", "")).strip()
                    if not text_value:
                        continue
                    payload: dict[str, object] = {}
                    folder_value = _record_folder(rec)
                    tags_value = _record_tags(rec)
                    if folder_value:
                        payload["category"] = folder_value
                    if tags_value:
                        payload["tags"] = tags_value
                    if payload:
                        scope_meta[text_value] = payload

                list_meta[scope_key] = scope_meta
                meta["list_meta"] = list_meta
                self._save_editor_meta(meta)

                self.log_queue.put(f"[data editor] saved {len(records)} list items")
                if show_dialog:
                    messagebox.showinfo("Saved", f"Saved {len(records)} items.", parent=self.root)
                return True
            except Exception as e:
                messagebox.showerror("Save Error", str(e), parent=self.root)
                return False

        def _selected_index() -> int | None:
            selected = tree.selection()
            if not selected:
                return None
            return node_to_index.get(selected[0])

        def _remember_group_open_state():
            for node_id, folder_name in list(folder_node_to_name.items()):
                if tree.exists(node_id):
                    group_open_state[folder_name] = bool(tree.item(node_id, "open"))

        def _set_group_open(is_open: bool):
            for node in tree.get_children(""):
                tree.item(node, open=is_open)
                folder_name = folder_node_to_name.get(node)
                if folder_name is not None:
                    group_open_state[folder_name] = bool(is_open)
            _persist_group_open_state()

        def _update_filter_options():
            folders: set[str] = set()
            tags: set[str] = set()
            has_unfiled = False
            has_untagged = False

            for rec in records:
                folder = _record_folder(rec)
                if folder:
                    folders.add(folder)
                else:
                    has_unfiled = True

                rec_tags = _record_tags(rec)
                if rec_tags:
                    tags.update(rec_tags)
                else:
                    has_untagged = True

            sorted_folders = sorted(folders, key=str.lower)
            folder_values = ["All", *sorted_folders]
            if has_unfiled:
                folder_values.append("(Unfiled)")
            if folder_var.get().strip() not in folder_values:
                folder_var.set("All")
            folder_combo["values"] = folder_values
            folder_edit_combo["values"] = sorted_folders

            sorted_tags = sorted(tags, key=str.lower)
            tag_values = ["All", *sorted_tags]
            if has_untagged:
                tag_values.append("(Untagged)")
            if tag_var.get().strip() not in tag_values:
                tag_var.set("All")
            tag_combo["values"] = tag_values

        def _refresh(selected_index: int | None = None):
            previous = _selected_index()
            target_idx = selected_index if selected_index is not None else previous
            query = search_var.get().strip().lower()

            _remember_group_open_state()
            tree.delete(*tree.get_children())
            node_to_index.clear()
            folder_node_to_name.clear()
            drag_state["target_node"] = None

            selected_folder = folder_var.get().strip()
            selected_tag = tag_var.get().strip().lower()
            grouped = bool(grouped_view_var.get() and selected_folder == "All")

            visible_indices: list[int] = []
            grouped_map: dict[str, list[int]] = {}
            for idx, rec in enumerate(records):
                text_value = str(rec.get("text", ""))
                folder_value = _record_folder(rec)
                tags_value = _record_tags(rec)

                haystack = f"{text_value} {folder_value} {' '.join(tags_value)}".lower()
                if query and query not in haystack:
                    continue

                if selected_folder != "All":
                    if selected_folder == "(Unfiled)" and folder_value:
                        continue
                    if selected_folder not in {"All", "(Unfiled)"} and folder_value.lower() != selected_folder.lower():
                        continue

                if selected_tag not in {"", "all"}:
                    if selected_tag == "(untagged)":
                        if tags_value:
                            continue
                    elif selected_tag not in tags_value:
                        continue

                visible_indices.append(idx)
                if grouped:
                    group_name = folder_value or "(Unfiled)"
                    grouped_map.setdefault(group_name, []).append(idx)

            if grouped:
                for folder_name in sorted(grouped_map.keys(), key=str.lower):
                    ids = grouped_map[folder_name]
                    parent_id = tree.insert(
                        "",
                        tk.END,
                        text=f"\U0001F4C1  {folder_name} ({len(ids)})",
                        open=group_open_state.get(folder_name, True),
                    )
                    folder_node_to_name[parent_id] = folder_name
                    for idx in ids:
                        text_value = str(records[idx].get("text", "")).strip()
                        preview = text_value if len(text_value) <= 72 else text_value[:69] + "..."
                        node_id = tree.insert(parent_id, tk.END, text=f"    {preview}")
                        node_to_index[node_id] = idx
            else:
                for idx in visible_indices:
                    text_value = str(records[idx].get("text", "")).strip()
                    preview = text_value if len(text_value) <= 72 else text_value[:69] + "..."
                    node_id = tree.insert("", tk.END, text=f"\u2022  {preview}")
                    node_to_index[node_id] = idx

            total = len(records)
            shown = len(visible_indices)
            if grouped:
                stats_var.set(f"{shown} shown in {len(grouped_map)} folders / {total} total")
            else:
                stats_var.set(f"{shown} shown / {total} total")

            if target_idx is not None:
                for node_id, idx in node_to_index.items():
                    if idx == target_idx:
                        tree.selection_set(node_id)
                        tree.focus(node_id)
                        tree.see(node_id)
                        break

            state = tk.NORMAL if grouped else tk.DISABLED
            expand_btn.configure(state=state)
            collapse_btn.configure(state=state)

        def _load():
            raw_items = load_fn()
            items = raw_items if isinstance(raw_items, list) else []

            meta = self._load_editor_meta()
            list_meta = meta.get("list_meta", {}) if isinstance(meta.get("list_meta", {}), dict) else {}
            scope_meta = list_meta.get(scope_key, {}) if isinstance(list_meta.get(scope_key, {}), dict) else {}

            records.clear()
            for item in items:
                text_value = str(item)
                item_meta = scope_meta.get(text_value, {}) if isinstance(scope_meta.get(text_value, {}), dict) else {}
                records.append(
                    {
                        "text": text_value,
                        "folder": str(item_meta.get("category", "")).strip(),
                        "tags": _normalize_tags(item_meta.get("tags", [])),
                    }
                )

            _update_filter_options()
            _refresh()

        def _on_select(_event=None):
            idx = _selected_index()
            if idx is None:
                return
            rec = records[idx]
            message_text.delete("1.0", tk.END)
            message_text.insert(tk.END, str(rec.get("text", "")))
            folder_edit_var.set(_record_folder(rec))
            tags_edit_var.set(", ".join(_record_tags(rec)))

        def _new():
            message_text.delete("1.0", tk.END)
            selected_folder = folder_var.get().strip()
            if selected_folder not in {"All", "(Unfiled)"}:
                folder_edit_var.set(selected_folder)
            else:
                folder_edit_var.set("")

            selected_tag = tag_var.get().strip()
            if selected_tag not in {"All", "(Untagged)"}:
                tags_edit_var.set(selected_tag)
            else:
                tags_edit_var.set("")

        def _save_selected():
            text_value = message_text.get("1.0", tk.END).strip()
            if not text_value:
                messagebox.showwarning("Save", f"{item_label} cannot be empty.", parent=self.root)
                return

            payload = {
                "text": text_value,
                "folder": folder_edit_var.get().strip(),
                "tags": _normalize_tags(tags_edit_var.get()),
            }

            idx = _selected_index()
            if idx is None:
                records.append(payload)
                idx = len(records) - 1
            else:
                records[idx] = payload

            if not _persist(show_dialog=False):
                return
            _update_filter_options()
            _refresh(selected_index=idx)
            self.log_queue.put(f"[data editor] updated {item_label.lower()} (saved)")

        def _delete_selected():
            idx = _selected_index()
            if idx is None:
                return
            if not messagebox.askyesno("Delete", f"Delete selected {item_label.lower()}?", parent=self.root):
                return
            records.pop(idx)
            if not _persist(show_dialog=False):
                return
            _update_filter_options()
            _refresh()

        def _on_tree_press(event):
            drag_state["index"] = None
            drag_state["dragging"] = False
            _set_drop_target(None)

            if not (grouped_view_var.get() and folder_var.get().strip() == "All"):
                return

            node_id = tree.identify_row(event.y)
            if not node_id:
                return

            idx = node_to_index.get(node_id)
            if idx is None:
                return
            drag_state["index"] = idx
            tree.configure(cursor="fleur")

        def _on_tree_drag(event):
            idx = drag_state.get("index")
            if idx is None:
                return

            drag_state["dragging"] = True
            if not (grouped_view_var.get() and folder_var.get().strip() == "All"):
                return

            target_folder = _nearest_folder_node(event.y)
            if target_folder:
                tree.item(target_folder, open=True)
                tree.see(target_folder)
            _set_drop_target(target_folder)

            rec = records[int(idx)]
            text_value = str(rec.get("text", "")).strip()
            preview = text_value if len(text_value) <= 32 else text_value[:29] + "..."
            folder_name = folder_node_to_name.get(target_folder, "")
            if folder_name == "(Unfiled)":
                folder_name = "Unfiled"
            ghost_text = f"{preview}  ->  {folder_name or '...'}"
            self._show_drag_ghost(ghost_text, event.x_root, event.y_root)

        def _on_tree_release(event):
            idx = drag_state.get("index")
            was_drag = bool(drag_state.get("dragging"))
            drag_state["index"] = None
            drag_state["dragging"] = False
            tree.configure(cursor="")
            self._hide_drag_ghost()

            if idx is None or not was_drag or not grouped_view_var.get() or folder_var.get().strip() != "All":
                _set_drop_target(None)
                return

            target_node = drag_state.get("target_node") or _nearest_folder_node(event.y)
            if not target_node:
                _set_drop_target(None)
                return

            folder_name = folder_node_to_name.get(str(target_node))
            if folder_name is None:
                _set_drop_target(None)
                return
            if folder_name == "(Unfiled)":
                folder_name = ""

            rec = records[int(idx)]
            if _record_folder(rec) == folder_name:
                _set_drop_target(None)
                return

            rec["folder"] = folder_name
            records[int(idx)] = rec
            if not _persist(show_dialog=False):
                _set_drop_target(None)
                return

            _update_filter_options()
            _refresh(selected_index=int(idx))
            self.log_queue.put(f"[data editor] moved {item_label.lower()} to {folder_name or '(Unfiled)'}")
            _set_drop_target(None)

        def _on_tree_open_close(_event=None):
            node_id = tree.focus()
            folder_name = folder_node_to_name.get(node_id)
            if folder_name is None:
                return
            group_open_state[folder_name] = bool(tree.item(node_id, "open"))
            _persist_group_open_state()

        tree.bind("<<TreeviewSelect>>", _on_select)
        tree.bind("<ButtonPress-1>", _on_tree_press)
        tree.bind("<B1-Motion>", _on_tree_drag)
        tree.bind("<ButtonRelease-1>", _on_tree_release)
        tree.bind("<<TreeviewOpen>>", _on_tree_open_close)
        tree.bind("<<TreeviewClose>>", _on_tree_open_close)
        search_var.trace_add("write", lambda *_args: _refresh())
        folder_combo.bind("<<ComboboxSelected>>", lambda _event: _refresh())
        tag_combo.bind("<<ComboboxSelected>>", lambda _event: _refresh())
        grouped_view_var.trace_add("write", lambda *_args: _refresh())
        expand_btn.configure(command=lambda: _set_group_open(True))
        collapse_btn.configure(command=lambda: _set_group_open(False))

        btn_frame = ttk.Frame(right)
        btn_frame.pack(anchor="w", padx=4, pady=4)
        ttk.Button(btn_frame, text="Reload", command=_load).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="New", command=_new).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Save Selected", command=_save_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Delete Selected", command=_delete_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Save All to File", command=lambda: _persist(show_dialog=True)).pack(side=tk.LEFT, padx=12)

        _load()

    def _build_kv_editor(
        self,
        parent: ttk.Frame,
        path: str,
        fields: list,
        anchors_field: str,
        anchors_label: str = "Anchors",
        group_field: str | None = None,
        group_label: str = "Folder",
        tags_field: str | None = None,
        tags_label: str = "Tag",
        list_fields: set[str] | None = None,
        grouped_tree: bool = False,
    ):
        """Split-pane editor for JSON objects where each value is a dict."""
        if list_fields is None:
            list_fields = set()

        pane = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        left = ttk.Frame(pane)
        pane.add(left, weight=1)
        filter_frame = ttk.LabelFrame(left, text="Filter")
        filter_frame.pack(fill=tk.X, padx=4, pady=(4, 2))
        filter_frame.columnconfigure(1, weight=1)

        search_var = tk.StringVar()
        ttk.Label(filter_frame, text="Search").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(filter_frame, textvariable=search_var, width=24).grid(row=0, column=1, sticky="we", padx=8, pady=4)

        row_i = 1
        group_filter_var = tk.StringVar(value="All")
        group_filter_combo = None
        if group_field:
            ttk.Label(filter_frame, text=group_label).grid(row=row_i, column=0, sticky="w", padx=8, pady=4)
            group_filter_combo = ttk.Combobox(
                filter_frame,
                textvariable=group_filter_var,
                values=["All"],
                state="readonly",
                width=30,
            )
            group_filter_combo.grid(row=row_i, column=1, sticky="we", padx=8, pady=4)
            row_i += 1

        tag_filter_var = tk.StringVar(value="All")
        tag_filter_combo = None
        if tags_field:
            ttk.Label(filter_frame, text=tags_label).grid(row=row_i, column=0, sticky="w", padx=8, pady=4)
            tag_filter_combo = ttk.Combobox(
                filter_frame,
                textvariable=tag_filter_var,
                values=["All"],
                state="readonly",
                width=30,
            )
            tag_filter_combo.grid(row=row_i, column=1, sticky="we", padx=8, pady=4)
            row_i += 1

        grouped_view_var = tk.BooleanVar(value=bool(grouped_tree and group_field))
        if grouped_tree and group_field:
            ttk.Checkbutton(
                filter_frame,
                text=f"Group keys by {group_label.lower()} (collapsible)",
                variable=grouped_view_var,
            ).grid(row=row_i, column=0, columnspan=2, sticky="w", padx=8, pady=(2, 4))
            row_i += 1

        filter_stats_var = tk.StringVar(value="0 items")
        ttk.Label(filter_frame, textvariable=filter_stats_var, foreground="gray").grid(
            row=row_i, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 4)
        )

        lb_frame = ttk.LabelFrame(left, text="Keys")
        lb_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=4, pady=4)
        expand_all_btn = None
        collapse_all_btn = None
        if grouped_tree and group_field:
            tree_actions_frame = ttk.Frame(lb_frame)
            tree_actions_frame.pack(side=tk.TOP, fill=tk.X, padx=4, pady=(2, 4))
            expand_all_btn = ttk.Button(tree_actions_frame, text="Expand All", width=12)
            collapse_all_btn = ttk.Button(tree_actions_frame, text="Collapse All", width=12)
            expand_all_btn.pack(side=tk.LEFT, padx=(0, 6))
            collapse_all_btn.pack(side=tk.LEFT)

        tree_container = ttk.Frame(lb_frame)
        tree_container.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        tree = ttk.Treeview(tree_container, show="tree", selectmode="browse", height=18)
        tree_scroll = ttk.Scrollbar(tree_container, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=tree_scroll.set)
        tree.tag_configure("drop_target", background="#dbeafe")
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        right = ttk.Frame(pane)
        pane.add(right, weight=2)
        form_frame = ttk.LabelFrame(right, text="Edit Entry")
        form_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        form_frame.columnconfigure(1, weight=1)

        field_vars: dict[str, tk.StringVar] = {}
        group_editor_combo = None
        for row_i, (label, field_key) in enumerate(fields):
            ttk.Label(form_frame, text=label).grid(row=row_i, column=0, sticky="w", padx=8, pady=4)
            var = tk.StringVar()
            if group_field and field_key == group_field:
                group_editor_combo = ttk.Combobox(form_frame, textvariable=var, width=54)
                group_editor_combo.grid(row=row_i, column=1, sticky="we", padx=8, pady=4)
            else:
                ttk.Entry(form_frame, textvariable=var, width=48).grid(row=row_i, column=1, sticky="we", padx=8, pady=4)
            field_vars[field_key] = var

        anchor_row = len(fields)
        ttk.Label(form_frame, text=f"{anchors_label}\n(one per line)").grid(
            row=anchor_row, column=0, sticky="nw", padx=8, pady=4
        )
        anchors_text = tk.Text(form_frame, width=56, height=10, wrap=tk.WORD)
        anchors_text.grid(row=anchor_row, column=1, sticky="nsew", padx=8, pady=4)
        form_frame.rowconfigure(anchor_row, weight=1)

        def _resize_anchors_text():
            # Auto-grow based on line count, with sane bounds so layout stays usable.
            try:
                line_count = int(anchors_text.index("end-1c").split(".")[0])
            except Exception:
                line_count = 10
            anchors_text.configure(height=max(10, min(22, line_count + 1)))

        data_store: dict = {"data": {}}
        filtered_keys: list[str] = []
        node_to_key: dict[str, str] = {}
        folder_node_to_group: dict[str, str] = {}
        scope_open_key = f"kv::{path}::group_open"
        raw_open_state = self.ui_state.setdefault("tree_open_state", {}).get(scope_open_key, {})
        group_open_state: dict[str, bool] = (
            {str(name): bool(is_open) for name, is_open in raw_open_state.items()}
            if isinstance(raw_open_state, dict)
            else {}
        )
        drag_state: dict[str, object] = {"key": None, "dragging": False, "target_node": None}

        def _persist_group_open_state():
            self.ui_state.setdefault("tree_open_state", {})[scope_open_key] = dict(group_open_state)
            try:
                self._save_ui_state()
            except Exception:
                pass

        def _entry_group(entry: dict) -> str:
            if not group_field:
                return ""
            return str(entry.get(group_field, "")).strip()

        def _normalize_list_value(value) -> list[str]:
            if isinstance(value, list):
                return [str(v).strip().lower() for v in value if str(v).strip()]
            if isinstance(value, str):
                return [part.strip().lower() for part in value.split(",") if part.strip()]
            return []

        def _entry_tags(entry: dict) -> list[str]:
            if not tags_field:
                return []
            return _normalize_list_value(entry.get(tags_field, []))

        def _matches_search(key: str, entry: dict, query: str) -> bool:
            if not query:
                return True
            parts: list[str] = [key]
            for value in entry.values():
                if isinstance(value, list):
                    parts.extend(str(v) for v in value)
                else:
                    parts.append(str(value))
            return query in " ".join(parts).lower()

        def _matches_group(entry: dict) -> bool:
            if not group_field:
                return True

            selected = group_filter_var.get().strip()
            if selected == "All":
                return True
            if selected == "(Unfiled)":
                return _entry_group(entry) == ""
            return _entry_group(entry).lower() == selected.lower()

        def _matches_tag(entry: dict) -> bool:
            if not tags_field:
                return True

            selected = tag_filter_var.get().strip().lower()
            if selected in {"", "all"}:
                return True

            tags = _entry_tags(entry)
            if selected == "(untagged)":
                return len(tags) == 0
            return selected in tags

        def _update_filter_options():
            groups: set[str] = set()
            tags: set[str] = set()
            has_unfiled = False
            has_untagged = False

            for value in data_store["data"].values():
                entry = value if isinstance(value, dict) else {}
                if group_field:
                    group_value = _entry_group(entry)
                    if group_value:
                        groups.add(group_value)
                    else:
                        has_unfiled = True
                if tags_field:
                    entry_tags = _entry_tags(entry)
                    if entry_tags:
                        tags.update(entry_tags)
                    else:
                        has_untagged = True

            if group_field:
                sorted_groups = sorted(groups, key=str.lower)
                group_values = ["All", *sorted_groups]
                if has_unfiled:
                    group_values.append("(Unfiled)")

                current_group = group_filter_var.get().strip() or "All"
                if group_filter_combo is not None:
                    group_filter_combo["values"] = group_values
                if current_group not in group_values:
                    current_group = "All"
                group_filter_var.set(current_group)

                if group_editor_combo is not None:
                    group_editor_combo["values"] = sorted_groups

            if tags_field:
                sorted_tags = sorted(tags, key=str.lower)
                tag_values = ["All", *sorted_tags]
                if has_untagged:
                    tag_values.append("(Untagged)")

                current_tag = tag_filter_var.get().strip() or "All"
                if tag_filter_combo is not None:
                    tag_filter_combo["values"] = tag_values
                if current_tag not in tag_values:
                    current_tag = "All"
                tag_filter_var.set(current_tag)

        def _selected_key() -> str | None:
            selected_nodes = tree.selection()
            if not selected_nodes:
                return None
            return node_to_key.get(selected_nodes[0])

        def _remember_group_open_state():
            for node_id, grp in list(folder_node_to_group.items()):
                if tree.exists(node_id):
                    group_open_state[grp] = bool(tree.item(node_id, "open"))

        def _set_group_nodes_open(is_open: bool):
            for node in tree.get_children(""):
                tree.item(node, open=is_open)
                grp = folder_node_to_group.get(node)
                if grp is not None:
                    group_open_state[grp] = bool(is_open)
            _persist_group_open_state()

        def _resolve_target_group_from_node(node_id: str) -> str | None:
            if node_id in folder_node_to_group:
                return folder_node_to_group[node_id]
            parent_id = tree.parent(node_id)
            if parent_id and parent_id in folder_node_to_group:
                return folder_node_to_group[parent_id]
            return None

        def _nearest_folder_node(y: int) -> str | None:
            direct = tree.identify_row(y)
            if direct:
                if direct in folder_node_to_group:
                    return direct
                parent_id = tree.parent(direct)
                if parent_id in folder_node_to_group:
                    return parent_id

            nearest_node = None
            nearest_distance = None
            for folder_node in tree.get_children(""):
                bbox = tree.bbox(folder_node)
                if not bbox:
                    continue
                _x, row_y, _w, row_h = bbox
                center_y = row_y + (row_h // 2)
                distance = abs(y - center_y)
                if nearest_distance is None or distance < nearest_distance:
                    nearest_distance = distance
                    nearest_node = folder_node
            return nearest_node

        def _set_drop_target_node(node_id: str | None):
            current = drag_state.get("target_node")
            if current and tree.exists(current):
                tree.item(current, tags=())

            drag_state["target_node"] = node_id
            if node_id and tree.exists(node_id):
                tree.item(node_id, tags=("drop_target",))

        def _refresh_group_action_state():
            if not (expand_all_btn and collapse_all_btn):
                return
            selected_group = group_filter_var.get().strip()
            use_group_tree = bool(group_field and grouped_tree and grouped_view_var.get() and selected_group == "All")
            new_state = tk.NORMAL if use_group_tree else tk.DISABLED
            expand_all_btn.configure(state=new_state)
            collapse_all_btn.configure(state=new_state)

        def _refresh_keys(selected_key: str | None = None):
            previous = _selected_key()
            target_key = selected_key or previous
            query = search_var.get().strip().lower()
            selected_group = group_filter_var.get().strip()
            use_group_tree = bool(group_field and grouped_tree and grouped_view_var.get() and selected_group == "All")

            _remember_group_open_state()
            tree.delete(*tree.get_children())
            filtered_keys.clear()
            node_to_key.clear()
            folder_node_to_group.clear()
            drag_state["target_node"] = None

            filtered_entries: list[tuple[str, dict]] = []

            for key in sorted(data_store["data"].keys()):
                entry = data_store["data"].get(key, {})
                if not isinstance(entry, dict):
                    entry = {}
                if not _matches_search(key, entry, query):
                    continue
                if not _matches_group(entry):
                    continue
                if not _matches_tag(entry):
                    continue
                filtered_keys.append(key)
                filtered_entries.append((key, entry))

            if use_group_tree:
                groups: dict[str, list[str]] = {}
                for key, entry in filtered_entries:
                    grp = _entry_group(entry) or "(Unfiled)"
                    groups.setdefault(grp, []).append(key)

                for grp in sorted(groups.keys(), key=str.lower):
                    keys = sorted(groups[grp], key=str.lower)
                    parent_id = tree.insert(
                        "",
                        tk.END,
                        text=f"\U0001F4C1  {grp} ({len(keys)})",
                        open=group_open_state.get(grp, True),
                    )
                    folder_node_to_group[parent_id] = grp
                    for key in keys:
                        node = tree.insert(parent_id, tk.END, text=f"    {key}")
                        node_to_key[node] = key
            else:
                for key, _entry in filtered_entries:
                    node = tree.insert("", tk.END, text=f"\u2022  {key}")
                    node_to_key[node] = key

            total = len(data_store["data"])
            visible = len(filtered_keys)
            if use_group_tree:
                folder_count = len({(_entry_group(entry) or "(Unfiled)") for _key, entry in filtered_entries})
                filter_stats_var.set(f"{visible} shown in {folder_count} folders / {total} total")
            else:
                filter_stats_var.set(f"{visible} shown / {total} total")

            if target_key and target_key in filtered_keys:
                for node_id, key in node_to_key.items():
                    if key == target_key:
                        tree.selection_set(node_id)
                        tree.focus(node_id)
                        tree.see(node_id)
                        break

            _refresh_group_action_state()

        def _reload():
            payload = load_json(path, default={})
            data_store["data"] = payload if isinstance(payload, dict) else {}
            _update_filter_options()
            _refresh_keys()

        def _on_select(_event=None):
            key = _selected_key()
            if not key:
                return
            entry = data_store["data"].get(key, {})
            for field_key, var in field_vars.items():
                if field_key == "key":
                    var.set(key)
                elif field_key in list_fields:
                    var.set(", ".join(_normalize_list_value(entry.get(field_key, []))))
                else:
                    var.set(str(entry.get(field_key, "")))
            raw_anchors = entry.get(anchors_field, [])
            anchors_text.delete("1.0", tk.END)
            anchors_text.insert(
                tk.END,
                "\n".join(raw_anchors if isinstance(raw_anchors, list) else [])
            )
            _resize_anchors_text()

        def _persist_data(show_dialog: bool = False) -> bool:
            try:
                atomic_write_json(path, data_store["data"])
                self.log_queue.put(f"[data editor] saved {len(data_store['data'])} entries to {path}")
                if show_dialog:
                    messagebox.showinfo("Saved", f"Saved {len(data_store['data'])} entries.", parent=self.root)
                return True
            except Exception as e:
                messagebox.showerror("Save Error", str(e), parent=self.root)
                return False

        def _on_tree_press(event):
            drag_state["key"] = None
            drag_state["dragging"] = False
            _set_drop_target_node(None)
            selected_group = group_filter_var.get().strip()
            use_group_tree = bool(group_field and grouped_tree and grouped_view_var.get() and selected_group == "All")
            if not use_group_tree:
                return

            node = tree.identify_row(event.y)
            if not node:
                return

            drag_state["key"] = node_to_key.get(node)
            if drag_state["key"]:
                tree.configure(cursor="fleur")

        def _on_tree_drag(event):
            if not drag_state.get("key"):
                return
            drag_state["dragging"] = True

            selected_group = group_filter_var.get().strip()
            use_group_tree = bool(group_field and grouped_tree and grouped_view_var.get() and selected_group == "All")
            if not use_group_tree:
                return

            target_folder_node = _nearest_folder_node(event.y)
            if target_folder_node:
                tree.item(target_folder_node, open=True)
                tree.see(target_folder_node)
            _set_drop_target_node(target_folder_node)

            moved_key = str(drag_state.get("key") or "")
            target_label = folder_node_to_group.get(target_folder_node, "")
            if target_label == "(Unfiled)":
                target_label = "Unfiled"
            ghost_label = f"{moved_key}  ->  {target_label or '...'}"
            self._show_drag_ghost(ghost_label, event.x_root, event.y_root)

        def _on_tree_release(event):
            moved_key = drag_state.get("key")
            was_dragging = bool(drag_state.get("dragging"))
            drag_state["key"] = None
            drag_state["dragging"] = False
            tree.configure(cursor="")
            self._hide_drag_ghost()
            if not moved_key or not group_field or not was_dragging:
                _set_drop_target_node(None)
                return

            selected_group = group_filter_var.get().strip()
            use_group_tree = bool(group_field and grouped_tree and grouped_view_var.get() and selected_group == "All")
            if not use_group_tree:
                _set_drop_target_node(None)
                return

            target_node = drag_state.get("target_node")
            if not target_node:
                target_node = _nearest_folder_node(event.y)
            if not target_node:
                _set_drop_target_node(None)
                return

            target_group = _resolve_target_group_from_node(target_node)
            if target_group is None:
                _set_drop_target_node(None)
                return
            if target_group == "(Unfiled)":
                target_group = ""

            entry = data_store["data"].get(moved_key, {})
            if not isinstance(entry, dict):
                _set_drop_target_node(None)
                return

            current_group = _entry_group(entry)
            if current_group == target_group:
                _set_drop_target_node(None)
                return

            entry[group_field] = target_group
            data_store["data"][moved_key] = entry

            if not _persist_data(show_dialog=False):
                _set_drop_target_node(None)
                return

            _update_filter_options()
            _refresh_keys(selected_key=moved_key)
            display_group = target_group or "(Unfiled)"
            self.log_queue.put(f"[data editor] moved key '{moved_key}' -> {display_group}")
            _set_drop_target_node(None)

        def _on_tree_open_close(_event=None):
            node_id = tree.focus()
            grp = folder_node_to_group.get(node_id)
            if grp is None:
                return
            group_open_state[grp] = bool(tree.item(node_id, "open"))
            _persist_group_open_state()

        tree.bind("<<TreeviewSelect>>", _on_select)
        tree.bind("<ButtonPress-1>", _on_tree_press)
        tree.bind("<B1-Motion>", _on_tree_drag)
        tree.bind("<ButtonRelease-1>", _on_tree_release)
        tree.bind("<<TreeviewOpen>>", _on_tree_open_close)
        tree.bind("<<TreeviewClose>>", _on_tree_open_close)
        anchors_text.bind("<KeyRelease>", lambda _event: _resize_anchors_text())
        search_var.trace_add("write", lambda *_args: _refresh_keys())
        if group_filter_combo is not None:
            group_filter_combo.bind("<<ComboboxSelected>>", lambda _event: _refresh_keys())
        if tag_filter_combo is not None:
            tag_filter_combo.bind("<<ComboboxSelected>>", lambda _event: _refresh_keys())
        if grouped_tree and group_field:
            grouped_view_var.trace_add("write", lambda *_args: _refresh_keys())
            if expand_all_btn is not None and collapse_all_btn is not None:
                expand_all_btn.configure(command=lambda: _set_group_nodes_open(True))
                collapse_all_btn.configure(command=lambda: _set_group_nodes_open(False))

        def _collect_entry() -> tuple[str, dict]:
            key = field_vars["key"].get().strip().lower() if "key" in field_vars else ""
            entry: dict = {}
            for field_key, var in field_vars.items():
                if field_key != "key":
                    if field_key in list_fields:
                        entry[field_key] = _normalize_list_value(var.get())
                    else:
                        entry[field_key] = var.get().strip()
            raw = anchors_text.get("1.0", tk.END).strip()
            entry[anchors_field] = [a.strip() for a in raw.splitlines() if a.strip()]
            return key, entry

        def _new():
            for var in field_vars.values():
                var.set("")
            if group_field and group_field in field_vars:
                selected_group = group_filter_var.get().strip()
                if selected_group not in {"", "All", "(Unfiled)"}:
                    field_vars[group_field].set(selected_group)
            if tags_field and tags_field in field_vars:
                selected_tag = tag_filter_var.get().strip()
                if selected_tag not in {"", "All", "(Untagged)"}:
                    field_vars[tags_field].set(selected_tag)
            anchors_text.delete("1.0", tk.END)
            _resize_anchors_text()

        def _save_selected():
            key, entry = _collect_entry()
            if not key:
                messagebox.showwarning("Save", "Key cannot be empty.", parent=self.root)
                return
            data_store["data"][key] = entry
            if not _persist_data(show_dialog=False):
                return
            _update_filter_options()
            _refresh_keys(selected_key=key)
            self.log_queue.put(f"[data editor] updated key: {key} (saved)")

        def _delete_selected():
            key = _selected_key()
            if not key:
                return
            if messagebox.askyesno("Delete", f"Delete '{key}'?", parent=self.root):
                data_store["data"].pop(key, None)
                if not _persist_data(show_dialog=False):
                    return
                _update_filter_options()
                _refresh_keys()

        def _save_all():
            _persist_data(show_dialog=True)

        btn_frame = ttk.Frame(right)
        btn_frame.pack(anchor="w", padx=4, pady=4)
        ttk.Button(btn_frame, text="Reload",          command=_reload).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="New",             command=_new).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Save Selected",   command=_save_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Delete Selected", command=_delete_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Save All to File",command=_save_all).pack(side=tk.LEFT, padx=12)

        _reload()
        _resize_anchors_text()

    # -----------------------------------------------------------------------
    # Process management
    # -----------------------------------------------------------------------

    def _discover_scripts(self) -> list[str]:
        script_paths = []
        for folder in [REPO_ROOT, REPO_ROOT / "daemons", REPO_ROOT / "utils"]:
            if not folder.exists():
                continue
            for path in sorted(folder.glob("*.py")):
                if path.name.startswith("__"):
                    continue
                script_paths.append(str(path.relative_to(REPO_ROOT)))
        dist_root = REPO_ROOT / "dist"
        if dist_root.exists():
            for path in sorted(dist_root.glob("**/*.exe")):
                script_paths.append(str(path.relative_to(REPO_ROOT)))
        return script_paths

    @staticmethod
    def _trim_path_punctuation(value: str) -> tuple[str, str]:
        raw = str(value or "")
        suffix_chars = ""
        while raw and raw[-1] in "),.;:]}":
            suffix_chars = raw[-1] + suffix_chars
            raw = raw[:-1]
        return raw, suffix_chars

    def _path_display_for_log(self, value: str) -> str:
        core, suffix = self._trim_path_punctuation(value)
        if not core:
            return value
        try:
            path_obj = Path(core)
            if path_obj.is_absolute():
                try:
                    rel = path_obj.relative_to(REPO_ROOT)
                    return str(rel) + suffix
                except Exception:
                    pass
                name = path_obj.name or "<path>"
                return f"<{name}>" + suffix
        except Exception:
            return value
        return value

    def _sanitize_log_text(self, message: str) -> str:
        text = str(message)

        # Redact Windows absolute paths like C:\Users\...
        def _replace_windows_abs(match):
            return self._path_display_for_log(match.group(0))

        text = re.sub(r"(?i)\b[A-Z]:\\[^ \t\n\r\"']+", _replace_windows_abs, text)
        return text

    def _sanitize_command_for_log(self, command: list[str]) -> str:
        parts = [self._path_display_for_log(str(arg)) for arg in command]
        return " ".join(parts)

    def _append_log(self, message: str):
        line = self._sanitize_log_text(str(message))
        self.log_buffer.append(line)
        if len(self.log_buffer) > 5000:
            self.log_buffer = self.log_buffer[-5000:]
        if self.log_text is not None and self._log_matches_filter(line):
            self.log_text.insert(tk.END, line + "\n")
            if not self.log_pause_var.get():
                self.log_text.see(tk.END)

    def _drain_log_queue(self):
        while True:
            try:
                msg = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(msg)
        self.root.after(150, self._drain_log_queue)

    def _spawn_process(self, name: str, command: list[str]):
        if name in self.processes and self.processes[name].poll() is None:
            self.log_queue.put(f"[{name}] already running")
            return

        creationflags = 0
        if sys.platform.startswith("win"):
            creationflags = subprocess.CREATE_NO_WINDOW

        proc = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            creationflags=creationflags,
        )
        self.processes[name] = proc
        self.log_queue.put(f"[{name}] started: {self._sanitize_command_for_log(command)}")
        self.root.after(0, self._refresh_glance)

        thread = threading.Thread(target=self._stream_process_output, args=(name, proc), daemon=True)
        thread.start()

    def _stream_process_output(self, name: str, proc: subprocess.Popen):
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            self.log_queue.put(f"[{name}] {raw_line.rstrip()}")
        exit_code = proc.wait()
        self.log_queue.put(f"[{name}] exited with code {exit_code}")
        if name == "monitor":
            self.root.after(0, lambda: self.monitor_status_var.set("Stopped"))
            self.root.after(0, self._refresh_monitor_mood_state)
        self.root.after(0, self._refresh_glance)

    def _stop_process(self, name: str):
        proc = self.processes.get(name)
        if not proc or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        self.log_queue.put(f"[{name}] stopped")
        self.root.after(0, self._refresh_glance)

    # -----------------------------------------------------------------------
    # Monitor controls
    # -----------------------------------------------------------------------

    def start_monitor(self):
        if getattr(sys, "frozen", False):
            command = [sys.executable, "--run-monitor"]
        else:
            command = [sys.executable, "mai_monitor.py"]
        self._spawn_process("monitor", command)
        self.monitor_status_var.set("Running")
        self.root.after(800, self._refresh_monitor_mood_state)
        self._refresh_glance()

    def stop_monitor(self):
        self._stop_process("monitor")
        try:
            state = read_mood_state(Paths.MOOD_STATE)
            set_session_inactive(state, path=Paths.MOOD_STATE)
        except Exception as e:
            self.log_queue.put(f"[mood] failed to mark session inactive on stop: {e}")
        self.monitor_status_var.set("Stopped")
        self._refresh_monitor_mood_state()
        self._refresh_glance()

    # -----------------------------------------------------------------------
    # Script controls
    # -----------------------------------------------------------------------

    def _build_python_script_command(self, script: str, args: list[str] | None = None) -> list[str]:
        script_args = args or []
        if getattr(sys, "frozen", False):
            return [sys.executable, "--run-script", script, *script_args]
        return [sys.executable, script, *script_args]

    def run_selected_script(self):
        script = self.script_var.get().strip()
        if not script:
            messagebox.showwarning("Script", "Select a script first.")
            return

        script_path = REPO_ROOT / script
        if not script_path.exists():
            messagebox.showerror("Script", f"Script not found: {script}")
            return

        args_text = self.script_args_var.get().strip()
        args = shlex.split(args_text, posix=False) if args_text else []

        name = f"script:{script}"
        if script_path.suffix.lower() == ".exe":
            command = [str(script_path), *args]
        else:
            command = self._build_python_script_command(script, args)
        self._spawn_process(name, command)
        self.script_status_var.set(f"Running {script}")

    def stop_selected_script(self):
        script = self.script_var.get().strip()
        if not script:
            return
        self._stop_process(f"script:{script}")
        self.script_status_var.set("Idle")

    # -----------------------------------------------------------------------
    # Monitor config form
    # -----------------------------------------------------------------------

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

    # -----------------------------------------------------------------------
    # Tray icon
    # -----------------------------------------------------------------------

    def _build_tray_icon_image(self):
        if Image is None or ImageDraw is None:
            return None
        img  = Image.new("RGB", (64, 64), color=(32, 32, 42))
        draw = ImageDraw.Draw(img)
        draw.ellipse((8, 8, 56, 56), fill=(110, 77, 255))
        draw.text((24, 20), "M", fill=(245, 245, 245))
        return img

    def _show_window(self):
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()
        self.root.focus_force()

    def _hide_to_tray(self):
        self._save_ui_state()
        if pystray is None:
            self.root.iconify()
            return
        if self.tray_icon is not None:
            self.root.withdraw()
            return
        icon_image = self._build_tray_icon_image()
        if icon_image is None:
            self.root.iconify()
            return

        def on_show(icon, _item):
            self.root.after(0, self._show_window)
            icon.stop()
            self.tray_icon = None

        def on_quit(icon, _item):
            icon.stop()
            self.tray_icon = None
            self.root.after(0, self.quit_app)

        menu = pystray.Menu(
            pystray.MenuItem("Show", on_show),
            pystray.MenuItem("Quit", on_quit),
        )
        self.tray_icon = pystray.Icon("mai_control_panel", icon_image, "Mai Control Panel", menu)
        self.root.withdraw()
        self.tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        self.tray_thread.start()

    def _on_window_minimize(self, _event):
        if self.root.state() == "iconic":
            self._hide_to_tray()

    def _on_close_request(self):
        self._hide_to_tray()

    def quit_app(self):
        if self._has_unsaved_changes() and not self._confirm_discard_unsaved("quitting"):
            return
        self._save_ui_state()
        for name in list(self.processes.keys()):
            self._stop_process(name)
        if self._glance_refresh_after_id is not None:
            try:
                self.root.after_cancel(self._glance_refresh_after_id)
            except Exception:
                pass
            self._glance_refresh_after_id = None
        self._hide_drag_ghost()
        if self._drag_ghost is not None:
            try:
                self._drag_ghost.destroy()
            except Exception:
                pass
            self._drag_ghost = None
            self._drag_ghost_label = None
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
            self.tray_icon = None
        self.root.destroy()


def _run_embedded_script(script: str, args: list[str]) -> int:
    script_candidate = Path(script)
    if script_candidate.is_absolute():
        script_path = script_candidate
    else:
        script_path = resolve_existing_path(script_candidate)
        if not script_path.exists():
            script_path = REPO_ROOT / script_candidate

    if not script_path.exists():
        print(f"[ERROR] Script not found: {script}")
        return 1

    repo_root_str = str(REPO_ROOT.resolve())
    script_parent_str = str(script_path.resolve().parent)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)
    if script_parent_str not in sys.path:
        sys.path.insert(0, script_parent_str)

    original_argv = list(sys.argv)
    try:
        sys.argv = [str(script_path), *args]
        runpy.run_path(str(script_path), run_name="__main__")
        return 0
    except SystemExit as e:
        if isinstance(e.code, int):
            return e.code
        return 0 if e.code is None else 1
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    if "--run-monitor" in sys.argv:
        from mai_monitor import main as run_monitor
        run_monitor()
    elif "--run-script" in sys.argv:
        idx = sys.argv.index("--run-script")
        if idx + 1 >= len(sys.argv):
            print("[ERROR] Missing script for --run-script")
            sys.exit(1)

        target_script = sys.argv[idx + 1]
        target_args = sys.argv[idx + 2:]
        sys.exit(_run_embedded_script(target_script, target_args))
    else:
        root = tk.Tk()
        app = MaiControlPanel(root)
        root.mainloop()
