import queue
import runpy
import shlex
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from utils.helpers import atomic_write_json, load_json, resolve_existing_path
from utils.paths import Paths

try:
    import pystray
    from PIL import Image, ImageDraw
except Exception:
    pystray = None
    Image = None
    ImageDraw = None


REPO_ROOT = Path(__file__).parent


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
        self.root.geometry("1100x780")
        self.root.minsize(980, 680)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.processes: dict[str, subprocess.Popen] = {}

        self.tray_icon = None
        self.tray_thread = None

        self.config_path = REPO_ROOT / "jsons" / "configs" / "config.json"

        self.monitor_status_var = tk.StringVar(value="Stopped")
        self.script_status_var = tk.StringVar(value="Idle")

        self.monitor_vars: dict[str, tk.Variable] = {}

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

    def _apply_ui_style(self):
        # Configure Tk named fonts directly to avoid Tcl parsing issues with
        # family names that contain spaces (e.g. "Segoe UI").
        try:
            tkfont.nametofont("TkDefaultFont").configure(family="Segoe UI", size=10)
            tkfont.nametofont("TkTextFont").configure(family="Segoe UI", size=10)
            tkfont.nametofont("TkMenuFont").configure(family="Segoe UI", size=10)
            tkfont.nametofont("TkHeadingFont").configure(family="Segoe UI", size=10, weight="bold")
        except Exception:
            pass
        # Ensure combobox dropdown list rows have enough line-height so
        # descenders (g, p, q, y) are not clipped.
        self.root.option_add("*TCombobox*Listbox.font", "{Segoe UI} 11")
        self.root.configure(background="#f3f5f8")

        style = ttk.Style()
        for theme_name in ("clam", "vista", "xpnative", "default"):
            if theme_name in style.theme_names():
                style.theme_use(theme_name)
                break

        style.configure(".", background="#f3f5f8", foreground="#1f2937")
        style.configure("TFrame", background="#f3f5f8")
        style.configure("TLabel", background="#f3f5f8", foreground="#1f2937")
        style.configure("TLabelframe", background="#f3f5f8", borderwidth=1, relief="solid")
        style.configure("TLabelframe.Label", background="#f3f5f8", foreground="#111827", font=("Segoe UI Semibold", 10))
        style.configure("TNotebook", background="#e5e7eb", tabmargins=(6, 6, 6, 0))
        style.configure("TNotebook.Tab", padding=(12, 6), font=("Segoe UI Semibold", 10))
        style.map("TNotebook.Tab", background=[("selected", "#ffffff"), ("active", "#f9fafb")])
        style.configure("TButton", padding=(10, 6), font=("Segoe UI Semibold", 9))
        style.configure("TEntry", fieldbackground="#ffffff")
        style.configure("TCombobox", fieldbackground="#ffffff", padding=(8, 4, 8, 4), font=("Segoe UI", 11))
        style.configure("Treeview", rowheight=28, font=("Segoe UI", 11))
        style.configure("Treeview.Heading", font=("Segoe UI Semibold", 10))

    def _build_ui(self):
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True)

        monitor_tab = ttk.Frame(notebook)
        scripts_tab = ttk.Frame(notebook)
        logs_tab    = ttk.Frame(notebook)
        data_tab    = ttk.Frame(notebook)

        notebook.add(monitor_tab, text="Monitor")
        notebook.add(scripts_tab, text="Scripts")
        notebook.add(logs_tab,    text="Logs")
        notebook.add(data_tab,    text="Data Editor")

        self._build_monitor_tab(monitor_tab)
        self._build_scripts_tab(scripts_tab)
        self._build_logs_tab(logs_tab)
        self._build_data_editor_tab(data_tab)

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

    # ---- Monitor tab -------------------------------------------------------

    def _build_monitor_tab(self, parent: ttk.Frame):
        controls = ttk.LabelFrame(parent, text="Mai Monitor")
        controls.pack(fill=tk.X, padx=12, pady=12)

        ttk.Label(controls, text="Status:").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ttk.Label(controls, textvariable=self.monitor_status_var).grid(row=0, column=1, sticky="w", padx=8, pady=8)

        ttk.Button(controls, text="Start Monitor", command=self.start_monitor).grid(row=0, column=2, padx=8, pady=8)
        ttk.Button(controls, text="Stop Monitor",  command=self.stop_monitor).grid(row=0, column=3, padx=8, pady=8)
        ttk.Button(controls, text="Reload Config", command=self._load_monitor_config_into_form).grid(row=0, column=4, padx=8, pady=8)

        form = ttk.LabelFrame(parent, text="Monitor Runtime Config (live-reloadable)")
        form.pack(fill=tk.X, padx=12, pady=8)

        fields = [
            ("twitch_channel",          "Twitch channel",                  "str"),
            ("owner_username",           "Owner username",                   "str"),
            ("response_chance_percent",  "Response chance %",                "float"),
            ("global_cooldown_seconds",  "Global cooldown (s)",              "int"),
            ("check_buffer_size",        "IRC buffer size",                  "int"),
            ("ignored_bot_usernames",    "Ignored bots (comma separated)",   "str"),
            ("config_reload_seconds",    "Config reload interval (s)",       "float"),
            ("registry_flush_seconds",   "Registry flush interval (s)",      "int"),
            ("irc_server",               "IRC server",                       "str"),
            ("irc_port",                 "IRC port",                         "int"),
        ]
        bool_fields = [
            ("respond_to_owner_always",  "Always respond to owner"),
            ("ignore_command_messages",  "Ignore command messages (!foo)"),
        ]

        for i, (key, label, _) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=i, column=0, sticky="w", padx=8, pady=5)
            var = tk.StringVar()
            ttk.Entry(form, textvariable=var, width=48).grid(row=i, column=1, sticky="w", padx=8, pady=5)
            self.monitor_vars[key] = var

        base_row = len(fields)
        for i, (key, label) in enumerate(bool_fields):
            var = tk.BooleanVar(value=False)
            ttk.Checkbutton(form, text=label, variable=var).grid(
                row=base_row + i, column=0, columnspan=2, sticky="w", padx=8, pady=4
            )
            self.monitor_vars[key] = var

        action_row = base_row + len(bool_fields)
        ttk.Button(form, text="Save Config", command=self.save_monitor_config).grid(
            row=action_row, column=0, padx=8, pady=10, sticky="w"
        )
        ttk.Label(
            form,
            text="Changes apply to running monitor automatically within the configured reload interval.",
        ).grid(row=action_row, column=1, sticky="w", padx=8, pady=10)

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

        ttk.Label(qt_frame, text="Username").grid(row=0, column=2, sticky="w", padx=8, pady=6)
        ttk.Entry(qt_frame, textvariable=self.qt_username_var, width=20).grid(row=0, column=3, sticky="w", padx=8, pady=6)

        # Dynamic fields frame (swapped on keyword change)
        self._qt_fields_frame = ttk.Frame(qt_frame)
        self._qt_fields_frame.grid(row=1, column=0, columnspan=4, sticky="w", padx=4, pady=4)
        self._build_qt_flirt_fields(self._qt_fields_frame)

        ttk.Button(qt_frame, text="Fire Command", command=self._fire_quick_test).grid(
            row=2, column=0, columnspan=4, padx=8, pady=8, sticky="w"
        )

        # Script launcher section
        launcher = ttk.LabelFrame(parent, text="Script Launcher")
        launcher.pack(fill=tk.X, padx=12, pady=8)

        script_choices = self._discover_scripts()
        if script_choices:
            self.script_var.set(script_choices[0])

        ttk.Label(launcher, text="Script").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        script_menu = ttk.Combobox(launcher, textvariable=self.script_var, values=script_choices, width=55)
        script_menu.grid(row=0, column=1, sticky="w", padx=8, pady=8)

        ttk.Label(launcher, text="Args").grid(row=1, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(launcher, textvariable=self.script_args_var, width=58).grid(row=1, column=1, sticky="w", padx=8, pady=8)

        ttk.Label(launcher, text="Status:").grid(row=2, column=0, sticky="w", padx=8, pady=8)
        ttk.Label(launcher, textvariable=self.script_status_var).grid(row=2, column=1, sticky="w", padx=8, pady=8)

        ttk.Button(launcher, text="Run Script",  command=self.run_selected_script).grid(row=0, column=2, padx=8, pady=8)
        ttk.Button(launcher, text="Stop Script", command=self.stop_selected_script).grid(row=1, column=2, padx=8, pady=8)

        info = ttk.LabelFrame(parent, text="Packaging")
        info.pack(fill=tk.X, padx=12, pady=8)
        ttk.Label(
            info,
            text="Use build_mai_ui.ps1 to package this panel as a windowed .exe. The panel launches scripts from this repo.",
        ).pack(anchor="w", padx=8, pady=8)

    def _build_qt_flirt_fields(self, parent: ttk.Frame):
        for w in parent.winfo_children():
            w.destroy()
        ttk.Label(parent, text="Theme").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(parent, textvariable=self.qt_theme_var, width=18).grid(row=0, column=1, sticky="w", padx=4, pady=4)
        ttk.Label(parent, text="Tone").grid(row=0, column=2, sticky="w", padx=8, pady=4)
        ttk.Entry(parent, textvariable=self.qt_tone_var, width=18).grid(row=0, column=3, sticky="w", padx=4, pady=4)
        ttk.Label(parent, text="Spice (1-10)").grid(row=0, column=4, sticky="w", padx=8, pady=4)
        ttk.Spinbox(parent, from_=1, to=10, textvariable=self.qt_spice_var, width=5).grid(
            row=0, column=5, sticky="w", padx=4, pady=4
        )

    def _build_qt_tarot_fields(self, parent: ttk.Frame):
        for w in parent.winfo_children():
            w.destroy()
        ttk.Label(parent, text="Question").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(parent, textvariable=self.qt_question_var, width=40).grid(row=0, column=1, sticky="w", padx=4, pady=4)
        ttk.Label(parent, text="Spread").grid(row=0, column=2, sticky="w", padx=8, pady=4)
        ttk.Combobox(
            parent, textvariable=self.qt_spread_var,
            values=["single", "3-card", "horseshoe", "celtic-cross"],
            state="readonly", width=14
        ).grid(row=0, column=3, sticky="w", padx=4, pady=4)

    def _build_qt_commands_fields(self, parent: ttk.Frame):
        for w in parent.winfo_children():
            w.destroy()
        ttk.Label(parent, text="Command Input").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(parent, textvariable=self.qt_command_input_var, width=40).grid(
            row=0, column=1, sticky="w", padx=4, pady=4
        )
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

        self.log_text = tk.Text(frame, wrap=tk.WORD, height=30)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=scrollbar.set)

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
        data_inner.add(themes_tab, text="Themes")
        data_inner.add(tones_tab, text="Tones")

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
        users_inner.add(normal_users_tab, text="Normal")
        users_inner.add(vip_users_tab, text="VIP")
        users_inner.add(moderator_users_tab, text="Moderators")

        self._build_list_editor(
            cooldown_tab,
            load_fn=lambda: load_json(Paths.COOLDOWN_MSGS, default={}).get("cooldown_messages", []),
            save_fn=lambda items: atomic_write_json(Paths.COOLDOWN_MSGS, {"cooldown_messages": items}),
            hint="{remaining} is replaced with the cooldown seconds at runtime.",
            source_path=Paths.COOLDOWN_MSGS,
            item_label="Cooldown Message",
        )
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
        self._build_kv_editor(
            commands_tab,
            path=Paths.COMMANDS,
            fields=[
                ("Key", "key"),
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
        records: list[dict] = []
        node_to_index: dict[str, int] = {}
        folder_node_to_name: dict[str, str] = {}
        drag_state: dict[str, object] = {"index": None, "dragging": False, "target_node": None}

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

        def _set_group_open(is_open: bool):
            for node in tree.get_children(""):
                tree.item(node, open=is_open)

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
                    parent_id = tree.insert("", tk.END, text=f"\U0001F4C1  {folder_name} ({len(ids)})", open=True)
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

        tree.bind("<<TreeviewSelect>>", _on_select)
        tree.bind("<ButtonPress-1>", _on_tree_press)
        tree.bind("<B1-Motion>", _on_tree_drag)
        tree.bind("<ButtonRelease-1>", _on_tree_release)
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
        drag_state: dict[str, object] = {"key": None, "dragging": False, "target_node": None}

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

        def _set_group_nodes_open(is_open: bool):
            for node in tree.get_children(""):
                tree.item(node, open=is_open)

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
                    parent_id = tree.insert("", tk.END, text=f"\U0001F4C1  {grp} ({len(keys)})", open=True)
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

        tree.bind("<<TreeviewSelect>>", _on_select)
        tree.bind("<ButtonPress-1>", _on_tree_press)
        tree.bind("<B1-Motion>", _on_tree_drag)
        tree.bind("<ButtonRelease-1>", _on_tree_release)
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

    def _append_log(self, message: str):
        self.log_text.insert(tk.END, message + "\n")
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
        self.log_queue.put(f"[{name}] started: {' '.join(command)}")

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

    def stop_monitor(self):
        self._stop_process("monitor")
        self.monitor_status_var.set("Stopped")

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
            return

        monitor = cfg.get("monitor", {}) if isinstance(cfg.get("monitor", {}), dict) else {}

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

        self.log_queue.put("[ui] monitor config loaded")

    def save_monitor_config(self):
        try:
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
            monitor["irc_server"]              = self.monitor_vars["irc_server"].get().strip() or "irc.chat.twitch.tv"
            monitor["irc_port"]                = int(self.monitor_vars["irc_port"].get().strip() or 6667)

            cfg["monitor"]        = monitor
            cfg["twitch_channel"] = monitor["twitch_channel"]

            atomic_write_json(self.config_path, cfg)
            self.log_queue.put("[ui] monitor config saved")
            messagebox.showinfo("Config", "Monitor config saved. Running monitor will auto-reload it.")
        except Exception as e:
            messagebox.showerror("Config", f"Failed to save config: {e}")
            self.log_queue.put(f"[ui] failed to save config: {e}")

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
        for name in list(self.processes.keys()):
            self._stop_process(name)
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
