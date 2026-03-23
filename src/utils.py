"""File type detection, metadata extraction, and content preview utilities."""

import os
import re
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

try:
    import magic
    MAGIC_AVAILABLE = True
except ImportError:
    MAGIC_AVAILABLE = False

try:
    from PIL import Image
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False


TEXT_EXTENSIONS = {
    ".txt", ".md", ".rst", ".csv", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".log", ".py", ".js",
    ".ts", ".html", ".css", ".xml", ".sh", ".bash", ".zsh",
    ".env", ".gitignore", ".dockerfile", ".tf", ".sql",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".heic"}
PDF_EXTENSION = ".pdf"
ARCHIVE_EXTENSIONS = {".zip", ".tar", ".gz", ".bz2", ".7z", ".rar", ".xz"}
INSTALLER_EXTENSIONS = {".dmg", ".pkg", ".exe", ".msi"}
DOCUMENT_EXTENSIONS = {".docx", ".doc", ".odt", ".pptx", ".ppt", ".xlsx", ".xls"}


def file_age_days(path: Path) -> float:
    stat = path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    now = datetime.now(tz=timezone.utc)
    return (now - mtime).total_seconds() / 86400


def file_size_bytes(path: Path) -> int:
    return path.stat().st_size


def get_mime_type(path: Path) -> str:
    if MAGIC_AVAILABLE:
        try:
            return magic.from_file(str(path), mime=True)
        except Exception:
            pass
    ext = path.suffix.lower()
    mime_map = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".csv": "text/csv",
        ".zip": "application/zip",
        ".dmg": "application/x-apple-diskimage",
    }
    return mime_map.get(ext, "application/octet-stream")


def extract_text_preview(path: Path, max_chars: int = 2000) -> Optional[str]:
    """Extract a text preview from a file for AI analysis."""
    ext = path.suffix.lower()

    if ext == PDF_EXTENSION:
        return _extract_pdf_preview(path, max_chars)

    if ext in TEXT_EXTENSIONS:
        return _extract_text_file_preview(path, max_chars)

    if ext in IMAGE_EXTENSIONS:
        return _extract_image_preview(path)

    if ext in DOCUMENT_EXTENSIONS:
        return _extract_document_preview(path, max_chars)

    return None


def _extract_pdf_preview(path: Path, max_chars: int) -> Optional[str]:
    if not PYMUPDF_AVAILABLE:
        return None
    try:
        doc = fitz.open(str(path))
        text = ""
        for page_num in range(min(2, len(doc))):
            page = doc[page_num]
            text += page.get_text()
            if len(text) >= max_chars:
                break
        doc.close()
        return text[:max_chars].strip() or None
    except Exception:
        return None


def _extract_text_file_preview(path: Path, max_chars: int) -> Optional[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(max_chars).strip() or None
    except Exception:
        return None


def _extract_image_preview(path: Path) -> Optional[str]:
    if not OCR_AVAILABLE:
        return None
    try:
        img = Image.open(path)
        text = pytesseract.image_to_string(img)
        return text[:1000].strip() or None
    except Exception:
        return None


def _extract_document_preview(path: Path, max_chars: int) -> Optional[str]:
    try:
        import zipfile
        if path.suffix.lower() in {".docx", ".odt"}:
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                content_file = "word/document.xml" if "word/document.xml" in names else None
                if not content_file:
                    content_file = next((n for n in names if "content" in n.lower()), None)
                if content_file:
                    raw = z.read(content_file).decode("utf-8", errors="replace")
                    # Strip XML tags
                    text = re.sub(r"<[^>]+>", " ", raw)
                    text = re.sub(r"\s+", " ", text).strip()
                    return text[:max_chars] or None
    except Exception:
        pass
    return None


def compute_file_hash(path: Path) -> str:
    """Compute SHA-256 hash of a file for duplicate detection."""
    sha256 = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    except Exception:
        return ""


def is_generic_name(filename: str) -> bool:
    """Return True if the filename looks auto-generated and worth renaming."""
    stem = Path(filename).stem.lower()
    patterns = [
        r"^screenshot\s+\d{4}-\d{2}-\d{2}",
        r"^screen shot \d{4}-\d{2}-\d{2}",
        r"^img_\d{4,}$",
        r"^image\d*$",
        r"^photo_\d+$",
        r"^document\d*$",
        r"^untitled\d*$",
        r"^scan\d*$",
        r"^file\d*$",
        r"^download\d*$",
        r"^copy of ",
        r"^\d{10,}$",
    ]
    return any(re.match(p, stem) for p in patterns)


def sanitize_filename(name: str) -> str:
    """Convert a suggested name to a safe filename (no spaces, lowercase)."""
    name = name.lower().strip()
    name = re.sub(r"[^\w\s\-.]", "", name)
    name = re.sub(r"[\s_]+", "-", name)
    name = re.sub(r"-+", "-", name)
    name = name.strip("-")
    return name[:120]  # cap length


def should_ignore(path: Path, ignore_patterns: list[str]) -> bool:
    """Check if a file should be ignored based on patterns."""
    import fnmatch
    name = path.name
    return any(fnmatch.fnmatch(name, p) for p in ignore_patterns)
