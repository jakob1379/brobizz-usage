from __future__ import annotations

from pathlib import Path

from platformdirs import user_data_path

APP_AUTHOR = "brobizz-usage"
APP_NAME = "brobizz-usage"


def get_user_data_path(*parts: str, ensure_exists: bool = False) -> Path:
    """Return the XDG user data path for Brobizz usage files."""
    base_path = user_data_path(APP_NAME, APP_AUTHOR, ensure_exists=ensure_exists)
    return base_path.joinpath(*parts)
