from uuid import uuid4

from flask import Flask, g, request

from app.logging_utils import create_logger, emit
from app.routes import api


def create_app() -> Flask:
    application = Flask(__name__, static_folder=None)
    application.config.update(MAX_CONTENT_LENGTH=8192)
    application.extensions["fixture_logger"] = create_logger()
    application.register_blueprint(api)

    @application.before_request
    def start_request():
        g.request_id = str(uuid4())
        g.marker = "logs-test"
        g.log_format = "json"
        emit("INFO", f"request_started method={request.method} endpoint={request.endpoint}")

    @application.after_request
    def finish_request(response):
        level = "ERROR" if response.status_code >= 500 else "INFO"
        if 400 <= response.status_code < 500:
            level = "WARNING"
        emit(level, f"request_completed status_code={response.status_code}")
        response.headers["X-Log-Request-Id"] = g.request_id
        return response

    return application


app = create_app()
