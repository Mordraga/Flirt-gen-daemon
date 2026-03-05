import os
import re
import shutil
import subprocess
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import colorchooser, messagebox, simpledialog, ttk

from ui.atoms.layout import _scrolled_listbox
from utils.helpers import atomic_write_json, load_json, resolve_existing_path
from utils.paths import Paths


REPO_ROOT = Path(__file__).resolve().parents[2]


COLORBLIND_PRESETS: dict[str, dict] = {
    "standard": {
        "chip_colors": {
            "monitor": "#22c55e",
            "routing": "#0ea5e9",
            "flirt": "#f97316",
            "tarot": "#a855f7",
            "commands": "#14b8a6",
        },
        "severity_colors": {
            "warn": "#f59e0b",
            "bad": "#ef4444",
            "idle": "#9ca3af",
        },
    },
    "protanomaly": {
        "chip_colors": {
            "monitor": "#0072b2",
            "routing": "#56b4e9",
            "flirt": "#e69f00",
            "tarot": "#cc79a7",
            "commands": "#009e73",
        },
        "severity_colors": {
            "warn": "#f0e442",
            "bad": "#d81b60",
            "idle": "#9aa0a6",
        },
    },
    "deutranomaly": {
        "chip_colors": {
            "monitor": "#1f77b4",
            "routing": "#17becf",
            "flirt": "#ff7f0e",
            "tarot": "#9467bd",
            "commands": "#bcbd22",
        },
        "severity_colors": {
            "warn": "#ffd166",
            "bad": "#ef476f",
            "idle": "#8d99ae",
        },
    },
    "tritanomaly": {
        "chip_colors": {
            "monitor": "#2ca02c",
            "routing": "#d62728",
            "flirt": "#8c564b",
            "tarot": "#e377c2",
            "commands": "#7f7f7f",
        },
        "severity_colors": {
            "warn": "#ff9f1c",
            "bad": "#c1121f",
            "idle": "#adb5bd",
        },
    },
}

def _select_color_for_var(self, target_var: tk.StringVar, title: str) -> None:
    initial = target_var.get().strip() or "#ffffff"
    _rgb, hex_value = colorchooser.askcolor(initialcolor=initial, title=title, parent=self.root)
    if not hex_value:
        return
    target_var.set(str(hex_value).lower())

def _apply_colorblind_preset_to_controls(self, mode: str) -> None:
    preset = COLORBLIND_PRESETS.get(str(mode or "").strip().lower())
    if not preset:
        return
    for key, color in preset["chip_colors"].items():
        var = self.settings_chip_color_vars.get(key)
        if var is not None:
            var.set(color)
    for key, color in preset["severity_colors"].items():
        var = self.settings_severity_color_vars.get(key)
        if var is not None:
            var.set(color)

def _is_valid_profile_name(self, value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9 _.\-]{1,40}", value or ""))

def _refresh_settings_profile_controls(self) -> None:
    if self.settings_ui_profile_var is None or self.settings_profile_combo is None:
        return
    profiles = self.ui_profiles.get("profiles", {}) if isinstance(self.ui_profiles, dict) else {}
    names = sorted([str(name) for name in profiles.keys() if str(name).strip()], key=str.lower)
    if not names:
        names = ["default"]
        self.ui_profiles = self._default_ui_profiles()
        self._save_ui_profiles()
    current = str(self.settings_ui_profile_var.get() or self.ui_profiles.get("active_profile", names[0])).strip()
    if current not in names:
        current = str(self.ui_profiles.get("active_profile", names[0]))
    if current not in names:
        current = names[0]
    self.settings_profile_combo["values"] = names
    self.settings_ui_profile_var.set(current)
    self.ui_profiles["active_profile"] = current

def _load_ui_profile_into_controls(self, profile_name: str, persist_active: bool = True) -> None:
    profiles = self.ui_profiles.get("profiles", {}) if isinstance(self.ui_profiles, dict) else {}
    selected = profiles.get(profile_name)
    if not isinstance(selected, dict):
        self._set_status(f"UI profile not found: {profile_name}", "warn")
        return
    if persist_active:
        self.ui_profiles["active_profile"] = profile_name
    self.ui_settings = self._merge_ui_settings(selected)
    self._sync_settings_controls_from_ui_settings()
    self._apply_ui_style()
    self._refresh_glance()
    self._mark_dirty("settings", False)
    if persist_active:
        self.ui_profiles.setdefault("profiles", {})[profile_name] = dict(self.ui_settings)
        self._save_ui_profiles()
        self._save_ui_settings()
        self._refresh_settings_profile_controls()
    self._set_status(f"Loaded UI profile '{profile_name}'.", "ok")

def _on_settings_profile_selected(self, _event=None) -> None:
    if self.settings_ui_profile_var is None:
        return
    selected = str(self.settings_ui_profile_var.get() or "").strip()
    if not selected:
        return
    self._load_ui_profile_into_controls(selected, persist_active=True)

def _save_as_new_ui_profile(self) -> None:
    initial = ""
    if self.settings_ui_profile_var is not None:
        initial = str(self.settings_ui_profile_var.get() or "").strip()
    requested = simpledialog.askstring(
        "Save UI Profile",
        "Profile name (letters/numbers/space/._-):",
        initialvalue=initial,
        parent=self.root,
    )
    if requested is None:
        return
    name = str(requested).strip()
    if not self._is_valid_profile_name(name):
        messagebox.showwarning("Profile", "Use 1-40 chars: letters, numbers, space, dot, dash, underscore.", parent=self.root)
        return
    profiles = self.ui_profiles.setdefault("profiles", {})
    if name in profiles:
        if not messagebox.askyesno("Profile Exists", f"Overwrite existing profile '{name}'?", parent=self.root):
            return
    self.ui_settings = self._collect_ui_settings_from_controls()
    profiles[name] = dict(self.ui_settings)
    self.ui_profiles["active_profile"] = name
    self._save_ui_profiles()
    self._save_ui_settings()
    self._refresh_settings_profile_controls()
    self._mark_dirty("settings", False)
    self._set_status(f"Saved UI profile '{name}'.", "ok")

