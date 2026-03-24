"""
Luminous - CustomTkinter desktop app.

Launch with: luminous-gui
Add --menubar to also run the rumps menubar icon.
"""

import json
import queue
import sys
import threading
from datetime import datetime
from pathlib import Path
from tkinter import filedialog
from typing import Optional

import customtkinter as ctk
import yaml

from .config import (
    CLOUD_STORAGE_PATHS,
    LUMINOUS_SUBFOLDERS,
    UNDO_FILE,
    ensure_config_dir,
    get_output_paths,
    load_config,
    save_config,
)
from .gui_components import (
    ACCENT,
    ACCENT_HOVER,
    CARD_BG,
    COLOR_MOVED,
    ActivityEntry,
    ActivityFeed,
    CloudStorageMenu,
    FolderRow,
)
from .organizer import organize_folder, undo_last
from .watcher import FolderWatcher

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

RULES_FILE = Path.home() / ".config" / "luminous" / "rules.yaml"
CACHE_FILE = Path.home() / ".config" / "luminous" / "cache.json"

FONT_TITLE = ("SF Pro Display", 20, "bold")
FONT_BODY = ("SF Pro Display", 14)
FONT_CAPTION = ("SF Pro Display", 12)


# ---------------------------------------------------------------------------
# Settings modal
# ---------------------------------------------------------------------------

