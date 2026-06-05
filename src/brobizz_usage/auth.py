from __future__ import annotations

import base64
import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse

import httpx
from platformdirs import user_config_path

from brobizz_usage.errors import BrobizzAuthError

AUTH_BASE_URL = "https://auth.brobizz.com"
API_BASE_URL = "https://login.brobizz.com"
PUBLIC_BASE_URL = "https://brobizz.com"
LOGIN_URL = f"{API_BASE_URL}/ture-og-forbrug"
TOKEN_PATH_NAME = "tokens.json"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class OAuthState:
    access_token: str
    refresh_token: str
    id_token: str | None
    client_id: str
    expires_at: int

    @property
    def is_expiring(self) -> bool:
        return self.expires_at <= int(time.time()) + 120


class OtpChannel(StrEnum):
    EMAIL = "email"
    SMS = "sms"


@dataclass(frozen=True)
class BrowserLoginCredentials:
    username: str
    password: str
    otp_channel: OtpChannel | None = None
    otp_channel_provider: Callable[[], OtpChannel] | None = None
    otp_provider: Callable[[], str] | None = None


def decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        raise ValueError("Token is not a JWT")
    payload = parts[1]
    payload += "=" * ((4 - len(payload) % 4) % 4)
    return json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))


def token_expiry(access_token: str, expires_in: int | None = None) -> int:
    try:
        exp = decode_jwt_payload(access_token).get("exp")
        if isinstance(exp, int):
            return exp
    except Exception:
        pass
    return int(time.time()) + int(expires_in or 3600)


def parse_form_params(body: str | None) -> dict[str, str]:
    if not body:
        return {}
    return dict(parse_qsl(body, keep_blank_values=True))


def token_endpoint_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.path.endswith("/oauth/token")


