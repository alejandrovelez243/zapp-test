"""Unit tests for app/rag/ingest.py.

All DB access is mocked via a fake ``AsyncSession`` (``MagicMock``).
Embedding calls use a ``FakeEmbedder`` that returns deterministic canned vectors.

NO real DB, NO real gateway, NO SQLite/aiosqlite.
``DocumentChunk.embedding`` is a pgvector ``Vector(1536)`` column; SQLite cannot
create that column type.  The real pgvector path is exercised via docker Postgres
and the eval suite (task 12).

Mocking strategy
----------------
- ``db.get(Document, id)`` -> ``AsyncMock(return_value=doc)``
  Always returns the same ``Document`` instance so in-place status mutations are
  visible on the second ``db.get()`` call inside ``reingest_and_swap``.
- ``db.add(obj)``           -> ``MagicMock()`` (sync in SQLAlchemy AsyncSession)
- ``db.flush()``            -> ``AsyncMock()`` (no-op)
- ``db.commit()``           -> ``AsyncMock()`` (no-op)
- ``db.execute(stmt)``      -> ``AsyncMock(return_value=result_mock)``
  ``result_mock.scalars().all()`` is configurable per test (defaults to ``[]``).
- ``db.delete(obj)``        -> ``AsyncMock()`` (no-op)

Requirements: faq-rag-003, faq-rag-004, faq-rag-008, faq-rag-018
Design contract: specs/faq-rag/design.md §2.3
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.rag.embeddings import EmbeddingService
from app.rag.ingest import (
    chunk_text,
    extract_text,
    ingest_document,
    reingest_and_swap,
)
from app.rag.models import Document, DocumentChunk

# ---------------------------------------------------------------------------
# Fake embedder (inherits EmbeddingService for type-compat; no Embedder used)
# ---------------------------------------------------------------------------


class FakeEmbedder(EmbeddingService):
    """Deterministic stand-in for EmbeddingService.  No network calls."""

    def __init__(
        self,
        dim: int = 3,
        raise_exc: Exception | None = None,
    ) -> None:
        super().__init__()  # sets self._embedder = None (no key needed)
        self.dim = dim
        self.raise_exc = raise_exc
        self.calls: list[list[str]] = []

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return canned vectors; raise if configured to do so."""
        self.calls.append(texts)
        if self.raise_exc is not None:
            raise self.raise_exc
        return [[float(i)] * self.dim for i in range(len(texts))]


# ---------------------------------------------------------------------------
# Mocked AsyncSession factory
# ---------------------------------------------------------------------------


def _make_db(
    doc: Document | None = None,
    old_chunks: list[DocumentChunk] | None = None,
) -> MagicMock:
    """Return a minimally-mocked AsyncSession.

    ``db.get`` always returns *doc*.
    ``db.execute`` returns a result whose ``scalars().all()`` yields *old_chunks*
    (defaults to ``[]``).
    ``db.add`` is a sync MagicMock (SQLAlchemy AsyncSession.add is synchronous).
    ``db.flush``, ``db.commit``, ``db.delete`` are AsyncMock no-ops.
    """
    db = MagicMock()
    db.get = AsyncMock(return_value=doc)

    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = old_chunks or []
    db.execute = AsyncMock(return_value=result_mock)

    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.delete = AsyncMock()
    return db


def _make_doc(document_id: int = 1, status: str = "pending") -> Document:
    """Create a real Document instance (no DB needed — no Vector column here)."""
    return Document(id=document_id, name="test.txt", content_type="txt", status=status)


# ---------------------------------------------------------------------------
# Autouse fixture: supply required env vars for get_settings()
# (database_url + admin_token have no defaults; called inside ingest_document)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _env_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set required env vars so get_settings() succeeds in ingest tests."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/test")
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")


# ---------------------------------------------------------------------------
# TestExtractText
# ---------------------------------------------------------------------------


