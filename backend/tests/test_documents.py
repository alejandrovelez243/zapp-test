"""Tests for app/api/documents.py — admin document endpoints.

Strategy
--------
- ``get_session`` is overridden with a minimal mock so no real DB is needed.
- ``_background_ingest`` / ``_background_reingest`` are patched to AsyncMock so
  no real gateway or DB connection is touched during background tasks.
- ``DocumentChunk.embedding`` is a pgvector Vector column that SQLite cannot
  create; the mock avoids any DB schema concern entirely.

Requirements: faq-rag-001, faq-rag-002, faq-rag-006, faq-rag-007, faq-rag-008
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db import get_session
from app.main import app
from app.rag.models import Document

_TOKEN = "secret-token"


# ---------------------------------------------------------------------------
# Autouse env — required fields for get_settings()
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Supply required env vars so get_settings() succeeds inside endpoints."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/test")
    monkeypatch.setenv("ADMIN_TOKEN", _TOKEN)


# ---------------------------------------------------------------------------
# Mock DB session
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_db() -> MagicMock:
    """Minimal AsyncSession mock.

    ``db.flush`` side-effect assigns ``id=1`` to any ``Document`` that was
    ``db.add``-ed without an id, simulating the auto-increment behaviour.
    """
    db = MagicMock()
    _added: list[Any] = []

    def _add(obj: Any) -> None:
        _added.append(obj)

    async def _flush() -> None:
        for obj in _added:
            if isinstance(obj, Document) and obj.id is None:
                obj.id = 1

    db.add = MagicMock(side_effect=_add)
    db.flush = AsyncMock(side_effect=_flush)
    db.get = AsyncMock(return_value=None)
    db.commit = AsyncMock()
    db.delete = AsyncMock()
    db.rollback = AsyncMock()

    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result_mock)
    return db


# ---------------------------------------------------------------------------
# TestClient fixture with overridden session
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(mock_db: MagicMock) -> Generator[TestClient, None, None]:
    """Return a TestClient whose DB session is replaced by ``mock_db``."""

    async def _override() -> AsyncGenerator[Any, None]:
        yield mock_db

    app.dependency_overrides[get_session] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /documents
# ---------------------------------------------------------------------------


class TestUploadDocument:
    """POST /documents — req: faq-rag-001, faq-rag-002, faq-rag-003."""

    def test_missing_token_returns_401(self, client: TestClient) -> None:
        """No X-Admin-Token header → 401; no DB mutation.

        req: faq-rag-002
        """
        resp = client.post(
            "/documents",
            files={"file": ("test.txt", b"hello", "text/plain")},
        )
        assert resp.status_code == 401

    def test_wrong_token_returns_403(self, client: TestClient) -> None:
        """Wrong token value → 403.

        req: faq-rag-002
        """
        resp = client.post(
            "/documents",
            files={"file": ("test.txt", b"hello", "text/plain")},
            headers={"X-Admin-Token": "wrong-token"},
        )
        assert resp.status_code == 403

    def test_valid_token_returns_202_with_doc_id(self, client: TestClient) -> None:
        """Valid token + txt file → 202 with {id: 1}.

        req: faq-rag-001
        """
        with patch("app.api.documents._background_ingest", new_callable=AsyncMock):
            resp = client.post(
                "/documents",
                files={"file": ("notes.txt", b"philosophy text", "text/plain")},
                headers={"X-Admin-Token": _TOKEN},
            )
        assert resp.status_code == 202
        assert resp.json()["id"] == 1

    def test_valid_token_schedules_background_ingest(self, client: TestClient) -> None:
        """Background ingest callable is invoked exactly once.

        req: faq-rag-003
        """
        with patch("app.api.documents._background_ingest", new_callable=AsyncMock) as mock_ingest:
            client.post(
                "/documents",
                files={"file": ("doc.md", b"# Philosophy", "text/markdown")},
                headers={"X-Admin-Token": _TOKEN},
            )
        mock_ingest.assert_called_once()

    def test_creates_pending_document_with_correct_fields(
        self, client: TestClient, mock_db: MagicMock
    ) -> None:
        """db.add is called with a Document(status=pending, content_type=txt).

        req: faq-rag-001
        """
        with patch("app.api.documents._background_ingest", new_callable=AsyncMock):
            client.post(
                "/documents",
                files={"file": ("course.txt", b"content", "text/plain")},
                headers={"X-Admin-Token": _TOKEN},
            )
        mock_db.add.assert_called_once()
        added = mock_db.add.call_args[0][0]
        assert isinstance(added, Document)
        assert added.status == "pending"
        assert added.content_type == "txt"

    def test_unsupported_extension_returns_422_no_add(
        self, client: TestClient, mock_db: MagicMock
    ) -> None:
        """.docx → 422; db.add NOT called.

        req: faq-rag-001
        """
        resp = client.post(
            "/documents",
            files={"file": ("report.docx", b"data", "application/octet-stream")},
            headers={"X-Admin-Token": _TOKEN},
        )
        assert resp.status_code == 422
        mock_db.add.assert_not_called()

    def test_missing_token_no_db_add(self, client: TestClient, mock_db: MagicMock) -> None:
        """Missing token → db.add is never called.

        req: faq-rag-002
        """
        client.post(
            "/documents",
            files={"file": ("test.txt", b"x", "text/plain")},
        )
        mock_db.add.assert_not_called()


# ---------------------------------------------------------------------------
# GET /documents
# ---------------------------------------------------------------------------


class TestListDocuments:
    """GET /documents — req: faq-rag-006, faq-rag-002."""

    def test_missing_token_returns_401(self, client: TestClient) -> None:
        """No token → 401.

        req: faq-rag-002
        """
        resp = client.get("/documents")
        assert resp.status_code == 401

    def test_returns_list_of_document_summaries(
        self, client: TestClient, mock_db: MagicMock
    ) -> None:
        """Returns [{id, name, status}] for each stored document.

        req: faq-rag-006
        """
        doc = Document(id=5, name="test.txt", content_type="txt", status="ready")
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [doc]
        mock_db.execute = AsyncMock(return_value=result_mock)

        resp = client.get("/documents", headers={"X-Admin-Token": _TOKEN})

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0] == {"id": 5, "name": "test.txt", "status": "ready"}

    def test_empty_corpus_returns_empty_list(self, client: TestClient) -> None:
        """No documents → 200 with empty list.

        req: faq-rag-006
        """
        resp = client.get("/documents", headers={"X-Admin-Token": _TOKEN})
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# DELETE /documents/{id}
# ---------------------------------------------------------------------------


class TestDeleteDocument:
    """DELETE /documents/{id} — req: faq-rag-007, faq-rag-002."""

    def test_missing_token_returns_401(self, client: TestClient) -> None:
        """No token → 401.

        req: faq-rag-002
        """
        resp = client.delete("/documents/1")
        assert resp.status_code == 401

    def test_delete_existing_doc_returns_204(self, client: TestClient, mock_db: MagicMock) -> None:
        """Existing doc → 204; db.delete is called.

        req: faq-rag-007
        """
        doc = Document(id=1, name="test.txt", content_type="txt", status="ready")
        mock_db.get = AsyncMock(return_value=doc)

        resp = client.delete("/documents/1", headers={"X-Admin-Token": _TOKEN})

        assert resp.status_code == 204
        mock_db.delete.assert_called()

    def test_delete_nonexistent_doc_returns_404(
        self, client: TestClient, mock_db: MagicMock
    ) -> None:
        """Non-existent doc → 404.

        req: faq-rag-007
        """
        mock_db.get = AsyncMock(return_value=None)
        resp = client.delete("/documents/99", headers={"X-Admin-Token": _TOKEN})
        assert resp.status_code == 404

    def test_missing_token_no_db_delete(self, client: TestClient, mock_db: MagicMock) -> None:
        """Missing token → db.delete NOT called.

        req: faq-rag-002
        """
        client.delete("/documents/1")
        mock_db.delete.assert_not_called()


# ---------------------------------------------------------------------------
# PUT /documents/{id}
# ---------------------------------------------------------------------------


class TestUpdateDocument:
    """PUT /documents/{id} — req: faq-rag-008, faq-rag-002."""

    def test_missing_token_returns_401(self, client: TestClient) -> None:
        """No token → 401.

        req: faq-rag-002
        """
        resp = client.put(
            "/documents/1",
            files={"file": ("new.txt", b"new content", "text/plain")},
        )
        assert resp.status_code == 401

    def test_update_existing_doc_returns_202(self, client: TestClient, mock_db: MagicMock) -> None:
        """Valid token + existing doc → 202 with {id}.

        req: faq-rag-008
        """
        doc = Document(id=1, name="old.txt", content_type="txt", status="ready")
        mock_db.get = AsyncMock(return_value=doc)

        with patch("app.api.documents._background_reingest", new_callable=AsyncMock):
            resp = client.put(
                "/documents/1",
                files={"file": ("new.txt", b"new content", "text/plain")},
                headers={"X-Admin-Token": _TOKEN},
            )
        assert resp.status_code == 202
        assert resp.json()["id"] == 1

    def test_update_schedules_reingest(self, client: TestClient, mock_db: MagicMock) -> None:
        """reingest_and_swap is scheduled as a background task.

        req: faq-rag-008
        """
        doc = Document(id=1, name="old.txt", content_type="txt", status="ready")
        mock_db.get = AsyncMock(return_value=doc)

        with patch(
            "app.api.documents._background_reingest", new_callable=AsyncMock
        ) as mock_reingest:
            client.put(
                "/documents/1",
                files={"file": ("new.txt", b"new content", "text/plain")},
                headers={"X-Admin-Token": _TOKEN},
            )
        mock_reingest.assert_called_once()

    def test_update_nonexistent_doc_returns_404(
        self, client: TestClient, mock_db: MagicMock
    ) -> None:
        """Non-existent doc → 404.

        req: faq-rag-008
        """
        mock_db.get = AsyncMock(return_value=None)
        resp = client.put(
            "/documents/99",
            files={"file": ("x.txt", b"x", "text/plain")},
            headers={"X-Admin-Token": _TOKEN},
        )
        assert resp.status_code == 404
