"""Tests for the Cloud Functions HTTP handlers."""
import hashlib
import importlib
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from flask import Flask, request

# Set required env vars before importing main
os.environ.setdefault("SMSOFFICE_API_KEY", "test-key")
os.environ.setdefault("SMSOFFICE_SENDER", "BitCamp")
os.environ.setdefault("MANYCHAT_SHARED_SECRET", "test-secret")

from functions_framework import create_app  # noqa: E402

import main  # noqa: E402  (kept for import-side-effect / coverage)
from smsoffice import SendResult, SmsOfficeClient, SmsOfficeError  # noqa: E402

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

    def test_non_ascii_auth_returns_401(self, send_client):
        r = send_client.post(
            "/",
            headers={"X-Auth-Token": "wrong-é", "Content-Type": "application/json"},
            data=json.dumps({"phone": "+995577123456", "content": "hi"}),
        )
        assert r.status_code == 401

    def test_missing_phone_returns_mappable_failure(self, send_client):
        r = send_client.post(
            "/",
            headers=auth_headers(),
            data=json.dumps({"content": "hi"}),
        )
        assert r.status_code == 200
        body = json.loads(r.data)
        assert body["success"] is False
        assert body["error"] == "missing_required_field"
        assert body["error_code"] is None

    def test_invalid_phone_returns_mappable_failure(self, send_client):
        r = send_client.post(
            "/",
            headers=auth_headers(),
            data=json.dumps({"phone": "abc", "content": "hi"}),
        )
        assert r.status_code == 200
        body = json.loads(r.data)
        assert body["success"] is False
        assert body["error"] == "invalid_phone"

    def test_content_too_long_returns_mappable_failure(self, send_client):
        with patch.object(SmsOfficeClient, "send") as send_mock:
            r = send_client.post(
                "/",
                headers=auth_headers(),
                data=json.dumps(
                    {"phone": "+995577123456", "content": "x" * 1001}
                ),
            )

        assert r.status_code == 200
        body = json.loads(r.data)
        assert body["success"] is False
        assert body["error"] == "content_too_long"
        send_mock.assert_not_called()

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
        assert body["reference"] == "abc"
        send_mock.assert_called_once()
        kwargs = send_mock.call_args.kwargs
        assert kwargs["destination"] == "995577123456"
        assert kwargs["reference"] == "abc"

    def test_happy_path_logs_structured_result_without_content_or_full_phone(
        self, send_client, capsys
    ):
        fake_result = SendResult(
            success=True, error_code=0, message="queued", raw={}
        )
        with patch.object(SmsOfficeClient, "send", return_value=fake_result):
            r = send_client.post(
                "/",
                headers=auth_headers(),
                data=json.dumps(
                    {
                        "phone": "+995577123456",
                        "content": "secret campaign message",
                        "reference": "broadcast-1",
                    }
                ),
            )

        assert r.status_code == 200
        log_lines = [
            json.loads(line)
            for line in capsys.readouterr().out.splitlines()
            if line.startswith("{")
        ]
        result_log = next(line for line in log_lines if line["event"] == "send_result")
        assert result_log["reference"] == "broadcast-1"
        assert result_log["destination_masked"] == "9955****3456"
        assert result_log["success"] is True
        assert result_log["error_code"] == 0
        serialized_logs = "\n".join(json.dumps(line) for line in log_lines)
        assert "secret campaign message" not in serialized_logs
        assert "995577123456" not in serialized_logs

    def test_urgent_false_string_stays_false(self, send_client):
        fake_result = SendResult(success=True, error_code=0, message="queued", raw={})
        with patch.object(SmsOfficeClient, "send", return_value=fake_result) as send_mock:
            r = send_client.post(
                "/",
                headers=auth_headers(),
                data=json.dumps(
                    {
                        "phone": "+995577123456",
                        "content": "hi",
                        "urgent": "false",
                    }
                ),
            )
        assert r.status_code == 200
        assert send_mock.call_args.kwargs["urgent"] is False

    def test_long_reference_is_hashed_to_smsoffice_limit(self, send_client):
        reference = "manychat-user-123456789-message-987654321"
        expected = hashlib.sha256(reference.encode("utf-8")).hexdigest()[:20]
        fake_result = SendResult(success=True, error_code=0, message="queued", raw={})
        with patch.object(SmsOfficeClient, "send", return_value=fake_result) as send_mock:
            r = send_client.post(
                "/",
                headers=auth_headers(),
                data=json.dumps(
                    {
                        "phone": "+995577123456",
                        "content": "hi",
                        "reference": reference,
                    }
                ),
            )

        assert r.status_code == 200
        body = json.loads(r.data)
        assert body["reference"] == expected
        assert send_mock.call_args.kwargs["reference"] == expected

    def test_smsoffice_failure_returns_mappable_failure(self, send_client):
        fake_result = SendResult(
            success=False, error_code=20, message="Insufficient balance", raw={}
        )
        with patch.object(SmsOfficeClient, "send", return_value=fake_result):
            r = send_client.post(
                "/",
                headers=auth_headers(),
                data=json.dumps({"phone": "+995577123456", "content": "hi"}),
            )
        assert r.status_code == 200
        body = json.loads(r.data)
        assert body["success"] is False
        assert body["error_code"] == 20

    def test_transport_error_returns_mappable_failure(self, send_client):
        with patch.object(
            SmsOfficeClient,
            "send",
            side_effect=SmsOfficeError("HTTP error calling smsoffice: timeout"),
        ):
            r = send_client.post(
                "/",
                headers=auth_headers(),
                data=json.dumps({"phone": "+995577123456", "content": "hi"}),
            )

        assert r.status_code == 200
        body = json.loads(r.data)
        assert body["success"] is False
        assert body["error"] == "smsoffice_error"
        assert "timeout" in body["message"]


class TestCallback:
    def test_imports_without_send_sms_secrets(self, monkeypatch):
        monkeypatch.delenv("SMSOFFICE_API_KEY", raising=False)
        monkeypatch.delenv("MANYCHAT_SHARED_SECRET", raising=False)

        spec = importlib.util.spec_from_file_location(
            "main_without_send_sms_secrets",
            Path(__file__).parents[1] / "main.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        app = Flask(__name__)
        with app.test_request_context("/"):
            body, status, headers = module.sms_callback(request)

        assert status == 200
        assert body == "OK"
        assert headers == {"Content-Type": "text/plain"}

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

    def test_logs_delivery_callback_with_masked_destination(
        self, callback_client, capsys
    ):
        r = callback_client.get(
            "/",
            query_string={
                "reference": "abc",
                "status": "Delivered",
                "reason": "",
                "destination": "995577123456",
                "timestamp": "20260516120000",
                "operator": "test",
            },
        )

        assert r.status_code == 200
        log_lines = [
            json.loads(line)
            for line in capsys.readouterr().out.splitlines()
            if line.startswith("{")
        ]
        callback_log = next(
            line for line in log_lines if line["event"] == "delivery_callback"
        )
        assert callback_log["reference"] == "abc"
        assert callback_log["status"] == "Delivered"
        assert callback_log["destination_masked"] == "9955****3456"
        assert "995577123456" not in json.dumps(callback_log)
