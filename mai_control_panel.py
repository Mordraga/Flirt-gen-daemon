import queue
import shlex
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from utils.helpers import atomic_write_json, load_json
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
    lb = tk.Listbox(parent, yscrollcommand=sb.set, selectmode=tk.SINGLE, width=60)
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
        self.root.geometry("1000x760")

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

        self._build_ui()
        self._load_monitor_config_into_form()

        self.root.after(150, self._drain_log_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close_request)
        self.root.bind("<Unmap>", self._on_window_minimize)

    # -----------------------------------------------------------------------
    # UI layout
    # -----------------------------------------------------------------------

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
            values=["flirt", "tarot"], state="readonly", width=12
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

    def _on_qt_keyword_change(self, _event=None):
        if self.qt_keyword_var.get() == "flirt":
            self._build_qt_flirt_fields(self._qt_fields_frame)
        else:
            self._build_qt_tarot_fields(self._qt_fields_frame)

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
        else:
            question  = self.qt_question_var.get().strip()
            spread    = self.qt_spread_var.get().strip()
            raw_input = " ".join(filter(None, [question, spread]))
            if not raw_input.strip():
                messagebox.showwarning("Quick Test", "Enter a question or spread type.")
                return

        command = [sys.executable, "main.py", keyword, raw_input, username]
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

        cooldown_tab = ttk.Frame(inner)
        fallback_tab = ttk.Frame(inner)
        themes_tab   = ttk.Frame(inner)
        tones_tab    = ttk.Frame(inner)

        inner.add(cooldown_tab, text="Cooldown Messages")
        inner.add(fallback_tab, text="Fallback Flirts")
        inner.add(themes_tab,   text="Themes")
        inner.add(tones_tab,    text="Tones")

        self._build_list_editor(
            cooldown_tab,
            load_fn=lambda: load_json(Paths.COOLDOWN_MSGS, default={}).get("cooldown_messages", []),
            save_fn=lambda items: atomic_write_json(Paths.COOLDOWN_MSGS, {"cooldown_messages": items}),
            hint="{remaining} is replaced with the cooldown seconds at runtime.",
        )
        self._build_list_editor(
            fallback_tab,
            load_fn=lambda: load_json(Paths.FALLBACK_FLIRTS, default={}).get("fallback_flirts", []),
            save_fn=lambda items: atomic_write_json(Paths.FALLBACK_FLIRTS, {"fallback_flirts": items}),
        )
        self._build_kv_editor(
            themes_tab,
            path=Paths.THEMES,
            fields=[("Key", "key"), ("Category", "category"), ("Description", "description")],
            anchors_field="anchors",
        )
        self._build_kv_editor(
            tones_tab,
            path=Paths.TONES,
            fields=[("Key", "key"), ("Description", "description")],
            anchors_field="anchors",
        )

    def _build_list_editor(self, parent: ttk.Frame, load_fn, save_fn, hint: str = ""):
        if hint:
            ttk.Label(parent, text=hint, foreground="gray").pack(anchor="w", padx=12, pady=(8, 2))

        list_frame = ttk.Frame(parent)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)
        lb, _ = _scrolled_listbox(list_frame)

        def _reload():
            lb.delete(0, tk.END)
            for item in load_fn():
                lb.insert(tk.END, item)

        def _add():
            val = simpledialog.askstring("Add Message", "New message:", parent=self.root)
            if val is not None and val.strip():
                lb.insert(tk.END, val.strip())

        def _edit():
            sel = lb.curselection()
            if not sel:
                messagebox.showinfo("Edit", "Select a message first.", parent=self.root)
                return
            idx = sel[0]
            val = simpledialog.askstring("Edit Message", "Edit:", initialvalue=lb.get(idx), parent=self.root)
            if val is not None and val.strip():
                lb.delete(idx)
                lb.insert(idx, val.strip())
                lb.selection_set(idx)

        def _delete():
            sel = lb.curselection()
            if not sel:
                messagebox.showinfo("Delete", "Select a message first.", parent=self.root)
                return
            if messagebox.askyesno("Delete", "Delete selected message?", parent=self.root):
                lb.delete(sel[0])

        def _save():
            items = list(lb.get(0, tk.END))
            try:
                save_fn(items)
                self.log_queue.put(f"[data editor] saved {len(items)} items")
                messagebox.showinfo("Saved", f"Saved {len(items)} items.", parent=self.root)
            except Exception as e:
                messagebox.showerror("Save Error", str(e), parent=self.root)

        btn_frame = ttk.Frame(parent)
        btn_frame.pack(anchor="w", padx=12, pady=4)
        ttk.Button(btn_frame, text="Reload", command=_reload).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Add",    command=_add).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Edit",   command=_edit).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Delete", command=_delete).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Save to File", command=_save).pack(side=tk.LEFT, padx=12)

        _reload()

    def _build_kv_editor(self, parent: ttk.Frame, path: str, fields: list, anchors_field: str):
        """Split-pane editor for JSON objects where each value is a dict."""
        pane = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        left = ttk.Frame(pane)
        pane.add(left, weight=1)
        lb_frame = ttk.LabelFrame(left, text="Keys (sorted)")
        lb_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        lb, _ = _scrolled_listbox(lb_frame)

        right = ttk.Frame(pane)
        pane.add(right, weight=2)
        form_frame = ttk.LabelFrame(right, text="Edit Entry")
        form_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        field_vars: dict[str, tk.StringVar] = {}
        for row_i, (label, field_key) in enumerate(fields):
            ttk.Label(form_frame, text=label).grid(row=row_i, column=0, sticky="w", padx=8, pady=4)
            var = tk.StringVar()
            ttk.Entry(form_frame, textvariable=var, width=36).grid(row=row_i, column=1, sticky="we", padx=8, pady=4)
            field_vars[field_key] = var

        anchor_row = len(fields)
        ttk.Label(form_frame, text="Anchors\n(one per line)").grid(
            row=anchor_row, column=0, sticky="nw", padx=8, pady=4
        )
        anchors_text = tk.Text(form_frame, width=36, height=8)
        anchors_text.grid(row=anchor_row, column=1, sticky="we", padx=8, pady=4)

        data_store: dict = {"data": {}}

        def _reload():
            data_store["data"] = load_json(path, default={})
            lb.delete(0, tk.END)
            for key in sorted(data_store["data"].keys()):
                lb.insert(tk.END, key)

        def _on_select(_event=None):
            sel = lb.curselection()
            if not sel:
                return
            key   = lb.get(sel[0])
            entry = data_store["data"].get(key, {})
            for field_key, var in field_vars.items():
                if field_key == "key":
                    var.set(key)
                else:
                    var.set(str(entry.get(field_key, "")))
            raw_anchors = entry.get(anchors_field, [])
            anchors_text.delete("1.0", tk.END)
            anchors_text.insert(
                tk.END,
                "\n".join(raw_anchors if isinstance(raw_anchors, list) else [])
            )

        lb.bind("<<ListboxSelect>>", _on_select)

        def _collect_entry() -> tuple[str, dict]:
            key = field_vars["key"].get().strip().lower() if "key" in field_vars else ""
            entry: dict = {}
            for field_key, var in field_vars.items():
                if field_key != "key":
                    entry[field_key] = var.get().strip()
            raw = anchors_text.get("1.0", tk.END).strip()
            entry[anchors_field] = [a.strip() for a in raw.splitlines() if a.strip()]
            return key, entry

        def _new():
            for var in field_vars.values():
                var.set("")
            anchors_text.delete("1.0", tk.END)

        def _save_selected():
            key, entry = _collect_entry()
            if not key:
                messagebox.showwarning("Save", "Key cannot be empty.", parent=self.root)
                return
            data_store["data"][key] = entry
            existing = list(lb.get(0, tk.END))
            if key not in existing:
                keys = sorted(existing + [key])
                lb.delete(0, tk.END)
                for k in keys:
                    lb.insert(tk.END, k)
            self.log_queue.put(f"[data editor] updated key: {key}")

        def _delete_selected():
            sel = lb.curselection()
            if not sel:
                return
            key = lb.get(sel[0])
            if messagebox.askyesno("Delete", f"Delete '{key}'?", parent=self.root):
                data_store["data"].pop(key, None)
                lb.delete(sel[0])

        def _save_all():
            try:
                atomic_write_json(path, data_store["data"])
                self.log_queue.put(f"[data editor] saved {len(data_store['data'])} entries to {path}")
                messagebox.showinfo("Saved", f"Saved {len(data_store['data'])} entries.", parent=self.root)
            except Exception as e:
                messagebox.showerror("Save Error", str(e), parent=self.root)

        btn_frame = ttk.Frame(right)
        btn_frame.pack(anchor="w", padx=4, pady=4)
        ttk.Button(btn_frame, text="Reload",          command=_reload).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="New",             command=_new).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Save Selected",   command=_save_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Delete Selected", command=_delete_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Save All to File",command=_save_all).pack(side=tk.LEFT, padx=12)

        _reload()

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
            command = [sys.executable, script, *args]
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
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
            self.tray_icon = None
        self.root.destroy()


if __name__ == "__main__":
    if "--run-monitor" in sys.argv:
        from mai_monitor import main as run_monitor
        run_monitor()
    else:
        root = tk.Tk()
        app = MaiControlPanel(root)
        root.mainloop()
