from __future__ import annotations

import json

from typer.testing import CliRunner

from brobizz_usage import cli


class FakeClient:
    instances: list["FakeClient"] = []

    def __init__(self, force_login: bool = False, **kwargs: object) -> None:
        self.force_login = force_login
        self.kwargs = kwargs
        self.instances.append(self)

    def get_all_transactions(
        self,
        account_id: str | None = None,
        search_string: str | None = None,
        include_payment_records: bool = False,
    ) -> dict[str, object]:
        return {
            "accountId": account_id or "resolved",
            "search": search_string,
            "includePaymentRecords": include_payment_records,
            "returnedCount": 6,
            "totalCount": 12,
            "transactions": [
                {
                    "id": 1,
                    "transactionDate": "2026-06-20",
                    "amount": 125,
                    "currency": "DKK",
                    "licenseplate": "AB12345",
                    "stationName": "Storebaelt",
                    "invoiceStatus": "Paid",
                    "receiptNumber": "R-1",
                },
                {
                    "id": 2,
                    "transactionDate": "2026-06-19",
                    "amount": 54,
                    "currency": "DKK",
                    "licenseplate": "CD67890",
                    "stationName": "Oresund",
                    "invoiceStatus": "Unpaid",
                    "receiptNumber": "R-2",
                },
                {"id": 3},
                {"id": 4},
                {"id": 5},
                {"id": 6},
            ],
        }

    def get_current_person(self) -> dict[str, object]:
        return {
            "currentAccountId": "account",
            "name": "Person",
        }

    def get_account(self, account_id: str) -> dict[str, object]:
        return {"accountId": account_id, "name": "Account"}


class FakeOAuthManager:
    instances: list["FakeOAuthManager"] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.calls: list[dict[str, object]] = []
        self.instances.append(self)

    def get_valid_state(self, force_login: bool = False, credentials: object | None = None) -> None:
        call: dict[str, object] = {"force_login": force_login, "credentials": credentials}
        if credentials is not None and getattr(credentials, "otp_channel_provider", None) is not None:
            call["otp_channel_from_provider"] = credentials.otp_channel_provider()
        self.calls.append(call)

    def logout(self) -> None:
        self.calls.append({"logout": True})


def test_trips_command_uses_global_force_login(monkeypatch) -> None:
    FakeClient.instances = []
    monkeypatch.setattr(cli, "BrobizzClient", FakeClient)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "--force-login",
            "trips",
            "--account-id",
            "account",
            "--search",
            "Storebaelt",
            "--include-payment-records",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "accountId": "account",
        "search": "Storebaelt",
        "includePaymentRecords": True,
        "returnedCount": 6,
        "totalCount": 12,
        "transactions": [
            {
                "id": 1,
                "transactionDate": "2026-06-20",
                "amount": 125,
                "currency": "DKK",
                "licenseplate": "AB12345",
                "stationName": "Storebaelt",
                "invoiceStatus": "Paid",
                "receiptNumber": "R-1",
            },
            {
                "id": 2,
                "transactionDate": "2026-06-19",
                "amount": 54,
                "currency": "DKK",
                "licenseplate": "CD67890",
                "stationName": "Oresund",
                "invoiceStatus": "Unpaid",
                "receiptNumber": "R-2",
            },
            {"id": 3},
            {"id": 4},
            {"id": 5},
            {"id": 6},
        ],
    }
    assert FakeClient.instances[0].force_login is True
    assert FakeClient.instances[0].kwargs["use_cache"] is True
    assert "\n  " in result.stdout


def test_trips_command_defaults_to_rich_cards(monkeypatch) -> None:
    FakeClient.instances = []
    monkeypatch.setattr(cli, "BrobizzClient", FakeClient)
    runner = CliRunner()

    result = runner.invoke(cli.app, ["trips"])

    assert result.exit_code == 0
    assert "Trips for account resolved" in result.stdout
    assert "Showing 5 latest of 6 returned (12 total)" in result.stdout
    assert "trip 1" in result.stdout
    assert "trip 5" in result.stdout
    assert "trip 6" not in result.stdout
    assert "2026-06-20" in result.stdout
    assert "125 DKK" in result.stdout
    assert "AB12345" in result.stdout
    assert "Storebaelt" in result.stdout
    assert "Paid" not in result.stdout
    assert "R-1" not in result.stdout
    assert "id" not in result.stdout
    assert result.stdout.lstrip()[0] != "{"


