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


def resolve_cloud_path(patterns: list) -> "Path | None":
    """Resolve a list of path patterns (with globs) to the first existing match."""
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


# Cloud storage paths indexed by provider name.
# Each value is a list of candidate paths/glob patterns (first match wins).
CLOUD_STORAGE_PATHS: dict[str, list] = {
    "iCloud Drive": [
        Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs",
    ],
    "Google Drive": [
        Path.home() / "Library" / "CloudStorage" / "GoogleDrive-*" / "My Drive",
        Path.home() / "Google Drive",
        Path.home() / "Google Drive" / "My Drive",
    ],
    "Dropbox": [
        Path.home() / "Dropbox",
        Path.home() / "Library" / "CloudStorage" / "Dropbox",
    ],
    "OneDrive": [
        Path.home() / "OneDrive",
        Path.home() / "Library" / "CloudStorage" / "OneDrive-*",
    ],
    "Box": [
        Path.home() / "Box",
        Path.home() / "Library" / "CloudStorage" / "Box-*",
    ],
}

# Legacy preset dict (kept for CLI compatibility)
CLOUD_STORAGE_PRESETS = {
    "Desktop": str(Path.home() / "Desktop"),
    "Downloads": str(Path.home() / "Downloads"),
    "Documents": str(Path.home() / "Documents"),
    **{
        name: str(resolve_cloud_path(patterns) or patterns[0])
        for name, patterns in CLOUD_STORAGE_PATHS.items()
    },
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
