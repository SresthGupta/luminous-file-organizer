"""Haiku-powered file categorization using the Anthropic API."""

import json
import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

import anthropic

from .utils import (
    extract_text_preview,
    file_age_days,
    file_size_bytes,
    get_mime_type,
    is_generic_name,
    TEXT_EXTENSIONS,
    IMAGE_EXTENSIONS,
    PDF_EXTENSION,
    DOCUMENT_EXTENSIONS,
)


@dataclass
class CategorizationResult:
    category: str          # e.g. "Work/Projects"
    suggested_name: Optional[str]  # e.g. "apartment-lease-2026.pdf"
    confidence: float      # 0.0 to 1.0
    reasoning: str         # short explanation


SYSTEM_PROMPT = """You are Luminous, a smart file organizer. Given information about a file, \
return a JSON object categorizing it.

The category should be a path like "Work/Projects", "Finance/Receipts", "School/Notes", etc.
Use these top-level categories when appropriate:
  Work, Finance, School, Personal, Media, Code, Docs, Archive, Misc

The suggested_name should be a short, descriptive, kebab-case filename (no extension) \
that replaces generic names like "Screenshot 2026-03-23" or "Document". \
Set it to null if the current name is already descriptive.

Rules:
- category: required string (use "/" for subcategories, max 2 levels)
- suggested_name: optional kebab-case string, null if not needed
- confidence: float 0.0-1.0 reflecting how sure you are
- reasoning: one sentence explanation

Respond ONLY with valid JSON, no markdown, no extra text."""


def _build_user_message(
    path: Path,
    content_preview: Optional[str],
    model: str,
    max_content_chars: int,
) -> str:
    size_kb = file_size_bytes(path) / 1024
    age = file_age_days(path)
    mime = get_mime_type(path)
    generic = is_generic_name(path.name)

    parts = [
        f"Filename: {path.name}",
        f"Extension: {path.suffix.lower()}",
        f"MIME type: {mime}",
        f"Size: {size_kb:.1f} KB",
        f"Age: {age:.1f} days",
        f"Generic name: {generic}",
    ]

    if content_preview:
        preview = content_preview[:max_content_chars]
        parts.append(f"\nContent preview:\n{preview}")

    return "\n".join(parts)


def categorize_file(
    path: Path,
    cfg: dict,
    client: Optional[anthropic.Anthropic] = None,
) -> CategorizationResult:
    """Call Haiku to categorize a single file."""
    if client is None:
        client = anthropic.Anthropic()

    model = cfg.get("anthropic_model", "claude-haiku-4-5-20251001")
    max_chars = cfg.get("max_content_chars", 2000)

    content_preview = extract_text_preview(path, max_chars)
    user_msg = _build_user_message(path, content_preview, model, max_chars)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=256,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = response.content[0].text.strip()
        data = json.loads(raw)
        return CategorizationResult(
            category=data.get("category", "Misc"),
            suggested_name=data.get("suggested_name"),
            confidence=float(data.get("confidence", 0.5)),
            reasoning=data.get("reasoning", ""),
        )
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        return CategorizationResult(
            category=_fallback_category(path),
            suggested_name=None,
            confidence=0.3,
            reasoning=f"Fallback categorization (parse error: {e})",
        )
    except anthropic.APIError as e:
        return CategorizationResult(
            category=_fallback_category(path),
            suggested_name=None,
            confidence=0.1,
            reasoning=f"API error: {e}",
        )


def categorize_batch(
    paths: list[Path],
    cfg: dict,
    client: Optional[anthropic.Anthropic] = None,
) -> list[CategorizationResult]:
    """Categorize multiple files, one call each (Haiku is cheap)."""
    if client is None:
        client = anthropic.Anthropic()
    return [categorize_file(p, cfg, client) for p in paths]


def _fallback_category(path: Path) -> str:
    """Simple extension-based fallback when API is unavailable."""
    ext = path.suffix.lower()
    if ext == PDF_EXTENSION:
        return "Docs/PDFs"
    if ext in IMAGE_EXTENSIONS:
        return "Media/Images"
    if ext in TEXT_EXTENSIONS:
        return "Docs/Text"
    if ext in DOCUMENT_EXTENSIONS:
        return "Docs/Office"
    if ext in {".mp4", ".mov", ".avi", ".mkv"}:
        return "Media/Video"
    if ext in {".mp3", ".wav", ".flac", ".aac"}:
        return "Media/Audio"
    if ext in {".zip", ".tar", ".gz", ".dmg", ".pkg"}:
        return "Archive"
    if ext in {".py", ".js", ".ts", ".go", ".rs", ".cpp", ".java"}:
        return "Code"
    return "Misc"
