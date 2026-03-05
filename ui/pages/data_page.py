import tkinter as tk
from tkinter import ttk

from utils.helpers import atomic_write_json, load_json
from utils.paths import Paths

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
    moods_tab = ttk.Frame(data_inner)
    data_inner.add(themes_tab, text="Themes")
    data_inner.add(tones_tab, text="Tones")
    data_inner.add(moods_tab, text="Moods")

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
    owner_tab = ttk.Frame(users_inner)
    users_inner.add(normal_users_tab, text="Normal")
    users_inner.add(vip_users_tab, text="VIP")
    users_inner.add(moderator_users_tab, text="Moderators")
    users_inner.add(owner_tab, text="Owner")

    self._build_tool_cooldown_editor(cooldown_tab)
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
    self._build_moods_editor(moods_tab)
    _cmd_hint = ttk.LabelFrame(commands_tab, text="How Commands Work")
    _cmd_hint.pack(fill=tk.X, padx=8, pady=(8, 0))
    ttk.Label(
        _cmd_hint,
        text=(
            "URL: appended to the chat output automatically — Mai does not generate it.\n"
            "Description & Context: guide Mai's in-character reaction to the command.\n"
            "Response Data: extra text Mai may reference (e.g. for !about). Leave blank if not needed."
        ),
        foreground="gray",
        justify=tk.LEFT,
        wraplength=720,
    ).pack(anchor="w", padx=10, pady=6)
    self._build_kv_editor(
        commands_tab,
        path=Paths.COMMANDS,
        fields=[
            ("Key", "key"),
            ("URL", "url"),
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
    self._build_owner_profile_editor(owner_tab)

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
