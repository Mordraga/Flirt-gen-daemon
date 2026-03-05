import tkinter as tk
from tkinter import messagebox, ttk

from utils.cooldown_messages import load_tool_cooldown_map, save_tool_cooldown_map
from utils.paths import Paths

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
