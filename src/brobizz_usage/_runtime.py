from __future__ import annotations

import sys
import sysconfig


def prefer_virtualenv_site_packages() -> None:
    """Keep inherited PYTHONPATH entries from shadowing the active virtualenv."""
    if sys.prefix == getattr(sys, "base_prefix", sys.prefix):
        return

    paths = sysconfig.get_paths()
    venv_site_paths = []
    for key in ("purelib", "platlib"):
        path = paths.get(key)
        if path and path not in venv_site_paths:
            venv_site_paths.append(path)

    if not venv_site_paths:
        return

    sys.path[:] = [path for path in sys.path if path not in venv_site_paths]
    insert_at = 1 if sys.path else 0
    for path in reversed(venv_site_paths):
        sys.path.insert(insert_at, path)
