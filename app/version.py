"""
Dynamic version manager for Palworld Server Manager.
Reads the current application version directly from CHANGELOG.md as the single source of truth.
When CHANGELOG.md is updated with a new version header (e.g. '## [1.0.1] - 2026-10-18'),
the application reflects the new version across all templates, APIs, and metadata automatically.
"""

from functools import lru_cache
import os
from pathlib import Path
import re
from typing import Optional

DEFAULT_VERSION = "1.0.0"


def find_changelog_path() -> Optional[Path]:
    """Locate the project CHANGELOG.md across development and container environments."""
    candidates = [
        # Standard repository root (../CHANGELOG.md relative to app/version.py)
        Path(__file__).resolve().parent.parent / "CHANGELOG.md",
        # Same directory fallback
        Path(__file__).resolve().parent / "CHANGELOG.md",
        # Docker container default working directory
        Path("/app/CHANGELOG.md"),
        # Current working directory fallback
        Path("./CHANGELOG.md"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


@lru_cache(maxsize=1)
def _cached_app_version() -> str:
    env_ver = os.getenv("APP_VERSION")
    if env_ver and env_ver.strip():
        return env_ver.strip().lstrip("v")

    changelog_file = find_changelog_path()
    if changelog_file and changelog_file.is_file():
        try:
            content = changelog_file.read_text(encoding="utf-8")
            match = re.search(
                r"^##\s*\[v?([0-9]+\.[0-9]+\.[0-9]+[^\]]*)\]",
                content,
                re.MULTILINE
            )
            if match:
                return match.group(1).strip()
        except Exception:
            pass

    return DEFAULT_VERSION


def get_app_version(fresh: bool = False) -> str:
    """Returns the current application version parsed from CHANGELOG.md."""
    if fresh:
        _cached_app_version.cache_clear()
    return _cached_app_version()


def get_latest_release_notes() -> str:
    """Extracts the release notes for the current version from CHANGELOG.md."""
    changelog_file = find_changelog_path()
    if not changelog_file or not changelog_file.is_file():
        return "Initial release of Palworld Server Manager."

    try:
        content = changelog_file.read_text(encoding="utf-8")
        current_ver = get_app_version()
        pattern = rf"^##\s*\[v?{re.escape(current_ver)}\][^\n]*\n(.*?)(?=\n##\s*\[|\Z)"
        match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
        if match:
            return match.group(1).strip()
    except Exception:
        pass

    return f"Release notes for Palworld Server Manager v{get_app_version()}."


__version__ = get_app_version()
