import json
import logging
import sys
from datetime import UTC, datetime

from flask import current_app, g

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class StdoutHandler(logging.StreamHandler):
    def emit(self, record: logging.LogRecord) -> None:
        # Hosts and test runners can replace stdout after importing the application.
        self.stream = sys.stdout
        super().emit(record)


class FixtureFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "request_id": record.fixture_request_id,
            "marker": record.fixture_marker,
            "sequence": record.fixture_sequence,
            "message": record.getMessage(),
        }
        if record.exc_info:
            event["message"] += "\n" + self.formatException(record.exc_info)
        if record.fixture_format == "json":
            return json.dumps(event, ensure_ascii=False)
        return f"[{event['level']}] {event['timestamp']} {event['request_id']} {event['message']}"


def create_logger() -> logging.Logger:
    # A private logger preserves DEBUG and avoids duplicate output from runtime/root handlers.
    logger = logging.Logger("apizit_logs_fixture", level=logging.DEBUG)
    logger.propagate = False
    handler = StdoutHandler()
    handler.setFormatter(FixtureFormatter())
    logger.addHandler(handler)
    return logger


def emit(level: str, message: str, *, sequence: int = 0, exc_info: bool = False) -> None:
    # Include correlation fields in message too: log viewers may display only this JSON field.
    rendered = f"marker={g.marker} request_id={g.request_id} sequence={sequence} {message}"
    current_app.extensions["fixture_logger"].log(
        getattr(logging, level),
        rendered,
        exc_info=exc_info,
        extra={
            "fixture_request_id": g.request_id,
            "fixture_marker": g.marker,
            "fixture_sequence": sequence,
            "fixture_format": g.log_format,
        },
    )
