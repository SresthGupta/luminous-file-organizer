"""Luminous CLI - AI-powered file organizer."""

import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from .config import (
    load_config,
    save_config,
    ensure_output_dirs,
    PID_FILE,
    ensure_config_dir,
)
from .organizer import (
    organize_folder,
    find_duplicates,
    find_cleanup_candidates,
    undo_last,
)
from .watcher import FolderWatcher

app = typer.Typer(
    name="luminous",
    help="Luminous - AI-powered file organizer using Claude Haiku",
    add_completion=False,
    rich_markup_mode="rich",
)
console = Console()

BANNER = (
    "[bold cyan]\n"
    "  __    _   _ __  __ ___ _  _  ___  _   _ ___\n"
    r" | |   | | | |  \/  |_ _| \| |/ _ \| | | / __|" + "\n"
    r" | |__ | |_| | |\/| || || .` | (_) | |_| \__ \\" + "\n"
    r" |____| \___/|_|  |_|___|_|\_|\___/ \___/|___/" + "\n"
    "[/bold cyan]\n"
    "[dim]Smart file organization powered by Claude Haiku[/dim]\n"
)


def _print_banner() -> None:
    console.print(BANNER)


def _print_summary(summary: dict, dry_run: bool) -> None:
    mode = "[yellow](dry run)[/yellow] " if dry_run else ""
    console.print(
        f"\n{mode}[bold]Summary:[/bold] "
        f"[green]{summary['moved']} moved[/green]  "
        f"[cyan]{summary['renamed']} renamed[/cyan]  "
        f"[dim]{summary['skipped']} skipped[/dim]  "
        f"[red]{summary['errors']} errors[/red]"
    )


