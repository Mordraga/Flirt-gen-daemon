import tkinter as tk
from tkinter import messagebox, ttk


def _build_scripts_tab(self, parent: ttk.Frame):
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

    self._qt_fields_frame = ttk.Frame(qt_frame)
    self._qt_fields_frame.grid(row=1, column=0, columnspan=4, sticky="w", padx=4, pady=4)
    self._build_qt_flirt_fields(self._qt_fields_frame)

    ttk.Button(qt_frame, text="Fire Command", command=self._fire_quick_test).grid(
        row=2, column=0, columnspan=4, padx=8, pady=8, sticky="w"
    )

    logs = ttk.LabelFrame(parent, text="Runtime Logs")
    logs.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 12))
    self._build_logs_tab(logs)



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
    keyword = self.qt_keyword_var.get()
    username = self.qt_username_var.get().strip() or "TestUser"

    if keyword == "flirt":
        theme = self.qt_theme_var.get().strip()
        tone = self.qt_tone_var.get().strip()
        spice = str(self.qt_spice_var.get())
        raw_input = " ".join(filter(None, [theme, tone, spice]))
        if not raw_input.strip():
            messagebox.showwarning("Quick Test", "Enter at least one flirt parameter.")
            return
    elif keyword == "tarot":
        question = self.qt_question_var.get().strip()
        spread = self.qt_spread_var.get().strip()
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
