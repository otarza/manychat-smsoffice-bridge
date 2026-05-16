"""Cloud Functions HTTP entry points.

Two functions live in this module, deployed as separate Cloud Functions
from the same source:

    send_sms      - Called by ManyChat External Request to send an SMS.
    sms_callback  - Called by smsoffice when a delivery status is known.

Both are pure HTTP handlers using functions_framework.
"""
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

SMSOFFICE_API_KEY = os.environ["SMSOFFICE_API_KEY"]
SMSOFFICE_SENDER = os.environ.get("SMSOFFICE_SENDER", "BitCamp")
MANYCHAT_SHARED_SECRET = os.environ["MANYCHAT_SHARED_SECRET"]

_client = SmsOfficeClient(api_key=SMSOFFICE_API_KEY, sender=SMSOFFICE_SENDER)


# ---- Helpers --------------------------------------------------------------

def _json(payload: dict, status: int = 200) -> Tuple[str, int, dict]:
    return (
        json.dumps(payload, ensure_ascii=False),
        status,
        {"Content-Type": "application/json; charset=utf-8"},
    )


def _authorized(request: Request) -> bool:
    """Constant-time-ish check of the shared secret header."""
    token = request.headers.get("X-Auth-Token", "")
    # Python string == is not constant-time, but for a 256-bit random token
    # the timing channel is negligible at this scale.
    return token == MANYCHAT_SHARED_SECRET


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
    urgent = bool(data.get("urgent", False))

    if not raw_phone or not content:
        return _json(
            {"success": False, "error": "phone and content are required"}, 400
        )

    try:
        destination = normalize_georgian(raw_phone)
    except InvalidPhoneError as e:
        log.info("Phone normalization failed: %s", e)
        return _json(
            {"success": False, "error": "invalid_phone", "detail": str(e)}, 400
        )

    log.info(
        "Sending SMS",
        extra={"destination": destination, "reference": reference, "len": len(content)},
    )

    try:
        result = _client.send(
            destination=destination,
            content=content,
            reference=reference,
            urgent=urgent,
        )
    except SmsOfficeError as e:
        log.error("smsoffice error: %s", e)
        return _json({"success": False, "error": str(e)}, 502)

    response_status = 200 if result.success else 502
    return _json(
        {
            "success": result.success,
            "error_code": result.error_code,
            "message": result.message,
            "destination": destination,
        },
        response_status,
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
