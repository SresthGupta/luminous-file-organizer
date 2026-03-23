"""
Luminous menubar app - native Mac menubar GUI using rumps.

Provides:
  - Menubar icon with status indicator
  - Recent activity feed (last 10 moves)
  - Pause / Resume watching
  - Quick-organize current watched folders
  - Settings window (watched folders, output folder, auto-rename toggle)
  - Quit
"""

import json
import os
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

import rumps

from .config import (
    CLOUD_STORAGE_PRESETS,
    UNDO_FILE,
    ensure_config_dir,
    ensure_output_dirs,
    get_output_paths,
    load_config,
    save_config,
)
from .organizer import organize_folder
from .watcher import FolderWatcher

# ---- Icons (text-based, rumps uses template images or text) ----
ICON_ACTIVE = "L"   # shown in menu bar when watching
ICON_PAUSED = "L"   # same letter, title changes


class ActivityLog:
    """Thread-safe ring buffer for recent file moves."""

    MAX = 20

    def __init__(self) -> None:
        self._entries: list[str] = []
        self._lock = threading.Lock()

    def add(self, src: str, dest: str) -> None:
        line = f"{Path(src).name} -> {Path(dest).parent.name}/{Path(dest).name}"
        with self._lock:
            self._entries.append(line)
            if len(self._entries) > self.MAX:
                self._entries.pop(0)

    def recent(self) -> list[str]:
        with self._lock:
            return list(reversed(self._entries))

    def load_from_disk(self) -> None:
        """Populate from persisted undo history."""
        if not UNDO_FILE.exists():
            return
        try:
            with open(UNDO_FILE) as f:
                history = json.load(f)
            for entry in history[-self.MAX:]:
                self.add(entry["src"], entry["dest"])
        except Exception:
            pass


