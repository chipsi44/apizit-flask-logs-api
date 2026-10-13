import json
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest

from app import create_app


@pytest.fixture
def client(capsys):
    application = create_app()
    application.config.update(TESTING=True)
    return application.test_client()


def read_events(capsys):
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_route_contract(client):
    routes = {
        (rule.rule, tuple(sorted(rule.methods - {"HEAD", "OPTIONS"})))
        for rule in client.application.url_map.iter_rules()
    }
    assert routes == {
        ("/health", ("GET",)),
        ("/info", ("GET",)),
        ("/echo", ("POST",)),
        ("/items/<int:item_id>", ("GET",)),
        ("/slow", ("GET",)),
        ("/logs/sample", ("GET",)),
        ("/logs/burst", ("POST",)),
        ("/logs/exception", ("GET",)),
        ("/logs/multiline", ("GET",)),
        ("/logs/timeline", ("POST",)),
    }


def test_health_is_immediate_and_every_call_has_correlated_logs(client, capsys, monkeypatch):
    def forbidden_sleep(_):
        pytest.fail("Health must not sleep")

    monkeypatch.setattr("app.routes.sleep", forbidden_sleep)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}
    request_id = response.headers["X-Log-Request-Id"]
    assert str(UUID(request_id)) == request_id
    events = read_events(capsys)
    assert len(events) == 2
    assert {event["request_id"] for event in events} == {request_id}
    assert "request_started" in events[0]["message"]
    assert "request_completed status_code=200" in events[-1]["message"]


def test_info(client):
    response = client.get("/info")
    assert response.status_code == 200
    assert response.json["framework"] == "flask"
    assert response.json["profile"] == "logs"
    assert response.json["max_burst_count"] == 1000


def test_echo_does_not_log_body_headers_or_query_values(client, capsys):
    response = client.post(
        "/echo?private=private-query-probe",
        json={"message": "private-body-probe", "count": 2},
        headers={"Authorization": "Bearer private-header-probe", "x-api-key": "private-key-probe"},
    )
    assert response.status_code == 200
    assert response.json == {"received": {"message": "private-body-probe", "count": 2}}
    captured = capsys.readouterr().out
    for sensitive in (
        "private-query-probe",
        "private-body-probe",
        "private-header-probe",
        "private-key-probe",
    ):
        assert sensitive not in captured


@pytest.mark.parametrize(
    "payload",
    [None, [], {}, {"message": "", "count": 1}, {"message": "hi", "count": True}],
)
def test_echo_validation(client, payload):
    assert client.post("/echo", json=payload).status_code == 400


def test_item(client):
    response = client.get("/items/7?include_details=true")
    assert response.status_code == 200
    assert response.json == {
        "item_id": 7,
        "include_details": True,
        "details": "Reference item 7",
    }
    assert client.get("/items/7").json == {"item_id": 7, "include_details": False}


@pytest.mark.parametrize("path", ["/items/0", "/items/7?include_details=maybe"])
def test_item_validation(client, path):
    assert client.get(path).status_code == 400


def test_slow_keeps_reference_contract_without_waiting(client, monkeypatch):
    waits = []
    monkeypatch.setattr("app.routes.sleep", waits.append)
    response = client.get("/slow")
    assert response.status_code == 200
    assert response.json == {"delay_seconds": 80, "status": "completed"}
    assert waits == [80]


def test_sample_emits_all_levels_once_per_sequence(client, capsys):
    response = client.get("/logs/sample?marker=sample-01")
    assert response.status_code == 200
    assert response.json["generated_logs"] == 25
    assert response.json["level_counts"] == {
        "DEBUG": 5,
        "INFO": 5,
        "WARNING": 5,
        "ERROR": 5,
        "CRITICAL": 5,
    }
    events = read_events(capsys)
    assert len(events) == 27
    batch = events[1:-1]
    assert [event["sequence"] for event in batch] == list(range(1, 26))
    assert {event["marker"] for event in batch} == {"sample-01"}
    for event in batch:
        assert response.json["request_id"] in event["message"]
        assert "marker=sample-01" in event["message"]


def test_burst_defaults(client, capsys):
    response = client.post("/logs/burst", json={})
    assert response.status_code == 200
    assert response.json["generated_logs"] == 100
    assert len(read_events(capsys)) == 102


def test_maximum_burst_volume_and_sequence(client, capsys):
    response = client.post(
        "/logs/burst", json={"count": 1000, "message_chars": 512, "marker": "m" * 64}
    )
    assert response.status_code == 200
    captured = capsys.readouterr().out
    events = [json.loads(line) for line in captured.splitlines()]
    assert len(events) == 1002
    assert [event["sequence"] for event in events[1:-1]] == list(range(1, 1001))
    assert all(event["marker"] == "m" * 64 for event in events[1:-1])
    assert len(captured.encode("utf-8")) < 1024 * 1024


@pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
def test_single_level_burst(client, capsys, level):
    response = client.post("/logs/burst", json={"count": 3, "level": level})
    assert response.status_code == 200
    assert response.json["level_counts"] == {level: 3}
    assert [event["level"] for event in read_events(capsys)[1:-1]] == [level] * 3


