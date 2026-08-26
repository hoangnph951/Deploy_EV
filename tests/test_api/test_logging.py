import logging

from src.apps.api.bootstrap.logging import RedactingFormatter


def test_redacting_formatter_removes_provider_and_request_secrets() -> None:
    record = logging.LogRecord(
        name="provider",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=(
            "GET https://example.test/path?api_key=goong-secret&token=session-secret "
            "Authorization: Bearer auth-secret Cookie=session-cookie"
        ),
        args=(),
        exc_info=None,
    )

    rendered = RedactingFormatter("%(message)s").format(record)

    assert "goong-secret" not in rendered
    assert "session-secret" not in rendered
    assert "auth-secret" not in rendered
    assert "session-cookie" not in rendered
    assert rendered.count("[REDACTED]") == 4


def test_redacting_formatter_removes_secrets_from_exception_text() -> None:
    try:
        raise RuntimeError("request failed: https://example.test?api_key=private-value")
    except RuntimeError:
        record = logging.LogRecord(
            name="provider",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="provider request failed",
            args=(),
            exc_info=__import__("sys").exc_info(),
        )

    rendered = RedactingFormatter("%(message)s").format(record)

    assert "private-value" not in rendered
    assert "api_key=[REDACTED]" in rendered
