"""Reusable GUI components for Luminous."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import customtkinter as ctk

ACCENT = "#4A90D9"
ACCENT_HOVER = "#3A7BC8"
COLOR_MOVED = "#4CAF50"
COLOR_RENAMED = "#4A90D9"
COLOR_SKIPPED = "#FF9800"
COLOR_ERROR = "#f44336"

CARD_BG = ("#2a2d3e", "#2a2d3e")


@dataclass
class ActivityEntry:
    src_name: str
    dest_dir: str
    dest_name: str
    action: str  # "moved", "renamed", "skipped", "error"
    timestamp: datetime


class ActivityFeed(ctk.CTkScrollableFrame):
    """Scrollable, color-coded feed of recent file operations."""

    ACTION_COLORS = {
        "moved": COLOR_MOVED,
        "renamed": COLOR_RENAMED,
        "skipped": COLOR_SKIPPED,
        "error": COLOR_ERROR,
    }

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._rows: list[ctk.CTkFrame] = []

    def prepend(self, entry: ActivityEntry) -> None:
        """Insert a new entry at the top (most recent)."""
        color = self.ACTION_COLORS.get(entry.action, "#888888")

        row = ctk.CTkFrame(self, corner_radius=8, fg_color=CARD_BG)
        row.pack(fill="x", padx=6, pady=3)

        # Colored left accent bar
        bar = ctk.CTkFrame(row, width=4, corner_radius=2, fg_color=color)
        bar.pack(side="left", fill="y", padx=(8, 0), pady=10)

        # Content area
        content = ctk.CTkFrame(row, fg_color="transparent")
        content.pack(side="left", fill="both", expand=True, padx=10, pady=8)

        dest_text = f"{entry.dest_dir}/{entry.dest_name}" if entry.dest_name != entry.src_name else entry.dest_dir
        name_label = ctk.CTkLabel(
            content,
            text=f"{entry.src_name}  \u2192  {dest_text}",
            font=ctk.CTkFont(size=13),
            anchor="w",
        )
        name_label.pack(fill="x")

        meta = ctk.CTkFrame(content, fg_color="transparent")
        meta.pack(fill="x", pady=(2, 0))

        ctk.CTkLabel(
            meta,
            text=entry.timestamp.strftime("%H:%M:%S"),
            font=ctk.CTkFont(size=11),
            text_color="#888888",
            anchor="w",
        ).pack(side="left")

        ctk.CTkLabel(
            meta,
            text=entry.action.upper(),
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=color,
            anchor="w",
        ).pack(side="left", padx=(8, 0))

        # Stack newest at top by re-packing
        row.pack_forget()
        if self._rows:
            row.pack(fill="x", padx=6, pady=3, before=self._rows[0])
        else:
            row.pack(fill="x", padx=6, pady=3)

        self._rows.insert(0, row)
        if len(self._rows) > 50:
            old = self._rows.pop()
            old.destroy()

    def clear(self) -> None:
        for row in self._rows:
            row.destroy()
        self._rows.clear()

    def load_history(self, history: list[dict]) -> None:
        """Populate feed from undo history list (oldest first, displayed newest first)."""
        self.clear()
        for entry in history[-30:]:
            src = Path(entry.get("src", ""))
            dest = Path(entry.get("dest", ""))
            try:
                ts = datetime.fromisoformat(entry.get("timestamp", ""))
            except (ValueError, TypeError):
                ts = datetime.now()
            action = "renamed" if src.name != dest.name else "moved"
            self.prepend(ActivityEntry(
                src_name=src.name,
                dest_dir=dest.parent.name,
                dest_name=dest.name,
                action=action,
                timestamp=ts,
            ))

    def show_empty(self) -> None:
        self.clear()
        ctk.CTkLabel(
            self,
            text="No activity yet.\nClick 'Organize Now' to get started.",
            font=ctk.CTkFont(size=13),
            text_color="#666",
            justify="center",
        ).pack(expand=True, pady=40)


class FolderRow(ctk.CTkFrame):
    """A single watched-folder row with a remove button."""

    def __init__(self, master, path: str, on_remove: Callable[[], None], **kwargs):
        super().__init__(master, corner_radius=6, fg_color=CARD_BG, **kwargs)
        self._path = path
        self._on_remove = on_remove
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)

        display = Path(self._path).name or self._path
        ctk.CTkLabel(
            self,
            text=display,
            font=ctk.CTkFont(size=12),
            anchor="w",
            wraplength=140,
        ).grid(row=0, column=0, padx=(8, 4), pady=6, sticky="w")

        ctk.CTkButton(
            self,
            text="x",
            width=22,
            height=22,
            corner_radius=4,
            fg_color="transparent",
            text_color="#888",
            hover_color=("#3a3a4e", "#3a3a4e"),
            command=self._on_remove,
        ).grid(row=0, column=1, padx=(0, 6), pady=6)

    @property
    def path(self) -> str:
        return self._path


class CloudStorageMenu(ctk.CTkToplevel):
    """Floating panel for picking a detected cloud storage folder."""

    def __init__(
        self,
        master,
        cloud_paths: dict,
        on_select: Callable[[str], None],
        **kwargs,
    ):
        super().__init__(master, **kwargs)
        self.title("Cloud Storage")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self._on_select = on_select

        ctk.CTkLabel(
            self,
            text="Cloud Storage Folders",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(padx=20, pady=(16, 8))

        for name, patterns in cloud_paths.items():
            resolved = _resolve_cloud(patterns)
            exists = resolved is not None
            path_str = str(resolved) if resolved else "(not installed)"

            row = ctk.CTkFrame(self, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=3)

            dot_color = COLOR_MOVED if exists else "#555"
            ctk.CTkLabel(row, text="o", text_color=dot_color, width=16,
                         font=ctk.CTkFont(size=10, weight="bold")).pack(side="left")

            btn = ctk.CTkButton(
                row,
                text=f"{name}",
                anchor="w",
                fg_color="transparent" if not exists else CARD_BG,
                text_color="#888" if not exists else ("#ddd", "#ddd"),
                hover_color=("#3a3a4e", "#3a3a4e") if exists else "transparent",
                state="normal" if exists else "disabled",
                command=(lambda p=str(resolved): self._pick(p)) if exists else None,
            )
            btn.pack(side="left", fill="x", expand=True, padx=4)

            if not exists:
                ctk.CTkLabel(row, text="not installed", font=ctk.CTkFont(size=10),
                             text_color="#555").pack(side="left")

        ctk.CTkButton(self, text="Cancel", command=self.destroy,
                      fg_color="transparent", width=80).pack(pady=(8, 16))

        self.after(10, self._center_on_parent)

    def _center_on_parent(self) -> None:
        self.update_idletasks()
        x = self.master.winfo_rootx() + self.master.winfo_width() // 2 - self.winfo_width() // 2
        y = self.master.winfo_rooty() + self.master.winfo_height() // 2 - self.winfo_height() // 2
        self.geometry(f"+{x}+{y}")

    def _pick(self, path: str) -> None:
        self._on_select(path)
        self.destroy()


def _resolve_cloud(patterns: list) -> Optional[Path]:
    """Resolve cloud storage patterns (supports glob wildcards)."""
    import glob as _glob
    for pattern in patterns:
        matches = _glob.glob(str(pattern))
        if matches:
            p = Path(matches[0])
            if p.exists():
                return p
        else:
            p = Path(str(pattern))
            if p.exists():
                return p
    return None
