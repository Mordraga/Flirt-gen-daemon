import queue
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

from ui.atoms import forms as ui_forms
from ui.atoms import layout as ui_layout
from ui.atoms import lists as ui_lists
from ui.atoms import text as ui_text
from ui.pages import analytics_page, data_page, glance_page, monitor_page, scripts_page, settings_page
from ui.pages.data import cooldown_editor, kv_editor, list_editor, moods_editor, owner_profile_editor

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


    # ---- UI module bindings -----------------------------------------------

    _create_scrollable_tab_container = ui_layout._create_scrollable_tab_container
    _build_collapsible_section = ui_layout._build_collapsible_section

    _register_text_widget = ui_text._register_text_widget
    _apply_text_widget_theme = ui_text._apply_text_widget_theme
    _set_text_widget_content = ui_text._set_text_widget_content

    _clear_treeview = ui_lists._clear_treeview
    _bind_enter_to_quick_test = ui_forms._bind_enter_to_quick_test

    _is_valid_username = monitor_page._is_valid_username
    _validate_monitor_event_inputs = monitor_page._validate_monitor_event_inputs
    _refresh_monitor_meta_label = monitor_page._refresh_monitor_meta_label
    _load_mood_names = monitor_page._load_mood_names
    _get_monitor_mood_reroll_settings = monitor_page._get_monitor_mood_reroll_settings
    _has_active_monitor_mood_session = monitor_page._has_active_monitor_mood_session
    _refresh_monitor_mood_state = monitor_page._refresh_monitor_mood_state
    _lock_selected_monitor_mood = monitor_page._lock_selected_monitor_mood
    _unlock_monitor_mood = monitor_page._unlock_monitor_mood
    _reroll_monitor_mood = monitor_page._reroll_monitor_mood
    _build_monitor_tab = monitor_page._build_monitor_tab
    _load_monitor_config_into_form = monitor_page._load_monitor_config_into_form
    save_monitor_config = monitor_page.save_monitor_config

    _format_glance_timestamp = glance_page._format_glance_timestamp
    _format_chat_message_timestamp = glance_page._format_chat_message_timestamp
    _chat_message_epoch_seconds = glance_page._chat_message_epoch_seconds
    _is_highlight_like_message = glance_page._is_highlight_like_message
    _insert_chatlog_rows = glance_page._insert_chatlog_rows
    _read_text_preview = glance_page._read_text_preview
    _read_last_jsonl_record = glance_page._read_last_jsonl_record
    _format_age_short = glance_page._format_age_short
    _resolve_chip_color = glance_page._resolve_chip_color
    _set_glance_cue = glance_page._set_glance_cue
    _build_glance_cue = glance_page._build_glance_cue
    _build_glance_output_card = glance_page._build_glance_output_card
    _build_glance_tab = glance_page._build_glance_tab
    _refresh_glance = glance_page._refresh_glance

    _refresh_analytics_chatlog_view = analytics_page._refresh_analytics_chatlog_view
    _format_analytics_time = analytics_page._format_analytics_time
    _build_chat_analytics_tab = analytics_page._build_chat_analytics_tab
    _refresh_chat_analytics = analytics_page._refresh_chat_analytics

    _select_color_for_var = settings_page._select_color_for_var
    _apply_colorblind_preset_to_controls = settings_page._apply_colorblind_preset_to_controls
    _is_valid_profile_name = settings_page._is_valid_profile_name
    _refresh_settings_profile_controls = settings_page._refresh_settings_profile_controls
    _load_ui_profile_into_controls = settings_page._load_ui_profile_into_controls
    _on_settings_profile_selected = settings_page._on_settings_profile_selected
    _save_as_new_ui_profile = settings_page._save_as_new_ui_profile
    _rename_selected_ui_profile = settings_page._rename_selected_ui_profile
    _delete_selected_ui_profile = settings_page._delete_selected_ui_profile
    _collect_ui_settings_from_controls = settings_page._collect_ui_settings_from_controls
    _apply_ui_settings_from_controls = settings_page._apply_ui_settings_from_controls
    _sync_settings_controls_from_ui_settings = settings_page._sync_settings_controls_from_ui_settings
    _snapshot_root = settings_page._snapshot_root
    _snapshot_target_files = settings_page._snapshot_target_files
    _list_config_snapshots = settings_page._list_config_snapshots
    _refresh_snapshot_list = settings_page._refresh_snapshot_list
    _create_config_snapshot = settings_page._create_config_snapshot
    _restore_selected_snapshot = settings_page._restore_selected_snapshot
    _persistent_backup_base_root = settings_page._persistent_backup_base_root
    _update_backup_root_label = settings_page._update_backup_root_label
    _open_backup_folder = settings_page._open_backup_folder
    _full_backup_root = settings_page._full_backup_root
    _list_full_backups = settings_page._list_full_backups
    _refresh_full_backup_list = settings_page._refresh_full_backup_list
    _create_full_backup_folder = settings_page._create_full_backup_folder
    _create_full_data_backup = settings_page._create_full_data_backup
    _restore_selected_full_backup = settings_page._restore_selected_full_backup
    _rename_selected_full_backup = settings_page._rename_selected_full_backup
    _delete_selected_full_backup = settings_page._delete_selected_full_backup
    _json_section_sources = settings_page._json_section_sources
    _section_backup_root = settings_page._section_backup_root
    _list_section_backups = settings_page._list_section_backups
    _refresh_section_backup_list = settings_page._refresh_section_backup_list
    _on_section_changed = settings_page._on_section_changed
    _create_section_backup = settings_page._create_section_backup
    _restore_selected_section_backup = settings_page._restore_selected_section_backup
    _rename_selected_section_backup = settings_page._rename_selected_section_backup
    _delete_selected_section_backup = settings_page._delete_selected_section_backup
    _wipe_jsons_contents = settings_page._wipe_jsons_contents
    _build_settings_tab = settings_page._build_settings_tab

    _build_scripts_tab = scripts_page._build_scripts_tab
    _build_qt_flirt_fields = scripts_page._build_qt_flirt_fields
    _build_qt_tarot_fields = scripts_page._build_qt_tarot_fields
    _build_qt_commands_fields = scripts_page._build_qt_commands_fields
    _on_qt_keyword_change = scripts_page._on_qt_keyword_change
    _fire_quick_test = scripts_page._fire_quick_test
    _build_logs_tab = scripts_page._build_logs_tab
    _clear_logs = scripts_page._clear_logs
    _log_matches_filter = scripts_page._log_matches_filter
    _rerender_logs = scripts_page._rerender_logs

    _build_data_editor_tab = data_page._build_data_editor_tab
    _build_moods_editor = moods_editor._build_moods_editor
    _refresh_owner_meta_label = owner_profile_editor._refresh_owner_meta_label
    _load_owner_profile_into_editor = owner_profile_editor._load_owner_profile_into_editor
    _build_owner_profile_editor = owner_profile_editor._build_owner_profile_editor
    _build_tool_cooldown_editor = cooldown_editor._build_tool_cooldown_editor
    _build_list_editor = list_editor._build_list_editor
    _build_kv_editor = kv_editor._build_kv_editor

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













    # ---- Monitor tab -------------------------------------------------------





























































    # ---- Data Editor tab ---------------------------------------------------







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
