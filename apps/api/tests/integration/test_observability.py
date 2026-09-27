"""Phase 16 (§20/§21/§113/§124): every response carries a request
correlation id, error responses keep the existing `detail` shape the
frontend already reads (never a breaking rename), and production hides
internal exception details while development/test stay verbose."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_every_response_carries_a_request_id_header(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")


def test_a_client_supplied_request_id_is_echoed_back(client):
    response = client.get("/health", headers={"X-Request-ID": "test-fixed-id-123"})
    assert response.headers["X-Request-ID"] == "test-fixed-id-123"


def test_404_error_body_keeps_the_existing_detail_field_and_adds_request_id(client):
    response = client.get("/api/watchlist/symbols/123")  # invalid ticker -> 422, still error-shaped
    body = response.json()
    assert "detail" in body
    assert "request_id" in body
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_unknown_route_is_a_plain_404_with_request_id(client):
    response = client.get("/api/this-route-does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert "detail" in body
    assert "request_id" in body


def test_production_hides_exception_details_but_development_stays_verbose():
    from app.config import Environment
    from app.observability import exception_detail_for_response

    exc = ValueError("connection string was postgres://user:hunter2@host/db")

    prod_detail = exception_detail_for_response(exc, Environment.PRODUCTION)
    assert prod_detail == "Internal server error"
    assert "hunter2" not in prod_detail
    assert "postgres://" not in prod_detail

    dev_detail = exception_detail_for_response(exc, Environment.DEVELOPMENT)
    assert "ValueError" in dev_detail
    assert "connection string" in dev_detail
