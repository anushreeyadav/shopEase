"""Phone number normalization, shared by the request schemas and the ORM models."""

import re

# Separators people commonly type. They are removed before validation.
_SEPARATORS = re.compile(r"[\s\-().]")
# 7 to 15 digits. International numbers ("+...") follow E.164, so their first digit is not 0;
# national numbers may start with 0, as in "020 7946 0958".
_NORMALIZED_PHONE = re.compile(r"\+[1-9]\d{6,14}|\d{7,15}")


def normalize_phone_number(value: str) -> str:
    """Return the number with separators removed, for example "+91 98765-43210" -> "+919876543210".

    Raise ValueError if the result is not a plausible phone number. The input is not part of
    the message, so it never appears in an error response or log.
    """
    normalized = _SEPARATORS.sub("", value.strip())
    if normalized.startswith("00"):  # international prefix written as 00 instead of +
        normalized = "+" + normalized[2:]
    if not _NORMALIZED_PHONE.fullmatch(normalized):
        raise ValueError("Phone number must have 7 to 15 digits, optionally starting with +")
    return normalized
