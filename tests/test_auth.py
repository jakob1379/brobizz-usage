from __future__ import annotations

import base64
import json
import stat
import sys
import time
from typing import Any

import pytest

from brobizz_usage._runtime import prefer_virtualenv_site_packages
from brobizz_usage.auth import (
    BrowserLoginCredentials,
    BrowserOAuthLogin,
    BrobizzAuthError,
    OAuthState,
    OtpChannel,
    TokenStore,
    token_expiry,
)


def jwt_with_payload(payload: dict[str, object]) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii").rstrip("=")
    return f"header.{encoded}.signature"


def test_token_expiry_prefers_jwt_exp() -> None:
    token = jwt_with_payload({"exp": 1_900_000_000})

    assert token_expiry(token, expires_in=10) == 1_900_000_000


def test_token_expiry_falls_back_to_expires_in() -> None:
    before = int(time.time())

    expires_at = token_expiry("not-a-jwt", expires_in=42)

    assert before + 42 <= expires_at <= int(time.time()) + 42


def test_token_store_writes_user_only_file(tmp_path) -> None:
    token_path = tmp_path / "token.json"
    store = TokenStore(token_path)
    state = OAuthState(
        access_token="access",
        refresh_token="refresh",
        id_token=None,
        client_id="client",
        expires_at=1_900_000_000,
    )

    store.save(state)

    assert store.load() == state
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600


def test_prefer_virtualenv_site_packages_moves_venv_ahead_of_pythonpath(monkeypatch) -> None:
    monkeypatch.setattr(sys, "prefix", "/tmp/project/.venv")
    monkeypatch.setattr(sys, "base_prefix", "/usr")
    monkeypatch.setattr(
        "sysconfig.get_paths",
        lambda: {
            "purelib": "/tmp/project/.venv/lib/python3.14/site-packages",
            "platlib": "/tmp/project/.venv/lib/python3.14/site-packages",
        },
    )
    monkeypatch.setattr(
        sys,
        "path",
        [
            "/tmp/project/.venv/bin",
            "/nix/store/python3.13-playwright/site-packages",
            "/tmp/project/.venv/lib/python3.14/site-packages",
            "/tmp/project/src",
        ],
    )

    prefer_virtualenv_site_packages()

    assert sys.path[:3] == [
        "/tmp/project/.venv/bin",
        "/tmp/project/.venv/lib/python3.14/site-packages",
        "/nix/store/python3.13-playwright/site-packages",
    ]


class FakeLocator:
    def __init__(self, page: "FakePage", role: str, name: str) -> None:
        self.page = page
        self.role = role
        self.name = name

    def click(self, **kwargs: Any) -> None:
        self.page.actions.append(("click", self.role, self.name, kwargs))
        if (self.role, self.name) in self.page.missing:
            raise RuntimeError(f"missing {self.name}")

    def fill(self, value: str, **kwargs: Any) -> None:
        self.page.actions.append(("fill", self.role, self.name, value, kwargs))


class FakePage:
    def __init__(self, missing: set[tuple[str, str]] | None = None) -> None:
        self.actions: list[tuple[Any, ...]] = []
        self.missing = missing or set()

    def get_by_role(self, role: str, name: str, **kwargs: Any) -> FakeLocator:
        return FakeLocator(self, role, name)


def test_prepare_otp_delivery_selects_sms_channel() -> None:
    page = FakePage()

    BrowserOAuthLogin()._prepare_otp_delivery(page, OtpChannel.SMS)

    assert ("click", "button", "Send a new one-time code", {"timeout": 10000}) in page.actions
    assert ("click", "button", "Send a one-time code via SMS", {"timeout": 5000}) in page.actions
    next_clicks = [action for action in page.actions if action[:3] == ("click", "button", "Next")]
    assert len(next_clicks) == 2


def test_run_step_reports_progress_and_step_failure() -> None:
    messages: list[str] = []
    login = BrowserOAuthLogin(progress=messages.append)

    with pytest.raises(BrobizzAuthError, match="Finding login form failed"):
        login._run_step("Finding login form", lambda: (_ for _ in ()).throw(RuntimeError("missing")))

    assert messages == ["Finding login form"]


def test_credential_login_prompts_for_channel_then_otp_during_live_flow() -> None:
    page = FakePage()

    def choose_channel() -> OtpChannel:
        page.actions.append(("provider", "channel"))
        return OtpChannel.SMS

    def enter_otp() -> str:
        page.actions.append(("provider", "otp"))
        return "123456"

    BrowserOAuthLogin()._complete_credential_login(
        page,
        BrowserLoginCredentials(
            username="user@example.com",
            password="secret",
            otp_channel_provider=choose_channel,
            otp_provider=enter_otp,
        ),
    )

    assert page.actions.index(("provider", "channel")) > page.actions.index(
        ("click", "button", "Next", {"timeout": 30000})
    )
    assert page.actions.index(("provider", "otp")) > page.actions.index(
        ("click", "button", "Send a one-time code via SMS", {"timeout": 5000})
    )
    assert ("fill", "textbox", "One-time password digit 6", "6", {"timeout": 30000}) in page.actions


def test_prepare_otp_delivery_selects_email_channel() -> None:
    page = FakePage()

    BrowserOAuthLogin()._prepare_otp_delivery(page, OtpChannel.EMAIL)

    assert ("click", "button", "Send a one-time code via email", {"timeout": 5000}) in page.actions


def test_prepare_otp_delivery_raises_when_channel_is_missing() -> None:
    page = FakePage(
        {
            ("button", "Send a one-time code via email"),
            ("button", "Send a one-time code via Email"),
            ("button", "Send a one-time code via e-mail"),
            ("button", "Send a one-time code via E-mail"),
        }
    )

    with pytest.raises(BrobizzAuthError, match="email"):
        BrowserOAuthLogin()._prepare_otp_delivery(page, OtpChannel.EMAIL)


def test_fill_otp_code_enters_one_digit_per_field() -> None:
    page = FakePage()

    BrowserOAuthLogin()._fill_otp_code(page, "123 456")

    fills = [action for action in page.actions if action[0] == "fill"]
    assert [(action[2], action[3]) for action in fills] == [
        ("One-time password digit 1", "1"),
        ("One-time password digit 2", "2"),
        ("One-time password digit 3", "3"),
        ("One-time password digit 4", "4"),
        ("One-time password digit 5", "5"),
        ("One-time password digit 6", "6"),
    ]


def test_fill_otp_code_rejects_non_six_digit_values() -> None:
    with pytest.raises(BrobizzAuthError, match="6 digits"):
        BrowserOAuthLogin()._fill_otp_code(FakePage(), "12345")
