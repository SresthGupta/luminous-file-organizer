# Luminous

**AI-powered file organizer for Mac** - smarter than Sparkle, private by design.

Luminous uses Claude Haiku (the fastest, cheapest Anthropic model) to read file contents and intelligently sort, rename, and organize your files -- automatically, locally, with no cloud uploads.

---

## Why Luminous beats Sparkle

| Feature | Sparkle | Luminous |
|---|---|---|
| Reads file contents | No (filenames only) | Yes (PDFs, text, images) |
| Auto-rename generics | No | Yes |
| Privacy | Cloud (OpenAI) | 100% local API calls |
| Cost | $9.25/mo | Pay-per-use (Haiku is ~$0.001/file) |
| GUI | Native Swift | Menubar + settings window |
| Watch any folder | Limited | Any path, cloud storage too |
| Open source | No | Yes |

---

## Features

- **Menubar app** -- always-on Mac menubar icon, recent activity feed, settings window
- **Folder watching** -- real-time monitoring via FSEvents; watch Desktop, Downloads, Documents, Google Drive, Dropbox, iCloud Drive, or any custom path
- **Three-tier organization**:
  - `Recents/` -- files < 3 days old (configurable)
  - `Library/` -- AI-sorted by category (Work/Projects, Finance/Receipts, ...)
  - `Manual/` -- folders Luminous never touches
- **Smart rename**: `Screenshot 2026-03-23 at 10.15.32 AM.png` -> `slack-design-review.png`
- **Content-aware**: reads first page of PDFs, text files, Word docs, OCRs screenshots
- **Duplicate detection** -- find and optionally remove bit-for-bit duplicates
- **Cleanup** -- flag old .dmg installers and .zip archives
- **Undo** -- reverse the last N moves with `luminous undo`
- **Dry-run** -- preview changes without moving anything

---

## Installation

### Requirements

- macOS 12+
- Python 3.12+
- An Anthropic API key (set as `ANTHROPIC_API_KEY`)

### Install

```bash
# Clone
git clone https://github.com/sresthgupta/luminous-file-organizer.git
cd luminous-file-organizer

# Create virtualenv
python3 -m venv .venv
source .venv/bin/activate

# Install
pip install -e .

# Set your API key
export ANTHROPIC_API_KEY="sk-ant-..."
```

### Optional: OCR support for screenshots

```bash
brew install tesseract
pip install pytesseract
```

---

## Usage

### Menubar App (recommended)

```bash
luminous-gui
```

This launches the Mac menubar app. Click the "L" icon to:
- See recent file moves
- Pause / resume watching
- Open Settings to configure folders, toggle auto-rename, etc.
- Trigger an immediate organize run

### CLI

```bash
# Organize a specific folder (or all watched folders)
luminous organize ~/Downloads
luminous organize  # all watched folders

# Dry run - see what would happen
luminous organize ~/Downloads --dry-run

# Start daemon watcher
luminous start

# Stop daemon
luminous stop

# Rename generically named files
luminous rename ~/Downloads

# Undo the last 5 moves
luminous undo 5

# Find duplicates
luminous duplicates ~/Documents

# Cleanup old installers
luminous cleanup ~/Downloads

# View/edit config
luminous config --show
luminous config --watch ~/Desktop ~/Downloads ~/Documents ~/Google\ Drive/My\ Drive
luminous config --output ~/Organized

# Stats
luminous stats
```

---

## Configuration

Config lives at `~/.config/luminous/config.json`. Key options:

```json
{
  "watched_folders": [
    "~/Desktop",
    "~/Downloads",
    "~/Documents",
    "~/Library/CloudStorage/GoogleDrive-you@gmail.com/My Drive"
  ],
  "output_base": "~/Documents/Luminous",
  "recents_days": 3,
  "auto_rename": true,
  "rename_confidence_threshold": 0.80,
  "auto_cleanup": false,
  "cleanup_extensions": [".dmg", ".pkg", ".zip"],
  "cleanup_age_days": 30,
  "manual_folders": [],
  "anthropic_model": "claude-haiku-4-5-20251001"
}
```

### Cloud Storage Presets

The settings window includes one-click presets for:
- iCloud Drive (`~/Library/Mobile Documents/com~apple~CloudDocs`)
- Dropbox (`~/Dropbox`)
- OneDrive (`~/OneDrive`)
- Google Drive (auto-detected from `~/Library/CloudStorage/GoogleDrive-*/My Drive`)

---

## How it works

1. New file detected in a watched folder (via FSEvents)
2. If file is < `recents_days` old: move to `Recents/`
3. Otherwise, extract a content preview:
   - PDFs: first 2 pages via PyMuPDF
   - Text/code: first 2000 chars
   - Images: OCR via Tesseract (if installed)
   - Word docs: XML text extraction
4. Send filename + preview to Claude Haiku:
   ```
   System: You are a file organizer. Return JSON with category, suggested_name, confidence.
   ```
5. Move file to `Library/{category}/`
6. If confidence >= 0.8 and name is generic: rename the file
7. Log move to `~/.config/luminous/undo_history.json`

---

## Output Structure

```
~/Documents/Luminous/
  Recents/
    report-draft.pdf
    screenshot-2026-03-23.png
  Library/
    Work/
      Projects/
        q1-roadmap.pdf
      Contracts/
        vendor-agreement-acme.pdf
    Finance/
      Receipts/
        amazon-order-receipt.pdf
      Tax Documents/
        w2-2025.pdf
    School/
      Assignments/
        cs101-homework-3.pdf
    Media/
      Screenshots/
        figma-design-review.png
  Manual/
    (user-controlled; Luminous never touches these)
```

---

## Cost Estimate

Claude Haiku pricing (as of 2026): ~$0.80/M input tokens, ~$4/M output tokens.

A typical file categorization uses ~300 input tokens and ~50 output tokens.
- Cost per file: ~$0.00024 (less than a quarter of a cent)
- 1,000 files organized: ~$0.24

For most users, Luminous costs pennies per month.

---

## License

MIT
