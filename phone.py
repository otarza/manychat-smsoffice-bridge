"""Phone number normalization for smsoffice.ge.

smsoffice expects Georgian numbers in international format without
the leading + or 00, e.g. 995577123456.
ManyChat stores phones in E.164 format with +, so we strip and normalize.
"""
import re

GEORGIA_COUNTRY_CODE = "995"
# Georgian mobile numbers: 9 digits after country code, starting with 5
GEORGIAN_MOBILE_PATTERN = re.compile(r"^995[5]\d{8}$")


class InvalidPhoneError(ValueError):
    """Raised when a phone number cannot be normalized to a valid Georgian format."""


def normalize_georgian(raw: str) -> str:
    """Normalize an input phone string to smsoffice format.

    Accepts forms like:
        +995577123456   -> 995577123456
        00995577123456  -> 995577123456
        995577123456    -> 995577123456
        577123456       -> 995577123456
        0577123456      -> 995577123456

    Args:
        raw: Phone number in any of the above formats.

    Returns:
        Normalized phone number, e.g. "995577123456".

    Raises:
        InvalidPhoneError: If the resulting number is not a valid Georgian mobile.
    """
    if not raw:
        raise InvalidPhoneError("Phone number is empty")

    # Strip everything that isn't a digit
    digits = re.sub(r"\D", "", raw)

    if not digits:
        raise InvalidPhoneError(f"No digits in input: {raw!r}")

    # Remove leading 00 (international prefix)
    if digits.startswith("00"):
        digits = digits[2:]

    # If already starts with 995, use as-is
    if digits.startswith("995"):
        normalized = digits
    else:
        # Strip a leading 0 (local format like 0577...) then prepend 995
        normalized = "995" + digits.lstrip("0")

    if not GEORGIAN_MOBILE_PATTERN.match(normalized):
        raise InvalidPhoneError(
            f"Not a valid Georgian mobile number: {raw!r} -> {normalized!r}"
        )

    return normalized