class TokenStore:
    """Filesystem-backed OAuth token store with user-only permissions."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or user_config_path("brobizz-usage", "brobizz-usage", ensure_exists=True) / TOKEN_PATH_NAME

    def load(self) -> OAuthState | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return OAuthState(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                id_token=data.get("id_token"),
                client_id=data["client_id"],
                expires_at=int(data["expires_at"]),
            )
        except FileNotFoundError:
            return None
        except Exception:
            self.delete()
            return None

    def save(self, state: OAuthState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(state), indent=2)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.write("\n")
        os.chmod(self.path, 0o600)

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)


class BrowserOAuthLogin:
    """Open a headed browser and capture the OAuth token exchange after login."""

    def __init__(
        self,
        login_url: str = LOGIN_URL,
        timeout_seconds: int = 300,
        headless: bool = False,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self.login_url = login_url
        self.timeout_seconds = timeout_seconds
        self.headless = headless
        self.progress = progress

    def login(self, credentials: BrowserLoginCredentials | None = None) -> OAuthState:
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrobizzAuthError("Playwright is required for browser login") from exc

        captured_state: OAuthState | None = None

        def capture_token_response(response: Any) -> None:
            nonlocal captured_state
            if captured_state is not None:
                return
            request = response.request
            if request.method.upper() != "POST" or not token_endpoint_url(response.url):
                return
            try:
                body = response.json()
            except Exception:
                return
            access_token = body.get("access_token")
            refresh_token = body.get("refresh_token")
            client_id = parse_form_params(request.post_data).get("client_id")
            if not access_token or not refresh_token or not client_id:
                return
            captured_state = OAuthState(
                access_token=access_token,
                refresh_token=refresh_token,
                id_token=body.get("id_token"),
                client_id=client_id,
                expires_at=token_expiry(access_token, body.get("expires_in")),
            )

        try:
            with sync_playwright() as playwright:
                self._emit_progress("Starting Chromium")
                browser = playwright.chromium.launch(headless=self.headless)
                context = browser.new_context()
                page = context.new_page()
                page.on("response", capture_token_response)
                self._open_login_page(page, credentials is not None)
                if credentials is not None:
                    self._complete_credential_login(page, credentials)

                deadline = time.monotonic() + self.timeout_seconds
                while captured_state is None and time.monotonic() < deadline:
                    page.wait_for_timeout(500)

                context.close()
                browser.close()
        except PlaywrightTimeoutError as exc:
            raise BrobizzAuthError("Browser login timed out before the login page loaded") from exc
        except PlaywrightError as exc:
            message = str(exc)
            if "Executable doesn't exist" in message:
                raise BrobizzAuthError(
                    "Playwright could not find a Chromium browser. In the Nix shell, ensure "
                    "PLAYWRIGHT_BROWSERS_PATH is set by running `direnv reload` or `nix develop`. "
                    "Outside Nix, run `playwright install chromium`."
                ) from exc
            raise BrobizzAuthError(f"Browser login failed: {message}") from exc

        if captured_state is None:
            raise BrobizzAuthError("Browser login did not complete before the timeout")
        return captured_state

    def _emit_progress(self, message: str) -> None:
        if self.progress is not None:
            self.progress(message)

    def _run_step(self, description: str, action: Callable[[], None]) -> None:
        self._emit_progress(description)
        try:
            action()
        except BrobizzAuthError:
            raise
        except Exception as exc:
            raise BrobizzAuthError(f"{description} failed: {exc}") from exc

    def _open_login_page(self, page: Any, automated_login: bool) -> None:
        if not automated_login:
            self._run_step(
                "Opening Brobizz self-service login page",
                lambda: page.goto(self.login_url, wait_until="domcontentloaded", timeout=60_000),
            )
            return
        self._run_step(
            "Opening brobizz.com",
            lambda: page.goto(PUBLIC_BASE_URL, wait_until="domcontentloaded", timeout=60_000),
        )
        self._run_step(
            "Clicking Log ind",
            lambda: page.get_by_role("link", name="Log ind", exact=True).click(timeout=30_000),
        )
        self._emit_progress("Waiting for Auth0 login form")
        self._emit_current_url(page)

    def _complete_credential_login(self, page: Any, credentials: BrowserLoginCredentials) -> None:
        self._run_step(
            "Filling email address",
            lambda: self._fill_first_available(
                [
                    lambda: page.get_by_role("textbox", name="Email address"),
                    lambda: page.get_by_label("Email address"),
                    lambda: page.locator('input[name="username"]'),
                    lambda: page.locator('input[name="email"]'),
                    lambda: page.locator('input[type="email"]'),
                    lambda: page.locator('input[autocomplete="username"]'),
                ],
                credentials.username,
            ),
        )
        self._run_step(
            "Filling password",
            lambda: self._fill_first_available(
                [
                    lambda: page.get_by_role("textbox", name="Password"),
                    lambda: page.get_by_label("Password"),
                    lambda: page.locator('input[name="password"]'),
                    lambda: page.locator('input[type="password"]'),
                    lambda: page.locator('input[autocomplete="current-password"]'),
                ],
                credentials.password,
            ),
        )
        self._run_step(
            "Submitting username and password",
            lambda: page.get_by_role("button", name="Next").click(timeout=30_000),
        )

        otp_channel = credentials.otp_channel
        if otp_channel is None and credentials.otp_channel_provider is not None:
            otp_channel = credentials.otp_channel_provider()
        if otp_channel is None:
            return
        if credentials.otp_provider is None:
            raise BrobizzAuthError("OTP prompt is required when an OTP channel is selected")

        self._prepare_otp_delivery(page, otp_channel)
        otp_code = credentials.otp_provider()
        self._fill_otp_code(page, otp_code)
        self._run_step(
            "Submitting one-time code",
            lambda: page.get_by_role("button", name="Next").click(timeout=30_000),
        )
        self._emit_progress("Waiting for OAuth token response")

    def _prepare_otp_delivery(self, page: Any, otp_channel: OtpChannel) -> None:
        if self._click_button_if_available(page, "Send a new one-time code", timeout=10_000):
            self._run_step(
                "Opening one-time-code delivery choices",
                lambda: page.get_by_role("button", name="Next").click(timeout=30_000),
            )

        labels = {
            OtpChannel.EMAIL: [
                "Send a one-time code via email",
                "Send a one-time code via Email",
                "Send a one-time code via e-mail",
                "Send a one-time code via E-mail",
            ],
            OtpChannel.SMS: ["Send a one-time code via SMS"],
        }[otp_channel]
        for label in labels:
            if self._click_button_if_available(page, label, timeout=5_000):
                self._run_step(
                    f"Sending {otp_channel.value} one-time code",
                    lambda: page.get_by_role("button", name="Next").click(timeout=30_000),
                )
                return
        raise BrobizzAuthError(f"Could not find the {otp_channel.value} one-time-code option")

    def _click_button_if_available(self, page: Any, name: str, timeout: int) -> bool:
        try:
            page.get_by_role("button", name=name, exact=True).click(timeout=timeout)
            return True
        except Exception:
            return False

    def _fill_first_available(self, locator_factories: list[Callable[[], Any]], value: str) -> None:
        errors: list[str] = []
        for locator_factory in locator_factories:
            try:
                locator_factory().fill(value, timeout=8_000)
                return
            except Exception as exc:
                errors.append(str(exc).splitlines()[0])
        raise BrobizzAuthError(f"Could not find a usable input field: {'; '.join(errors)}")

    def _emit_current_url(self, page: Any) -> None:
        try:
            self._emit_progress(f"Current browser URL: {page.url}")
        except Exception:
            pass

    def _fill_otp_code(self, page: Any, otp_code: str) -> None:
        normalized_code = re.sub(r"\s+", "", otp_code)
        if not normalized_code.isdigit() or len(normalized_code) != 6:
            raise BrobizzAuthError("OTP code must contain exactly 6 digits")
        self._emit_progress("Filling one-time code")
        for index, digit in enumerate(normalized_code, start=1):
            page.get_by_role("textbox", name=f"One-time password digit {index}").fill(digit, timeout=30_000)


class OAuthManager:
    """Coordinates token storage, refresh, and browser re-authentication."""

    def __init__(
        self,
        store: TokenStore | None = None,
        browser_login: BrowserOAuthLogin | None = None,
        session: httpx.Client | None = None,
    ) -> None:
        self.store = store or TokenStore()
        self.browser_login = browser_login or BrowserOAuthLogin()
        self.session = session or httpx.Client()

    def get_valid_state(
        self,
        force_login: bool = False,
        credentials: BrowserLoginCredentials | None = None,
    ) -> OAuthState:
        state = None if force_login or credentials is not None else self.store.load()
        if state is None:
            return self.login(credentials)
        if state.is_expiring:
            return self.refresh_or_login(state)
        return state

    def login(self, credentials: BrowserLoginCredentials | None = None) -> OAuthState:
        state = self.browser_login.login(credentials)
        self.store.save(state)
        return state

    def logout(self) -> None:
        self.store.delete()

    def refresh_or_login(self, state: OAuthState) -> OAuthState:
        try:
            return self.refresh(state)
        except BrobizzAuthError:
            self.store.delete()
            return self.login()

    def refresh(self, state: OAuthState) -> OAuthState:
        response = self.session.post(
            f"{AUTH_BASE_URL}/oauth/token",
            data={
                "client_id": state.client_id,
                "grant_type": "refresh_token",
                "refresh_token": state.refresh_token,
            },
            headers={
                "accept": "application/json",
                "content-type": "application/x-www-form-urlencoded",
                "origin": API_BASE_URL,
                "referer": f"{API_BASE_URL}/",
                "user-agent": USER_AGENT,
            },
            timeout=30,
        )
        if response.status_code >= 400:
            raise BrobizzAuthError(f"Token refresh failed with HTTP {response.status_code}")
        try:
            token_response = response.json()
            access_token = token_response["access_token"]
        except Exception as exc:
            raise BrobizzAuthError("Token refresh returned an invalid response") from exc
        refreshed = OAuthState(
            access_token=access_token,
            refresh_token=token_response.get("refresh_token", state.refresh_token),
            id_token=token_response.get("id_token", state.id_token),
            client_id=state.client_id,
            expires_at=token_expiry(access_token, token_response.get("expires_in")),
        )
        self.store.save(refreshed)
        return refreshed