@pytest.mark.parametrize(
    "options",
    [
        {"count": 0},
        {"count": 1001},
        {"count": -1},
        {"count": True},
        {"count": 1.5},
        {"count": "100"},
        {"message_chars": -1},
        {"message_chars": 513},
        {"message_chars": False},
        {"level": "fatal"},
        {"level": []},
        {"format": "xml"},
        {"format": []},
        {"marker": ""},
        {"marker": "a" * 65},
        {"marker": "one\n[ERROR] forged"},
        {"marker": "one\rforged"},
        {"marker": "one\x1b[31m"},
        {"marker": []},
        {"message": "private-unaccepted-body-probe"},
    ],
)
def test_invalid_burst_options_cannot_emit_bulk_or_injected_logs(client, capsys, options):
    response = client.post("/logs/burst", json=options)
    assert response.status_code == 400
    events = read_events(capsys)
    assert len(events) == 3
    assert all(event["sequence"] == 0 for event in events)
    assert all("forged" not in event["message"] for event in events)
    assert all("private-unaccepted-body-probe" not in event["message"] for event in events)


@pytest.mark.parametrize("payload", [None, [], "string", 2])
def test_burst_requires_json_object(client, payload):
    assert client.post("/logs/burst", json=payload).status_code == 400


def test_oversized_body_is_rejected_before_bulk_generation(client, capsys):
    response = client.post("/logs/burst", data=" " * 8193, content_type="application/json")
    assert response.status_code == 413
    assert len(read_events(capsys)) == 2


def test_text_format_and_handler_does_not_duplicate_logs(client, capsys):
    response = client.post(
        "/logs/burst", json={"count": 2, "level": "WARNING", "format": "text", "marker": "text-01"}
    )
    assert response.status_code == 200
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 4
    assert json.loads(lines[0])["sequence"] == 0
    assert all(line.startswith("[WARNING]") for line in lines[1:3])
    assert all("marker=text-01" in line for line in lines[1:])
    assert lines[-1].startswith("[INFO]")


@pytest.mark.parametrize("log_format", ["json", "text"])
def test_exception_has_stack_and_api_recovers(client, capsys, log_format):
    response = client.get(f"/logs/exception?format={log_format}&marker=failure-01")
    assert response.status_code == 500
    assert response.json["generated_logs"] == 1
    captured = capsys.readouterr().out
    assert "Traceback (most recent call last)" in captured
    assert "RuntimeError: Intentional synthetic failure" in captured
    if log_format == "json":
        events = [json.loads(line) for line in captured.splitlines()]
        assert len(events) == 3
        assert events[1]["level"] == "ERROR"
        assert "\n" in events[1]["message"]
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize("log_format", ["json", "text"])
def test_multiline_and_unicode(client, capsys, log_format):
    response = client.get(f"/logs/multiline?format={log_format}")
    assert response.status_code == 200
    assert response.json["generated_logs"] == 3
    captured = capsys.readouterr().out
    assert "été, français, café" in captured
    assert "日本語" in captured
    assert "العربية" in captured
    assert "🚀" in captured
    if log_format == "json":
        events = [json.loads(line) for line in captured.splitlines()]
        assert len(events) == 5
        assert "multiline_start\nsecond line\nthird line" in events[1]["message"]
    else:
        assert "multiline_start\nsecond line\nthird line" in captured


def test_timeline_paces_logs_and_limits_total_wait(client, capsys, monkeypatch):
    waits = []
    monkeypatch.setattr("app.routes.sleep", waits.append)
    response = client.post("/logs/timeline", json={"count": 11, "interval_ms": 500})
    assert response.status_code == 200
    assert response.json["wait_ms"] == 5000
    assert waits == [0.5] * 10
    assert len(read_events(capsys)) == 13


@pytest.mark.parametrize(
    "options",
    [{"count": 0}, {"count": 51}, {"interval_ms": -1}, {"count": 11, "interval_ms": 501}],
)
def test_timeline_rejects_excessive_wait_before_sleep(client, monkeypatch, options):
    def forbidden_sleep(_):
        pytest.fail("Invalid requests must not wait")

    monkeypatch.setattr("app.routes.sleep", forbidden_sleep)
    assert client.post("/logs/timeline", json=options).status_code == 400


def test_concurrent_calls_keep_independent_ids_and_markers(client, capsys):
    application = client.application

    def invoke(index):
        with application.test_client() as concurrent_client:
            return concurrent_client.post(
                "/logs/burst", json={"count": 10, "marker": f"parallel-{index}"}
            ).json

    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(executor.map(invoke, range(8)))
    events = read_events(capsys)
    assert len(events) == 96
    assert len({response["request_id"] for response in responses}) == 8
    for response in responses:
        correlated = [event for event in events if event["request_id"] == response["request_id"]]
        assert len(correlated) == 12
        synthetic = [event for event in correlated if event["sequence"] > 0]
        assert [event["sequence"] for event in synthetic] == list(range(1, 11))
        assert {event["marker"] for event in synthetic} == {response["marker"]}
