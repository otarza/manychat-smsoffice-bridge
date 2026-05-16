# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Commands

```bash
make install    # pip install -r requirements-dev.txt
make test       # python -m pytest tests/ -v
make lint       # python -m ruff check .
make run        # serve send_sms on http://localhost:8080 (requires .env)
make run-cb     # serve sms_callback on http://localhost:8081
make deploy     # ./deploy.sh — deploys both Cloud Functions to GCP
make logs-tail  # watch live send/callback logs
make logs-broadcast-tail # watch live broadcast table
make logs-results-tail # watch live send results table
make logs-results  # show latest send results
make logs-failures # show latest send failures
```

Run a single test file: `python -m pytest tests/test_main.py -v`

Local setup requires copying `.env.example` to `.env` and filling in `SMSOFFICE_API_KEY` and `MANYCHAT_SHARED_SECRET`.

## Architecture

Three source modules, two deployed Cloud Functions:

- **`main.py`** — HTTP entry points (`send_sms`, `sms_callback`) using `functions_framework`. Both are deployed as separate Cloud Functions from the same source directory via `deploy.sh`.
- **`smsoffice.py`** — Synchronous `SmsOfficeClient` wrapping the smsoffice.ge REST API. Returns `SendResult` dataclass; raises `SmsOfficeError` on failure.
- **`phone.py`** — `normalize_georgian()` converts E.164/local Georgian formats to the bare `995XXXXXXXXX` format smsoffice expects. Raises `InvalidPhoneError` for non-Georgian or invalid numbers.

### Key constraints

**Lazy send_sms configuration in `main.py`:** `SMSOFFICE_API_KEY` and `MANYCHAT_SHARED_SECRET` are read only when `send_sms` handles a request. `sms_callback` must remain importable and runnable without either secret.

**ManyChat response mapping:** Authorized `send_sms` POST requests return HTTP 200 for expected validation failures, smsoffice business failures, and smsoffice transport failures so ManyChat can map JSON fields and branch on `success`. Keep auth and method failures as HTTP errors.

**smsoffice reference limit:** smsoffice limits callback `reference` labels to 20 UTF-8 bytes. Long ManyChat references are hashed to a stable 20-character value and returned in the response.

**Test client setup:** Tests use `functions_framework.create_app(target="send_sms", source="main.py")` to get a Flask test client — not direct function calls.

**smsoffice `ErrorCode` location:** The API inconsistently places `ErrorCode` at the top level or nested inside `Output`. `SmsOfficeClient.send()` checks both locations.

**Authentication:** `send_sms` checks `X-Auth-Token` against `MANYCHAT_SHARED_SECRET`. The `sms_callback` function has no auth — it must return the literal string `"OK"` per smsoffice docs.

**Logging:** `main.py` emits structured JSON events to stdout. Do not log message content, full phone numbers, API keys, or ManyChat secrets. Use masked destinations and content hashes for broadcast debugging.

## Deployment

`deploy.sh` deploys `send_sms` and `sms_callback` as separate Cloud Functions (2nd gen). It creates separate runtime service accounts; only `send_sms` receives Secret Manager access and secret env vars. The `.gcloudignore` excludes `tests/`, docs, and dev files from the uploaded source.
