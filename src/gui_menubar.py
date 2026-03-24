"""
Luminous menubar-only app (rumps-based).
Used when --menubar flag is passed to luminous-gui, or run standalone.
"""

import json
import threading
from pathlib import Path
from typing import Optional

import rumps

from .config import (
    CLOUD_STORAGE_PRESETS,
    UNDO_FILE,
    ensure_output_dirs,
    get_output_paths,
    load_config,
    save_config,
)
from .organizer import organize_folder
from .watcher import FolderWatcher


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
        if not UNDO_FILE.exists():
            return
        try:
            with open(UNDO_FILE) as f:
                history = json.load(f)
            for entry in history[-self.MAX:]:
                self.add(entry["src"], entry["dest"])
        except Exception:
            pass


class LuminousMenubarApp(rumps.App):
    """Luminous menubar application (companion to the main window)."""

    def __init__(self) -> None:
        super().__init__("Luminous", title="L", quit_button=None)
        self._cfg = load_config()
        self._paused = False
        self._watcher: Optional[FolderWatcher] = None
        self._activity = ActivityLog()
        self._activity.load_from_disk()
        self._build_menu()
        self._start_watcher()

    def _build_menu(self) -> None:
        self.menu.clear()
        status_text = "Paused" if self._paused else "Watching"
        self.menu = [
            rumps.MenuItem(f"Status: {status_text}", callback=None),
            None,
            rumps.MenuItem("Organize Now", callback=self.organize_now),
            rumps.MenuItem(
                "Pause Watching" if not self._paused else "Resume Watching",
                callback=self.toggle_pause,
            ),
            None,
            rumps.MenuItem("Recent Activity", callback=None),
        ]
        recent = self._activity.recent()
        for line in (recent[:10] if recent else ["(no activity yet)"]):
            shortened = line if len(line) < 70 else line[:67] + "..."
            self.menu.add(rumps.MenuItem(f"  {shortened}", callback=None))
        self.menu.add(None)
        self.menu.add(rumps.MenuItem("Quit", callback=self.quit_app))

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
            t = threading.Thread(target=self._organize_file, args=(path, cfg), daemon=True)
            t.start()

        self._watcher = FolderWatcher(existing, on_new_file)
        t = threading.Thread(target=self._watcher.start, daemon=True)
        t.start()

    def _stop_watcher(self) -> None:
        if self._watcher:
            self._watcher.stop()
            self._watcher = None

    def _organize_file(self, path: Path, cfg: dict) -> None:
        try:
            summary = organize_folder(path.parent, cfg, dry_run=False, verbose=False)
            self._activity.add(str(path), str(path))
            rumps.notification(
                "Luminous",
                f"Organized {path.name}",
                f"{summary['moved']} moved, {summary['renamed']} renamed",
                sound=False,
            )
        except Exception as e:
            rumps.notification("Luminous", "Error", str(e), sound=False)
        self._build_menu()

    @rumps.clicked("Organize Now")
    def organize_now(self, _) -> None:
        cfg = load_config()
        ensure_output_dirs(cfg)
        folders = [Path(f).expanduser().resolve() for f in cfg.get("watched_folders", [])]

        def run() -> None:
            total = 0
            for folder in folders:
                if folder.exists():
                    s = organize_folder(folder, cfg, dry_run=False, verbose=False)
                    total += s.get("moved", 0)
            rumps.notification("Luminous", "Done", f"{total} file(s) organized.")
            self._build_menu()

        threading.Thread(target=run, daemon=True).start()

    def toggle_pause(self, _) -> None:
        self._paused = not self._paused
        if self._paused:
            self._stop_watcher()
        else:
            self._cfg = load_config()
            self._start_watcher()
        self._build_menu()

    def quit_app(self, _) -> None:
        self._stop_watcher()
        rumps.quit_application()
