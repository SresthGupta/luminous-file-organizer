"""Smart file renaming logic."""

from pathlib import Path
from typing import Optional

from .utils import sanitize_filename, is_generic_name


def build_new_path(
    original: Path,
    suggested_name: Optional[str],
    destination_dir: Path,
) -> Path:
    """
    Construct the destination path for a file, applying a suggested rename
    if one is provided and the original name looks generic.

    Returns the final destination Path (may have a counter suffix to avoid collisions).
    """
    if suggested_name and is_generic_name(original.name):
        clean = sanitize_filename(suggested_name)
        if not clean:
            clean = sanitize_filename(original.stem)
        stem = clean
    else:
        stem = original.stem

    dest = destination_dir / (stem + original.suffix)

    # Avoid overwriting existing files
    counter = 1
    while dest.exists():
        dest = destination_dir / f"{stem}-{counter}{original.suffix}"
        counter += 1

    return dest


def safe_move(src: Path, dest: Path) -> Path:
    """
    Move src to dest. Creates parent directories as needed.
    Returns the final destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dest)
    return dest
