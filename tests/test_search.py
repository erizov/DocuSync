"""Tests for search functionality."""

import pytest
from app.search import (
    search_documents, search_by_md5,
    get_documents_by_drive, get_document_statistics
)
from app.database import Document


def test_search_documents_empty(test_db):
    """Test search with no documents."""
    results = search_documents("test query")

    assert isinstance(results, list)
    assert len(results) == 0


def test_search_by_md5(test_db):
    """Test search by MD5 hash."""
    results = search_by_md5("dummy_hash")

    assert isinstance(results, list)


def test_get_documents_by_drive(test_db):
    """Test getting documents by drive."""
    results = get_documents_by_drive("C")

    assert isinstance(results, list)


def test_get_document_statistics(test_db):
    """Test getting document statistics."""
    stats = get_document_statistics()

    assert isinstance(stats, dict)
    assert "total_documents" in stats
    assert "total_size_bytes" in stats
    assert "by_drive" in stats
    assert "by_type" in stats

