import tkinter as tk
from tkinter import messagebox, ttk

from utils.helpers import atomic_write_json, load_json

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