class TestExtractText:
    """Tests for extract_text() — req: faq-rag-003."""

    def test_txt_decode_utf8(self) -> None:
        """Plain text bytes are decoded as UTF-8.

        req: faq-rag-003
        """
        text = "Hello world — philosophy!"
        result = extract_text(text.encode("utf-8"), "txt")
        assert result == text

    def test_md_decode_utf8(self) -> None:
        """Markdown bytes are decoded as UTF-8.

        req: faq-rag-003
        """
        text = "# Título\n\nContenido en español."
        result = extract_text(text.encode("utf-8"), "md")
        assert result == text

    def test_pdf_extraction_via_mocked_pypdf(self) -> None:
        """PDF content_type delegates to PdfReader; text is joined by newlines.

        req: faq-rag-003
        """
        page1 = MagicMock()
        page1.extract_text.return_value = "Page one text."
        page2 = MagicMock()
        page2.extract_text.return_value = "Page two text."

        with patch("app.rag.ingest.PdfReader") as mock_reader_cls:
            mock_reader_cls.return_value.pages = [page1, page2]
            result = extract_text(b"fake-pdf-bytes", "pdf")

        assert result == "Page one text.\nPage two text."

    def test_pdf_none_page_text_becomes_empty_string(self) -> None:
        """Pages returning None from extract_text() are treated as empty string.

        req: faq-rag-003
        """
        page = MagicMock()
        page.extract_text.return_value = None

        with patch("app.rag.ingest.PdfReader") as mock_reader_cls:
            mock_reader_cls.return_value.pages = [page]
            result = extract_text(b"fake-pdf-bytes", "pdf")

        assert result == ""

    def test_unsupported_content_type_raises_value_error(self) -> None:
        """Unknown content_type raises ValueError.

        req: faq-rag-003
        """
        with pytest.raises(ValueError, match="Unsupported content_type"):
            extract_text(b"data", "docx")


# ---------------------------------------------------------------------------
# TestChunkText
# ---------------------------------------------------------------------------


class TestChunkText:
    """Tests for chunk_text() — req: faq-rag-003."""

    def test_empty_string_returns_empty_list(self) -> None:
        """Blank text produces no chunks.

        req: faq-rag-003
        """
        assert chunk_text("", chunk_size=100, chunk_overlap=10) == []

    def test_text_shorter_than_chunk_size_produces_one_chunk(self) -> None:
        """Text shorter than chunk_size yields a single chunk equal to the text.

        req: faq-rag-003
        """
        text = "Short text."
        result = chunk_text(text, chunk_size=100, chunk_overlap=10)
        assert result == [text]

    def test_no_overlap_chunks_cover_full_text(self) -> None:
        """With overlap=0, chunks tile the text without repeating characters.

        req: faq-rag-003
        """
        text = "abcdefghij"  # 10 chars
        result = chunk_text(text, chunk_size=3, chunk_overlap=0)
        # windows: "abc", "def", "ghi", "j"
        assert result == ["abc", "def", "ghi", "j"]

    def test_overlap_creates_shared_characters(self) -> None:
        """With overlap=2, consecutive chunks share 2 trailing characters.

        text="abcde", chunk_size=4, overlap=2, step=2:
          window[0:4]="abcd", window[2:6]="cde", window[4:8]="e"

        req: faq-rag-003
        """
        text = "abcde"  # 5 chars; chunk_size=4, overlap=2, step=2
        result = chunk_text(text, chunk_size=4, chunk_overlap=2)
        # windows: "abcd", "cde", "e" — overlap means re-entering from step=2
        assert result == ["abcd", "cde", "e"]
        # Verify overlap: tail of chunk[0] equals head of chunk[1] (2-char overlap)
        assert result[0][-2:] == result[1][:2]

    def test_chunk_sizes_respect_chunk_size(self) -> None:
        """No chunk exceeds chunk_size characters.

        req: faq-rag-003
        """
        text = "x" * 50
        result = chunk_text(text, chunk_size=10, chunk_overlap=3)
        assert all(len(c) <= 10 for c in result)

    def test_first_and_second_chunk_share_overlap(self) -> None:
        """The tail of chunk[i] equals the head of chunk[i+1] up to overlap chars.

        req: faq-rag-003
        """
        text = "ABCDEFGHIJ"  # 10 chars; size=6, overlap=2, step=4
        result = chunk_text(text, chunk_size=6, chunk_overlap=2)
        # chunks: [0:6]="ABCDEF", [4:10]="EFGHIJ"
        assert result[0][-2:] == result[1][:2]


