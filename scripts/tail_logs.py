#!/usr/bin/env python3
"""Poll bridge logs and print a compact, human-readable live view."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime


FILTERS = {
    "broadcast": (
        'resource.type="cloud_run_revision" AND '
        "((resource.labels.service_name=\"send-sms\" AND "
        "(jsonPayload.event=\"send_result\" OR "
        "jsonPayload.event=\"send_exception\" OR "
        "jsonPayload.event=\"send_validation_failed\")) OR "
        "(resource.labels.service_name=\"sms-callback\" AND "
        'jsonPayload.event="delivery_callback"))'
    ),
    "results": (
        'resource.type="cloud_run_revision" AND '
        'resource.labels.service_name="send-sms" AND '
        'jsonPayload.event="send_result"'
    ),
    "failures": (
        'resource.type="cloud_run_revision" AND '
        'resource.labels.service_name="send-sms" AND '
        "(jsonPayload.event=\"send_exception\" OR "
        "jsonPayload.event=\"send_validation_failed\" OR "
        "jsonPayload.success=false)"
    ),
}


def _short_time(value: str) -> str:
    if not value:
        return "--:--:--"
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).strftime("%H:%M:%S")
    except ValueError:
        return value[:19]


def _clip(value, width: int) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\n", " ")
    if len(text) <= width:
        return text.ljust(width)
    return f"{text[: width - 1]}…"


def _payload(entry: dict) -> dict:
    payload = entry.get("jsonPayload")
    if isinstance(payload, dict):
        return payload

    text = entry.get("textPayload")
    if isinstance(text, str) and text.lstrip().startswith("{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    return {}


def _event_mark(payload: dict) -> str:
    event = payload.get("event", "")
    success = payload.get("success")
    if event == "delivery_callback":
        return "CALLBACK"
    if event in {"send_exception", "send_validation_failed"}:
        return "FAIL"
    if success is True:
        return "OK"
    if success is False:
        return "FAIL"
    return event or "LOG"


def _format_entry(entry: dict) -> str | None:
    payload = _payload(entry)
    event = payload.get("event")
    if not event:
        return None

    mark = _event_mark(payload)
    reference = payload.get("reference") or "-"
    phone = payload.get("destination_masked") or "-"
    error_code = payload.get("error_code")
    status = payload.get("status") or "-"
    message = payload.get("message") or payload.get("error") or payload.get("reason") or "-"

    return " ".join(
        [
            _clip(_short_time(entry.get("timestamp", "")), 8),
            _clip(mark, 8),
            _clip(event, 22),
            _clip(reference, 22),
            _clip(phone, 14),
            _clip(f"code={error_code}" if error_code is not None else "", 10),
            _clip(f"status={status}" if status != "-" else "", 18),
            _clip(message, 70),
        ]
    ).rstrip()


def _entry_key(entry: dict) -> tuple:
    return (
        entry.get("logName", ""),
        entry.get("insertId", ""),
        entry.get("timestamp", ""),
    )


def _print_header() -> None:
    print(
        " ".join(
            [
                _clip("time", 8),
                _clip("result", 8),
                _clip("event", 22),
                _clip("reference", 22),
                _clip("phone", 14),
                _clip("code", 10),
                _clip("status", 18),
                "message",
            ]
        ),
        flush=True,
    )
    print("-" * 180, flush=True)


def _read_entries(project: str, mode: str, freshness: str, limit: int) -> list[dict]:
    command = [
        "gcloud",
        "logging",
        "read",
        FILTERS[mode],
        f"--project={project}",
        f"--freshness={freshness}",
        f"--limit={limit}",
        "--format=json",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    if not result.stdout.strip():
        return []
    parsed = json.loads(result.stdout)
    return parsed if isinstance(parsed, list) else []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument(
        "--mode",
        choices=sorted(FILTERS),
        default="broadcast",
        help="Which bridge log stream to show.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Polling interval in seconds.",
    )
    parser.add_argument(
        "--freshness",
        default="30m",
        help="How far back each polling query should look.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Max log entries to fetch per poll.",
    )
    args = parser.parse_args()

    print(
        f"Polling {args.mode} logs for {args.project} every {args.interval:g}s. "
        "Press Ctrl-C to stop.",
        flush=True,
    )
    print(f"Showing matching logs from the last {args.freshness}, then new matches.", flush=True)
    _print_header()

    seen: set[tuple] = set()

    try:
        while True:
            entries = _read_entries(args.project, args.mode, args.freshness, args.limit)
            for entry in reversed(entries):
                key = _entry_key(entry)
                if key in seen:
                    continue
                seen.add(key)
                line = _format_entry(entry)
                if line:
                    print(line, flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    except (json.JSONDecodeError, RuntimeError) as exc:
        print(f"Could not read logs: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
