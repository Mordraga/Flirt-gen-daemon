import tkinter as tk
from tkinter import messagebox, ttk

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
