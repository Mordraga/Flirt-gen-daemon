import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from utils.chat_analytics import analyze_activity, find_highlights, load_chat_log
from utils.helpers import resolve_existing_path
from utils.paths import Paths

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

def _format_analytics_time(self, value) -> str:
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