def _rename_selected_ui_profile(self) -> None:
    if self.settings_ui_profile_var is None:
        return
    old_name = str(self.settings_ui_profile_var.get() or "").strip()
    if not old_name:
        messagebox.showwarning("Profile", "Select a profile first.", parent=self.root)
        return
    profiles = self.ui_profiles.get("profiles", {}) if isinstance(self.ui_profiles, dict) else {}
    if old_name not in profiles:
        messagebox.showwarning("Profile", f"Profile not found: {old_name}", parent=self.root)
        return
    requested = simpledialog.askstring(
        "Rename UI Profile",
        "New profile name:",
        initialvalue=old_name,
        parent=self.root,
    )
    if requested is None:
        return
    new_name = str(requested).strip()
    if new_name == old_name:
        return
    if not self._is_valid_profile_name(new_name):
        messagebox.showwarning("Profile", "Use 1-40 chars: letters, numbers, space, dot, dash, underscore.", parent=self.root)
        return
    if new_name in profiles:
        messagebox.showwarning("Profile", f"A profile named '{new_name}' already exists.", parent=self.root)
        return
    profiles[new_name] = profiles.pop(old_name)
    if str(self.ui_profiles.get("active_profile", "")) == old_name:
        self.ui_profiles["active_profile"] = new_name
    self._save_ui_profiles()
    self._refresh_settings_profile_controls()
    self._set_status(f"Renamed profile '{old_name}' to '{new_name}'.", "ok")

def _delete_selected_ui_profile(self) -> None:
    if self.settings_ui_profile_var is None:
        return
    target = str(self.settings_ui_profile_var.get() or "").strip()
    if not target:
        messagebox.showwarning("Profile", "Select a profile first.", parent=self.root)
        return
    profiles = self.ui_profiles.get("profiles", {}) if isinstance(self.ui_profiles, dict) else {}
    if target not in profiles:
        messagebox.showwarning("Profile", f"Profile not found: {target}", parent=self.root)
        return
    if len(profiles) <= 1:
        messagebox.showwarning("Profile", "At least one UI profile must remain.", parent=self.root)
        return
    if not messagebox.askyesno("Delete Profile", f"Delete UI profile '{target}'?", parent=self.root):
        return
    profiles.pop(target, None)
    next_name = sorted(profiles.keys(), key=str.lower)[0]
    self.ui_profiles["active_profile"] = next_name
    self._save_ui_profiles()
    self._refresh_settings_profile_controls()
    self._load_ui_profile_into_controls(next_name, persist_active=True)
    self._set_status(f"Deleted profile '{target}'.", "ok")

def _collect_ui_settings_from_controls(self) -> dict:
    if (
        self.settings_dark_mode_var is None
        or self.settings_colorblind_mode_var is None
        or self.settings_font_scale_var is None
        or self.settings_density_var is None
    ):
        return dict(self.ui_settings)

    mode = str(self.settings_colorblind_mode_var.get() or "standard").strip().lower()
    if mode not in COLORBLIND_PRESETS:
        mode = "standard"
    font_scale = str(self.settings_font_scale_var.get() or "100%").strip()
    if font_scale not in {"90%", "100%", "115%"}:
        font_scale = "100%"
    density = str(self.settings_density_var.get() or "comfortable").strip().lower()
    if density not in {"compact", "comfortable"}:
        density = "comfortable"

    payload = {
        "dark_mode": bool(self.settings_dark_mode_var.get()),
        "colorblind_mode": mode,
        "chip_colors": {},
        "severity_colors": {},
        "font_scale": font_scale,
        "density": density,
    }

    preset = COLORBLIND_PRESETS[mode]
    for key, default in preset["chip_colors"].items():
        var = self.settings_chip_color_vars.get(key)
        raw = str(var.get()).strip().lower() if var is not None else default
        payload["chip_colors"][key] = raw if self._is_hex_color(raw) else default

    for key, default in preset["severity_colors"].items():
        var = self.settings_severity_color_vars.get(key)
        raw = str(var.get()).strip().lower() if var is not None else default
        payload["severity_colors"][key] = raw if self._is_hex_color(raw) else default

    return self._merge_ui_settings(payload)

def _apply_ui_settings_from_controls(self, save: bool) -> None:
    self.ui_settings = self._collect_ui_settings_from_controls()
    self._apply_ui_style()
    self._refresh_glance()
    if save:
        active_profile = str(self.ui_profiles.get("active_profile", "default")).strip() or "default"
        if self.settings_ui_profile_var is not None:
            selected = str(self.settings_ui_profile_var.get() or "").strip()
            if selected:
                active_profile = selected
        self.ui_profiles.setdefault("profiles", {})[active_profile] = dict(self.ui_settings)
        self.ui_profiles["active_profile"] = active_profile
        self._save_ui_profiles()
        self._save_ui_settings()
        self._refresh_settings_profile_controls()
        self.log_queue.put("[settings] UI settings saved")
        self._set_status(f"Settings saved to profile '{active_profile}'.", "ok")
        self._mark_dirty("settings", False)
        messagebox.showinfo("Settings", "Accessibility settings saved.", parent=self.root)
    else:
        self.log_queue.put("[settings] UI settings applied")
        self._set_status("Settings applied.", "ok")

