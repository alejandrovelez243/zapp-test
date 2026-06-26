"""Tests for GET /health.

Requirement: platform-scaffold-008
  WHEN a client requests GET /health THE SYSTEM SHALL respond with HTTP 200
  and a JSON status body.
"""

from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_200_ok() -> None:
    """GET /health -> 200 {"status": "ok"}.  # platform-scaffold-008"""
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
