"""Core organization logic: tie together categorization, renaming, and file movement."""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich import box

from .categorizer import categorize_file, categorize_batch, CategorizationResult
from .renamer import build_new_path, safe_move
from .config import (
    load_config,
    get_output_paths,
    ensure_output_dirs,
    LUMINOUS_SUBFOLDERS,
    UNDO_FILE,
    ensure_config_dir,
)
from .utils import (
    file_age_days,
    should_ignore,
    compute_file_hash,
    ARCHIVE_EXTENSIONS,
    INSTALLER_EXTENSIONS,
)

console = Console()


def _load_undo_history() -> list[dict]:
    ensure_config_dir()
    if UNDO_FILE.exists():
        with open(UNDO_FILE) as f:
            return json.load(f)
    return []


def _save_undo_history(history: list[dict]) -> None:
    ensure_config_dir()
    with open(UNDO_FILE, "w") as f:
        json.dump(history, f, indent=2)


def _record_move(src: str, dest: str, history: list[dict]) -> None:
    history.append({
        "timestamp": datetime.now().isoformat(),
        "src": src,
        "dest": dest,
    })


def organize_folder(
    folder: Path,
    cfg: dict,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict:
    """
    Organize all files in `folder` using the Luminous three-tier system.
    Returns a summary dict with counts.
    """
    ensure_output_dirs(folder)
    output_paths = get_output_paths(folder)
    ignore_patterns = cfg.get("ignore_patterns", [])
    recents_days = cfg.get("recents_days", 3)
    rename_threshold = cfg.get("rename_confidence_threshold", 0.8)
    auto_rename = cfg.get("auto_rename", True)
    manual_folders = [str(Path(m).resolve()) for m in cfg.get("manual_folders", [])]

    files = [
        p for p in folder.iterdir()
        if p.is_file() and not should_ignore(p, ignore_patterns)
        and p.parent.name not in LUMINOUS_SUBFOLDERS
    ]

    # Promote aged-out files from Recents/ to AI Library/
    recents_dir = output_paths["recents"]
    if recents_dir.exists():
        for p in list(recents_dir.iterdir()):
            if p.is_file() and not should_ignore(p, ignore_patterns):
                if file_age_days(p) > recents_days:
                    files.append(p)

    summary = {"total": len(files), "moved": 0, "renamed": 0, "skipped": 0, "errors": 0}
    history = _load_undo_history()

    if not files:
        console.print(f"[dim]No files to organize in {folder}[/dim]")
        return summary

    table = Table(
        "File", "Action", "Destination", "Category",
        box=box.SIMPLE_HEAVY, show_header=True,
        header_style="bold cyan", expand=True,
    )

    for i, path in enumerate(files, 1):
        try:
            _process_file(
                path=path,
                output_paths=output_paths,
                cfg=cfg,
                dry_run=dry_run,
                recents_days=recents_days,
                rename_threshold=rename_threshold,
                auto_rename=auto_rename,
                manual_folders=manual_folders,
                summary=summary,
                history=history,
                table=table,
            )
        except Exception as e:
            summary["errors"] += 1
            if verbose:
                console.print(f"[red]Error processing {path.name}: {e}[/red]")

    if not dry_run:
        _save_undo_history(history[-500:])  # Keep last 500 moves

    console.print(table)
    return summary


def _process_file(
    path: Path,
    output_paths: dict,
    cfg: dict,
    dry_run: bool,
    recents_days: float,
    rename_threshold: float,
    auto_rename: bool,
    manual_folders: list[str],
    summary: dict,
    history: list[dict],
    table,
) -> None:
    str_path = str(path.resolve())

    # Skip if in a manual folder
    if any(str_path.startswith(m) for m in manual_folders):
        summary["skipped"] += 1
        table.add_row(path.name, "[dim]skipped[/dim]", "[dim]manual folder[/dim]", "-")
        return

    age = file_age_days(path)

    # Recents tier: file is new
    if age <= recents_days:
        dest_dir = output_paths["recents"]
        dest = build_new_path(path, None, dest_dir)
        action = "[green]recents[/green]"
        category = "Recents"
        rename_note = ""
        if not dry_run:
            _record_move(str(path), str(dest), history)
            safe_move(path, dest)
        summary["moved"] += 1
        table.add_row(path.name, action, str(dest.parent), category)
        return

    # Library tier: categorize via Claude CLI or fast paths
    result: CategorizationResult = categorize_file(path, cfg)

    dest_dir = output_paths["library"] / result.category
    new_name = None
    if auto_rename and result.suggested_name and result.confidence >= rename_threshold:
        new_name = result.suggested_name

    dest = build_new_path(path, new_name, dest_dir)
    action = "[blue]AI Library[/blue]"
    rename_note = f" -> {dest.name}" if new_name else ""

    if not dry_run:
        _record_move(str(path), str(dest), history)
        safe_move(path, dest)
        if new_name:
            summary["renamed"] += 1

    summary["moved"] += 1
    table.add_row(
        path.name + ("[yellow]*[/yellow]" if new_name else ""),
        action,
        str(result.category),
        f"{result.confidence:.0%}",
    )


def find_duplicates(folder: Path, cfg: dict) -> dict[str, list[Path]]:
    """
    Find files in folder that are byte-for-byte identical.
    Returns a dict mapping hash -> list of paths.
    """
    ignore_patterns = cfg.get("ignore_patterns", [])
    hash_map: dict[str, list[Path]] = {}

    for path in folder.rglob("*"):
        if not path.is_file() or should_ignore(path, ignore_patterns):
            continue
        h = compute_file_hash(path)
        if h:
            hash_map.setdefault(h, []).append(path)

    return {h: paths for h, paths in hash_map.items() if len(paths) > 1}


def find_cleanup_candidates(folder: Path, cfg: dict) -> list[Path]:
    """Return files that are old installers/archives safe to remove."""
    cleanup_exts = set(cfg.get("cleanup_extensions", []))
    age_days = cfg.get("cleanup_age_days", 30)
    candidates = []

    for path in folder.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in cleanup_exts and file_age_days(path) > age_days:
            candidates.append(path)

    return candidates


def undo_last(n: int = 1) -> int:
    """Undo the last n file moves. Returns count of undone moves."""
    history = _load_undo_history()
    if not history:
        console.print("[yellow]Nothing to undo.[/yellow]")
        return 0

    to_undo = history[-n:]
    undone = 0
    for entry in reversed(to_undo):
        src = Path(entry["src"])
        dest = Path(entry["dest"])
        if dest.exists():
            safe_move(dest, src)
            undone += 1
            console.print(f"  Restored [cyan]{dest.name}[/cyan] -> [green]{src}[/green]")
        else:
            console.print(f"  [red]Cannot undo: {dest} not found[/red]")

    _save_undo_history(history[:-n] if undone else history)
    return undone