# ---------------------------------------------------------------------------
# TestIngestDocument
# ---------------------------------------------------------------------------


class TestIngestDocument:
    """Tests for ingest_document() — req: faq-rag-003, faq-rag-004, faq-rag-018."""

    async def test_happy_path_status_ready(self) -> None:
        """On success Document.status transitions to 'ready'.

        req: faq-rag-003, faq-rag-004
        """
        doc = _make_doc()
        db = _make_db(doc=doc)
        content = b"Hello philosophy world."
        await ingest_document(db, doc.id or 1, content, "txt", FakeEmbedder())
        assert doc.status == "ready"

    async def test_happy_path_chunks_added_to_db(self) -> None:
        """db.add() is called once per chunk produced by chunk_text.

        req: faq-rag-003
        """
        doc = _make_doc()
        db = _make_db(doc=doc)
        # With defaults chunk_size=1000, overlap=150 and this short text → 1 chunk.
        content = b"Short philosophy text."
        await ingest_document(db, doc.id or 1, content, "txt", FakeEmbedder())
        # db.add was called once (one chunk from the short text).
        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert isinstance(added, DocumentChunk)
        assert added.text == "Short philosophy text."
        assert added.ordinal == 0

    async def test_happy_path_multiple_chunks(self) -> None:
        """Multiple chunks produce multiple db.add() calls.

        req: faq-rag-003
        """
        doc = _make_doc()
        db = _make_db(doc=doc)
        # chunk_size=5, overlap=0 → 3 chunks for "Hello world!" (12 chars)
        # Override settings via small chunk_size by patching get_settings.
        from app.config import Settings

        fake_settings = Settings(
            database_url="postgresql+asyncpg://x:x@localhost/x",
            admin_token="tok",
            chunk_size=5,
            chunk_overlap=0,
        )
        with patch("app.rag.ingest.get_settings", return_value=fake_settings):
            content = b"Hello world!"
            await ingest_document(db, doc.id or 1, content, "txt", FakeEmbedder())

        # "Hello", " worl", "d!" → 3 chunks
        assert db.add.call_count == 3

    async def test_happy_path_commit_called(self) -> None:
        """db.commit() is called exactly once on success.

        req: faq-rag-003
        """
        doc = _make_doc()
        db = _make_db(doc=doc)
        await ingest_document(db, doc.id or 1, b"text", "txt", FakeEmbedder())
        db.commit.assert_called_once()

    async def test_embedder_failure_sets_status_failed(self) -> None:
        """When the embedder raises, Document.status becomes 'failed'.

        req: faq-rag-018
        """
        doc = _make_doc()
        db = _make_db(doc=doc)
        exc = RuntimeError("embed gateway down")
        embedder = FakeEmbedder(raise_exc=exc)
        await ingest_document(db, doc.id or 1, b"some text", "txt", embedder)
        assert doc.status == "failed"

    async def test_embedder_failure_stores_error_message(self) -> None:
        """The error message is stored verbatim in Document.error.

        req: faq-rag-018
        """
        doc = _make_doc()
        db = _make_db(doc=doc)
        embedder = FakeEmbedder(raise_exc=RuntimeError("timeout"))
        await ingest_document(db, doc.id or 1, b"some text", "txt", embedder)
        assert doc.error == "timeout"

    async def test_embedder_failure_commits_failed_status(self) -> None:
        """On failure, db.commit() is still called to persist status=failed.

        req: faq-rag-018
        """
        doc = _make_doc()
        db = _make_db(doc=doc)
        embedder = FakeEmbedder(raise_exc=RuntimeError("err"))
        await ingest_document(db, doc.id or 1, b"text", "txt", embedder)
        db.commit.assert_called_once()

    async def test_extract_failure_sets_status_failed(self) -> None:
        """Unsupported content_type during extract -> status=failed, corpus intact.

        req: faq-rag-018
        """
        doc = _make_doc()
        db = _make_db(doc=doc)
        await ingest_document(db, doc.id or 1, b"data", "docx", FakeEmbedder())
        assert doc.status == "failed"
        assert doc.error is not None

    async def test_missing_document_returns_early(self) -> None:
        """When db.get returns None (document deleted), the function is a no-op.

        req: faq-rag-003
        """
        db = _make_db(doc=None)
        # Should not raise; db.add / db.flush / db.commit not called.
        await ingest_document(db, 99, b"text", "txt", FakeEmbedder())
        db.add.assert_not_called()
        db.commit.assert_not_called()

    async def test_status_transitions_ingesting_then_ready(self) -> None:
        """Document status passes through 'ingesting' before reaching 'ready'.

        req: faq-rag-003
        """
        doc = _make_doc()
        statuses: list[str] = []

        original_flush = AsyncMock()

        async def _recording_flush() -> None:
            statuses.append(doc.status)
            await original_flush()

        db = _make_db(doc=doc)
        db.flush = _recording_flush

        await ingest_document(db, doc.id or 1, b"text", "txt", FakeEmbedder())

        assert "ingesting" in statuses
        assert doc.status == "ready"