def _sync_settings_controls_from_ui_settings(self) -> None:
    if self.settings_ui_profile_var is not None:
        self.settings_ui_profile_var.set(str(self.ui_profiles.get("active_profile", "default")))
    if self.settings_dark_mode_var is not None:
        self.settings_dark_mode_var.set(bool(self.ui_settings.get("dark_mode", False)))
    if self.settings_colorblind_mode_var is not None:
        self.settings_colorblind_mode_var.set(str(self.ui_settings.get("colorblind_mode", "standard")))
    if self.settings_font_scale_var is not None:
        self.settings_font_scale_var.set(str(self.ui_settings.get("font_scale", "100%")))
    if self.settings_density_var is not None:
        self.settings_density_var.set(str(self.ui_settings.get("density", "comfortable")))

    chip_colors = self.ui_settings.get("chip_colors", {})
    for key, var in self.settings_chip_color_vars.items():
        var.set(str(chip_colors.get(key, var.get())))
    severity_colors = self.ui_settings.get("severity_colors", {})
    for key, var in self.settings_severity_color_vars.items():
        var.set(str(severity_colors.get(key, var.get())))

def _snapshot_root(self) -> Path:
    return REPO_ROOT / "jsons" / "configs" / "snapshots"

def _snapshot_target_files(self) -> list[Path]:
    return [self.config_path, self.ui_settings_path, self.ui_profiles_path, self.ui_state_path]

def _list_config_snapshots(self) -> list[Path]:
    root = self._snapshot_root()
    if not root.exists():
        return []
    items = [path for path in root.iterdir() if path.is_dir()]
    return sorted(items, key=lambda item: item.name, reverse=True)

def _refresh_snapshot_list(self) -> None:
    if self.settings_snapshot_listbox is None:
        return
    self.settings_snapshot_name_to_path.clear()
    self.settings_snapshot_listbox.delete(0, tk.END)
    for snap in self._list_config_snapshots():
        name = snap.name
        self.settings_snapshot_name_to_path[name] = snap
        self.settings_snapshot_listbox.insert(tk.END, name)

def _create_config_snapshot(self) -> None:
    try:
        root = self._snapshot_root()
        root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        snapshot_dir = root / stamp
        suffix = 1
        while snapshot_dir.exists():
            snapshot_dir = root / f"{stamp}_{suffix}"
            suffix += 1
        snapshot_dir.mkdir(parents=True, exist_ok=False)

        copied = 0
        for src in self._snapshot_target_files():
            if not src.exists():
                continue
            shutil.copy2(src, snapshot_dir / src.name)
            copied += 1

        self._refresh_snapshot_list()
        self._set_status(f"Created snapshot {snapshot_dir.name} ({copied} files).", "ok")
        self.log_queue.put(f"[settings] created snapshot {snapshot_dir}")
    except Exception as e:
        self._set_status(f"Snapshot creation failed: {e}", "error")
        messagebox.showerror("Snapshot", f"Failed to create snapshot: {e}", parent=self.root)

def _restore_selected_snapshot(self) -> None:
    if self.settings_snapshot_listbox is None:
        return
    selection = self.settings_snapshot_listbox.curselection()
    if not selection:
        messagebox.showwarning("Snapshot", "Select a snapshot to restore.", parent=self.root)
        return
    name = str(self.settings_snapshot_listbox.get(selection[0]))
    snap_path = self.settings_snapshot_name_to_path.get(name)
    if snap_path is None or not snap_path.exists():
        messagebox.showerror("Snapshot", f"Snapshot not found: {name}", parent=self.root)
        self._refresh_snapshot_list()
        return
    if not self._confirm_discard_unsaved("restoring a snapshot"):
        return
    if not messagebox.askyesno(
        "Restore Snapshot",
        f"Restore snapshot '{name}'?\nThis overwrites current config and UI settings files.",
        parent=self.root,
    ):
        return
    try:
        for dst in self._snapshot_target_files():
            src = snap_path / dst.name
            if src.exists():
                shutil.copy2(src, dst)
        self.ui_profiles = self._load_ui_profiles(self._load_ui_settings())
        active_name = str(self.ui_profiles.get("active_profile", "default"))
        self.ui_settings = dict(self.ui_profiles.get("profiles", {}).get(active_name, self._default_ui_settings()))
        self.ui_state = self._load_ui_state()
        self._refresh_settings_profile_controls()
        self._sync_settings_controls_from_ui_settings()
        self._apply_ui_style()
        self._load_monitor_config_into_form()
        self._load_owner_profile_into_editor()
        self._refresh_glance()
        self._refresh_chat_analytics()
        self._mark_dirty("settings", False)
        self._mark_dirty("data", False)
        self._set_status(f"Restored snapshot {name}.", "ok")
        self.log_queue.put(f"[settings] restored snapshot {snap_path}")
    except Exception as e:
        self._set_status(f"Snapshot restore failed: {e}", "error")
        messagebox.showerror("Snapshot", f"Failed to restore snapshot: {e}", parent=self.root)

def _persistent_backup_base_root(self) -> Path:
    candidates: list[Path] = []
    local_appdata = str(os.getenv("LOCALAPPDATA") or "").strip()
    appdata = str(os.getenv("APPDATA") or "").strip()
    if local_appdata:
        candidates.append(Path(local_appdata) / "MaiControlPanel" / "backups")
    if appdata:
        candidates.append(Path(appdata) / "MaiControlPanel" / "backups")
    candidates.append(Path.home() / ".mai_control_panel" / "backups")
    candidates.append(REPO_ROOT / "backups")

    for root in candidates:
        try:
            root.mkdir(parents=True, exist_ok=True)
            return root
        except Exception:
            continue
    return REPO_ROOT / "backups"

def _update_backup_root_label(self) -> None:
    base = self._persistent_backup_base_root()
    self.settings_backup_root_var.set(str(base))

