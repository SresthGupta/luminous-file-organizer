"""File categorization using Claude Code CLI with caching and smart rules."""

import json
import os
import subprocess
import hashlib
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict

import yaml

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
    category: str
    suggested_name: Optional[str]
    confidence: float
    reasoning: str


# --- Extension-based fast path (no AI needed) ---

EXTENSION_CATEGORIES = {
    ".dmg": "Installers",
    ".pkg": "Installers",
    ".app": "Installers",
    ".msi": "Installers",
    ".exe": "Installers",
    ".zip": "Archives",
    ".tar": "Archives",
    ".gz": "Archives",
    ".rar": "Archives",
    ".7z": "Archives",
    ".bz2": "Archives",
    ".xz": "Archives",
    ".mp3": "Media/Music",
    ".wav": "Media/Music",
    ".flac": "Media/Music",
    ".aac": "Media/Music",
    ".m4a": "Media/Music",
    ".ogg": "Media/Music",
    ".mp4": "Media/Video",
    ".mov": "Media/Video",
    ".avi": "Media/Video",
    ".mkv": "Media/Video",
    ".wmv": "Media/Video",
    ".webm": "Media/Video",
    ".py": "Code/Python",
    ".js": "Code/JavaScript",
    ".ts": "Code/TypeScript",
    ".go": "Code/Go",
    ".rs": "Code/Rust",
    ".java": "Code/Java",
    ".cpp": "Code/C++",
    ".c": "Code/C",
    ".rb": "Code/Ruby",
    ".sh": "Code/Shell",
}


# --- Cache ---

CACHE_DIR = Path.home() / ".config" / "luminous"
CACHE_FILE = CACHE_DIR / "cache.json"
RULES_FILE = CACHE_DIR / "rules.yaml"


def _load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_cache(cache: dict):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def _cache_key(path: Path) -> str:
    stat = path.stat()
    return f"{path}:{stat.st_mtime_ns}:{stat.st_size}"


def _load_custom_rules() -> dict:
    """Load user-defined keyword-to-category rules from rules.yaml."""
    if RULES_FILE.exists():
        try:
            data = yaml.safe_load(RULES_FILE.read_text())
            return data.get("custom_categories", {})
        except (yaml.YAMLError, OSError):
            return {}
    return {}


def _create_default_rules():
    """Create a default rules.yaml if none exists."""
    if not RULES_FILE.exists():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        default = {
            "custom_categories": {
                "receipt": "Finance/Receipts",
                "invoice": "Finance/Invoices",
                "resume": "Personal/Career",
                "cover letter": "Personal/Career",
                "homework": "School/Assignments",
                "syllabus": "School/Reference",
            }
        }
        RULES_FILE.write_text(yaml.dump(default, default_flow_style=False))


# --- Claude CLI helper ---