# ---------------------------------------------------------------------------
# TestReingestAndSwap
# ---------------------------------------------------------------------------


class TestReingestAndSwap:
    """Tests for reingest_and_swap() — req: faq-rag-008."""

    def _make_old_chunk(self, doc_id: int = 1, ordinal: int = 0) -> MagicMock:
        """Return a MagicMock with DocumentChunk spec (avoids Vector column)."""
        chunk = MagicMock(spec=DocumentChunk)
        chunk.document_id = doc_id
        chunk.ordinal = ordinal
        return chunk

    async def test_old_chunks_deleted_on_success(self) -> None:
        """Old DocumentChunk rows are deleted after a successful re-ingest.

        req: faq-rag-008
        """
        doc = _make_doc(status="pending")
        old_chunk1 = self._make_old_chunk(ordinal=0)
        old_chunk2 = self._make_old_chunk(ordinal=1)
        db = _make_db(doc=doc, old_chunks=[old_chunk1, old_chunk2])

        await reingest_and_swap(db, doc.id or 1, b"new text", "txt", FakeEmbedder())

        assert doc.status == "ready"
        # db.delete called for each old chunk.
        assert db.delete.call_count == 2
        deleted_objs = [c.args[0] for c in db.delete.call_args_list]
        assert old_chunk1 in deleted_objs
        assert old_chunk2 in deleted_objs

    async def test_new_chunks_committed_before_deletion(self) -> None:
        """db.commit is called at least twice: once for ingest, once for deletion.

        req: faq-rag-008
        """
        doc = _make_doc()
        old_chunk = self._make_old_chunk()
        db = _make_db(doc=doc, old_chunks=[old_chunk])

        await reingest_and_swap(db, doc.id or 1, b"text", "txt", FakeEmbedder())

        # At minimum: one commit inside ingest_document, one after deleting old chunks.
        assert db.commit.call_count >= 2

    async def test_old_chunks_preserved_when_ingest_fails(self) -> None:
        """On embedder failure, old chunks are NOT deleted (corpus stays usable).

        req: faq-rag-008
        """
        doc = _make_doc()
        old_chunk = self._make_old_chunk()
        db = _make_db(doc=doc, old_chunks=[old_chunk])
        embedder = FakeEmbedder(raise_exc=RuntimeError("embed failed"))

        await reingest_and_swap(db, doc.id or 1, b"text", "txt", embedder)

        assert doc.status == "failed"
        db.delete.assert_not_called()

    async def test_no_old_chunks_deletion_is_noop(self) -> None:
        """With no pre-existing chunks, deletion loop is a no-op; no db.delete call.

        req: faq-rag-008
        """
        doc = _make_doc()
        db = _make_db(doc=doc, old_chunks=[])

        await reingest_and_swap(db, doc.id or 1, b"text", "txt", FakeEmbedder())

        db.delete.assert_not_called()
        assert doc.status == "ready"

    async def test_new_chunk_added_after_reingest(self) -> None:
        """db.add is called for the new chunk created during re-ingest.

        req: faq-rag-008
        """
        doc = _make_doc()
        old_chunk = self._make_old_chunk()
        db = _make_db(doc=doc, old_chunks=[old_chunk])

        await reingest_and_swap(db, doc.id or 1, b"new content", "txt", FakeEmbedder())

        db.add.assert_called()
        added = db.add.call_args[0][0]
        assert isinstance(added, DocumentChunk)
        assert added.text == "new content"
