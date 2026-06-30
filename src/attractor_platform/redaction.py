from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

SECRET_KEY_FRAGMENTS = ("api_key", "apikey", "token", "secret", "password", "credential")
SECRET_ASSIGNMENT = re.compile(
    r"(?ix)"
    r"(?P<prefix>"
    r"(?P<key_quote>[\"']?)"
    r"(?P<key>[a-z0-9_-]*(?:api[_-]?key|token|secret|password|credential)[a-z0-9_-]*)"
    r"(?P=key_quote)"
    r"\s*(?:=|:)\s*"
    r")"
    r"(?P<value_quote>[\"']?)"
    r"(?P<value>[^\s,\"'}\]]+)"
    r"(?P=value_quote)"
)


def is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(fragment in normalized for fragment in SECRET_KEY_FRAGMENTS)


def redact_text(value: str) -> str:
    return SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group('prefix')}{match.group('value_quote')}[REDACTED]"
        f"{match.group('value_quote')}",
        value,
    )


def redact_value(key: str, value: Any) -> Any:
    if is_secret_key(key):
        return "[REDACTED]"
    return redact_any(value)


def redact_any(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {str(key): redact_value(str(key), item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_any(item) for item in value]
    return value


def redact_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): redact_value(str(key), value) for key, value in payload.items()}
