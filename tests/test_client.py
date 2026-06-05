from __future__ import annotations

import base64
import json
import time
from typing import Any

import pytest

from brobizz_usage.auth import OAuthState
from brobizz_usage.client import BrobizzClient, resolve_account_id
from brobizz_usage.errors import BrobizzError


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self.payload = payload

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.headers: dict[str, str] = {}
        self.responses = responses
        self.requests: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(self.headers),
                "kwargs": kwargs,
            }
        )
        return self.responses.pop(0)


class FakeOAuthManager:
    def __init__(self, initial: OAuthState, refreshed: OAuthState | None = None) -> None:
        self.initial = initial
        self.refreshed = refreshed or initial
        self.refreshes = 0

    def get_valid_state(self, force_login: bool = False) -> OAuthState:
        return self.initial

    def refresh_or_login(self, state: OAuthState) -> OAuthState:
        self.refreshes += 1
        return self.refreshed


def oauth_state(access_token: str, expires_at: int | None = None) -> OAuthState:
    return OAuthState(
        access_token=access_token,
        refresh_token=f"{access_token}-refresh",
        id_token=None,
        client_id="client",
        expires_at=expires_at if expires_at is not None else int(time.time()) + 3600,
    )


def jwt_with_payload(payload: dict[str, object]) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii").rstrip("=")
    return f"header.{encoded}.signature"


def test_cache_namespace_prefers_stable_token_subject() -> None:
    client = object.__new__(BrobizzClient)
    first = oauth_state(jwt_with_payload({"sub": "user"}))
    second = oauth_state(jwt_with_payload({"sub": "user"}))

    assert client._cache_namespace(first) == client._cache_namespace(second)


def test_resolve_account_id_prefers_current_then_default_then_first_usable() -> None:
    assert resolve_account_id({"currentAccountId": "current", "defaultAccountId": "default"}) == "current"
    assert (
        resolve_account_id(
            {
                "currentAccountId": "00000000-0000-0000-0000-000000000000",
                "defaultAccountId": "default",
                "accountIds": ["first"],
            }
        )
        == "default"
    )
    assert (
        resolve_account_id(
            {
                "currentAccountId": "00000000-0000-0000-0000-000000000000",
                "defaultAccountId": None,
                "accountIds": ["00000000-0000-0000-0000-000000000000", "first"],
            }
        )
        == "first"
    )


def test_resolve_account_id_raises_when_no_usable_account() -> None:
    with pytest.raises(BrobizzError):
        resolve_account_id({"accountIds": ["00000000-0000-0000-0000-000000000000"]})


def test_transactions_pagination_derives_pages_when_total_pages_is_zero() -> None:
    client = object.__new__(BrobizzClient)
    pages = {
        1: {
            "pageSize": 2,
            "filteredCount": 5,
            "totalPages": 0,
            "paginatedItems": [{"id": 1}, {"id": 2}],
        },
        2: {"paginatedItems": [{"id": 3}, {"id": 4}]},
        3: {"paginatedItems": [{"id": 5}]},
    }
    calls: list[int] = []

    def get_transactions_page(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs["page_number"])
        return pages[kwargs["page_number"]]

    client.get_transactions_page = get_transactions_page  # type: ignore[method-assign]

    result = client.get_all_transactions(account_id="account")

    assert calls == [1, 2, 3]
    assert result == {
        "accountId": "account",
        "totalCount": 5,
        "returnedCount": 5,
        "transactions": [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 5}],
    }


def test_refreshes_before_expiry() -> None:
    initial = oauth_state("old", expires_at=int(time.time()) - 1)
    refreshed = oauth_state("new")
    manager = FakeOAuthManager(initial, refreshed)
    session = FakeSession([FakeResponse(200, {"ok": True})])
    client = BrobizzClient(oauth_manager=manager, session=session, use_cache=False)

    assert client.request("GET", "/getCurrentPerson") == {"ok": True}

    assert manager.refreshes == 1
    assert session.requests[0]["headers"]["authorization"] == "Bearer new"


def test_retries_once_after_unauthorized_response() -> None:
    initial = oauth_state("old")
    refreshed = oauth_state("new")
    manager = FakeOAuthManager(initial, refreshed)
    session = FakeSession([FakeResponse(401, {}), FakeResponse(200, {"ok": True})])
    client = BrobizzClient(oauth_manager=manager, session=session, use_cache=False)

    assert client.request("GET", "/getCurrentPerson") == {"ok": True}

    assert manager.refreshes == 1
    assert [request["headers"]["authorization"] for request in session.requests] == [
        "Bearer old",
        "Bearer new",
    ]


class MemoryCache:
    def __init__(self, payload: Any | None = None) -> None:
        self.payload = payload
        self.gets: list[tuple[str, str, dict[str, Any], str]] = []
        self.sets: list[tuple[str, str, dict[str, Any], Any, str]] = []

    def get(self, method: str, path: str, kwargs: dict[str, Any], namespace: str) -> Any | None:
        self.gets.append((method, path, kwargs, namespace))
        return self.payload

    def set(self, method: str, path: str, kwargs: dict[str, Any], payload: Any, namespace: str) -> None:
        self.sets.append((method, path, kwargs, payload, namespace))


def test_request_uses_cache_before_http() -> None:
    manager = FakeOAuthManager(oauth_state("token"))
    session = FakeSession([])
    cache = MemoryCache({"ok": True})
    client = BrobizzClient(oauth_manager=manager, session=session, cache=cache)

    assert client.request("GET", "/getCurrentPerson") == {"ok": True}

    assert session.requests == []
    assert len(cache.gets) == 1
    assert cache.gets[0][:3] == ("GET", "/getCurrentPerson", {})


def test_request_writes_successful_get_to_cache() -> None:
    manager = FakeOAuthManager(oauth_state("token"))
    session = FakeSession([FakeResponse(200, {"ok": True})])
    cache = MemoryCache()
    client = BrobizzClient(oauth_manager=manager, session=session, cache=cache)

    assert client.request("GET", "/getCurrentPerson") == {"ok": True}

    assert len(cache.sets) == 1
    assert cache.sets[0][:4] == ("GET", "/getCurrentPerson", {}, {"ok": True})


def test_force_login_disables_cache_reads() -> None:
    manager = FakeOAuthManager(oauth_state("token"))
    session = FakeSession([FakeResponse(200, {"fresh": True})])
    cache = MemoryCache({"stale": True})
    client = BrobizzClient(oauth_manager=manager, session=session, cache=cache, force_login=True)

    assert client.request("GET", "/getCurrentPerson") == {"fresh": True}

    assert cache.gets == []
    assert cache.sets == []