def _open_backup_folder(self) -> None:
    root = self._persistent_backup_base_root()
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(root))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(root)], cwd=REPO_ROOT)
        else:
            subprocess.Popen(["xdg-open", str(root)], cwd=REPO_ROOT)
        self._set_status(f"Opened backup folder: {root}", "ok")
    except Exception as e:
        self._set_status(f"Could not open backup folder: {e}", "error")
        messagebox.showerror("Backup Folder", f"Failed to open backup folder:\n{root}\n\n{e}", parent=self.root)

def _full_backup_root(self) -> Path:
    return self._persistent_backup_base_root() / "full_data"

def _list_full_backups(self) -> list[Path]:
    root = self._full_backup_root()
    if not root.exists():
        return []
    candidates = [item for item in root.iterdir() if item.is_dir()]
    return sorted(candidates, key=lambda item: item.name, reverse=True)

def _refresh_full_backup_list(self) -> None:
    self._update_backup_root_label()
    if self.settings_full_backup_listbox is None:
        return
    self.settings_full_backup_name_to_path.clear()
    self.settings_full_backup_listbox.delete(0, tk.END)
    for item in self._list_full_backups():
        name = item.name
        self.settings_full_backup_name_to_path[name] = item
        self.settings_full_backup_listbox.insert(tk.END, name)

def _create_full_backup_folder(self, name_prefix: str = "all_data") -> Path:
    root = self._full_backup_root()
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = root / f"{name_prefix}_{stamp}"
    suffix = 1
    while backup_dir.exists():
        backup_dir = root / f"{name_prefix}_{stamp}_{suffix}"
        suffix += 1
    backup_dir.mkdir(parents=True, exist_ok=False)

    source_jsons = REPO_ROOT / "jsons"
    target_jsons = backup_dir / "jsons"
    if source_jsons.exists():
        shutil.copytree(source_jsons, target_jsons)
    else:
        target_jsons.mkdir(parents=True, exist_ok=True)
    return backup_dir

def _create_full_data_backup(self) -> None:
    try:
        backup_dir = self._create_full_backup_folder(name_prefix="all_data")
        self._refresh_full_backup_list()
        self.log_queue.put(f"[settings] full data backup created: {backup_dir}")
        self._set_status(f"Full data backup created: {backup_dir}", "ok")
    except Exception as e:
        self._set_status(f"Full data backup failed: {e}", "error")
        messagebox.showerror("Backup", f"Failed to create full data backup: {e}", parent=self.root)

def _restore_selected_full_backup(self) -> None:
    if self.settings_full_backup_listbox is None:
        return
    selection = self.settings_full_backup_listbox.curselection()
    if not selection:
        messagebox.showwarning("Backup", "Select a backup to restore.", parent=self.root)
        return
    name = str(self.settings_full_backup_listbox.get(selection[0]))
    backup_path = self.settings_full_backup_name_to_path.get(name)
    if backup_path is None or not backup_path.exists():
        messagebox.showerror("Backup", f"Backup not found: {name}", parent=self.root)
        self._refresh_full_backup_list()
        return
    source_jsons = backup_path / "jsons"
    if not source_jsons.exists():
        messagebox.showerror("Backup", f"Backup is missing jsons/: {name}", parent=self.root)
        return
    if not self._confirm_discard_unsaved("restoring a full data backup"):
        return
    if not messagebox.askyesno(
        "Restore Full Data Backup",
        f"Restore backup '{name}'?\nThis overwrites all files under jsons/.",
        parent=self.root,
    ):
        return

    try:
        current_jsons = REPO_ROOT / "jsons"
        self._create_full_backup_folder(name_prefix="pre_restore")
        if current_jsons.exists():
            shutil.rmtree(current_jsons)
        shutil.copytree(source_jsons, current_jsons)

        self.ui_profiles = self._load_ui_profiles(self._load_ui_settings())
        active_name = str(self.ui_profiles.get("active_profile", "default"))
        self.ui_settings = dict(self.ui_profiles.get("profiles", {}).get(active_name, self._default_ui_settings()))
        self.ui_state = self._load_ui_state()
        self._sync_settings_controls_from_ui_settings()
        self._refresh_settings_profile_controls()
        self._apply_ui_style()
        self._load_monitor_config_into_form()
        self._load_owner_profile_into_editor()
        self._refresh_chat_analytics()
        self._refresh_glance()
        self._refresh_snapshot_list()
        self._refresh_full_backup_list()
        self._mark_dirty("settings", False)
        self._mark_dirty("data", False)
        self.log_queue.put(f"[settings] restored full data backup: {backup_path}")
        self._set_status(f"Restored full data backup: {name}", "ok")
    except Exception as e:
        self._set_status(f"Full data restore failed: {e}", "error")
        messagebox.showerror("Backup", f"Failed to restore full data backup: {e}", parent=self.root)

def _rename_selected_full_backup(self) -> None:
    if self.settings_full_backup_listbox is None:
        return
    selection = self.settings_full_backup_listbox.curselection()
    if not selection:
        messagebox.showwarning("Backup", "Select a backup first.", parent=self.root)
        return
    old_name = str(self.settings_full_backup_listbox.get(selection[0]))
    backup_path = self.settings_full_backup_name_to_path.get(old_name)
    if backup_path is None or not backup_path.exists():
        self._refresh_full_backup_list()
        messagebox.showerror("Backup", f"Backup not found: {old_name}", parent=self.root)
        return
    requested = simpledialog.askstring("Rename Backup", "New backup name:", initialvalue=old_name, parent=self.root)
    if requested is None:
        return
    new_name = str(requested).strip()
    if not self._is_valid_profile_name(new_name):
        messagebox.showwarning("Backup", "Use 1-40 chars: letters, numbers, space, dot, dash, underscore.", parent=self.root)
        return
    target = backup_path.parent / new_name
    if target.exists():
        messagebox.showwarning("Backup", f"A backup named '{new_name}' already exists.", parent=self.root)
        return
    try:
        backup_path.rename(target)
        self._refresh_full_backup_list()
        self._set_status(f"Renamed backup '{old_name}' to '{new_name}'.", "ok")
    except Exception as e:
        self._set_status(f"Backup rename failed: {e}", "error")
        messagebox.showerror("Backup", f"Failed to rename backup: {e}", parent=self.root)

