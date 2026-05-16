"""Tests for phone normalization."""
import pytest

from phone import InvalidPhoneError, normalize_georgian


class TestNormalizeGeorgian:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("+995577123456", "995577123456"),
            ("00995577123456", "995577123456"),
            ("995577123456", "995577123456"),
            ("577123456", "995577123456"),
            ("0577123456", "995577123456"),
            ("+995 577 12 34 56", "995577123456"),
            ("995-577-123-456", "995577123456"),
            ("(995) 577 123 456", "995577123456"),
        ],
    )
    def test_valid_formats(self, raw, expected):
        assert normalize_georgian(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "abc",
            "123",
            "995123456789",  # not starting with 5 after country code
            "995577",         # too short
            "9955771234567",  # too long
            "+1234567890",    # not Georgian
        ],
    )
    def test_invalid_formats_raise(self, raw):
        with pytest.raises(InvalidPhoneError):
            normalize_georgian(raw)

    def test_none_raises(self):
        with pytest.raises(InvalidPhoneError):
            normalize_georgian(None)  # type: ignore[arg-type]
