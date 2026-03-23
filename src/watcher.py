"""FSEvents-based folder watcher for real-time file organization."""

import os
import time
import threading
from pathlib import Path
from typing import Callable

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent


class LuminousEventHandler(FileSystemEventHandler):
    """Handle new file events and queue them for processing."""

    def __init__(self, callback: Callable[[Path], None], debounce_seconds: float = 2.0):
        super().__init__()
        self._callback = callback
        self._debounce = debounce_seconds
        self._pending: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return
        path_str = event.src_path
        self._schedule(path_str)

    def on_moved(self, event) -> None:
        """Also handle files moved into the watched folder."""
        if event.is_directory:
            return
        self._schedule(event.dest_path)

    def _schedule(self, path_str: str) -> None:
        """Debounce: wait until the file stops changing before processing."""
        with self._lock:
            if path_str in self._pending:
                self._pending[path_str].cancel()
            timer = threading.Timer(
                self._debounce,
                self._fire,
                args=[path_str],
            )
            self._pending[path_str] = timer
            timer.start()

    def _fire(self, path_str: str) -> None:
        with self._lock:
            self._pending.pop(path_str, None)
        path = Path(path_str)
        if path.exists() and path.is_file():
            self._callback(path)


class FolderWatcher:
    """Watch multiple folders and invoke a callback on new files."""

    def __init__(self, folders: list[Path], callback: Callable[[Path], None]):
        self._folders = folders
        self._callback = callback
        self._observer = Observer()

    def start(self) -> None:
        handler = LuminousEventHandler(self._callback)
        for folder in self._folders:
            if folder.exists():
                self._observer.schedule(handler, str(folder), recursive=False)
        self._observer.start()

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join()

    def join(self) -> None:
        try:
            while self._observer.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
