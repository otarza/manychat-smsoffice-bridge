"""Thin client for the smsoffice.ge SMS API.

API docs: https://smsoffice.ge/integration/
"""
import logging
from dataclasses import dataclass
from typing import Optional

import requests

log = logging.getLogger(__name__)

SMSOFFICE_SEND_URL = "https://smsoffice.ge/api/v2/send/"
SMSOFFICE_STATUS_URL = "https://smsoffice.ge/api/v2/getMessageStatus/"
SMSOFFICE_BALANCE_URL = "https://smsoffice.ge/api/getBalance"


class SmsOfficeError(Exception):
    """Raised when smsoffice returns a non-success response."""

    def __init__(self, message: str, error_code: Optional[int] = None):
        super().__init__(message)
        self.error_code = error_code


@dataclass
class SendResult:
    success: bool
    error_code: Optional[int]
    message: str
    raw: dict


class SmsOfficeClient:
    """Synchronous client for smsoffice.ge."""

    def __init__(
        self,
        api_key: str,
        sender: str,
        timeout: float = 8.0,
        session: Optional[requests.Session] = None,
    ):
        if not api_key:
            raise ValueError("api_key is required")
        if not sender:
            raise ValueError("sender is required")
        self.api_key = api_key
        self.sender = sender
        self.timeout = timeout
        self.session = session or requests.Session()

    def send(
        self,
        destination: str,
        content: str,
        reference: Optional[str] = None,
        urgent: bool = False,
    ) -> SendResult:
        """Send a single SMS.

        Args:
            destination: Phone in 995XXXXXXXXX format (no + or 00).
            content: Message body (max 1000 chars per smsoffice docs).
            reference: Optional unique label for delivery-status tracking.
            urgent: If True, bypass the stop list (requires approved sender).

        Returns:
            SendResult with parsed response.

        Raises:
            SmsOfficeError: On HTTP error or unparseable response.
        """
        payload = {
            "key": self.api_key,
            "destination": destination,
            "sender": self.sender,
            "content": content,
        }
        if reference:
            payload["reference"] = reference
        if urgent:
            payload["urgent"] = "true"

        try:
            r = self.session.post(
                SMSOFFICE_SEND_URL, data=payload, timeout=self.timeout
            )
        except requests.RequestException as e:
            raise SmsOfficeError(f"HTTP error calling smsoffice: {e}") from e

        try:
            data = r.json()
        except ValueError as e:
            raise SmsOfficeError(
                f"Non-JSON response from smsoffice (status {r.status_code}): "
                f"{r.text[:200]}"
            ) from e

        # Response shape: {"Success": bool, "Message": str, "Output": {...} or int, "ErrorCode": int}
        # ErrorCode location varies; check both top-level and Output dict
        error_code = data.get("ErrorCode")
        output = data.get("Output")
        if isinstance(output, dict) and "ErrorCode" in output:
            error_code = output["ErrorCode"]

        return SendResult(
            success=bool(data.get("Success")),
            error_code=error_code,
            message=str(data.get("Message", "")),
            raw=data,
        )

    def get_balance(self) -> int:
        """Return remaining SMS credits on the account."""
        try:
            r = self.session.get(
                SMSOFFICE_BALANCE_URL,
                params={"key": self.api_key},
                timeout=self.timeout,
            )
            r.raise_for_status()
            return int(r.text.strip())
        except (requests.RequestException, ValueError) as e:
            raise SmsOfficeError(f"Failed to fetch balance: {e}") from e
