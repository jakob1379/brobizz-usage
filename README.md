# Brobizz Usage

Command-line tool for showing Brobizz trips and account usage.

<p align="center">
  <img src=".github/assets/crossing.svg" width="100%" alt="A car crosses a suspension bridge and passes a toll gantry; the crossing then appears in a terminal running brobizz-usage trips as a pink trip card for an unpaid trip, above a steel blue card for a paid one. Example data.">
</p>

Log in once with your Brobizz account, then read your toll trips and account details from the terminal, as JSON, or from Python.

## Quick Start

From this repository:

```bash
nix develop
uv sync --extra dev
uv run brobizz-usage auth login
uv run brobizz-usage trips
```

That is the normal flow. Login runs in headless Chromium and asks for:

1. Brobizz/Auth0 email
2. Password
3. One-time-code channel: `SMS|email`, default `SMS`
4. The received one-time code

After login, tokens are saved in your user config directory with user-only file permissions and reused automatically. Expired tokens are refreshed for you.

## Install As A Tool

For regular use outside the development shell:

```bash
uv tool install .
uvx playwright install chromium
brobizz-usage auth login
brobizz-usage trips
```

## Common Commands

| Task                            | Command                      |
| ------------------------------- | ---------------------------- |
| Show recent trips as cards      | `brobizz-usage trips`        |
| Show trips as JSON              | `brobizz-usage trips --json` |
| Show account details (JSON)     | `brobizz-usage account`      |
| Log out and remove saved tokens | `brobizz-usage auth logout`  |

Trip cards are pink while the invoice is unpaid and steel blue once it is paid.

## Login Options

You can prefill login values to skip prompts:

```bash
brobizz-usage auth login --username you@example.com
brobizz-usage auth login --username you@example.com --password 'secret'
brobizz-usage auth login --username you@example.com --password 'secret' --otp-channel sms
```

For scripts, avoid putting the password in shell history:

```bash
printf '%s\n' 'secret' | brobizz-usage auth login --username you@example.com --password-stdin --otp-channel sms
```

`auth login` is headless by default, which is suitable for servers. To debug the browser flow visually:

```bash
brobizz-usage auth login --browser-login
```

## Trip Options

```bash
brobizz-usage trips -n 10
brobizz-usage trips --full
brobizz-usage trips --search "Storebaelt"
brobizz-usage trips --include-payment-records
brobizz-usage trips --json
```

| Option                      | Effect                                                     |
| --------------------------- | ---------------------------------------------------------- |
| `--number`, `-n`            | Number of latest trip cards to show. Defaults to `5`.      |
| `--full`                    | Show additional scalar fields on each visible card.        |
| `--search`                  | Filter transactions by search text.                        |
| `--include-payment-records` | Include standalone payments, vouchers, and drafts.         |
| `--json`                    | Output raw trips and usage records as JSON.                |
| `--account-id`              | Read trips for a specific account instead of the default.  |

## Account Options

```bash
brobizz-usage account
brobizz-usage account --account-id ACCOUNT_ID
```

If `--account-id` is omitted, the CLI uses `currentAccountId`, then `defaultAccountId`, then the first usable `accountIds` value.

## Cache

API responses are cached on disk for one hour by default.

```bash
brobizz-usage --no-cache trips
brobizz-usage --cache-ttl 300 trips
brobizz-usage --force-login trips
```

| Option          | Effect                                                     |
| --------------- | ---------------------------------------------------------- |
| `--no-cache`    | Bypass cached API responses.                               |
| `--cache-ttl`   | Set cache lifetime in seconds.                             |
| `--force-login` | Ignore saved tokens and log in again before the command.   |

These are global options, so they go before the command name.

Inspect the cache directory:

```bash
python -c 'from brobizz_usage import get_user_data_path; print(get_user_data_path("cache", ensure_exists=True))'
```

## Python API

```python
from brobizz_usage import BrobizzClient

client = BrobizzClient()
person = client.get_current_person()
account = client.get_account(person["currentAccountId"])
transactions = client.get_all_transactions(search_string="Storebaelt")
```

## Development

Run tests:

```bash
uv run pytest
```

The tests mock token state, HTTP sessions, and CLI clients. They do not run live browser login or live Brobizz API calls.

Captured payloads are not required by the package. If you save samples locally, keep them under the app's XDG data directory:

```bash
python -c 'from brobizz_usage import get_user_data_path; print(get_user_data_path(ensure_exists=True))'
```
