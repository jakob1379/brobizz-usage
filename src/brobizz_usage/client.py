from __future__ import annotations

import hashlib
import math
from typing import Any

import httpx

from brobizz_usage.auth import API_BASE_URL, USER_AGENT, OAuthManager, OAuthState, decode_jwt_payload
from brobizz_usage.cache import DiskResponseCache
from brobizz_usage.errors import BrobizzError

EMPTY_GUID = "00000000-0000-0000-0000-000000000000"


def resolve_account_id(person: dict[str, Any]) -> str:
    """Pick the usable account id from the current-person response."""
    for value in (person.get("currentAccountId"), person.get("defaultAccountId")):
        if value and value != EMPTY_GUID:
            return value
    account_ids = [value for value in person.get("accountIds", []) if value and value != EMPTY_GUID]
    if account_ids:
        return account_ids[0]
    raise BrobizzError("No usable account id was returned by /getCurrentPerson")


class BrobizzClient:
    """HTTPX-based client for the Brobizz self-service API."""

    def __init__(
        self,
        oauth_manager: OAuthManager | None = None,
        session: httpx.Client | None = None,
        force_login: bool = False,
        cache: DiskResponseCache | None = None,
        use_cache: bool = True,
    ) -> None:
        self.oauth_manager = oauth_manager or OAuthManager()
        self.oauth_state = self.oauth_manager.get_valid_state(force_login=force_login)
        self.session = session or httpx.Client()
        self.cache = cache or DiskResponseCache()
        self.cache_namespace = self._cache_namespace(self.oauth_state)
        self.use_cache = use_cache and not force_login
        self.session.headers.update(
            {
                "accept": "application/json, text/plain, */*",
                "accept-language": "en-US,en;q=0.9",
                "origin": API_BASE_URL,
                "referer": f"{API_BASE_URL}/ture-og-forbrug",
                "user-agent": USER_AGENT,
            }
        )
        self._apply_auth_header()

    def _apply_auth_header(self) -> None:
        self.session.headers["authorization"] = f"Bearer {self.oauth_state.access_token}"

    def refresh_access_token(self) -> None:
        self.oauth_state = self.oauth_manager.refresh_or_login(self.oauth_state)
        self.cache_namespace = self._cache_namespace(self.oauth_state)
        self._apply_auth_header()

    def _cache_namespace(self, state: OAuthState) -> str:
        for token in (state.id_token, state.access_token):
            if not token:
                continue
            try:
                payload = decode_jwt_payload(token)
            except Exception:
                continue
            for claim in ("sub", "email", "name"):
                value = payload.get(claim)
                if isinstance(value, str) and value:
                    return hashlib.sha256(value.encode("utf-8")).hexdigest()
        return hashlib.sha256(state.access_token.encode("utf-8")).hexdigest()

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Send an authenticated API request and retry once after refreshing auth."""
        cacheable = self.use_cache and method.upper() == "GET"
        if cacheable:
            cached_payload = self.cache.get(method, path, kwargs, self.cache_namespace)
            if cached_payload is not None:
                return cached_payload
        if self.oauth_state.is_expiring:
            self.refresh_access_token()
        response = self.session.request(method, f"{API_BASE_URL}{path}", timeout=30, **kwargs)
        if response.status_code in {401, 403}:
            self.refresh_access_token()
            response = self.session.request(method, f"{API_BASE_URL}{path}", timeout=30, **kwargs)
        if response.status_code >= 400:
            raise BrobizzError(f"{method} {path} failed with HTTP {response.status_code}")
        payload = response.json()
        if cacheable:
            self.cache.set(method, path, kwargs, payload, self.cache_namespace)
        return payload

    def get_current_person(self) -> dict[str, Any]:
        return self.request("GET", "/getCurrentPerson")

    def get_account(self, account_id: str) -> dict[str, Any]:
        return self.request("GET", f"/accounts/{account_id}")

    def get_transactions_page(
        self,
        account_id: str,
        page_number: int = 1,
        search_string: str | None = None,
        include_standalone_payments: bool | None = None,
        include_payment_vouchers: bool | None = None,
        include_draft: bool | None = None,
    ) -> dict[str, Any]:
        params: dict[str, str | int] = {"PageNumber": page_number}
        if search_string is not None:
            params["SearchString"] = search_string
        if include_standalone_payments is not None:
            params["IncludeStandalonePayments"] = str(include_standalone_payments).lower()
        if include_payment_vouchers is not None:
            params["IncludePaymentVouchers"] = str(include_payment_vouchers).lower()
        if include_draft is not None:
            params["IncludeDraft"] = str(include_draft).lower()
        return self.request("GET", f"/accounts/{account_id}/transactions", params=params)

    def get_all_transactions(
        self,
        account_id: str | None = None,
        search_string: str | None = None,
        include_payment_records: bool = False,
    ) -> dict[str, Any]:
        if account_id is None:
            person = self.get_current_person()
            account_id = resolve_account_id(person)
        include_value = True if include_payment_records else None
        first_page = self.get_transactions_page(
            account_id=account_id,
            page_number=1,
            search_string=search_string,
            include_standalone_payments=include_value,
            include_payment_vouchers=include_value,
            include_draft=include_value,
        )
        items = list(first_page.get("paginatedItems", []))
        page_size = int(first_page.get("pageSize") or len(items) or 20)
        total_count = int(first_page.get("filteredCount") or first_page.get("totalCount") or len(items))
        total_pages = int(first_page.get("totalPages") or 0)
        if total_pages <= 0 and total_count > page_size:
            total_pages = math.ceil(total_count / page_size)
        for page_number in range(2, total_pages + 1):
            page = self.get_transactions_page(
                account_id=account_id,
                page_number=page_number,
                search_string=search_string,
                include_standalone_payments=include_value,
                include_payment_vouchers=include_value,
                include_draft=include_value,
            )
            page_items = page.get("paginatedItems", [])
            if not page_items:
                break
            items.extend(page_items)
        return {
            "accountId": account_id,
            "totalCount": total_count,
            "returnedCount": len(items),
            "transactions": items,
        }