@app.command()
def organize(
    folder: Optional[Path] = typer.Argument(None, help="Folder to organize (default: all watched folders)"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show what would happen without moving files"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
) -> None:
    """Organize files in a folder using AI categorization."""
    _print_banner()
    cfg = load_config()

    folders: list[Path]
    if folder:
        folders = [folder.expanduser().resolve()]
    else:
        folders = [Path(f).expanduser().resolve() for f in cfg["watched_folders"]]

    for f in folders:
        if not f.exists():
            console.print(f"[red]Folder not found: {f}[/red]")
            continue
        console.print(f"\n[bold]Organizing[/bold] [cyan]{f}[/cyan]")
        summary = organize_folder(f, cfg, dry_run=dry_run, verbose=verbose)
        _print_summary(summary, dry_run)


@app.command()
def start() -> None:
    """Start the Luminous daemon to watch folders continuously."""
    _print_banner()
    cfg = load_config()
    ensure_output_dirs(cfg)

    watched = [Path(f).expanduser().resolve() for f in cfg["watched_folders"]]
    existing = [f for f in watched if f.exists()]

    if not existing:
        console.print("[red]No watched folders exist. Run `luminous config` to set them up.[/red]")
        raise typer.Exit(1)

    console.print(Panel.fit(
        "\n".join(f"  [cyan]{f}[/cyan]" for f in existing),
        title="[bold green]Luminous is watching[/bold green]",
        border_style="green",
    ))

    def on_new_file(path: Path) -> None:
        console.print(f"\n[dim]New file detected:[/dim] [cyan]{path.name}[/cyan]")
        folder = path.parent
        summary = organize_folder(folder, cfg, dry_run=False, verbose=False)

    # Write PID file
    ensure_config_dir()
    PID_FILE.write_text(str(os.getpid()))

    watcher = FolderWatcher(existing, on_new_file)
    watcher.start()
    console.print("[dim]Press Ctrl+C to stop.[/dim]\n")

    try:
        watcher.join()
    finally:
        if PID_FILE.exists():
            PID_FILE.unlink()


@app.command()
def stop() -> None:
    """Stop the running Luminous daemon."""
    if not PID_FILE.exists():
        console.print("[yellow]Luminous is not running.[/yellow]")
        raise typer.Exit(1)
    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        PID_FILE.unlink()
        console.print(f"[green]Luminous daemon (PID {pid}) stopped.[/green]")
    except ProcessLookupError:
        PID_FILE.unlink()
        console.print("[yellow]Process not found -- cleaned up stale PID file.[/yellow]")


@app.command()
def rename(
    folder: Path = typer.Argument(..., help="Folder to rename generic files in"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n"),
) -> None:
    """Rename generically named files (screenshots, untitled docs) using AI."""
    _print_banner()
    cfg = load_config()
    cfg_override = dict(cfg)
    cfg_override["recents_days"] = 0  # Force all files through AI rename path
    folder = folder.expanduser().resolve()
    if not folder.exists():
        console.print(f"[red]Folder not found: {folder}[/red]")
        raise typer.Exit(1)
    console.print(f"\n[bold]Renaming generics in[/bold] [cyan]{folder}[/cyan]")
    summary = organize_folder(folder, cfg_override, dry_run=dry_run)
    _print_summary(summary, dry_run)


@app.command()
def undo(
    count: int = typer.Argument(1, help="Number of recent moves to undo"),
) -> None:
    """Undo the last N file moves."""
    console.print(f"[bold]Undoing last {count} move(s)...[/bold]")
    n = undo_last(count)
    if n:
        console.print(f"[green]Restored {n} file(s).[/green]")


@app.command()
def duplicates(
    folder: Optional[Path] = typer.Argument(None, help="Folder to scan (default: Luminous Library)"),
    remove: bool = typer.Option(False, "--remove", help="Delete duplicate files (keeps first found)"),
) -> None:
    """Find (and optionally remove) duplicate files."""
    cfg = load_config()
    from .config import get_output_paths
    scan_dir = folder.expanduser().resolve() if folder else get_output_paths(cfg)["library"]
    console.print(f"[bold]Scanning for duplicates in[/bold] [cyan]{scan_dir}[/cyan]")

    dups = find_duplicates(scan_dir, cfg)
    if not dups:
        console.print("[green]No duplicates found.[/green]")
        return

    table = Table("Hash (short)", "Count", "Files", box=box.SIMPLE)
    for h, paths in dups.items():
        table.add_row(h[:12], str(len(paths)), "\n".join(str(p) for p in paths))
    console.print(table)

    if remove:
        removed = 0
        for paths in dups.values():
            for dup in paths[1:]:
                dup.unlink()
                removed += 1
        console.print(f"[green]Removed {removed} duplicate(s).[/green]")


@app.command()
def cleanup(
    folder: Optional[Path] = typer.Argument(None),
    remove: bool = typer.Option(False, "--remove", help="Actually delete the files"),
) -> None:
    """Find old .dmg, .zip, and installer files safe to remove."""
    cfg = load_config()
    scan_dir = (
        folder.expanduser().resolve() if folder
        else Path(cfg["watched_folders"][0]).expanduser()
    )
    console.print(f"[bold]Scanning for cleanup candidates in[/bold] [cyan]{scan_dir}[/cyan]")
    candidates = find_cleanup_candidates(scan_dir, cfg)

    if not candidates:
        console.print("[green]Nothing to clean up.[/green]")
        return

    table = Table("File", "Size", "Age (days)", box=box.SIMPLE)
    from .utils import file_age_days, file_size_bytes
    for p in candidates:
        size_mb = file_size_bytes(p) / (1024 * 1024)
        age = file_age_days(p)
        table.add_row(str(p), f"{size_mb:.1f} MB", f"{age:.0f}")
    console.print(table)

    if remove:
        for p in candidates:
            p.unlink()
        console.print(f"[green]Deleted {len(candidates)} file(s).[/green]")
    else:
        console.print("[dim]Run with --remove to delete these files.[/dim]")


@app.command()
def config(
    watch: Optional[list[Path]] = typer.Option(None, "--watch", "-w", help="Set watched folders"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Set output base folder"),
    recents_days: Optional[int] = typer.Option(None, "--recents-days", help="Days threshold for Recents tier"),
    no_rename: bool = typer.Option(False, "--no-rename", help="Disable auto-renaming"),
    show: bool = typer.Option(False, "--show", help="Print current config"),
) -> None:
    """View or update Luminous configuration."""
    cfg = load_config()

    if watch:
        cfg["watched_folders"] = [str(p.expanduser().resolve()) for p in watch]
        console.print(f"[green]Watched folders updated.[/green]")
    if output:
        cfg["output_base"] = str(output.expanduser().resolve())
        console.print(f"[green]Output folder set to {output}.[/green]")
    if recents_days is not None:
        cfg["recents_days"] = recents_days
    if no_rename:
        cfg["auto_rename"] = False

    if any([watch, output, recents_days is not None, no_rename]):
        save_config(cfg)

    if show or not any([watch, output, recents_days is not None, no_rename]):
        import json
        console.print(Panel(
            json.dumps(cfg, indent=2),
            title="[bold]Luminous Config[/bold]",
            border_style="cyan",
        ))


@app.command()
def stats() -> None:
    """Show organization statistics from the undo history."""
    from .config import UNDO_FILE
    import json
    if not UNDO_FILE.exists():
        console.print("[dim]No history yet. Run `luminous organize` to get started.[/dim]")
        return

    with open(UNDO_FILE) as f:
        history = json.load(f)

    console.print(f"[bold cyan]Total files organized:[/bold cyan] {len(history)}")

    dest_counts: dict[str, int] = {}
    for entry in history:
        dest_dir = str(Path(entry["dest"]).parent)
        dest_counts[dest_dir] = dest_counts.get(dest_dir, 0) + 1

    table = Table("Category Folder", "Files", box=box.SIMPLE)
    for folder, count in sorted(dest_counts.items(), key=lambda x: -x[1])[:20]:
        table.add_row(folder, str(count))
    console.print(table)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
