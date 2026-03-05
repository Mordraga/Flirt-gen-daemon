import tkinter as tk
from tkinter import messagebox, ttk

from utils.helpers import atomic_write_json
from utils.mood_engine import load_moods, load_moods_from_payload
from utils.paths import Paths

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