def _run_claude(prompt: str, timeout: int = 90) -> str:
    """Run a prompt through Claude Code CLI (uses Max subscription)."""
    try:
        result = subprocess.run(
            ["claude", "--print", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return '{"error": "timeout"}'
    except FileNotFoundError:
        return '{"error": "claude CLI not found"}'
    except Exception as e:
        return f'{{"error": "{str(e)}"}}'


# --- Screenshot detection ---

def _is_screenshot(name: str) -> bool:
    lower = name.lower()
    return any(p in lower for p in [
        "screenshot", "screen shot", "screen_shot",
        "capture d'ecran", "bildschirmfoto",
    ])


# --- Main categorization ---

def categorize_file(path: Path, cfg: dict) -> CategorizationResult:
    """Categorize a single file using layered strategy:
    1. Check cache
    2. Check extension fast path
    3. Check custom keyword rules
    4. Check screenshot patterns
    5. Call Claude CLI as last resort
    """
    cache = _load_cache()
    key = _cache_key(path)

    # 1. Cache hit
    if key in cache:
        d = cache[key]
        return CategorizationResult(**d)

    result = _categorize_internal(path, cfg)

    # Save to cache
    cache[key] = asdict(result)
    _save_cache(cache)

    return result


def _categorize_internal(path: Path, cfg: dict) -> CategorizationResult:
    ext = path.suffix.lower()
    name = path.stem

    # 2. Extension fast path
    if ext in EXTENSION_CATEGORIES:
        return CategorizationResult(
            category=EXTENSION_CATEGORIES[ext],
            suggested_name=None,
            confidence=0.95,
            reasoning=f"Categorized by extension ({ext})",
        )

    # 3. Screenshot detection
    if _is_screenshot(path.name) and ext in IMAGE_EXTENSIONS:
        suggested = None
        if is_generic_name(path.name):
            suggested = f"screenshot-{path.stem.split()[-1].lower()}" if " " in path.stem else None
        return CategorizationResult(
            category="Screenshots",
            suggested_name=suggested,
            confidence=0.95,
            reasoning="Detected as screenshot by filename pattern",
        )

    # 4. Custom keyword rules
    rules = _load_custom_rules()
    lower_name = path.name.lower()
    for keyword, category in rules.items():
        if keyword.lower() in lower_name:
            return CategorizationResult(
                category=category,
                suggested_name=None,
                confidence=0.85,
                reasoning=f"Matched custom rule: '{keyword}'",
            )

    # 5. Claude CLI call
    return _categorize_with_claude(path, cfg)


def _categorize_with_claude(path: Path, cfg: dict) -> CategorizationResult:
    """Use Claude Code CLI to categorize a file."""
    max_chars = cfg.get("max_content_chars", 1500)
    content_preview = extract_text_preview(path, max_chars)

    size_kb = file_size_bytes(path) / 1024
    age = file_age_days(path)
    mime = get_mime_type(path)
    generic = is_generic_name(path.name)

    prompt = f"""You are a file organizer. Analyze this file and return ONLY a valid JSON object, no other text.

File: {path.name}
Extension: {path.suffix.lower()}
MIME: {mime}
Size: {size_kb:.1f} KB
Age: {age:.0f} days
Generic name: {generic}
"""

    if content_preview:
        prompt += f"\nContent preview (first {max_chars} chars):\n{content_preview[:max_chars]}\n"

    prompt += """
Return JSON with these fields:
- "category": one of Work/Projects, Work/Documents, School/Assignments, School/Notes, Finance/Receipts, Finance/Statements, Personal/Photos, Personal/Documents, Reference/Books, Reference/Articles, Media/Music, Media/Video, Code, Installers, Archives, Screenshots, Misc
- "suggested_name": kebab-case descriptive name (no extension) if current name is generic, otherwise null
- "confidence": float 0.0-1.0
- "reasoning": one sentence

ONLY output the JSON object. No markdown, no explanation."""

    raw = _run_claude(prompt)

    # Try to parse JSON from the response
    try:
        # Handle markdown code blocks
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        data = json.loads(raw)
        return CategorizationResult(
            category=data.get("category", "Misc"),
            suggested_name=data.get("suggested_name"),
            confidence=float(data.get("confidence", 0.5)),
            reasoning=data.get("reasoning", ""),
        )
    except (json.JSONDecodeError, KeyError, ValueError):
        return CategorizationResult(
            category=_fallback_category(path),
            suggested_name=None,
            confidence=0.3,
            reasoning=f"Fallback (could not parse Claude response)",
        )


def categorize_batch(
    paths: list[Path],
    cfg: dict,
    batch_size: int = 5,
) -> list[CategorizationResult]:
    """Categorize files in batches. Uses cache and fast paths first,
    only calls Claude CLI for files that need AI analysis."""
    results = []
    needs_claude = []
    needs_claude_indices = []

    for i, p in enumerate(paths):
        cache = _load_cache()
        key = _cache_key(p)

        # Check cache
        if key in cache:
            results.append(CategorizationResult(**cache[key]))
            continue

        # Check fast paths (extension, screenshot, custom rules)
        ext = p.suffix.lower()
        if ext in EXTENSION_CATEGORIES:
            r = CategorizationResult(
                category=EXTENSION_CATEGORIES[ext],
                suggested_name=None,
                confidence=0.95,
                reasoning=f"Extension fast path ({ext})",
            )
            results.append(r)
            cache[key] = asdict(r)
            _save_cache(cache)
            continue

        if _is_screenshot(p.name) and ext in IMAGE_EXTENSIONS:
            r = CategorizationResult(
                category="Screenshots",
                suggested_name=None,
                confidence=0.95,
                reasoning="Screenshot pattern match",
            )
            results.append(r)
            cache[key] = asdict(r)
            _save_cache(cache)
            continue

        rules = _load_custom_rules()
        matched = False
        for keyword, category in rules.items():
            if keyword.lower() in p.name.lower():
                r = CategorizationResult(
                    category=category,
                    suggested_name=None,
                    confidence=0.85,
                    reasoning=f"Custom rule: '{keyword}'",
                )
                results.append(r)
                cache[key] = asdict(r)
                _save_cache(cache)
                matched = True
                break

        if matched:
            continue

        # Needs Claude
        results.append(None)  # placeholder
        needs_claude.append(p)
        needs_claude_indices.append(i)

    # Process files needing Claude in batches
    for batch_start in range(0, len(needs_claude), batch_size):
        batch = needs_claude[batch_start:batch_start + batch_size]
        batch_indices = needs_claude_indices[batch_start:batch_start + batch_size]

        if len(batch) == 1:
            r = _categorize_with_claude(batch[0], cfg)
            results[batch_indices[0]] = r
        else:
            # Batch call: send multiple files in one prompt
            batch_results = _categorize_batch_with_claude(batch, cfg)
            for idx, r in zip(batch_indices, batch_results):
                results[idx] = r

    return results


def _categorize_batch_with_claude(
    paths: list[Path],
    cfg: dict,
) -> list[CategorizationResult]:
    """Send multiple files to Claude in a single call."""
    max_chars = cfg.get("max_content_chars", 800)

    files_desc = []
    for i, p in enumerate(paths):
        preview = extract_text_preview(p, max_chars)
        desc = f"File {i+1}: {p.name} | ext: {p.suffix} | size: {file_size_bytes(p)/1024:.0f}KB | age: {file_age_days(p):.0f}d | generic: {is_generic_name(p.name)}"
        if preview:
            desc += f"\n  Preview: {preview[:400]}"
        files_desc.append(desc)

    prompt = f"""You are a file organizer. Categorize ALL {len(paths)} files below. Return a JSON ARRAY with one object per file, in order.

{chr(10).join(files_desc)}

Each object must have: "category", "suggested_name" (null if name is fine), "confidence" (0-1), "reasoning" (1 sentence).

Categories: Work/Projects, Work/Documents, School/Assignments, School/Notes, Finance/Receipts, Finance/Statements, Personal/Photos, Personal/Documents, Reference/Books, Reference/Articles, Media/Music, Media/Video, Code, Installers, Archives, Screenshots, Misc

ONLY output the JSON array. No markdown, no explanation."""

    raw = _run_claude(prompt)

    try:
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        data = json.loads(raw)
        results = []
        cache = _load_cache()
        for i, item in enumerate(data):
            r = CategorizationResult(
                category=item.get("category", "Misc"),
                suggested_name=item.get("suggested_name"),
                confidence=float(item.get("confidence", 0.5)),
                reasoning=item.get("reasoning", ""),
            )
            results.append(r)
            if i < len(paths):
                cache[_cache_key(paths[i])] = asdict(r)
        _save_cache(cache)
        return results
    except (json.JSONDecodeError, KeyError, ValueError):
        # Fallback: categorize each individually
        return [
            CategorizationResult(
                category=_fallback_category(p),
                suggested_name=None,
                confidence=0.3,
                reasoning="Batch parse failed, using fallback",
            )
            for p in paths
        ]


def _fallback_category(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == PDF_EXTENSION:
        return "Docs/PDFs"
    if ext in IMAGE_EXTENSIONS:
        return "Media/Images"
    if ext in TEXT_EXTENSIONS:
        return "Docs/Text"
    if ext in DOCUMENT_EXTENSIONS:
        return "Docs/Office"
    return "Misc"


# Initialize default rules on import
_create_default_rules()
