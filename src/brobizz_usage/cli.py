from __future__ import annotations

import json
import re
import sys
from typing import Annotated, Any, Callable, TypeVar

from brobizz_usage._runtime import prefer_virtualenv_site_packages

prefer_virtualenv_site_packages()

import typer

from brobizz_usage.auth import BrowserLoginCredentials, BrowserOAuthLogin, OAuthManager, OtpChannel
from brobizz_usage.cache import DEFAULT_CACHE_TTL_SECONDS, DiskResponseCache
from brobizz_usage.client import BrobizzClient, resolve_account_id
from brobizz_usage.errors import BrobizzError

T = TypeVar("T")

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
auth_app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
app.add_typer(auth_app, name="auth")


DEFAULT_JSON_INDENT = 2


def json_stdout(data: Any) -> None:
    json.dump(data, sys.stdout, ensure_ascii=False, indent=DEFAULT_JSON_INDENT)
    sys.stdout.write("\n")


def run_command(action: Callable[[], T]) -> T:
    try:
        return action()
    except BrobizzError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc


@app.callback()
def app_options(
    ctx: typer.Context,
    force_login: Annotated[
        bool,
        typer.Option("--force-login", help="Ignore saved tokens and open browser login first."),
    ] = False,
    no_cache: Annotated[
        bool,
        typer.Option("--no-cache", help="Bypass the one-hour on-disk API response cache."),
    ] = False,
    cache_ttl: Annotated[
        int,
        typer.Option("--cache-ttl", help="Seconds to keep successful GET API responses in the on-disk cache."),
    ] = DEFAULT_CACHE_TTL_SECONDS,
) -> None:
    """Brobizz usage and account JSON commands."""
    ctx.obj = {"force_login": force_login, "no_cache": no_cache, "cache_ttl": cache_ttl}


def should_force_login(ctx: typer.Context) -> bool:
    return bool((ctx.obj or {}).get("force_login", False))


def create_client(ctx: typer.Context) -> BrobizzClient:
    cache_ttl = int((ctx.obj or {}).get("cache_ttl", DEFAULT_CACHE_TTL_SECONDS))
    if cache_ttl <= 0:
        raise BrobizzError("--cache-ttl must be greater than 0")
    return BrobizzClient(
        force_login=should_force_login(ctx),
        use_cache=not bool((ctx.obj or {}).get("no_cache", False)),
        cache=DiskResponseCache(ttl_seconds=cache_ttl),
    )


def read_stdin_secret(name: str) -> str:
    value = sys.stdin.read().strip()
    if not value:
        raise BrobizzError(f"{name} read from stdin was empty")
    return value


def prompt_otp_channel() -> OtpChannel:
    typer.echo("One-time code delivery channel:")
    typer.echo("  1. SMS")
    typer.echo("  2. Email")
    value = typer.prompt("Choose channel", default="1").strip().lower()
    if value in {"1", "sms"}:
        return OtpChannel.SMS
    if value in {"2", "email", "mail"}:
        return OtpChannel.EMAIL
    raise BrobizzError("Choose OTP channel 1/sms or 2/email")


def prompt_otp_code() -> str:
    while True:
        value = typer.prompt("One-time code")
        normalized_value = re.sub(r"\s+", "", value)
        if normalized_value.isdigit() and len(normalized_value) == 6:
            return normalized_value
        typer.echo("One-time code must contain exactly 6 digits. Try again.", err=True)


def resolve_login_credentials(
    username: str | None,
    password: str | None,
    password_stdin: bool,
    otp_channel: OtpChannel | None,
) -> BrowserLoginCredentials | None:
    if password is not None and password_stdin:
        raise BrobizzError("--password and --password-stdin are mutually exclusive")
    if password_stdin and otp_channel is None:
        raise BrobizzError("--otp-channel is required when --password-stdin is used")
    if username is None:
        if password is not None or password_stdin or otp_channel is not None:
            raise BrobizzError("--username is required for automated credential login")
        return None

    resolved_password = password
    if password_stdin:
        resolved_password = read_stdin_secret("Password")
    if resolved_password is None:
        resolved_password = typer.prompt("Password", hide_input=True)

    otp_channel_provider = None if otp_channel is not None else prompt_otp_channel
    otp_provider = prompt_otp_code
    return BrowserLoginCredentials(
        username=username,
        password=resolved_password,
        otp_channel=otp_channel,
        otp_channel_provider=otp_channel_provider,
        otp_provider=otp_provider,
    )


