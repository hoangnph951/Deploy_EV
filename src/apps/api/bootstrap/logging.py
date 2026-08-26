import logging
import re
import sys

_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_SENSITIVE_QUERY_VALUE = re.compile(
    r"(?i)([?&](?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|"
    r"password|secret|token)=)[^&\s]+"
)
_SENSITIVE_HEADER_VALUE = re.compile(
    r"(?i)\b(authorization|proxy-authorization|cookie|set-cookie)(\s*[:=]\s*)"
    r".*?(?=\s+\b(?:authorization|proxy-authorization|cookie|set-cookie)\s*[:=]|"
    r"[\r\n,]|$)"
)
_BEARER_VALUE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_PROVIDER_KEY_VALUE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{12,}|lsv2_[A-Za-z0-9_-]{12,})\b"
)


def redact_log_secrets(value: str) -> str:
    redacted = _SENSITIVE_QUERY_VALUE.sub(r"\1[REDACTED]", value)
    redacted = _SENSITIVE_HEADER_VALUE.sub(r"\1\2[REDACTED]", redacted)
    redacted = _BEARER_VALUE.sub("Bearer [REDACTED]", redacted)
    return _PROVIDER_KEY_VALUE.sub("[REDACTED]", redacted)


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_log_secrets(super().format(record))


def configure_logging(log_level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(RedactingFormatter(_LOG_FORMAT))
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        handlers=[handler],
        force=True,
    )
    # httpx INFO logs include query parameters, which would expose provider API keys.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
