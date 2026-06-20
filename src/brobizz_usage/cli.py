from __future__ import annotations

import json
import re
import sys
from typing import Annotated, Any, Callable, TypeVar

from brobizz_usage._runtime import prefer_virtualenv_site_packages

prefer_virtualenv_site_packages()

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from brobizz_usage.auth import BrowserLoginCredentials, BrowserOAuthLogin, OAuthManager, OtpChannel
from brobizz_usage.cache import DEFAULT_CACHE_TTL_SECONDS, DiskResponseCache
from brobizz_usage.client import BrobizzClient, resolve_account_id
from brobizz_usage.errors import BrobizzError

T = TypeVar("T")

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
auth_app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
app.add_typer(auth_app, name="auth")


DEFAULT_JSON_INDENT = 2
DEFAULT_TRIP_CARD_COUNT = 5


def json_stdout(data: Any) -> None:
    json.dump(data, sys.stdout, ensure_ascii=False, indent=DEFAULT_JSON_INDENT)
    sys.stdout.write("\n")


def first_text_value(data: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


def format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def format_money(transaction: dict[str, Any]) -> str | None:
    amount_key = next(
        (
            key
            for key in (
                "amount",
                "totalAmount",
                "price",
                "chargedAmount",
                "transactionAmount",
            )
            if transaction.get(key) is not None
        ),
        None,
    )
    if amount_key is None:
        return None
    currency = first_text_value(transaction, ("currency", "currencyCode", "amountCurrency"))
    amount = format_scalar(transaction[amount_key])
    return f"{amount} {currency}" if currency else amount


def transaction_date(transaction: dict[str, Any]) -> str | None:
    return first_text_value(
        transaction,
        (
            "transactionDate",
            "date",
            "usageDate",
            "createdDate",
            "createdAt",
            "startDate",
        ),
    )


def transaction_license_plate(transaction: dict[str, Any]) -> str | None:
    return first_text_value(
        transaction,
        (
            "licenseplate",
            "licensePlate",
            "licensePlateNumber",
            "numberPlate",
            "plateNumber",
            "registrationNumber",
        ),
    )


def transaction_station_name(transaction: dict[str, Any]) -> str | None:
    return first_text_value(
        transaction,
        (
            "stationName",
            "station",
            "locationName",
            "merchantName",
        ),
    )


def transaction_invoice_status(transaction: dict[str, Any]) -> str | None:
    return first_text_value(transaction, ("invoiceStatus", "paymentStatus"))


def is_paid_invoice(transaction: dict[str, Any]) -> bool:
    status = transaction_invoice_status(transaction)
    if status is None:
        return False
    normalized_status = re.sub(r"[\s_-]+", "", status).lower()
    return normalized_status in {"paid", "settled", "complete", "completed"}


def transaction_card_styles(transaction: dict[str, Any]) -> tuple[str, str]:
    if is_paid_invoice(transaction):
        return ("steel_blue", "white on steel_blue")
    return ("deep_pink4", "white on deep_pink4")


def transaction_compact_rows(transaction: dict[str, Any]) -> list[tuple[str, str]]:
    rows = [
        ("date", transaction_date(transaction)),
        ("amount", format_money(transaction)),
        ("licenseplate", transaction_license_plate(transaction)),
        ("stationName", transaction_station_name(transaction)),
    ]
    return [(label, value) for label, value in rows if value is not None]


def transaction_extra_scalar_rows(transaction: dict[str, Any]) -> list[tuple[str, str]]:
    skipped_keys = {
        "amount",
        "amountCurrency",
        "chargedAmount",
        "currency",
        "currencyCode",
        "date",
        "createdAt",
        "createdDate",
        "licenseplate",
        "licensePlate",
        "licensePlateNumber",
        "merchantName",
        "numberPlate",
        "paymentStatus",
        "plateNumber",
        "price",
        "registrationNumber",
        "station",
        "stationName",
        "startDate",
        "totalAmount",
        "transactionAmount",
        "transactionDate",
        "usageDate",
    }
    rows = []
    for key, value in transaction.items():
        if key in skipped_keys or value in (None, ""):
            continue
        if isinstance(value, list | dict):
            continue
        rows.append((key, format_scalar(value)))
    return rows


def print_trips_cards(result: dict[str, Any], number: int = DEFAULT_TRIP_CARD_COUNT, full: bool = False) -> None:
    console = Console()
    transactions = result.get("transactions", [])
    if not isinstance(transactions, list):
        transactions = []

    account_id = result.get("accountId", "unknown")
    returned_count = int(result.get("returnedCount") or len(transactions))
    total_count = result.get("totalCount", returned_count)
    visible_transactions = transactions[:number]
    console.print(Text(f"Trips for account {account_id}", style="bold"))
    console.print(f"Showing {len(visible_transactions)} latest of {returned_count} returned ({total_count} total)")

    if not transactions:
        console.print(Panel("No trips found", title="Trips", border_style="cyan"))
        return

    for index, item in enumerate(visible_transactions, start=1):
        if not isinstance(item, dict):
            item = {"value": item}
        border_style, title_style = transaction_card_styles(item)
        details = Table.grid(padding=(0, 1))
        details.add_column(style="dim")
        details.add_column()
        for key, value in transaction_compact_rows(item):
            details.add_row(key, value)
        if full:
            for key, value in transaction_extra_scalar_rows(item):
                details.add_row(key, value)
        console.print(
            Panel(
                details,
                title=Text(f" trip {index} ", style=title_style),
                title_align="left",
                border_style=border_style,
                style=border_style,
            )
        )


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
    value = typer.prompt("One-time code delivery channel (SMS|email)", default="SMS").strip().lower()
    if value == "sms":
        return OtpChannel.SMS
    if value == "email":
        return OtpChannel.EMAIL
    raise BrobizzError("Choose OTP channel SMS or email")


def prompt_otp_code() -> str:
    while True:
        value = typer.prompt("One-time code")
        normalized_value = re.sub(r"\s+", "", value)
        if normalized_value.isdigit() and len(normalized_value) == 6:
            return normalized_value
        typer.echo("One-time code must contain exactly 6 digits. Try again.", err=True)


def prompt_required_text(prompt: str) -> str:
    value = typer.prompt(prompt).strip()
    if not value:
        raise BrobizzError(f"{prompt} is required")
    return value


def resolve_login_credentials(
    username: str | None,
    password: str | None,
    password_stdin: bool,
    otp_channel: OtpChannel | None,
    prompt_missing: bool = False,
) -> BrowserLoginCredentials | None:
    if password is not None and password_stdin:
        raise BrobizzError("--password and --password-stdin are mutually exclusive")
    if password_stdin and otp_channel is None:
        raise BrobizzError("--otp-channel is required when --password-stdin is used")
    if username is None:
        if prompt_missing and not password_stdin:
            username = prompt_required_text("Email address")
        elif prompt_missing:
            raise BrobizzError("--username is required when --password-stdin is used")
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


def resolve_browser_login(headless: bool, credentials: BrowserLoginCredentials | None) -> BrowserOAuthLogin:
    if headless and credentials is None:
        raise BrobizzError("headless login requires credential prompts or options")
    return BrowserOAuthLogin(
        headless=credentials is not None and headless,
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
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output trips and usage records as JSON."),
    ] = False,
    full: Annotated[
        bool,
        typer.Option("--full", help="Show all scalar fields on each visible card."),
    ] = False,
    number: Annotated[
        int,
        typer.Option("--number", "-n", help="Number of latest trip cards to show."),
    ] = DEFAULT_TRIP_CARD_COUNT,
) -> None:
    """Output all trips and usage records."""

    def action() -> None:
        if not json_output and number <= 0:
            raise BrobizzError("--number must be greater than 0")
        client = create_client(ctx)
        result = client.get_all_transactions(
            account_id=account_id,
            search_string=search,
            include_payment_records=include_payment_records,
        )
        if json_output:
            json_stdout(result)
        else:
            print_trips_cards(result, number=number, full=full)

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
            help="Brobizz/Auth0 account email. Prefills the headless CLI login prompt.",
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
            "--headless/--browser-login",
            help="Use CLI credential prompts with headless Chromium, or open the headed browser login.",
        ),
    ] = True,
) -> None:
    """Log in and save new tokens."""

    def action() -> None:
        credentials = resolve_login_credentials(
            username,
            password,
            password_stdin,
            otp_channel,
            prompt_missing=headless,
        )
        browser_login = resolve_browser_login(headless, credentials)
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