class SettingsWindow:
    """Tkinter settings window (spawned on demand, runs in main thread via after())."""

    def __init__(self, app: "LuminousApp") -> None:
        self._app = app

    def open(self) -> None:
        """Build and show the settings window."""
        cfg = load_config()

        root = tk.Tk()
        root.title("Luminous Settings")
        root.resizable(False, False)
        root.configure(bg="#1e1e2e")

        ACCENT = "#89b4fa"
        BG = "#1e1e2e"
        FG = "#cdd6f4"
        SURFACE = "#313244"
        BTN_BG = "#45475a"

        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TLabel", background=BG, foreground=FG, font=("SF Pro Display", 13))
        style.configure("TButton", background=BTN_BG, foreground=FG, font=("SF Pro Display", 12))
        style.configure("TCheckbutton", background=BG, foreground=FG, font=("SF Pro Display", 12))
        style.configure("TEntry", fieldbackground=SURFACE, foreground=FG, font=("SF Pro Display", 12))
        style.configure("TFrame", background=BG)
        style.configure("TLabelframe", background=BG, foreground=ACCENT)
        style.configure("TLabelframe.Label", background=BG, foreground=ACCENT, font=("SF Pro Display", 12, "bold"))
        style.configure("Treeview", background=SURFACE, foreground=FG,
                        fieldbackground=SURFACE, font=("SF Pro Display", 12))
        style.configure("Treeview.Heading", background=BTN_BG, foreground=ACCENT)
        style.map("TButton", background=[("active", ACCENT)])

        root.configure(bg=BG)
        pad = {"padx": 12, "pady": 6}

        # --- Header ---
        header = tk.Label(root, text="Luminous", bg=BG, fg=ACCENT,
                          font=("SF Pro Display", 22, "bold"))
        header.grid(row=0, column=0, columnspan=2, pady=(18, 2))
        sub = tk.Label(root, text="AI-powered file organizer", bg=BG, fg="#6c7086",
                       font=("SF Pro Display", 11))
        sub.grid(row=1, column=0, columnspan=2, pady=(0, 14))

        # --- Watched Folders ---
        folders_frame = ttk.LabelFrame(root, text="Watched Folders", padding=10)
        folders_frame.grid(row=2, column=0, columnspan=2, sticky="ew", **pad)

        folder_list = tk.Listbox(
            folders_frame, bg=SURFACE, fg=FG, selectbackground=ACCENT,
            selectforeground=BG, font=("SF Pro Text", 12),
            height=6, width=55, borderwidth=0, highlightthickness=0,
        )
        folder_list.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(folders_frame, orient="vertical", command=folder_list.yview)
        scrollbar.pack(side="right", fill="y")
        folder_list.configure(yscrollcommand=scrollbar.set)

        for f in cfg["watched_folders"]:
            folder_list.insert("end", f)

        btn_frame = ttk.Frame(root)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=4)

        def add_folder() -> None:
            path = filedialog.askdirectory(title="Choose a folder to watch")
            if path:
                folder_list.insert("end", path)

        def add_preset() -> None:
            win = tk.Toplevel(root)
            win.title("Add preset")
            win.configure(bg=BG)
            win.resizable(False, False)
            lbl = tk.Label(win, text="Choose a preset folder:", bg=BG, fg=FG,
                           font=("SF Pro Display", 12))
            lbl.pack(padx=16, pady=(12, 4))
            for name, path in CLOUD_STORAGE_PRESETS.items():
                p = Path(path)
                state = "normal" if p.exists() else "disabled"
                label = f"{name}  ({path})" if p.exists() else f"{name}  (not found)"
                b = ttk.Button(
                    win, text=label, state=state,
                    command=lambda p=path, w=win: [folder_list.insert("end", p), w.destroy()]
                )
                b.pack(fill="x", padx=16, pady=2)
            ttk.Button(win, text="Cancel", command=win.destroy).pack(pady=(4, 12))

        def remove_folder() -> None:
            sel = folder_list.curselection()
            if sel:
                folder_list.delete(sel[0])

        ttk.Button(btn_frame, text="+ Add Folder", command=add_folder).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="+ Preset", command=add_preset).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Remove", command=remove_folder).pack(side="left", padx=4)

        # --- Output Folder ---
        out_frame = ttk.LabelFrame(root, text="Output Base Folder", padding=10)
        out_frame.grid(row=4, column=0, columnspan=2, sticky="ew", **pad)

        output_var = tk.StringVar(value=cfg["output_base"])
        out_entry = ttk.Entry(out_frame, textvariable=output_var, width=45)
        out_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        def pick_output() -> None:
            path = filedialog.askdirectory(title="Choose output base folder")
            if path:
                output_var.set(path)

        ttk.Button(out_frame, text="Browse", command=pick_output).pack(side="left")

        # --- Options ---
        opts_frame = ttk.LabelFrame(root, text="Options", padding=10)
        opts_frame.grid(row=5, column=0, columnspan=2, sticky="ew", **pad)

        auto_rename_var = tk.BooleanVar(value=cfg.get("auto_rename", True))
        ttk.Checkbutton(
            opts_frame, text="Auto-rename generic files (screenshots, untitled docs)",
            variable=auto_rename_var,
        ).grid(row=0, column=0, sticky="w", pady=2)

        recents_var = tk.IntVar(value=cfg.get("recents_days", 3))
        recents_row = ttk.Frame(opts_frame)
        recents_row.grid(row=1, column=0, sticky="w", pady=2)
        ttk.Label(recents_row, text="Recents threshold (days):").pack(side="left")
        ttk.Entry(recents_row, textvariable=recents_var, width=5).pack(side="left", padx=6)

        # --- Save / Cancel ---
        action_frame = ttk.Frame(root)
        action_frame.grid(row=6, column=0, columnspan=2, pady=(8, 16))

        def save_and_close() -> None:
            new_cfg = load_config()
            new_cfg["watched_folders"] = list(folder_list.get(0, "end"))
            new_cfg["output_base"] = output_var.get()
            new_cfg["auto_rename"] = auto_rename_var.get()
            new_cfg["recents_days"] = recents_var.get()
            save_config(new_cfg)
            self._app.reload_config()
            root.destroy()
            rumps.notification(
                "Luminous", "Settings saved",
                "Restarting file watcher with new config.",
            )

        save_btn = tk.Button(
            action_frame, text="Save", bg=ACCENT, fg=BG,
            font=("SF Pro Display", 13, "bold"),
            relief="flat", padx=18, pady=6,
            command=save_and_close,
        )
        save_btn.pack(side="left", padx=8)

        ttk.Button(action_frame, text="Cancel", command=root.destroy).pack(side="left", padx=8)

        root.eval("tk::PlaceWindow . center")
        root.lift()
        root.attributes("-topmost", True)
        root.after(100, lambda: root.attributes("-topmost", False))
        root.mainloop()


