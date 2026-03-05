import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from utils.helpers import atomic_write_json, load_json

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