class SettingsModal(ctk.CTkToplevel):
    """Modal settings window."""

    def __init__(self, parent: "LuminousWindow", **kwargs):
        super().__init__(parent, **kwargs)
        self.title("Settings")
        self.geometry("460x340")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self._parent = parent
        self._cfg = load_config()
        self._build()
        self.after(10, self._center)

    def _center(self) -> None:
        self.update_idletasks()
        px = self._parent.winfo_rootx()
        py = self._parent.winfo_rooty()
        pw = self._parent.winfo_width()
        ph = self._parent.winfo_height()
        x = px + pw // 2 - self.winfo_width() // 2
        y = py + ph // 2 - self.winfo_height() // 2
        self.geometry(f"+{x}+{y}")

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Settings", font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=ACCENT).grid(row=0, column=0, padx=24, pady=(20, 4))

        # Auto-rename toggle
        ctk.CTkLabel(self, text="Auto-rename generic files", font=ctk.CTkFont(size=12),
                     text_color="#888", anchor="w").grid(row=1, column=0, padx=24, sticky="w")

        self._rename_switch = ctk.CTkSwitch(self, text="", onvalue=True, offvalue=False)
        self._rename_switch.grid(row=2, column=0, padx=24, pady=(2, 12), sticky="w")
        if self._cfg.get("auto_rename", True):
            self._rename_switch.select()

        # Recents threshold
        ctk.CTkLabel(self, text="Recents threshold (days)", font=ctk.CTkFont(size=12),
                     text_color="#888", anchor="w").grid(row=3, column=0, padx=24, sticky="w")

        self._recents_var = ctk.StringVar(value=str(self._cfg.get("recents_days", 3)))
        ctk.CTkEntry(self, textvariable=self._recents_var, width=60,
                     font=ctk.CTkFont(size=12)).grid(row=4, column=0, padx=24, pady=(2, 12), sticky="w")

        # Cache management
        cache_row = ctk.CTkFrame(self, fg_color="transparent")
        cache_row.grid(row=5, column=0, padx=24, pady=(0, 12), sticky="ew")

        cache_size = self._get_cache_size()
        ctk.CTkLabel(cache_row, text=f"Cache: {cache_size}",
                     font=ctk.CTkFont(size=12), text_color="#888").pack(side="left")
        ctk.CTkButton(cache_row, text="Clear Cache", width=90, height=26,
                      fg_color="transparent", border_width=1,
                      command=self._clear_cache).pack(side="left", padx=(12, 0))

        # Batch size
        ctk.CTkLabel(self, text="Batch size", font=ctk.CTkFont(size=12),
                     text_color="#888", anchor="w").grid(row=6, column=0, padx=24, sticky="w")
        self._batch_var = ctk.StringVar(value=str(self._cfg.get("batch_size", 5)))
        ctk.CTkEntry(self, textvariable=self._batch_var, width=60,
                     font=ctk.CTkFont(size=12)).grid(row=7, column=0, padx=24, pady=(2, 16), sticky="w")

        # Buttons
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=8, column=0, padx=24, pady=(0, 20))

        ctk.CTkButton(btn_row, text="Save", fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      width=100, command=self._save).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text="Cancel", fg_color="transparent", width=80,
                      command=self.destroy).pack(side="left")

    def _get_cache_size(self) -> str:
        if CACHE_FILE.exists():
            size_kb = CACHE_FILE.stat().st_size / 1024
            try:
                data = json.loads(CACHE_FILE.read_text())
                return f"{len(data)} entries ({size_kb:.1f} KB)"
            except Exception:
                return f"{size_kb:.1f} KB"
        return "empty"

    def _clear_cache(self) -> None:
        if CACHE_FILE.exists():
            CACHE_FILE.unlink()
        self.destroy()

    def _save(self) -> None:
        self._cfg["auto_rename"] = bool(self._rename_switch.get())
        try:
            self._cfg["recents_days"] = int(self._recents_var.get())
        except ValueError:
            pass
        try:
            self._cfg["batch_size"] = int(self._batch_var.get())
        except ValueError:
            pass
        save_config(self._cfg)
        self._parent.reload_config()
        self.destroy()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class LuminousWindow(ctk.CTk):
    """The Luminous desktop app main window."""

    def __init__(self):
        super().__init__()
        self.title("Luminous")
        self.geometry("900x620")
        self.minsize(720, 500)

        self._cfg = load_config()
        self._event_queue: queue.Queue = queue.Queue()
        self._watcher: Optional[FolderWatcher] = None
        self._watching = False
        self._folder_rows: list[FolderRow] = []
        self._settings_modal: Optional[SettingsModal] = None
        self._cloud_menu: Optional[CloudStorageMenu] = None

        self._build_ui()
        self._load_activity_history()
        self._refresh_stats()
        self._start_watcher()
        self._poll_queue()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main_area()
        self._build_statusbar()

    def _build_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(self, width=220, corner_radius=0,
                               fg_color=("#16213e", "#16213e"))
        sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(4, weight=1)

        # Logo
        ctk.CTkLabel(sidebar, text="Luminous",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=ACCENT).grid(row=0, column=0, padx=20, pady=(22, 2))
        ctk.CTkLabel(sidebar, text="AI file organizer",
                     font=ctk.CTkFont(size=11),
                     text_color="#555").grid(row=1, column=0, padx=20, pady=(0, 18))

        # Watched folders section
        ctk.CTkLabel(sidebar, text="WATCHED FOLDERS",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color="#555", anchor="w").grid(row=2, column=0, padx=16, sticky="w")

        # Scrollable folder list
        self._folder_scroll = ctk.CTkScrollableFrame(sidebar, height=160,
                                                      fg_color="transparent")
        self._folder_scroll.grid(row=3, column=0, padx=8, pady=(4, 6), sticky="ew")
        self._folder_scroll.grid_columnconfigure(0, weight=1)
        self._render_folder_list()

        # Buttons frame
        btn_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        btn_frame.grid(row=4, column=0, padx=8, pady=0, sticky="ew")
        btn_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(btn_frame, text="+ Add Folder",
                      height=32, corner_radius=8,
                      command=self._add_folder).grid(row=0, column=0, pady=(0, 4), sticky="ew")

        ctk.CTkButton(btn_frame, text="Cloud Storage",
                      height=32, corner_radius=8,
                      fg_color="transparent",
                      border_width=1,
                      text_color=(ACCENT, ACCENT),
                      hover_color=("#1e2a44", "#1e2a44"),
                      command=self._show_cloud_menu).grid(row=1, column=0, pady=(0, 4), sticky="ew")

        # Bottom buttons
        bottom = ctk.CTkFrame(sidebar, fg_color="transparent")
        bottom.grid(row=5, column=0, padx=8, pady=(0, 16), sticky="sew")
        sidebar.grid_rowconfigure(5, weight=0)
        bottom.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(bottom, text="Settings",
                      height=32, corner_radius=8,
                      fg_color="transparent",
                      text_color=("#ccc", "#ccc"),
                      hover_color=("#1e2a44", "#1e2a44"),
                      command=self._open_settings).grid(row=0, column=0, pady=(0, 6), sticky="ew")

        self._organize_btn = ctk.CTkButton(
            bottom, text="Organize Now",
            height=42, corner_radius=10,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._organize_now,
        )
        self._organize_btn.grid(row=1, column=0, sticky="ew")

    def _build_main_area(self) -> None:
        main = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(0, weight=1)

        self._tabs = ctk.CTkTabview(main, anchor="nw")
        self._tabs.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        for name in ("Activity", "Files", "Rules", "Stats"):
            self._tabs.add(name)
            self._tabs.tab(name).grid_columnconfigure(0, weight=1)
            self._tabs.tab(name).grid_rowconfigure(0, weight=1)

        self._build_activity_tab()
        self._build_files_tab()
        self._build_rules_tab()
        self._build_stats_tab()

    def _build_activity_tab(self) -> None:
        tab = self._tabs.tab("Activity")

        # Undo button row
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))

        ctk.CTkLabel(top, text="Recent Activity",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     anchor="w").pack(side="left", fill="x", expand=True)

        ctk.CTkButton(top, text="Undo Last",
                      width=90, height=28,
                      corner_radius=6,
                      fg_color="transparent",
                      border_width=1,
                      command=self._undo_last).pack(side="right")

        self._activity_feed = ActivityFeed(tab)
        self._activity_feed.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        tab.grid_rowconfigure(1, weight=1)

    def _build_files_tab(self) -> None:
        tab = self._tabs.tab("Files")

        ctk.CTkLabel(tab, text="Organized Folders",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     anchor="w").grid(row=0, column=0, padx=16, pady=(12, 4), sticky="w")

        self._files_scroll = ctk.CTkScrollableFrame(tab)
        self._files_scroll.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        tab.grid_rowconfigure(1, weight=1)

        self._refresh_files_tab()

    def _build_rules_tab(self) -> None:
        tab = self._tabs.tab("Rules")
        tab.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(tab, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))

        ctk.CTkLabel(header, text="Custom Rules",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     anchor="w").pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(header, text="keyword -> category",
                     font=ctk.CTkFont(size=11),
                     text_color="#666").pack(side="right")

        self._rules_scroll = ctk.CTkScrollableFrame(tab)
        self._rules_scroll.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 4))

        # Add rule row
        add_row = ctk.CTkFrame(tab, fg_color="transparent")
        add_row.grid(row=2, column=0, padx=8, pady=(4, 12), sticky="ew")

        self._rule_kw = ctk.CTkEntry(add_row, placeholder_text="keyword",
                                      width=140, height=32)
        self._rule_kw.pack(side="left", padx=(0, 6))

        self._rule_cat = ctk.CTkEntry(add_row, placeholder_text="Category/Subcategory",
                                       width=200, height=32)
        self._rule_cat.pack(side="left", padx=(0, 6))

        ctk.CTkButton(add_row, text="+ Add Rule", width=90, height=32,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self._add_rule).pack(side="left")

        self._refresh_rules_tab()

    def _build_stats_tab(self) -> None:
        tab = self._tabs.tab("Stats")
        tab.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(tab, text="Statistics",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     anchor="w").grid(row=0, column=0, padx=16, pady=(12, 4), sticky="w")

        self._stats_scroll = ctk.CTkScrollableFrame(tab)
        self._stats_scroll.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

    def _build_statusbar(self) -> None:
        bar = ctk.CTkFrame(self, height=36, corner_radius=0,
                           fg_color=("#111827", "#111827"))
        bar.grid(row=1, column=1, sticky="ew")
        bar.grid_columnconfigure(1, weight=1)
        bar.grid_propagate(False)

        self._status_label = ctk.CTkLabel(
            bar, text="Watching 0 folders",
            font=ctk.CTkFont(size=12),
            text_color="#888",
        )
        self._status_label.grid(row=0, column=0, padx=16, sticky="w")

        self._last_label = ctk.CTkLabel(
            bar, text="",
            font=ctk.CTkFont(size=12),
            text_color="#666",
        )
        self._last_label.grid(row=0, column=1, padx=8, sticky="e")

        self._watch_toggle = ctk.CTkButton(
            bar, text="Stop Watching",
            width=110, height=26,
            corner_radius=6,
            fg_color="transparent",
            border_width=1,
            text_color=("#ccc", "#ccc"),
            command=self._toggle_watching,
        )
        self._watch_toggle.grid(row=0, column=2, padx=16, sticky="e")

    # ------------------------------------------------------------------
    # Folder list rendering
    # ------------------------------------------------------------------

    def _render_folder_list(self) -> None:
        for row in self._folder_rows:
            row.destroy()
        self._folder_rows.clear()

        for folder_path in self._cfg.get("watched_folders", []):
            self._add_folder_row(folder_path)

        if not self._folder_rows:
            ctk.CTkLabel(self._folder_scroll, text="No folders watched",
                         font=ctk.CTkFont(size=11),
                         text_color="#555").pack(pady=8)

    def _add_folder_row(self, path: str) -> None:
        row = FolderRow(
            self._folder_scroll,
            path=path,
            on_remove=lambda p=path: self._remove_folder(p),
        )
        row.pack(fill="x", pady=2)
        self._folder_rows.append(row)

    # ------------------------------------------------------------------
    # Folder management
    # ------------------------------------------------------------------

    def _add_folder(self) -> None:
        path = filedialog.askdirectory(title="Choose a folder to watch")
        if path and path not in self._cfg.get("watched_folders", []):
            self._cfg.setdefault("watched_folders", []).append(path)
            save_config(self._cfg)
            self._render_folder_list()
            self._restart_watcher()
            self._update_status()

    def _remove_folder(self, path: str) -> None:
        folders = self._cfg.get("watched_folders", [])
        if path in folders:
            folders.remove(path)
            save_config(self._cfg)
            self._render_folder_list()
            self._restart_watcher()
            self._update_status()

    def _show_cloud_menu(self) -> None:
        if self._cloud_menu and self._cloud_menu.winfo_exists():
            self._cloud_menu.focus()
            return
        self._cloud_menu = CloudStorageMenu(
            self,
            cloud_paths=CLOUD_STORAGE_PATHS,
            on_select=self._add_cloud_folder,
        )

    def _add_cloud_folder(self, path: str) -> None:
        if path and path not in self._cfg.get("watched_folders", []):
            self._cfg.setdefault("watched_folders", []).append(path)
            save_config(self._cfg)
            self._render_folder_list()
            self._restart_watcher()
            self._update_status()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _open_settings(self) -> None:
        if self._settings_modal and self._settings_modal.winfo_exists():
            self._settings_modal.focus()
            return
        self._settings_modal = SettingsModal(self)

    def reload_config(self) -> None:
        self._cfg = load_config()
        self._render_folder_list()
        self._restart_watcher()
        self._update_status()

    # ------------------------------------------------------------------
    # Organize
    # ------------------------------------------------------------------

    def _organize_now(self) -> None:
        self._organize_btn.configure(state="disabled", text="Organizing...")
        folders = [
            Path(f).expanduser().resolve()
            for f in self._cfg.get("watched_folders", [])
            if Path(f).expanduser().resolve().exists()
        ]
        if not folders:
            self._organize_btn.configure(state="normal", text="Organize Now")
            return

        def run() -> None:
            cfg = load_config()
            total = 0
            for folder in folders:
                try:
                    s = organize_folder(folder, cfg, dry_run=False, verbose=False)
                    total += s.get("moved", 0)
                except Exception as e:
                    self._event_queue.put(("error", str(e)))
            self._event_queue.put(("organize_done", total))

        threading.Thread(target=run, daemon=True).start()

    def _undo_last(self) -> None:
        def run() -> None:
            try:
                n = undo_last(1)
                self._event_queue.put(("undo_done", n))
            except Exception as e:
                self._event_queue.put(("error", str(e)))

        threading.Thread(target=run, daemon=True).start()

    # ------------------------------------------------------------------
    # Watcher
    # ------------------------------------------------------------------

    def _start_watcher(self) -> None:
        folders = [
            Path(f).expanduser().resolve()
            for f in self._cfg.get("watched_folders", [])
        ]
        existing = [f for f in folders if f.exists()]
        if not existing:
            return

        def on_file(path: Path) -> None:
            cfg = load_config()
            try:
                organize_folder(path.parent, cfg, dry_run=False, verbose=False)
                self._event_queue.put(("file_organized", str(path)))
            except Exception as e:
                self._event_queue.put(("error", str(e)))

        self._watcher = FolderWatcher(existing, on_file)
        t = threading.Thread(target=self._watcher.start, daemon=True)
        t.start()
        self._watching = True
        self._update_status()

    def _stop_watcher(self) -> None:
        if self._watcher:
            self._watcher.stop()
            self._watcher = None
        self._watching = False
        self._update_status()

    def _restart_watcher(self) -> None:
        self._stop_watcher()
        self._start_watcher()

    def _toggle_watching(self) -> None:
        if self._watching:
            self._stop_watcher()
        else:
            self._start_watcher()
        self._update_status()

    # ------------------------------------------------------------------
    # Queue polling (background -> main thread bridge)
    # ------------------------------------------------------------------

    def _poll_queue(self) -> None:
        try:
            while True:
                msg = self._event_queue.get_nowait()
                self._handle_event(msg)
        except queue.Empty:
            pass
        self.after(400, self._poll_queue)

    def _handle_event(self, msg: tuple) -> None:
        kind = msg[0]

        if kind == "organize_done":
            total = msg[1]
            self._organize_btn.configure(state="normal", text="Organize Now")
            self._last_label.configure(
                text=f"Organized {total} file(s) just now"
            )
            self._load_activity_history()
            self._refresh_stats()
            self._refresh_files_tab()

        elif kind == "file_organized":
            self._load_activity_history()
            self._last_label.configure(text=f"Organized {Path(msg[1]).name}")
            self._refresh_stats()

        elif kind == "undo_done":
            n = msg[1]
            self._last_label.configure(text=f"Undid {n} move(s)")
            self._load_activity_history()
            self._refresh_stats()

        elif kind == "error":
            self._organize_btn.configure(state="normal", text="Organize Now")
            self._last_label.configure(text=f"Error: {msg[1][:60]}")

    # ------------------------------------------------------------------
    # Status bar
    # ------------------------------------------------------------------

    def _update_status(self) -> None:
        folders = self._cfg.get("watched_folders", [])
        existing = [f for f in folders if Path(f).exists()]
        count = len(existing)

        if self._watching:
            self._status_label.configure(
                text=f"Watching {count} folder{'s' if count != 1 else ''}",
                text_color=COLOR_MOVED,
            )
            self._watch_toggle.configure(text="Stop Watching")
        else:
            self._status_label.configure(text="Paused", text_color="#888")
            self._watch_toggle.configure(text="Start Watching")

    # ------------------------------------------------------------------
    # Activity feed
    # ------------------------------------------------------------------

    def _load_activity_history(self) -> None:
        if not UNDO_FILE.exists():
            self._activity_feed.show_empty()
            return
        try:
            with open(UNDO_FILE) as f:
                history = json.load(f)
        except Exception:
            self._activity_feed.show_empty()
            return

        if history:
            self._activity_feed.load_history(history)
        else:
            self._activity_feed.show_empty()

    # ------------------------------------------------------------------
    # Files tab
    # ------------------------------------------------------------------

    def _refresh_files_tab(self) -> None:
        for w in self._files_scroll.winfo_children():
            w.destroy()

        watched = [
            Path(f).expanduser().resolve()
            for f in self._cfg.get("watched_folders", [])
        ]

        for folder in watched:
            if not folder.exists():
                continue
            output_paths = get_output_paths(folder)
            folder_label = ctk.CTkLabel(
                self._files_scroll,
                text=str(folder),
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#aaa",
                anchor="w",
            )
            folder_label.pack(fill="x", padx=10, pady=(10, 2))
            for tier_name in LUMINOUS_SUBFOLDERS:
                tier_path = output_paths.get(
                    "recents" if tier_name == "Recents"
                    else "library" if tier_name == "AI Library"
                    else "manual"
                )
                if tier_path is not None:
                    self._render_tier(tier_name, tier_path)

    def _render_tier(self, tier_name: str, tier_path: Path) -> None:
        if not tier_path.exists():
            return

        tier_frame = ctk.CTkFrame(self._files_scroll, corner_radius=8, fg_color=CARD_BG)
        tier_frame.pack(fill="x", padx=6, pady=4)

        # Count total files
        try:
            all_files = list(tier_path.rglob("*"))
            total = sum(1 for f in all_files if f.is_file())
        except PermissionError:
            total = 0

        header = ctk.CTkFrame(tier_frame, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(10, 4))

        ctk.CTkLabel(header, text=tier_name,
                     font=ctk.CTkFont(size=14, weight="bold"),
                     anchor="w").pack(side="left")
        ctk.CTkLabel(header, text=f"{total} files",
                     font=ctk.CTkFont(size=12),
                     text_color="#666").pack(side="right")

        # List immediate subdirectories with file counts
        try:
            subdirs = sorted(
                [d for d in tier_path.iterdir() if d.is_dir()],
                key=lambda d: d.name,
            )
        except PermissionError:
            subdirs = []

        for sub in subdirs[:20]:
            try:
                count = sum(1 for f in sub.rglob("*") if f.is_file())
            except PermissionError:
                count = 0
            if count == 0:
                continue

            row = ctk.CTkFrame(tier_frame, fg_color="transparent")
            row.pack(fill="x", padx=20, pady=1)

            ctk.CTkLabel(row, text=sub.name,
                         font=ctk.CTkFont(size=12),
                         text_color="#bbb",
                         anchor="w").pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(row, text=str(count),
                         font=ctk.CTkFont(size=12),
                         text_color="#666").pack(side="right")

        if not subdirs:
            ctk.CTkLabel(tier_frame, text="(empty)",
                         font=ctk.CTkFont(size=11),
                         text_color="#555").pack(padx=20, pady=(0, 8), anchor="w")
        else:
            ctk.CTkFrame(tier_frame, height=1, fg_color="transparent").pack(pady=(4, 0))

    # ------------------------------------------------------------------
    # Rules tab
    # ------------------------------------------------------------------

    def _load_rules(self) -> dict:
        if not RULES_FILE.exists():
            return {}
        try:
            data = yaml.safe_load(RULES_FILE.read_text())
            return data.get("custom_categories", {}) if data else {}
        except Exception:
            return {}

    def _save_rules(self, rules: dict) -> None:
        ensure_config_dir()
        RULES_FILE.write_text(yaml.dump({"custom_categories": rules}, default_flow_style=False))

    def _refresh_rules_tab(self) -> None:
        for w in self._rules_scroll.winfo_children():
            w.destroy()

        rules = self._load_rules()
        if not rules:
            ctk.CTkLabel(self._rules_scroll, text="No custom rules yet.",
                         font=ctk.CTkFont(size=12),
                         text_color="#666").pack(pady=20)
            return

        for keyword, category in sorted(rules.items()):
            row = ctk.CTkFrame(self._rules_scroll, corner_radius=6, fg_color=CARD_BG)
            row.pack(fill="x", padx=6, pady=3)
            row.grid_columnconfigure(1, weight=1)

            ctk.CTkLabel(row, text=keyword,
                         font=ctk.CTkFont(size=13, weight="bold"),
                         anchor="w",
                         text_color=ACCENT).grid(row=0, column=0, padx=(12, 8), pady=8)

            ctk.CTkLabel(row, text=f"-> {category}",
                         font=ctk.CTkFont(size=13),
                         anchor="w").grid(row=0, column=1, padx=0, pady=8, sticky="w")

            ctk.CTkButton(row, text="x", width=28, height=28,
                          corner_radius=4,
                          fg_color="transparent",
                          text_color="#666",
                          hover_color=("#3a3a4e", "#3a3a4e"),
                          command=lambda kw=keyword: self._delete_rule(kw),
                          ).grid(row=0, column=2, padx=8, pady=8)

    def _add_rule(self) -> None:
        keyword = self._rule_kw.get().strip()
        category = self._rule_cat.get().strip()
        if not keyword or not category:
            return
        rules = self._load_rules()
        rules[keyword] = category
        self._save_rules(rules)
        self._rule_kw.delete(0, "end")
        self._rule_cat.delete(0, "end")
        self._refresh_rules_tab()

    def _delete_rule(self, keyword: str) -> None:
        rules = self._load_rules()
        rules.pop(keyword, None)
        self._save_rules(rules)
        self._refresh_rules_tab()

    # ------------------------------------------------------------------
    # Stats tab
    # ------------------------------------------------------------------

    def _refresh_stats(self) -> None:
        for w in self._stats_scroll.winfo_children():
            w.destroy()

        history: list[dict] = []
        if UNDO_FILE.exists():
            try:
                with open(UNDO_FILE) as f:
                    history = json.load(f)
            except Exception:
                pass

        # Total
        stat_card = ctk.CTkFrame(self._stats_scroll, corner_radius=8, fg_color=CARD_BG)
        stat_card.pack(fill="x", padx=6, pady=4)

        ctk.CTkLabel(stat_card, text=str(len(history)),
                     font=ctk.CTkFont(size=32, weight="bold"),
                     text_color=ACCENT).pack(padx=20, pady=(12, 2))
        ctk.CTkLabel(stat_card, text="Total Files Organized",
                     font=ctk.CTkFont(size=13),
                     text_color="#888").pack(padx=20, pady=(0, 12))

        if not history:
            return

        # Last organize time
        try:
            last_ts = datetime.fromisoformat(history[-1].get("timestamp", ""))
            last_str = last_ts.strftime("%b %d %Y at %H:%M")
        except Exception:
            last_str = "unknown"

        info_card = ctk.CTkFrame(self._stats_scroll, corner_radius=8, fg_color=CARD_BG)
        info_card.pack(fill="x", padx=6, pady=4)
        info_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(info_card, text="Last organized",
                     font=ctk.CTkFont(size=12), text_color="#888",
                     anchor="w").grid(row=0, column=0, padx=16, pady=10, sticky="w")
        ctk.CTkLabel(info_card, text=last_str,
                     font=ctk.CTkFont(size=12),
                     anchor="e").grid(row=0, column=1, padx=16, pady=10, sticky="e")

        # Cache stats
        cache_entries = 0
        if CACHE_FILE.exists():
            try:
                cache_entries = len(json.loads(CACHE_FILE.read_text()))
            except Exception:
                pass

        ctk.CTkLabel(info_card, text="Cache hits saved",
                     font=ctk.CTkFont(size=12), text_color="#888",
                     anchor="w").grid(row=1, column=0, padx=16, pady=(0, 10), sticky="w")
        ctk.CTkLabel(info_card, text=str(cache_entries),
                     font=ctk.CTkFont(size=12),
                     anchor="e").grid(row=1, column=1, padx=16, pady=(0, 10), sticky="e")

        # Top categories
        dest_counts: dict[str, int] = {}
        for entry in history:
            dest_dir = Path(entry.get("dest", "")).parent.name
            if dest_dir:
                dest_counts[dest_dir] = dest_counts.get(dest_dir, 0) + 1

        if not dest_counts:
            return

        ctk.CTkLabel(self._stats_scroll, text="FILES BY CATEGORY",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color="#555",
                     anchor="w").pack(padx=14, pady=(8, 4), fill="x")

        top_cats = sorted(dest_counts.items(), key=lambda x: -x[1])[:10]
        max_count = top_cats[0][1] if top_cats else 1

        for cat, count in top_cats:
            row = ctk.CTkFrame(self._stats_scroll, corner_radius=6, fg_color=CARD_BG)
            row.pack(fill="x", padx=6, pady=2)
            row.grid_columnconfigure(1, weight=1)

            ctk.CTkLabel(row, text=cat,
                         font=ctk.CTkFont(size=12),
                         anchor="w").grid(row=0, column=0, padx=(12, 8), pady=8, sticky="w")

            # Progress bar
            bar_frame = ctk.CTkFrame(row, fg_color="transparent")
            bar_frame.grid(row=0, column=1, padx=(0, 8), pady=8, sticky="ew")

            pct = count / max_count
            ctk.CTkProgressBar(bar_frame, height=8,
                               progress_color=ACCENT).pack(side="left", fill="x",
                                                           expand=True, padx=(0, 8))
            bar_frame.winfo_children()[0].set(pct)

            ctk.CTkLabel(row, text=str(count),
                         font=ctk.CTkFont(size=12),
                         text_color="#888",
                         width=30).grid(row=0, column=2, padx=(0, 12), pady=8)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Luminous GUI")
    parser.add_argument("--menubar", action="store_true",
                        help="Also run the rumps menubar icon (macOS only)")
    args, _ = parser.parse_known_args()

    if args.menubar:
        try:
            import rumps

            # Import the old menubar app class from a separate module reference
            # so both can coexist. Run menubar in background thread.
            def _run_menubar() -> None:
                from .gui_menubar import LuminousMenubarApp
                LuminousMenubarApp().run()

            t = threading.Thread(target=_run_menubar, daemon=True)
            t.start()
        except ImportError:
            pass

    app = LuminousWindow()
    app.mainloop()


if __name__ == "__main__":
    main()
