# Brobizz Usage

Command-line tool for showing Brobizz trips and account usage.

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

After login, tokens are saved securely in your user config directory and reused automatically.

## Install As A Tool

For regular use outside the development shell:

```bash
uv tool install .
uvx playwright install chromium
brobizz-usage auth login
brobizz-usage trips
```

## Common Commands

Show recent trips as terminal cards:

```bash
brobizz-usage trips
```

Show trips as JSON:

```bash
brobizz-usage trips --json
```

Show account details:

```bash
brobizz-usage account
```

Log out:

```bash
brobizz-usage auth logout
```

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

Options:

- `--number`, `-n`: number of latest trip cards to show. Defaults to `5`.
- `--full`: show additional scalar fields on each visible card.
- `--search`: filter transactions by search text.
- `--include-payment-records`: include standalone payments, vouchers, and drafts.
- `--json`: output raw trips and usage records as JSON.

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

Options:

- `--no-cache`: bypass cached API responses.
- `--cache-ttl`: set cache lifetime in seconds.
- `--force-login`: ignore saved tokens and log in again before the command.

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