def test_trips_command_accepts_number_and_full_options(monkeypatch) -> None:
    FakeClient.instances = []
    monkeypatch.setattr(cli, "BrobizzClient", FakeClient)
    runner = CliRunner()

    result = runner.invoke(cli.app, ["trips", "-n", "2", "--full"])

    assert result.exit_code == 0
    assert "Showing 2 latest of 6 returned (12 total)" in result.stdout
    assert "trip 1" in result.stdout
    assert "trip 2" in result.stdout
    assert "trip 3" not in result.stdout
    assert "id" in result.stdout
    assert "receiptNumber" in result.stdout


def test_trips_command_rejects_non_positive_card_count(monkeypatch) -> None:
    FakeClient.instances = []
    monkeypatch.setattr(cli, "BrobizzClient", FakeClient)
    runner = CliRunner()

    result = runner.invoke(cli.app, ["trips", "--number", "0"])

    assert result.exit_code == 1
    assert "--number must be greater than 0" in result.stderr
    assert FakeClient.instances == []


def test_trips_json_ignores_card_count(monkeypatch) -> None:
    FakeClient.instances = []
    monkeypatch.setattr(cli, "BrobizzClient", FakeClient)
    runner = CliRunner()

    result = runner.invoke(cli.app, ["trips", "--json", "--number", "0"])

    assert result.exit_code == 0
    assert len(json.loads(result.stdout)["transactions"]) == 6


def test_api_commands_can_disable_cache(monkeypatch) -> None:
    FakeClient.instances = []
    monkeypatch.setattr(cli, "BrobizzClient", FakeClient)
    runner = CliRunner()

    result = runner.invoke(cli.app, ["--no-cache", "account"])

    assert result.exit_code == 0
    assert FakeClient.instances[0].kwargs["use_cache"] is False


def test_api_commands_validate_cache_ttl(monkeypatch) -> None:
    FakeClient.instances = []
    monkeypatch.setattr(cli, "BrobizzClient", FakeClient)
    runner = CliRunner()

    result = runner.invoke(cli.app, ["--cache-ttl", "0", "account"])

    assert result.exit_code == 1
    assert "--cache-ttl must be greater than 0" in result.stderr
    assert FakeClient.instances == []


def test_account_command_outputs_combined_person_and_account_json(monkeypatch) -> None:
    monkeypatch.setattr(cli, "BrobizzClient", FakeClient)
    runner = CliRunner()

    account_result = runner.invoke(cli.app, ["account"])

    assert account_result.exit_code == 0
    assert json.loads(account_result.stdout) == {
        "person": {"currentAccountId": "account", "name": "Person"},
        "account": {"accountId": "account", "name": "Account"},
    }


def test_person_command_is_not_registered() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.app, ["person"])

    assert result.exit_code != 0


def test_account_accepts_explicit_json_option(monkeypatch) -> None:
    monkeypatch.setattr(cli, "BrobizzClient", FakeClient)
    runner = CliRunner()

    result = runner.invoke(cli.app, ["account", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "person": {"currentAccountId": "account", "name": "Person"},
        "account": {"accountId": "account", "name": "Account"},
    }


def test_indent_and_command_local_force_login_are_not_cli_options() -> None:
    runner = CliRunner()

    indent_result = runner.invoke(cli.app, ["trips", "--indent", "0"])
    command_force_login_result = runner.invoke(cli.app, ["trips", "--force-login"])

    assert indent_result.exit_code != 0
    assert command_force_login_result.exit_code != 0


def test_auth_login_without_credentials_keeps_manual_flow(monkeypatch) -> None:
    FakeOAuthManager.instances = []
    monkeypatch.setattr(cli, "OAuthManager", FakeOAuthManager)
    runner = CliRunner()

    result = runner.invoke(cli.app, ["auth", "login"])

    assert result.exit_code == 0
    assert result.stdout == "Login complete\n"
    call = FakeOAuthManager.instances[0].calls[0]
    assert call["force_login"] is True
    assert call["credentials"] is None
    assert FakeOAuthManager.instances[0].kwargs["browser_login"].headless is False


def test_auth_login_accepts_password_option(monkeypatch) -> None:
    FakeOAuthManager.instances = []
    monkeypatch.setattr(cli, "OAuthManager", FakeOAuthManager)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["auth", "login", "--username", "user@example.com", "--password", "secret", "--otp-channel", "sms"],
    )

    assert result.exit_code == 0
    credentials = FakeOAuthManager.instances[0].calls[0]["credentials"]
    assert credentials is not None
    assert credentials.username == "user@example.com"
    assert credentials.password == "secret"
    assert credentials.otp_channel == cli.OtpChannel.SMS
    assert credentials.otp_provider is not None
    assert FakeOAuthManager.instances[0].kwargs["browser_login"].headless is True
    assert FakeOAuthManager.instances[0].kwargs["browser_login"].progress is not None