class LuminousApp(rumps.App):
    """The Luminous menubar application."""

    def __init__(self) -> None:
        super().__init__("Luminous", title="L", quit_button=None)

        self._cfg = load_config()
        self._paused = False
        self._watcher: Optional[FolderWatcher] = None
        self._watcher_thread: Optional[threading.Thread] = None
        self._activity = ActivityLog()
        self._activity.load_from_disk()
        self._settings_window = SettingsWindow(self)

        self._build_menu()
        self._start_watcher()

    # ----- Menu construction -----

    def _build_menu(self) -> None:
        self.menu.clear()

        status_text = "Paused" if self._paused else "Watching"
        color = "" if self._paused else ""

        self.menu = [
            rumps.MenuItem(f"Status: {status_text}", callback=None),
            None,  # separator
            rumps.MenuItem("Organize Now", callback=self.organize_now),
            rumps.MenuItem(
                "Pause Watching" if not self._paused else "Resume Watching",
                callback=self.toggle_pause,
            ),
            None,
            rumps.MenuItem("Recent Activity", callback=None),
        ]

        # Inject recent activity items (non-clickable)
        recent = self._activity.recent()
        if recent:
            for line in recent[:10]:
                shortened = line if len(line) < 70 else line[:67] + "..."
                item = rumps.MenuItem(f"  {shortened}", callback=None)
                self.menu.add(item)
        else:
            self.menu.add(rumps.MenuItem("  (no activity yet)", callback=None))

        self.menu.add(None)
        self.menu.add(rumps.MenuItem("Settings...", callback=self.open_settings))
        self.menu.add(None)
        self.menu.add(rumps.MenuItem("Quit Luminous", callback=self.quit_app))

    def _refresh_menu(self) -> None:
        """Rebuild the menu to show updated activity / status."""
        self._build_menu()

    # ----- Watcher management -----

    def _start_watcher(self) -> None:
        if self._paused:
            return
        folders = [
            Path(f).expanduser().resolve()
            for f in self._cfg.get("watched_folders", [])
        ]
        existing = [f for f in folders if f.exists()]
        if not existing:
            return

        def on_new_file(path: Path) -> None:
            cfg = load_config()
            ensure_output_dirs(cfg)
            # Run organize in background thread to avoid blocking watcher
            t = threading.Thread(target=self._organize_file, args=(path, cfg), daemon=True)
            t.start()

        self._watcher = FolderWatcher(existing, on_new_file)
        self._watcher_thread = threading.Thread(target=self._watcher.start, daemon=True)
        self._watcher_thread.start()

    def _stop_watcher(self) -> None:
        if self._watcher:
            self._watcher.stop()
            self._watcher = None

    def _organize_file(self, path: Path, cfg: dict) -> None:
        try:
            summary = organize_folder(path.parent, cfg, dry_run=False, verbose=False)
            self._activity.add(str(path), str(path))  # placeholder; real dest logged in organizer
            rumps.notification(
                "Luminous",
                f"Organized {path.name}",
                f"{summary['moved']} moved, {summary['renamed']} renamed",
                sound=False,
            )
        except Exception as e:
            rumps.notification("Luminous", "Error", str(e), sound=False)
        self._refresh_menu()

    # ----- Callbacks -----

    @rumps.clicked("Organize Now")
    def organize_now(self, _) -> None:
        cfg = load_config()
        ensure_output_dirs(cfg)
        folders = [
            Path(f).expanduser().resolve()
            for f in cfg.get("watched_folders", [])
        ]

        def run() -> None:
            total_moved = 0
            for folder in folders:
                if folder.exists():
                    s = organize_folder(folder, cfg, dry_run=False, verbose=False)
                    total_moved += s.get("moved", 0)
            rumps.notification(
                "Luminous",
                "Organization complete",
                f"{total_moved} file(s) moved.",
            )
            self._refresh_menu()

        threading.Thread(target=run, daemon=True).start()

    def toggle_pause(self, _) -> None:
        self._paused = not self._paused
        if self._paused:
            self._stop_watcher()
            self.title = "L"
            rumps.notification("Luminous", "Watching paused", "File watching is now paused.")
        else:
            self._start_watcher()
            self.title = "L"
            rumps.notification("Luminous", "Watching resumed", "File watching is now active.")
        self._refresh_menu()

    def open_settings(self, _) -> None:
        # Run Tkinter window in a separate thread to avoid blocking rumps event loop
        t = threading.Thread(target=self._settings_window.open, daemon=True)
        t.start()

    def reload_config(self) -> None:
        """Called by SettingsWindow after saving."""
        self._cfg = load_config()
        self._stop_watcher()
        if not self._paused:
            self._start_watcher()
        self._refresh_menu()

    def quit_app(self, _) -> None:
        self._stop_watcher()
        rumps.quit_application()


def main() -> None:
    app = LuminousApp()
    app.run()


if __name__ == "__main__":
    main()
