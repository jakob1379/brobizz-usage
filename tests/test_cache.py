from __future__ import annotations

import json
import time

from brobizz_usage.cache import DiskResponseCache


def test_disk_response_cache_round_trips_payload(tmp_path) -> None:
    cache = DiskResponseCache(path=tmp_path)
    payload = {"items": [{"id": 1}]}

    cache.set("GET", "/accounts/account/transactions", {"params": {"PageNumber": 1}}, payload, "user")

    assert cache.get("GET", "/accounts/account/transactions", {"params": {"PageNumber": 1}}, "user") == payload


def test_disk_response_cache_keys_include_params(tmp_path) -> None:
    cache = DiskResponseCache(path=tmp_path)
    cache.set("GET", "/transactions", {"params": {"PageNumber": 1}}, {"page": 1}, "user")
    cache.set("GET", "/transactions", {"params": {"PageNumber": 2}}, {"page": 2}, "user")

    assert cache.get("GET", "/transactions", {"params": {"PageNumber": 1}}, "user") == {"page": 1}
    assert cache.get("GET", "/transactions", {"params": {"PageNumber": 2}}, "user") == {"page": 2}


def test_disk_response_cache_keys_include_namespace(tmp_path) -> None:
    cache = DiskResponseCache(path=tmp_path)
    cache.set("GET", "/person", {}, {"name": "A"}, "user-a")
    cache.set("GET", "/person", {}, {"name": "B"}, "user-b")

    assert cache.get("GET", "/person", {}, "user-a") == {"name": "A"}
    assert cache.get("GET", "/person", {}, "user-b") == {"name": "B"}


def test_disk_response_cache_ignores_expired_entries(tmp_path) -> None:
    cache = DiskResponseCache(path=tmp_path, ttl_seconds=1)
    cache.set("GET", "/person", {}, {"name": "Person"}, "user")
    cache_file = next(tmp_path.glob("*.json"))
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    data["created_at"] = time.time() - 2
    cache_file.write_text(json.dumps(data), encoding="utf-8")

    assert cache.get("GET", "/person", {}, "user") is None