def test_auth_login_accepts_password_stdin(monkeypatch) -> None:
    FakeOAuthManager.instances = []
    monkeypatch.setattr(cli, "OAuthManager", FakeOAuthManager)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["auth", "login", "--username", "user@example.com", "--password-stdin", "--otp-channel", "email"],
        input="secret\n",
    )

    assert result.exit_code == 0
    credentials = FakeOAuthManager.instances[0].calls[0]["credentials"]
    assert credentials is not None
    assert credentials.password == "secret"
    assert credentials.otp_channel == cli.OtpChannel.EMAIL
    assert FakeOAuthManager.instances[0].kwargs["browser_login"].headless is True


def test_auth_login_prompts_for_otp_channel_when_interactive(monkeypatch) -> None:
    FakeOAuthManager.instances = []
    monkeypatch.setattr(cli, "OAuthManager", FakeOAuthManager)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["auth", "login", "--username", "user@example.com", "--password", "secret"],
        input="2\n",
    )

    assert result.exit_code == 0
    call = FakeOAuthManager.instances[0].calls[0]
    credentials = call["credentials"]
    assert credentials is not None
    assert credentials.otp_channel is None
    assert call["otp_channel_from_provider"] == cli.OtpChannel.EMAIL
    assert "One-time code delivery channel" in result.stdout


def test_otp_provider_retries_until_code_has_six_digits(monkeypatch) -> None:
    responses = iter(["6569551", "656955"])
    monkeypatch.setattr(cli.typer, "prompt", lambda prompt: next(responses))

    assert cli.prompt_otp_code() == "656955"


def test_auth_login_can_force_headed_automated_login(monkeypatch) -> None:
    FakeOAuthManager.instances = []
    monkeypatch.setattr(cli, "OAuthManager", FakeOAuthManager)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["auth", "login", "--username", "user@example.com", "--password", "secret", "--otp-channel", "sms", "--headed"],
    )

    assert result.exit_code == 0
    assert FakeOAuthManager.instances[0].kwargs["browser_login"].headless is False


def test_auth_login_rejects_conflicting_password_sources(monkeypatch) -> None:
    FakeOAuthManager.instances = []
    monkeypatch.setattr(cli, "OAuthManager", FakeOAuthManager)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["auth", "login", "--username", "user@example.com", "--password", "secret", "--password-stdin"],
    )

    assert result.exit_code == 1
    assert "mutually exclusive" in result.stderr
    assert FakeOAuthManager.instances == []


def test_auth_login_rejects_headless_manual_login(monkeypatch) -> None:
    FakeOAuthManager.instances = []
    monkeypatch.setattr(cli, "OAuthManager", FakeOAuthManager)
    runner = CliRunner()

    result = runner.invoke(cli.app, ["auth", "login", "--headless"])

    assert result.exit_code == 1
    assert "--headless requires --username" in result.stderr
    assert FakeOAuthManager.instances == []


def test_auth_login_rejects_conflicting_browser_modes(monkeypatch) -> None:
    FakeOAuthManager.instances = []
    monkeypatch.setattr(cli, "OAuthManager", FakeOAuthManager)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "auth",
            "login",
            "--username",
            "user@example.com",
            "--password",
            "secret",
            "--otp-channel",
            "sms",
            "--headless",
            "--headed",
        ],
    )

    assert result.exit_code == 1
    assert "--headless and --headed are mutually exclusive" in result.stderr
    assert FakeOAuthManager.instances == []


def test_auth_login_requires_otp_channel_with_password_stdin(monkeypatch) -> None:
    FakeOAuthManager.instances = []
    monkeypatch.setattr(cli, "OAuthManager", FakeOAuthManager)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["auth", "login", "--username", "user@example.com", "--password-stdin"],
        input="secret\n",
    )

    assert result.exit_code == 1
    assert "--otp-channel is required when --password-stdin is used" in result.stderr
    assert FakeOAuthManager.instances == []
