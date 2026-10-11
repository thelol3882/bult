"""The global error format: AppError, validation errors, unknown exceptions."""

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import ConflictError
from app.core.logging import TraceIdFilter
from app.core.middleware import trace_id_var

APP_BODY = {
    "name": "blog",
    "preset": "fastapi",
    "repo_url": "https://github.com/example/blog.git",
}


def test_app_error_has_code_and_echoes_request_id(app: FastAPI):
    @app.get("/_conflict")
    async def conflict() -> None:
        raise ConflictError("it is taken", field="name")

    response = TestClient(app).get("/_conflict", headers={"X-Request-ID": "req-123"})

    assert response.status_code == 409
    assert response.headers["X-Request-ID"] == "req-123"
    assert response.json() == {
        "detail": "it is taken",
        "code": "conflict",
        "field": "name",
        "trace_id": "req-123",
    }


def test_request_id_is_generated_when_missing(client: TestClient):
    response = client.get("/apps/nope")

    assert response.status_code == 404
    trace_id = response.headers["X-Request-ID"]
    assert trace_id
    assert response.json()["trace_id"] == trace_id


def test_unknown_exception_is_a_generic_500(app: FastAPI):
    @app.get("/_boom")
    async def boom() -> None:
        raise RuntimeError("secret: /var/lib/bult/key")

    response = TestClient(app, raise_server_exceptions=False).get("/_boom")

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal_error"
    assert body["detail"] == "Internal server error"
    assert body["trace_id"] == response.headers["X-Request-ID"]
    assert "secret" not in response.text


def test_validation_error_names_the_field_without_the_request_part(
    client: TestClient,
):
    response = client.post("/apps", json={**APP_BODY, "preset": "ruby"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert set(body["fields"]) == {"preset"}  # not "body.preset"


def test_validation_error_for_missing_body_field_and_query(client: TestClient):
    response = client.post("/apps", json={"preset": "fastapi"})

    assert set(response.json()["fields"]) == {"name", "repo_url"}


def test_validation_error_for_broken_json_points_at_body(client: TestClient):
    response = client.post(
        "/apps", content="{not json", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422
    assert list(response.json()["fields"]) == ["body"]


def test_app_name_message_is_friendly_not_a_regex(client: TestClient):
    response = client.post("/apps", json={**APP_BODY, "name": "My_App"})

    message = response.json()["fields"]["name"]
    assert message.startswith("Use lowercase letters, digits and hyphens")
    assert "^[a-z0-9]" not in message


def test_unknown_route_uses_the_uniform_body(client: TestClient):
    response = client.get("/nope", headers={"X-Request-ID": "req-404"})

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Not Found",
        "code": "not_found",
        "trace_id": "req-404",
    }


def test_wrong_method_is_405_with_allow_header(client: TestClient):
    response = client.put("/apps")

    assert response.status_code == 405
    body = response.json()
    assert body["code"] == "method_not_allowed"
    assert body["trace_id"] == response.headers["X-Request-ID"]
    assert response.headers["Allow"]


def test_log_records_carry_the_trace_id(app: FastAPI, caplog):
    @app.get("/_log")
    async def log() -> None:
        logging.getLogger("app.test").warning("inside request")

    caplog.handler.addFilter(TraceIdFilter())
    TestClient(app).get("/_log", headers={"X-Request-ID": "req-log"})

    [record] = [r for r in caplog.records if r.message == "inside request"]
    assert record.trace_id == "req-log"  # pyright: ignore[reportAttributeAccessIssue]
    assert trace_id_var.get() == ""  # reset after the request
