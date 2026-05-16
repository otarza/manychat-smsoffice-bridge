"""Tests for the Cloud Functions HTTP handlers."""
import json
import os
from unittest.mock import patch

import pytest

# Set required env vars before importing main
os.environ.setdefault("SMSOFFICE_API_KEY", "test-key")
os.environ.setdefault("SMSOFFICE_SENDER", "BitCamp")
os.environ.setdefault("MANYCHAT_SHARED_SECRET", "test-secret")

from functions_framework import create_app  # noqa: E402

import main  # noqa: E402  (kept for import-side-effect / coverage)
from smsoffice import SendResult, SmsOfficeClient  # noqa: E402

# Silence unused warning
_ = main


def auth_headers():
    return {"X-Auth-Token": "test-secret", "Content-Type": "application/json"}


@pytest.fixture
def send_client():
    app = create_app(target="send_sms", source="main.py")
    return app.test_client()


@pytest.fixture
def callback_client():
    app = create_app(target="sms_callback", source="main.py")
    return app.test_client()


class TestSendSms:
    def test_missing_auth_returns_401(self, send_client):
        r = send_client.post(
            "/",
            data=json.dumps({"phone": "+995577123456", "content": "hi"}),
            content_type="application/json",
        )
        assert r.status_code == 401

    def test_missing_phone_returns_400(self, send_client):
        r = send_client.post(
            "/",
            headers=auth_headers(),
            data=json.dumps({"content": "hi"}),
        )
        assert r.status_code == 400
        assert json.loads(r.data)["success"] is False

    def test_invalid_phone_returns_400(self, send_client):
        r = send_client.post(
            "/",
            headers=auth_headers(),
            data=json.dumps({"phone": "abc", "content": "hi"}),
        )
        assert r.status_code == 400
        assert json.loads(r.data)["error"] == "invalid_phone"

    def test_happy_path(self, send_client):
        fake_result = SendResult(
            success=True, error_code=0, message="queued", raw={}
        )
        with patch.object(SmsOfficeClient, "send", return_value=fake_result) as send_mock:
            r = send_client.post(
                "/",
                headers=auth_headers(),
                data=json.dumps(
                    {
                        "phone": "+995577123456",
                        "content": "გამარჯობა",
                        "reference": "abc",
                    }
                ),
            )
        assert r.status_code == 200
        body = json.loads(r.data)
        assert body["success"] is True
        assert body["destination"] == "995577123456"
        send_mock.assert_called_once()
        kwargs = send_mock.call_args.kwargs
        assert kwargs["destination"] == "995577123456"
        assert kwargs["reference"] == "abc"

    def test_smsoffice_failure_returns_502(self, send_client):
        fake_result = SendResult(
            success=False, error_code=20, message="Insufficient balance", raw={}
        )
        with patch.object(SmsOfficeClient, "send", return_value=fake_result):
            r = send_client.post(
                "/",
                headers=auth_headers(),
                data=json.dumps({"phone": "+995577123456", "content": "hi"}),
            )
        assert r.status_code == 502
        body = json.loads(r.data)
        assert body["success"] is False
        assert body["error_code"] == 20


class TestCallback:
    def test_returns_ok(self, callback_client):
        r = callback_client.get(
            "/",
            query_string={
                "reference": "abc",
                "status": "Delivered",
                "destination": "995577123456",
                "timestamp": "20260516120000",
            },
        )
        assert r.status_code == 200
        assert r.data == b"OK"
