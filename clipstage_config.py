"""
ClipStage v5.0 - shared configuration (single source of truth).

api.py, indexer.py and generate_thumbs.py all import from here, so the volume list,
video extensions, clip-ID hash, collection name and paths can never drift apart.
Everything is overridable with environment variables (see .env.sample).
"""

import hashlib
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# -- Search collection ---------------------------------------------------------
# "clips_v2" = the schema with token_separators (word-by-word search).
COLLECTION = os.environ.get("CLIPSTAGE_COLLECTION", "clips_v2")

# -- Volumes -------------------------------------------------------------------
VOLUMES_ROOT = Path(os.environ.get("CLIPSTAGE_VOLUMES_ROOT", "/Volumes"))

DEFAULT_SCAN_VOLUMES = [
    "EDIT", "EDIT2", "INGEST", "PLAYOUT", "DIGITAL", "SHARE FOLDER", "TRANSCODER",
]
_scan_env = os.environ.get("CLIPSTAGE_SCAN_VOLUMES", "")
SCAN_VOLUMES = (
    [v.strip() for v in _scan_env.split(",") if v.strip()]
    if _scan_env.strip() else list(DEFAULT_SCAN_VOLUMES)
)

# -- Media rules ---------------------------------------------------------------
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mxf", ".avi", ".mkv", ".m4v",
                    ".mpg", ".mpeg", ".r3d", ".braw"}

# Folder names skipped at ANY depth (case-insensitive exact match).
EXCLUDE_FOLDERS = {
    "@recycle", "#recycle", "@recently-snapshot", ".trashes",
    ".temporaryitems", "lost+found", "$recycle.bin",
}

# -- Paths ---------------------------------------------------------------------
STAGING_PATH = os.environ.get("CLIPSTAGE_STAGING_PATH", "/Users/Shared/staging")
STATIC_DIR = BASE_DIR / "static"
THUMB_DIR = Path(os.environ.get("CLIPSTAGE_THUMB_DIR", str(STATIC_DIR / "thumbs")))


def clip_uid(path: str) -> str:
    """Stable clip ID = first 16 hex chars of md5(path). The UI uses the same value for
    /thumb/<id> and /stream/<id>. Moving or renaming a file therefore creates a new clip."""
    return hashlib.md5(path.encode()).hexdigest()[:16]


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