def _delete_selected_full_backup(self) -> None:
    if self.settings_full_backup_listbox is None:
        return
    selection = self.settings_full_backup_listbox.curselection()
    if not selection:
        messagebox.showwarning("Backup", "Select a backup first.", parent=self.root)
        return
    name = str(self.settings_full_backup_listbox.get(selection[0]))
    backup_path = self.settings_full_backup_name_to_path.get(name)
    if backup_path is None or not backup_path.exists():
        self._refresh_full_backup_list()
        messagebox.showerror("Backup", f"Backup not found: {name}", parent=self.root)
        return
    if not messagebox.askyesno("Delete Backup", f"Delete backup '{name}'?", parent=self.root):
        return
    try:
        shutil.rmtree(backup_path)
        self._refresh_full_backup_list()
        self._set_status(f"Deleted backup '{name}'.", "ok")
    except Exception as e:
        self._set_status(f"Backup delete failed: {e}", "error")
        messagebox.showerror("Backup", f"Failed to delete backup: {e}", parent=self.root)

def _json_section_sources(self) -> dict[str, Path]:
    base = REPO_ROOT / "jsons"
    return {
        "configs": base / "configs",
        "data": base / "data",
        "calls": base / "calls",
    }

def _section_backup_root(self) -> Path:
    return self._persistent_backup_base_root() / "sections"

def _list_section_backups(self, section: str) -> list[Path]:
    root = self._section_backup_root() / section
    if not root.exists():
        return []
    return sorted([item for item in root.iterdir() if item.is_dir()], key=lambda item: item.name, reverse=True)

def _refresh_section_backup_list(self) -> None:
    if self.settings_section_backup_listbox is None or self.settings_section_var is None:
        return
    section = str(self.settings_section_var.get() or "configs").strip().lower()
    self.settings_section_backup_name_to_path.clear()
    self.settings_section_backup_listbox.delete(0, tk.END)
    for item in self._list_section_backups(section):
        name = item.name
        self.settings_section_backup_name_to_path[name] = item
        self.settings_section_backup_listbox.insert(tk.END, name)

def _on_section_changed(self, _event=None) -> None:
    self._refresh_section_backup_list()

def _create_section_backup(self) -> None:
    if self.settings_section_var is None:
        return
    section = str(self.settings_section_var.get() or "").strip().lower()
    source = self._json_section_sources().get(section)
    if source is None:
        messagebox.showwarning("Section Backup", "Select a valid section.", parent=self.root)
        return
    try:
        root = self._section_backup_root() / section
        root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = root / f"{section}_{stamp}"
        suffix = 1
        while backup_dir.exists():
            backup_dir = root / f"{section}_{stamp}_{suffix}"
            suffix += 1
        if source.exists():
            shutil.copytree(source, backup_dir)
        else:
            backup_dir.mkdir(parents=True, exist_ok=False)
        self._refresh_section_backup_list()
        self._set_status(f"Created {section} backup: {backup_dir.name}", "ok")
    except Exception as e:
        self._set_status(f"Section backup failed: {e}", "error")
        messagebox.showerror("Section Backup", f"Failed to create section backup: {e}", parent=self.root)

def _restore_selected_section_backup(self) -> None:
    if self.settings_section_backup_listbox is None or self.settings_section_var is None:
        return
    section = str(self.settings_section_var.get() or "").strip().lower()
    source_dir = self._json_section_sources().get(section)
    if source_dir is None:
        messagebox.showwarning("Section Backup", "Select a valid section.", parent=self.root)
        return
    selection = self.settings_section_backup_listbox.curselection()
    if not selection:
        messagebox.showwarning("Section Backup", "Select a section backup to restore.", parent=self.root)
        return
    name = str(self.settings_section_backup_listbox.get(selection[0]))
    backup_path = self.settings_section_backup_name_to_path.get(name)
    if backup_path is None or not backup_path.exists():
        self._refresh_section_backup_list()
        messagebox.showerror("Section Backup", f"Backup not found: {name}", parent=self.root)
        return
    if not self._confirm_discard_unsaved(f"restoring {section} backup"):
        return
    if not messagebox.askyesno(
        "Restore Section Backup",
        f"Restore '{name}' into jsons/{section}?\nThis overwrites that section.",
        parent=self.root,
    ):
        return
    try:
        pre_root = self._section_backup_root() / section
        pre_root.mkdir(parents=True, exist_ok=True)
        pre_name = f"pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        pre_path = pre_root / pre_name
        suffix = 1
        while pre_path.exists():
            pre_path = pre_root / f"{pre_name}_{suffix}"
            suffix += 1
        if source_dir.exists():
            shutil.copytree(source_dir, pre_path)
            shutil.rmtree(source_dir)
        shutil.copytree(backup_path, source_dir)

        if section == "configs":
            self.ui_profiles = self._load_ui_profiles(self._load_ui_settings())
            active_name = str(self.ui_profiles.get("active_profile", "default"))
            self.ui_settings = dict(
                self.ui_profiles.get("profiles", {}).get(active_name, self._default_ui_settings())
            )
            self.ui_state = self._load_ui_state()
            self._refresh_settings_profile_controls()
            self._sync_settings_controls_from_ui_settings()
            self._apply_ui_style()
        self._load_monitor_config_into_form()
        self._load_owner_profile_into_editor()
        self._refresh_chat_analytics()
        self._refresh_glance()
        self._refresh_snapshot_list()
        self._refresh_full_backup_list()
        self._refresh_section_backup_list()
        self._mark_dirty("settings", False)
        self._mark_dirty("data", False)
        self._set_status(f"Restored {section} backup '{name}'.", "ok")
    except Exception as e:
        self._set_status(f"Section restore failed: {e}", "error")
        messagebox.showerror("Section Backup", f"Failed to restore section backup: {e}", parent=self.root)

