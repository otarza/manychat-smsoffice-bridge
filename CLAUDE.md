# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
make install    # pip install -r requirements-dev.txt
make test       # python -m pytest tests/ -v
make lint       # ruff check .
make run        # serve send_sms on http://localhost:8080 (requires .env)
make run-cb     # serve sms_callback on http://localhost:8081 (requires .env)
make deploy     # ./deploy.sh — deploys both Cloud Functions to GCP
```

Run a single test file: `python -m pytest tests/test_main.py -v`

Local setup requires copying `.env.example` to `.env` and filling in `SMSOFFICE_API_KEY` and `MANYCHAT_SHARED_SECRET`.

## Architecture

Three source modules, two deployed Cloud Functions:

- **`main.py`** — HTTP entry points (`send_sms`, `sms_callback`) using `functions_framework`. Both are deployed as separate Cloud Functions from the same source directory via `deploy.sh`.
- **`smsoffice.py`** — Synchronous `SmsOfficeClient` wrapping the smsoffice.ge REST API. Returns `SendResult` dataclass; raises `SmsOfficeError` on failure.
- **`phone.py`** — `normalize_georgian()` converts E.164/local Georgian formats to the bare `995XXXXXXXXX` format smsoffice expects. Raises `InvalidPhoneError` for non-Georgian or invalid numbers.

### Key constraints

**Module-level env var reads in `main.py`:** `os.environ["SMSOFFICE_API_KEY"]` and `os.environ["MANYCHAT_SHARED_SECRET"]` are evaluated at import time. Tests must set these env vars before importing `main` (see `tests/test_main.py` top-of-file pattern).

**Test client setup:** Tests use `functions_framework.create_app(target="send_sms", source="main.py")` to get a Flask test client — not direct function calls.

**smsoffice `ErrorCode` location:** The API inconsistently places `ErrorCode` at the top level or nested inside `Output`. `SmsOfficeClient.send()` checks both locations (`smsoffice.py:105-108`).

**Authentication:** `send_sms` checks `X-Auth-Token` against `MANYCHAT_SHARED_SECRET`. The `sms_callback` function has no auth — it must return the literal string `"OK"` per smsoffice docs.

## Deployment

`deploy.sh` deploys `send_sms` and `sms_callback` as separate Cloud Functions (2nd gen). Secrets come from GCP Secret Manager via `--set-secrets` flags — not environment variables baked into the deploy. The `.gcloudignore` excludes `tests/` and dev files from the uploaded source.
