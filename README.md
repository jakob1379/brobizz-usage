# Brobizz Usage

Packaged Python CLI and client library for Brobizz trips, usage, account, and profile JSON.

## Install

Enter the Nix development shell first:

```bash
nix develop
```

Then install the Python dependencies:

```bash
uv sync --extra dev
```

For normal use without the dev tools:

```bash
uv tool install .
uvx playwright install chromium
```

## Authentication

The first authenticated command opens a headed Playwright browser at:

```text
https://login.brobizz.com/ture-og-forbrug
```

Complete the Brobizz/Auth0 login in that browser. The CLI captures the OAuth token exchange from the isolated browser context and stores the token state in the user config directory via `platformdirs` with file mode `0600`.

The client refreshes tokens before expiry and retries once after `401` or `403`. If refresh fails, stale token state is deleted and a new browser login is opened. The package does not read HAR files, `.brobizz_token_cache.json`, or any other reverse-engineering artifact.

For automated login, pass the account email and provide the password directly or on stdin:

```bash
brobizz-usage auth login --username you@example.com --password 'secret'
```

If `--otp-channel` is omitted, the CLI shows an interactive SMS/email menu during the live login flow, immediately before it sends the one-time code. For non-interactive callers, pass the channel explicitly:

```bash
brobizz-usage auth login --username you@example.com --password 'secret' --otp-channel sms
brobizz-usage auth login --username you@example.com --password 'secret' --otp-channel email
brobizz-usage auth login --username you@example.com --password-stdin --otp-channel sms
```

Automated credential login runs Chromium headless by default whenever `--username` is passed. Use this mode on servers or from other tools that can provide `--password` or `--password-stdin` and `--otp-channel`. `--headless` can be passed explicitly for readability in scripts; `--headed` shows Chromium for debugging the automated flow. Manual login without `--username` is always headed.

After the channel is selected and the code is sent, the CLI prompts for the received one-time code in the same browser flow.

To watch the browser being controlled by the CLI while debugging selectors or login-page changes, add `--headed`:

```bash
brobizz-usage auth login --username you@example.com --headed
brobizz-usage auth login --username you@example.com --password 'secret' --otp-channel sms --headed
```

## CLI

```bash
brobizz-usage trips
brobizz-usage trips --json
brobizz-usage --force-login trips --search "Storebaelt" --include-payment-records
brobizz-usage account
brobizz-usage account --json
brobizz-usage auth login
brobizz-usage auth logout
```

Global options:

- `--force-login`: ignore saved tokens and open browser login first.

Shared options on API commands:

- `--account-id`: Brobizz account id. Defaults to `currentAccountId`, then `defaultAccountId`, then the first usable `accountIds` value.

`account` outputs combined `person` and `account` objects as JSON.

API commands cache successful GET responses on disk for one hour by default. This keeps repeated `trips` and `account` calls fast and avoids unnecessary Brobizz requests. Cache keys include the authenticated token subject when available; use `--no-cache` or `--force-login` when you need a fresh request.

```bash
brobizz-usage trips
brobizz-usage --no-cache trips
brobizz-usage --cache-ttl 300 trips
```

The cache lives below the package user data directory, which you can inspect with:

```bash
python -c 'from brobizz_usage import get_user_data_path; print(get_user_data_path("cache", ensure_exists=True))'
```

`trips` also supports:

- `--json`: output trips and usage records as JSON instead of Rich-formatted cards.
- `--number`, `-n`: number of latest trip cards to show. Defaults to `5`.
- `--full`: expand each visible card with additional scalar fields.
- `--search`: optional transaction search string.
- `--include-payment-records`: include standalone payments, payment vouchers, and drafts.

## Python API

```python
from brobizz_usage import BrobizzClient

client = BrobizzClient()
person = client.get_current_person()
account = client.get_account(person["currentAccountId"])
transactions = client.get_all_transactions(search_string="Storebaelt")
```

## Tests

```bash
uv run pytest
```

Automated tests mock token state, HTTP sessions, and CLI clients. They do not run live browser login or live Brobizz API calls.

Captured payloads are not required by the package. If you save samples locally, keep them under
the app's XDG data directory:

```bash
python -c 'from brobizz_usage import get_user_data_path; print(get_user_data_path(ensure_exists=True))'
```