def _rename_selected_section_backup(self) -> None:
    if self.settings_section_backup_listbox is None:
        return
    selection = self.settings_section_backup_listbox.curselection()
    if not selection:
        messagebox.showwarning("Section Backup", "Select a section backup first.", parent=self.root)
        return
    old_name = str(self.settings_section_backup_listbox.get(selection[0]))
    backup_path = self.settings_section_backup_name_to_path.get(old_name)
    if backup_path is None or not backup_path.exists():
        self._refresh_section_backup_list()
        messagebox.showerror("Section Backup", f"Backup not found: {old_name}", parent=self.root)
        return
    requested = simpledialog.askstring(
        "Rename Section Backup",
        "New backup name:",
        initialvalue=old_name,
        parent=self.root,
    )
    if requested is None:
        return
    new_name = str(requested).strip()
    if not self._is_valid_profile_name(new_name):
        messagebox.showwarning("Section Backup", "Use 1-40 chars: letters, numbers, space, dot, dash, underscore.", parent=self.root)
        return
    target = backup_path.parent / new_name
    if target.exists():
        messagebox.showwarning("Section Backup", f"A backup named '{new_name}' already exists.", parent=self.root)
        return
    try:
        backup_path.rename(target)
        self._refresh_section_backup_list()
        self._set_status(f"Renamed section backup '{old_name}' to '{new_name}'.", "ok")
    except Exception as e:
        self._set_status(f"Section backup rename failed: {e}", "error")
        messagebox.showerror("Section Backup", f"Failed to rename section backup: {e}", parent=self.root)

def _delete_selected_section_backup(self) -> None:
    if self.settings_section_backup_listbox is None:
        return
    selection = self.settings_section_backup_listbox.curselection()
    if not selection:
        messagebox.showwarning("Section Backup", "Select a section backup first.", parent=self.root)
        return
    name = str(self.settings_section_backup_listbox.get(selection[0]))
    backup_path = self.settings_section_backup_name_to_path.get(name)
    if backup_path is None or not backup_path.exists():
        self._refresh_section_backup_list()
        messagebox.showerror("Section Backup", f"Backup not found: {name}", parent=self.root)
        return
    if not messagebox.askyesno("Delete Section Backup", f"Delete section backup '{name}'?", parent=self.root):
        return
    try:
        shutil.rmtree(backup_path)
        self._refresh_section_backup_list()
        self._set_status(f"Deleted section backup '{name}'.", "ok")
    except Exception as e:
        self._set_status(f"Section backup delete failed: {e}", "error")
        messagebox.showerror("Section Backup", f"Failed to delete section backup: {e}", parent=self.root)

def _wipe_jsons_contents(self) -> None:
    if not messagebox.askyesno(
        "Wipe jsons",
        "Delete all files/folders inside jsons/? A safety full backup will be created first.",
        parent=self.root,
    ):
        return
    token = simpledialog.askstring(
        "Confirm Wipe",
        "Type WIPE to continue:",
        parent=self.root,
    )
    if str(token or "").strip().upper() != "WIPE":
        self._set_status("Wipe cancelled.", "warn")
        return
    try:
        self._create_full_backup_folder(name_prefix="pre_wipe")
        jsons_root = REPO_ROOT / "jsons"
        jsons_root.mkdir(parents=True, exist_ok=True)
        for child in list(jsons_root.iterdir()):
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

        for folder in ("configs", "data", "calls"):
            (jsons_root / folder).mkdir(parents=True, exist_ok=True)

        self.ui_settings = self._default_ui_settings()
        self.ui_profiles = self._default_ui_profiles()
        self.ui_state = self._default_ui_state()
        self._save_ui_profiles()
        self._save_ui_settings()
        self._save_ui_state()
        self._sync_settings_controls_from_ui_settings()
        self._refresh_settings_profile_controls()
        self._apply_ui_style()
        self._refresh_snapshot_list()
        self._refresh_full_backup_list()
        self._refresh_section_backup_list()
        self._load_monitor_config_into_form()
        self._load_owner_profile_into_editor()
        self._refresh_chat_analytics()
        self._refresh_glance()
        self._mark_dirty("settings", False)
        self._mark_dirty("data", False)
        self._set_status("Wiped jsons contents. You can now build custom JSON data from scratch.", "ok")
        self.log_queue.put("[settings] wiped jsons contents")
    except Exception as e:
        self._set_status(f"Wipe failed: {e}", "error")
        messagebox.showerror("Wipe jsons", f"Failed to wipe jsons contents: {e}", parent=self.root)

