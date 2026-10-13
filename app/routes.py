import re
from collections import Counter
from time import sleep

from flask import Blueprint, g, jsonify, request

from app.logging_utils import LEVELS, emit

api = Blueprint("api", __name__)
SLOW_RESPONSE_SECONDS = 80
MAX_BURST_COUNT = 1000
MAX_MESSAGE_CHARS = 512
MAX_TIMELINE_COUNT = 50
MAX_TIMELINE_MS = 5000
MARKER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")


class InvalidOptions(ValueError):
    pass


@api.errorhandler(InvalidOptions)
def invalid_options(error):
    emit("WARNING", "invalid_options")
    return jsonify(error=str(error), request_id=g.request_id), 400


def integer_option(options: dict, name: str, default: int, minimum: int, maximum: int) -> int:
    value = options.get(name, default)
    if type(value) is not int or not minimum <= value <= maximum:
        raise InvalidOptions(f"'{name}' must be an integer from {minimum} to {maximum}.")
    return value


def set_log_options(options: dict) -> None:
    marker = options.get("marker", "logs-test")
    log_format = options.get("format", "json")
    if not isinstance(marker, str) or MARKER_PATTERN.fullmatch(marker) is None:
        raise InvalidOptions(
            "'marker' must be 1-64 ASCII letters, digits, dots, dashes or underscores."
        )
    if not isinstance(log_format, str) or log_format not in {"json", "text"}:
        raise InvalidOptions("'format' must be json or text.")
    g.marker = marker
    g.log_format = log_format


def json_options(allowed: set[str]) -> dict:
    options = request.get_json(silent=True)
    if not isinstance(options, dict):
        raise InvalidOptions("The request body must be a JSON object.")
    if set(options) - allowed:
        raise InvalidOptions("The request contains unsupported options.")
    return options


def summary(count: int, levels: list[str], **extra):
    return jsonify(
        status="completed",
        generated_logs=count,
        level_counts=dict(Counter(levels)),
        marker=g.marker,
        request_id=g.request_id,
        format=g.log_format,
        **extra,
    )


def generate_logs(count: int, level: str, message_chars: int = 0) -> list[str]:
    levels = []
    for index in range(count):
        current_level = LEVELS[index % len(LEVELS)] if level == "mixed" else level
        # Separated words avoid looking like a long opaque credential in a log viewer's redactor.
        padding = ("synthetic " * ((message_chars + 9) // 10))[:message_chars]
        emit(current_level, f"synthetic_event {padding}".rstrip(), sequence=index + 1)
        levels.append(current_level)
    return levels


@api.get("/health")
def health():
    """Return an immediate health response without generating a bulk log scenario."""
    return jsonify(status="ok")


@api.get("/info")
def info():
    """Describe the log fixture's formats, levels and per-request resource bounds."""
    return jsonify(
        framework="flask",
        profile="logs",
        max_burst_count=MAX_BURST_COUNT,
        max_message_chars=MAX_MESSAGE_CHARS,
        max_timeline_ms=MAX_TIMELINE_MS,
        levels=list(LEVELS),
        formats=["json", "text"],
    )


@api.post("/echo")
def echo():
    """Echo a message and integer count without writing the request body to logs."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise InvalidOptions("The request body must be a JSON object.")
    message = payload.get("message")
    count = payload.get("count")
    if not isinstance(message, str) or not message:
        raise InvalidOptions("'message' must be a non-empty string.")
    if type(count) is not int:
        raise InvalidOptions("'count' must be an integer.")
    # Request bodies are returned, never logged.
    return jsonify(received={"message": message, "count": count})


@api.get("/items/<int:item_id>")
def item(item_id: int):
    """Return a reference item with optional details for a positive integer ID."""
    if item_id < 1:
        raise InvalidOptions("'item_id' must be a positive integer.")
    raw_include_details = request.args.get("include_details", "false").lower()
    if raw_include_details not in {"true", "false"}:
        raise InvalidOptions("'include_details' must be true or false.")
    include_details = raw_include_details == "true"
    response = {"item_id": item_id, "include_details": include_details}
    if include_details:
        response["details"] = f"Reference item {item_id}"
    return jsonify(response)


@api.get("/slow")
def slow():
    """Wait exactly 80 seconds for the inherited duration probe; never use for health."""
    sleep(SLOW_RESPONSE_SECONDS)
    return jsonify(delay_seconds=SLOW_RESPONSE_SECONDS, status="completed")


@api.get("/logs/sample")
def sample():
    """Generate 25 synthetic events covering DEBUG, INFO, WARNING, ERROR and CRITICAL."""
    set_log_options(request.args.to_dict())
    return summary(25, generate_logs(25, "mixed"))


@api.post("/logs/burst")
def burst():
    """Generate 1-1000 synthetic logs with configurable level, format, marker and padding."""
    options = json_options({"count", "level", "format", "marker", "message_chars"})
    count = integer_option(options, "count", 100, 1, MAX_BURST_COUNT)
    message_chars = integer_option(options, "message_chars", 0, 0, MAX_MESSAGE_CHARS)
    level = options.get("level", "mixed")
    if not isinstance(level, str) or level not in {*LEVELS, "mixed"}:
        raise InvalidOptions("'level' must be mixed, DEBUG, INFO, WARNING, ERROR or CRITICAL.")
    set_log_options(options)
    return summary(count, generate_logs(count, level, message_chars), message_chars=message_chars)


@api.get("/logs/exception")
def exception():
    """Log a deliberate Python traceback and return HTTP 500 while keeping the API healthy."""
    set_log_options(request.args.to_dict())
    try:
        raise RuntimeError("Intentional synthetic failure for APIZIT log qualification")
    except RuntimeError:
        emit("ERROR", "intentional_exception", sequence=1, exc_info=True)
    return (
        jsonify(
            error="Intentional test error; the API remains healthy.",
            generated_logs=1,
            marker=g.marker,
            request_id=g.request_id,
        ),
        500,
    )


@api.get("/logs/multiline")
def multiline():
    """Emit three events exercising multiline messages, Unicode and a warning."""
    set_log_options(request.args.to_dict())
    emit("INFO", "multiline_start\nsecond line\nthird line", sequence=1)
    emit("INFO", "Unicode: été, français, café — 日本語 — العربية — 🚀", sequence=2)
    emit("WARNING", "synthetic_warning_after_multiline", sequence=3)
    return summary(3, ["INFO", "INFO", "WARNING"])


@api.post("/logs/timeline")
def timeline():
    """Emit paced logs with at most five seconds of cumulative synchronous waiting."""
    options = json_options({"count", "interval_ms", "format", "marker"})
    count = integer_option(options, "count", 10, 1, MAX_TIMELINE_COUNT)
    interval_ms = integer_option(options, "interval_ms", 100, 0, MAX_TIMELINE_MS)
    duration_ms = (count - 1) * interval_ms
    if duration_ms > MAX_TIMELINE_MS:
        raise InvalidOptions(f"The total wait must not exceed {MAX_TIMELINE_MS} ms.")
    set_log_options(options)
    for index in range(count):
        if index:
            sleep(interval_ms / 1000)
        emit("INFO", "timeline_step", sequence=index + 1)
    return summary(count, ["INFO"] * count, wait_ms=duration_ms)
