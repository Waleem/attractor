from __future__ import annotations

from attractor_platform.redaction import redact_mapping, redact_text


def test_redact_text_masks_common_secret_shapes() -> None:
    text = "OPENAI_API_KEY=sk-test-secret password=hunter2 normal=value"

    redacted = redact_text(text)

    assert "sk-test-secret" not in redacted
    assert "hunter2" not in redacted
    assert "normal=value" in redacted


def test_redact_text_masks_colon_and_json_like_secret_shapes() -> None:
    text = 'api_key: sk-secret token: abc123 "token": "json-secret" password: hunter2 normal=value'

    redacted = redact_text(text)

    assert "sk-secret" not in redacted
    assert "abc123" not in redacted
    assert "json-secret" not in redacted
    assert "hunter2" not in redacted
    assert "normal=value" in redacted


def test_redact_mapping_recurses() -> None:
    payload = {
        "safe": "ok",
        "token": "abc123",
        "nested": {"api_key": "secret", "items": ["plain", {"password": "pw"}]},
    }

    assert redact_mapping(payload) == {
        "safe": "ok",
        "token": "[REDACTED]",
        "nested": {"api_key": "[REDACTED]", "items": ["plain", {"password": "[REDACTED]"}]},
    }