def _build_settings_tab(self, parent: ttk.Frame):
    container = ttk.Frame(parent)
    container.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
    container.columnconfigure(0, weight=1)

    appearance = ttk.LabelFrame(container, text="Appearance")
    appearance.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    appearance.columnconfigure(1, weight=1)
    appearance.columnconfigure(2, weight=1)

    self.settings_dark_mode_var = tk.BooleanVar(value=bool(self.ui_settings.get("dark_mode", False)))
    self.settings_colorblind_mode_var = tk.StringVar(value=str(self.ui_settings.get("colorblind_mode", "standard")))
    self.settings_font_scale_var = tk.StringVar(value=str(self.ui_settings.get("font_scale", "100%")))
    self.settings_density_var = tk.StringVar(value=str(self.ui_settings.get("density", "comfortable")))
    self.settings_ui_profile_var = tk.StringVar(value=str(self.ui_profiles.get("active_profile", "default")))

    ttk.Checkbutton(appearance, text="Dark mode", variable=self.settings_dark_mode_var).grid(
        row=0, column=0, sticky="w", padx=8, pady=8
    )
    ttk.Label(appearance, text="Vision preset").grid(row=1, column=0, sticky="w", padx=8, pady=8)
    preset_combo = ttk.Combobox(
        appearance,
        textvariable=self.settings_colorblind_mode_var,
        values=["standard", "protanomaly", "deutranomaly", "tritanomaly"],
        state="readonly",
        width=18,
    )
    preset_combo.grid(row=1, column=1, sticky="w", padx=8, pady=8)
    preset_combo.bind(
        "<<ComboboxSelected>>",
        lambda _event: self._apply_colorblind_preset_to_controls(self.settings_colorblind_mode_var.get()),
    )
    ttk.Label(
        appearance,
        text="Pick a profile, then tweak colors if needed.",
    ).grid(row=1, column=2, sticky="w", padx=8, pady=8)

    ttk.Label(appearance, text="Font scale").grid(row=2, column=0, sticky="w", padx=8, pady=8)
    ttk.Combobox(
        appearance,
        textvariable=self.settings_font_scale_var,
        values=["90%", "100%", "115%"],
        state="readonly",
        width=10,
    ).grid(row=2, column=1, sticky="w", padx=8, pady=8)

    ttk.Label(appearance, text="Density").grid(row=3, column=0, sticky="w", padx=8, pady=8)
    ttk.Combobox(
        appearance,
        textvariable=self.settings_density_var,
        values=["comfortable", "compact"],
        state="readonly",
        width=14,
    ).grid(row=3, column=1, sticky="w", padx=8, pady=8)

    ttk.Label(appearance, text="UI profile").grid(row=4, column=0, sticky="w", padx=8, pady=8)
    profile_combo = ttk.Combobox(
        appearance,
        textvariable=self.settings_ui_profile_var,
        state="readonly",
        width=22,
    )
    profile_combo.grid(row=4, column=1, sticky="w", padx=8, pady=8)
    profile_combo.bind("<<ComboboxSelected>>", self._on_settings_profile_selected)
    self.settings_profile_combo = profile_combo

    profile_actions = ttk.Frame(appearance)
    profile_actions.grid(row=4, column=2, sticky="w", padx=8, pady=8)
    ttk.Button(profile_actions, text="Save As New", command=self._save_as_new_ui_profile).pack(side=tk.LEFT, padx=(0, 6))
    ttk.Button(profile_actions, text="Rename", command=self._rename_selected_ui_profile).pack(side=tk.LEFT, padx=(0, 6))
    ttk.Button(profile_actions, text="Delete", command=self._delete_selected_ui_profile).pack(side=tk.LEFT)

    appearance_actions = ttk.Frame(appearance)
    appearance_actions.grid(row=0, column=3, rowspan=5, sticky="ne", padx=8, pady=8)
    ttk.Button(
        appearance_actions,
        text="Save Settings",
        command=lambda: self._apply_ui_settings_from_controls(save=True),
    ).pack(side=tk.TOP, fill=tk.X, pady=(0, 6))
    ttk.Button(
        appearance_actions,
        text="Apply",
        command=lambda: self._apply_ui_settings_from_controls(save=False),
    ).pack(side=tk.TOP, fill=tk.X, pady=(0, 6))
    ttk.Button(
        appearance_actions,
        text="Reset To Profile",
        command=lambda: self._apply_colorblind_preset_to_controls(self.settings_colorblind_mode_var.get()),
    ).pack(side=tk.TOP, fill=tk.X, pady=(0, 6))
    ttk.Button(
        appearance_actions,
        text="Backup All Data",
        command=self._create_full_data_backup,
    ).pack(side=tk.TOP, fill=tk.X)

    chips = ttk.LabelFrame(container, text="Monitor Chip Colors")
    chips.grid(row=1, column=0, sticky="ew", pady=(0, 8))
    chips.columnconfigure(1, weight=1)

    chip_colors = self.ui_settings.get("chip_colors", {})
    chip_labels = {
        "monitor": "Monitor",
        "routing": "Routing",
        "flirt": "Flirt Output",
        "tarot": "Tarot Output",
        "commands": "Command Output",
    }
    for row, (key, label) in enumerate(chip_labels.items()):
        ttk.Label(chips, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=6)
        var = tk.StringVar(value=str(chip_colors.get(key, "#22c55e")))
        self.settings_chip_color_vars[key] = var
        ttk.Entry(chips, textvariable=var, width=14).grid(row=row, column=1, sticky="w", padx=8, pady=6)
        ttk.Button(
            chips,
            text="Pick...",
            command=lambda v=var, l=label: self._select_color_for_var(v, f"{l} Color"),
        ).grid(row=row, column=2, sticky="w", padx=8, pady=6)
        self._bind_dirty_var("settings", var)

    severity = ttk.LabelFrame(container, text="Shared Status Colors")
    severity.grid(row=2, column=0, sticky="ew", pady=(0, 8))
    severity.columnconfigure(1, weight=1)

    severity_colors = self.ui_settings.get("severity_colors", {})
    severity_labels = {
        "warn": "Warning",
        "bad": "Error",
        "idle": "Idle",
    }
    for row, (key, label) in enumerate(severity_labels.items()):
        ttk.Label(severity, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=6)
        var = tk.StringVar(value=str(severity_colors.get(key, "#9ca3af")))
        self.settings_severity_color_vars[key] = var
        ttk.Entry(severity, textvariable=var, width=14).grid(row=row, column=1, sticky="w", padx=8, pady=6)
        ttk.Button(
            severity,
            text="Pick...",
            command=lambda v=var, l=label: self._select_color_for_var(v, f"{l} Color"),
        ).grid(row=row, column=2, sticky="w", padx=8, pady=6)
        self._bind_dirty_var("settings", var)

    full_backups = ttk.LabelFrame(container, text="Full Data Backups (all jsons/*)")
    full_backups.grid(row=3, column=0, sticky="ew", pady=(0, 8))
    full_backups.columnconfigure(0, weight=1)

    full_backup_meta = ttk.Frame(full_backups)
    full_backup_meta.pack(fill=tk.X, padx=8, pady=(8, 0))
    ttk.Label(full_backup_meta, text="Stored at").pack(side=tk.LEFT, padx=(0, 6))
    ttk.Label(full_backup_meta, textvariable=self.settings_backup_root_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
    ttk.Button(full_backup_meta, text="Open Folder", command=self._open_backup_folder).pack(side=tk.RIGHT)

    full_backup_box = ttk.Frame(full_backups)
    full_backup_box.pack(fill=tk.X, padx=8, pady=8)
    full_backup_list, _full_backup_scroll = _scrolled_listbox(full_backup_box)
    full_backup_list.configure(height=6)
    self.settings_full_backup_listbox = full_backup_list

    full_backup_actions = ttk.Frame(full_backups)
    full_backup_actions.pack(anchor="w", padx=8, pady=(0, 8))
    ttk.Button(full_backup_actions, text="Create Full Backup", command=self._create_full_data_backup).pack(
        side=tk.LEFT, padx=(0, 8)
    )
    ttk.Button(full_backup_actions, text="Restore Selected", command=self._restore_selected_full_backup).pack(
        side=tk.LEFT, padx=(0, 8)
    )
    ttk.Button(full_backup_actions, text="Rename Selected", command=self._rename_selected_full_backup).pack(
        side=tk.LEFT, padx=(0, 8)
    )
    ttk.Button(full_backup_actions, text="Delete Selected", command=self._delete_selected_full_backup).pack(
        side=tk.LEFT, padx=(0, 8)
    )
    ttk.Button(full_backup_actions, text="Refresh List", command=self._refresh_full_backup_list).pack(side=tk.LEFT)

    section_backups = ttk.LabelFrame(container, text="Section Backups (configs/data/calls)")
    section_backups.grid(row=4, column=0, sticky="ew", pady=(0, 8))
    section_backups.columnconfigure(0, weight=1)

    section_controls = ttk.Frame(section_backups)
    section_controls.pack(fill=tk.X, padx=8, pady=(8, 4))
    self.settings_section_var = tk.StringVar(value="configs")
    ttk.Label(section_controls, text="Section").pack(side=tk.LEFT, padx=(0, 8))
    section_combo = ttk.Combobox(
        section_controls,
        textvariable=self.settings_section_var,
        values=["configs", "data", "calls"],
        state="readonly",
        width=12,
    )
    section_combo.pack(side=tk.LEFT, padx=(0, 8))
    section_combo.bind("<<ComboboxSelected>>", self._on_section_changed)

    section_list_frame = ttk.Frame(section_backups)
    section_list_frame.pack(fill=tk.X, padx=8, pady=4)
    section_backup_list, _section_backup_scroll = _scrolled_listbox(section_list_frame)
    section_backup_list.configure(height=6)
    self.settings_section_backup_listbox = section_backup_list

    section_actions = ttk.Frame(section_backups)
    section_actions.pack(anchor="w", padx=8, pady=(0, 8))
    ttk.Button(section_actions, text="Create Backup", command=self._create_section_backup).pack(
        side=tk.LEFT, padx=(0, 8)
    )
    ttk.Button(section_actions, text="Restore Selected", command=self._restore_selected_section_backup).pack(
        side=tk.LEFT, padx=(0, 8)
    )
    ttk.Button(section_actions, text="Rename Selected", command=self._rename_selected_section_backup).pack(
        side=tk.LEFT, padx=(0, 8)
    )
    ttk.Button(section_actions, text="Delete Selected", command=self._delete_selected_section_backup).pack(
        side=tk.LEFT, padx=(0, 8)
    )
    ttk.Button(section_actions, text="Refresh List", command=self._refresh_section_backup_list).pack(side=tk.LEFT)

    dangerous = ttk.LabelFrame(container, text="Danger Zone")
    dangerous.grid(row=5, column=0, sticky="ew", pady=(0, 8))
    dangerous.columnconfigure(1, weight=1)
    ttk.Label(
        dangerous,
        text="Wipe all contents under jsons/ (keeps empty folders and UI config defaults).",
        foreground=self.theme_palette["text_subtle"],
    ).grid(row=0, column=0, sticky="w", padx=8, pady=8)
    ttk.Button(dangerous, text="Wipe jsons Contents", command=self._wipe_jsons_contents).grid(
        row=0, column=1, sticky="e", padx=8, pady=8
    )

    self._bind_dirty_var("settings", self.settings_dark_mode_var)
    self._bind_dirty_var("settings", self.settings_colorblind_mode_var)
    self._bind_dirty_var("settings", self.settings_font_scale_var)
    self._bind_dirty_var("settings", self.settings_density_var)
    self._bind_dirty_var("settings", self.settings_ui_profile_var)
    self._refresh_settings_profile_controls()
    self._refresh_full_backup_list()
    self._refresh_section_backup_list()
    self._mark_dirty("settings", False)
