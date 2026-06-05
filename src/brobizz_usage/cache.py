from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brobizz_usage.paths import get_user_data_path

DEFAULT_CACHE_TTL_SECONDS = 3600


def _json_default(value: Any) -> str:
    return str(value)


@dataclass(frozen=True)
class DiskResponseCache:
    """Small filesystem cache for successful Brobizz JSON API responses."""

    path: Path | None = None
    ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS

    @property
    def root(self) -> Path:
        return self.path or get_user_data_path("cache", ensure_exists=True)

    def get(self, method: str, path: str, kwargs: dict[str, Any], namespace: str) -> Any | None:
        cache_path = self._path_for(method, path, kwargs, namespace)
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        created_at = data.get("created_at")
        if not isinstance(created_at, int | float):
            return None
        if created_at + self.ttl_seconds <= time.time():
            return None
        return data.get("payload")

    def set(self, method: str, path: str, kwargs: dict[str, Any], payload: Any, namespace: str) -> None:
        cache_path = self._path_for(method, path, kwargs, namespace)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"created_at": time.time(), "payload": payload}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _path_for(self, method: str, path: str, kwargs: dict[str, Any], namespace: str) -> Path:
        key_payload = {
            "namespace": namespace,
            "method": method.upper(),
            "path": path,
            "params": kwargs.get("params"),
            "json": kwargs.get("json"),
            "data": kwargs.get("data"),
        }
        key = json.dumps(key_payload, sort_keys=True, default=_json_default)
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.json"
