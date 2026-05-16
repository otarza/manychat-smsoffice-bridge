"""Cloud Functions HTTP entry points.

Two functions live in this module, deployed as separate Cloud Functions
from the same source:

    send_sms      - Called by ManyChat External Request to send an SMS.
    sms_callback  - Called by smsoffice when a delivery status is known.

Both are pure HTTP handlers using functions_framework.
"""
import hashlib
import hmac
import json
import logging
import os
from typing import Tuple

import functions_framework
from flask import Request

from phone import InvalidPhoneError, normalize_georgian
from smsoffice import SmsOfficeClient, SmsOfficeError

# ---- Logging setup --------------------------------------------------------

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
log = logging.getLogger("smsoffice-bridge")

# ---- Configuration --------------------------------------------------------

SMSOFFICE_CONTENT_MAX_CHARS = 1000
SMSOFFICE_REFERENCE_MAX_BYTES = 20
SMSOFFICE_TIMEOUT_SECONDS = 8.0

_client = None


# ---- Helpers --------------------------------------------------------------

def _json(payload: dict, status: int = 200) -> Tuple[str, int, dict]:
    return (
        json.dumps(payload, ensure_ascii=False),
        status,
        {"Content-Type": "application/json; charset=utf-8"},
    )


def _authorized(request: Request) -> bool:
    """Constant-time check of the shared secret header."""
    token = request.headers.get("X-Auth-Token", "")
    expected = os.environ["MANYCHAT_SHARED_SECRET"]
    return hmac.compare_digest(token.encode(), expected.encode())


def _parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _sms_reference(reference: str | None) -> str | None:
    """Fit ManyChat references into smsoffice's 20-byte callback label limit."""
    if not reference:
        return None
    encoded = reference.encode("utf-8")
    if len(encoded) <= SMSOFFICE_REFERENCE_MAX_BYTES:
        return reference
    return hashlib.sha256(encoded).hexdigest()[:SMSOFFICE_REFERENCE_MAX_BYTES]


def _sms_timeout() -> float:
    return float(os.environ.get("SMSOFFICE_TIMEOUT_SECONDS", SMSOFFICE_TIMEOUT_SECONDS))


def _sms_client() -> SmsOfficeClient:
    """Lazily initialize the smsoffice client for send_sms only."""
    global _client
    if _client is None:
        _client = SmsOfficeClient(
            api_key=os.environ["SMSOFFICE_API_KEY"],
            sender=os.environ.get("SMSOFFICE_SENDER", "BitCamp"),
            timeout=_sms_timeout(),
        )
    return _client


# ---- send_sms -------------------------------------------------------------

@functions_framework.http
def send_sms(request: Request):
    """Send an SMS triggered by a ManyChat External Request.

    Expected JSON body:
        {
            "phone": "+995577123456",
            "content": "Your message in Georgian or English",
            "reference": "optional-unique-id"
        }

    Returns a flat JSON object ManyChat can branch on:
        {
            "success": true,
            "error_code": 0,
            "message": "...",
            "destination": "995577123456"
        }
    """
    if request.method != "POST":
        return _json({"success": False, "error": "POST required"}, 405)

    if not _authorized(request):
        log.warning("Unauthorized request from %s", request.remote_addr)
        return _json({"success": False, "error": "unauthorized"}, 401)

    data = request.get_json(silent=True) or {}
    raw_phone = (data.get("phone") or "").strip()
    content = (data.get("content") or "").strip()
    reference = (data.get("reference") or "").strip() or None
    urgent = _parse_bool(data.get("urgent", False))

    if not raw_phone or not content:
        return _json(
            {
                "success": False,
                "error": "missing_required_field",
                "error_code": None,
                "message": "phone and content are required",
            }
        )

    if len(content) > SMSOFFICE_CONTENT_MAX_CHARS:
        return _json(
            {
                "success": False,
                "error": "content_too_long",
                "error_code": None,
                "message": (
                    f"content exceeds {SMSOFFICE_CONTENT_MAX_CHARS} character limit"
                ),
            }
        )

    try:
        destination = normalize_georgian(raw_phone)
    except InvalidPhoneError as e:
        log.info("Phone normalization failed: %s", e)
        return _json(
            {
                "success": False,
                "error": "invalid_phone",
                "error_code": None,
                "message": "invalid phone",
                "detail": str(e),
            }
        )

    api_reference = _sms_reference(reference)

    log.info(
        "Sending SMS",
        extra={
            "destination": destination,
            "reference": api_reference,
            "len": len(content),
        },
    )

    try:
        result = _sms_client().send(
            destination=destination,
            content=content,
            reference=api_reference,
            urgent=urgent,
        )
    except SmsOfficeError as e:
        log.error("smsoffice error: %s", e)
        return _json(
            {
                "success": False,
                "error": "smsoffice_error",
                "error_code": e.error_code,
                "message": str(e),
                "destination": destination,
                "reference": api_reference,
            }
        )

    return _json(
        {
            "success": result.success,
            "error_code": result.error_code,
            "message": result.message,
            "destination": destination,
            "reference": api_reference,
        },
    )


# ---- sms_callback ---------------------------------------------------------

@functions_framework.http
def sms_callback(request: Request):
    """Receive delivery status from smsoffice.

    smsoffice calls this URL (configured in your smsoffice profile) with
    query parameters:
        reference, status, reason, destination, timestamp, operator

    Per smsoffice docs, the response body must be the literal string "OK".

    TODO: persist these to Firestore / BigQuery / Sheets for reporting.
    For now we just log them so they show up in Cloud Logging.
    """
    params = {
        "reference": request.args.get("reference", ""),
        "status": request.args.get("status", ""),
        "reason": request.args.get("reason", ""),
        "destination": request.args.get("destination", ""),
        "timestamp": request.args.get("timestamp", ""),
        "operator": request.args.get("operator", ""),
    }
    log.info("Delivery callback: %s", params)
    return ("OK", 200, {"Content-Type": "text/plain"})
