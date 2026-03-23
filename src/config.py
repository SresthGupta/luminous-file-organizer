"""Configuration management for Luminous."""

import os
import json
import glob as _glob
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".config" / "luminous"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FILE = CONFIG_DIR / "luminous.log"
UNDO_FILE = CONFIG_DIR / "undo_history.json"
PID_FILE = CONFIG_DIR / "luminous.pid"


def _find_google_drive() -> list[str]:
    """Auto-detect Google Drive paths on macOS."""
    patterns = [
        str(Path.home() / "Library" / "CloudStorage" / "GoogleDrive-*" / "My Drive"),
        str(Path.home() / "Google Drive"),
        str(Path.home() / "Google Drive" / "My Drive"),
    ]
    found = []
    for pat in patterns:
        found.extend(_glob.glob(pat))
    return found


CLOUD_STORAGE_PRESETS = {
    "Desktop": str(Path.home() / "Desktop"),
    "Downloads": str(Path.home() / "Downloads"),
    "Documents": str(Path.home() / "Documents"),
    "iCloud Drive": str(Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"),
    "Dropbox": str(Path.home() / "Dropbox"),
    "OneDrive": str(Path.home() / "OneDrive"),
    "Google Drive": str(Path.home() / "Google Drive"),
}


DEFAULT_CONFIG = {
    "watched_folders": [
        str(Path.home() / "Desktop"),
        str(Path.home() / "Downloads"),
        str(Path.home() / "Documents"),
    ],
    "output_base": str(Path.home() / "Documents" / "Luminous"),
    "recents_days": 3,
    "auto_rename": True,
    "rename_confidence_threshold": 0.80,
    "auto_cleanup": False,
    "cleanup_extensions": [".dmg", ".pkg", ".zip"],
    "cleanup_age_days": 30,
    "manual_folders": [],
    "anthropic_model": "claude-haiku-4-5-20251001",
    "max_content_chars": 2000,
    "batch_size": 5,
    "ignore_patterns": [
        ".*",
        "~*",
        "*.tmp",
        "*.part",
        "desktop.ini",
        ".DS_Store",
        "Thumbs.db",
    ],
}


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict[str, Any]:
    ensure_config_dir()
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    with open(CONFIG_FILE) as f:
        data = json.load(f)
    # Merge with defaults so new keys are always present
    merged = DEFAULT_CONFIG.copy()
    merged.update(data)
    return merged


def save_config(cfg: dict[str, Any]) -> None:
    ensure_config_dir()
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def get_output_paths(cfg: dict[str, Any]) -> dict[str, Path]:
    base = Path(cfg["output_base"])
    return {
        "recents": base / "Recents",
        "library": base / "Library",
        "manual": base / "Manual",
    }


def ensure_output_dirs(cfg: dict[str, Any]) -> None:
    for path in get_output_paths(cfg).values():
        path.mkdir(parents=True, exist_ok=True)
