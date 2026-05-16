"""Tests for SmsOfficeClient."""
import pytest
import responses

from smsoffice import SmsOfficeClient, SmsOfficeError, SMSOFFICE_SEND_URL


@pytest.fixture
def client():
    return SmsOfficeClient(api_key="test-key", sender="BitCamp")


class TestSend:
    @responses.activate
    def test_success(self, client):
        responses.add(
            responses.POST,
            SMSOFFICE_SEND_URL,
            json={"Success": True, "Message": "queued", "Output": 0, "ErrorCode": 0},
            status=200,
        )
        result = client.send(destination="995577123456", content="hi")
        assert result.success is True
        assert result.error_code == 0

    @responses.activate
    def test_failure_code(self, client):
        responses.add(
            responses.POST,
            SMSOFFICE_SEND_URL,
            json={
                "Success": False,
                "Message": "Insufficient balance",
                "Output": {"ErrorCode": 20},
                "ErrorCode": 20,
            },
            status=200,
        )
        result = client.send(destination="995577123456", content="hi")
        assert result.success is False
        assert result.error_code == 20
        assert "balance" in result.message.lower()

    @responses.activate
    def test_non_json_response_raises(self, client):
        responses.add(
            responses.POST, SMSOFFICE_SEND_URL, body="<html>error</html>", status=500
        )
        with pytest.raises(SmsOfficeError):
            client.send(destination="995577123456", content="hi")

    @responses.activate
    def test_payload_includes_reference_and_urgent(self, client):
        responses.add(
            responses.POST,
            SMSOFFICE_SEND_URL,
            json={"Success": True, "ErrorCode": 0, "Message": ""},
            status=200,
        )
        client.send(
            destination="995577123456",
            content="hi",
            reference="ref-123",
            urgent=True,
        )
        body = responses.calls[0].request.body
        assert "reference=ref-123" in body
        assert "urgent=true" in body


class TestConstruction:
    def test_requires_api_key(self):
        with pytest.raises(ValueError):
            SmsOfficeClient(api_key="", sender="BitCamp")

    def test_requires_sender(self):
        with pytest.raises(ValueError):
            SmsOfficeClient(api_key="x", sender="")