def resolve_browser_login(headless: bool, headed: bool, credentials: BrowserLoginCredentials | None) -> BrowserOAuthLogin:
    if headless and headed:
        raise BrobizzError("--headless and --headed are mutually exclusive")
    if headless and credentials is None:
        raise BrobizzError("--headless requires --username for automated credential login")
    return BrowserOAuthLogin(
        headless=credentials is not None and not headed,
        progress=lambda message: typer.echo(message, err=True),
    )


def get_account_profile(client: BrobizzClient, account_id: str | None = None) -> dict[str, Any]:
    person = client.get_current_person()
    resolved_account_id = account_id or resolve_account_id(person)
    return {
        "person": person,
        "account": client.get_account(resolved_account_id),
    }


@app.command()
def trips(
    ctx: typer.Context,
    account_id: Annotated[
        str | None,
        typer.Option("--account-id", help="Brobizz account id. Defaults to the current usable account."),
    ] = None,
    search: Annotated[str | None, typer.Option("--search", help="Optional transaction search string.")] = None,
    include_payment_records: Annotated[
        bool,
        typer.Option(
            "--include-payment-records",
            help="Include standalone payments, payment vouchers, and drafts.",
        ),
    ] = False,
) -> None:
    """Output all trips and usage records as JSON."""

    def action() -> None:
        client = create_client(ctx)
        result = client.get_all_transactions(
            account_id=account_id,
            search_string=search,
            include_payment_records=include_payment_records,
        )
        json_stdout(result)

    run_command(action)


@app.command()
def account(
    ctx: typer.Context,
    account_id: Annotated[
        str | None,
        typer.Option("--account-id", help="Brobizz account id. Defaults to the current usable account."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output account details as JSON. This is the current default."),
    ] = False,
) -> None:
    """Output combined person and account details as JSON."""
    del json_output

    def action() -> None:
        client = create_client(ctx)
        json_stdout(get_account_profile(client, account_id))

    run_command(action)


@auth_app.command("login")
def auth_login(
    username: Annotated[
        str | None,
        typer.Option(
            "--username",
            help="Brobizz/Auth0 account email. Enables automated Playwright login, headless by default.",
        ),
    ] = None,
    password: Annotated[
        str | None,
        typer.Option("--password", help="Password for automated login. May be visible in shell history/process lists."),
    ] = None,
    password_stdin: Annotated[
        bool,
        typer.Option("--password-stdin", help="Read the automated-login password from stdin."),
    ] = False,
    otp_channel: Annotated[
        OtpChannel | None,
        typer.Option("--otp-channel", help="Select the one-time-code delivery channel during automated login."),
    ] = None,
    headless: Annotated[
        bool,
        typer.Option(
            "--headless",
            help="Explicitly run automated credential login without showing Chromium. Requires --username.",
        ),
    ] = False,
    headed: Annotated[
        bool,
        typer.Option(
            "--headed",
            help="Show Chromium during automated credential login for debugging. Manual login is always headed.",
        ),
    ] = False,
) -> None:
    """Force browser login and save new tokens."""

    def action() -> None:
        credentials = resolve_login_credentials(username, password, password_stdin, otp_channel)
        browser_login = resolve_browser_login(headless, headed, credentials)
        OAuthManager(browser_login=browser_login).get_valid_state(force_login=True, credentials=credentials)
        typer.echo("Login complete")

    run_command(action)


@auth_app.command("logout")
def auth_logout() -> None:
    """Remove saved token state."""
    OAuthManager().logout()
    typer.echo("Logged out")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
