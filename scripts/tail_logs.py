#!/usr/bin/env python3
"""Tail bridge logs in a compact, human-readable format."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
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
    payload = entry.get("jsonPayload") or {}
    event = payload.get("event")
    if not event:
        text_payload = entry.get("textPayload")
        return f"{_short_time(entry.get('timestamp', ''))} TEXT {text_payload}" if text_payload else None

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


def _iter_json_stream(stream):
    decoder = json.JSONDecoder()
    buffer = ""
    for chunk in iter(lambda: stream.read(1), ""):
        buffer += chunk
        stripped = buffer.lstrip()
        if not stripped:
            buffer = ""
            continue
        try:
            value, end = decoder.raw_decode(stripped)
        except json.JSONDecodeError:
            continue
        consumed_prefix = len(buffer) - len(stripped)
        buffer = buffer[consumed_prefix + end :]
        if isinstance(value, list):
            for item in value:
                yield item
        elif isinstance(value, dict):
            yield value


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
        "--buffer-window",
        default="1s",
        help="gcloud logging tail buffer window.",
    )
    args = parser.parse_args()

    command = [
        "gcloud",
        "beta",
        "logging",
        "tail",
        FILTERS[args.mode],
        f"--project={args.project}",
        "--format=json",
        f"--buffer-window={args.buffer_window}",
    ]

    print(f"Streaming {args.mode} logs for {args.project}. Press Ctrl-C to stop.")
    _print_header()

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        print("gcloud was not found on PATH.", file=sys.stderr)
        return 127

    assert process.stdout is not None
    assert process.stderr is not None

    try:
        for entry in _iter_json_stream(process.stdout):
            line = _format_entry(entry)
            if line:
                print(line, flush=True)
    except KeyboardInterrupt:
        process.terminate()
        return 130
    finally:
        stderr = process.stderr.read()
        if stderr:
            print(stderr, file=sys.stderr, end="")

    return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
