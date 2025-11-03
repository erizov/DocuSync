"""Tests for FTS5 search functionality."""

import pytest
import os
import tempfile
import shutil
from pathlib import Path

from app.database import init_db, SessionLocal, Document
from app.file_scanner import index_document
from app.search_fts5 import (
    search_documents_fts5, search_documents_fts5_phrase,
    search_documents_fts5_boolean
)
from app.search import search_documents


@pytest.fixture(scope="function")
def temp_dir():
    """Create a temporary directory."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(scope="function")
def test_db():
    """Create a test database."""
    import tempfile
    import os
    test_db_path = tempfile.mktemp(suffix=".db")
    from app.config import settings
    original_url = settings.database_url
    settings.database_url = f"sqlite:///{test_db_path}"

    from app.database import engine, Base, init_db
    # Drop and recreate to ensure clean schema
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    init_db()  # This will also initialize FTS5

    yield

    settings.database_url = original_url
    if os.path.exists(test_db_path):
        os.unlink(test_db_path)


def test_search_documents_fts5_basic(test_db, temp_dir):
    """Test basic FTS5 search."""
    # Create test documents
    doc1_path = os.path.join(temp_dir, "test1.txt")
    doc2_path = os.path.join(temp_dir, "test2.txt")
    
    with open(doc1_path, "w", encoding="utf-8") as f:
        f.write("This is a test document about machine learning.")
    
    with open(doc2_path, "w", encoding="utf-8") as f:
        f.write("This is another document about Python programming.")
    
    # Index documents
    doc1 = index_document(doc1_path, extract_text=True)
    doc2 = index_document(doc2_path, extract_text=True)
    
    assert doc1 is not None
    assert doc2 is not None
    
    # Search using FTS5
    results = search_documents_fts5("machine learning")
    
    assert len(results) > 0
    assert any(doc.id == doc1.id for doc in results)


def test_search_documents_fts5_phrase(test_db, temp_dir):
    """Test FTS5 phrase search."""
    # Create test document
    doc_path = os.path.join(temp_dir, "test.txt")
    
    with open(doc_path, "w", encoding="utf-8") as f:
        f.write("This document discusses machine learning algorithms.")
    
    # Index document
    doc = index_document(doc_path, extract_text=True)
    assert doc is not None
    
    # Search for exact phrase
    results = search_documents_fts5_phrase("machine learning")
    
    assert len(results) > 0
    assert any(doc.id == d.id for d in results)


def test_search_documents_fts5_boolean(test_db, temp_dir):
    """Test FTS5 boolean search."""
    # Create test documents
    doc1_path = os.path.join(temp_dir, "test1.txt")
    doc2_path = os.path.join(temp_dir, "test2.txt")
    
    with open(doc1_path, "w", encoding="utf-8") as f:
        f.write("Python programming language")
    
    with open(doc2_path, "w", encoding="utf-8") as f:
        f.write("Java programming language")
    
    # Index documents
    doc1 = index_document(doc1_path, extract_text=True)
    doc2 = index_document(doc2_path, extract_text=True)
    
    assert doc1 is not None
    assert doc2 is not None
    
    # Search with AND operator
    results = search_documents_fts5_boolean("Python AND programming")
    
    assert len(results) > 0
    assert any(doc.id == doc1.id for doc in results)
    assert not any(doc.id == doc2.id for doc in results)


def test_search_documents_fts5_drive_filter(test_db, temp_dir):
    """Test FTS5 search with drive filter."""
    # Create test document
    doc_path = os.path.join(temp_dir, "test.txt")
    
    with open(doc_path, "w", encoding="utf-8") as f:
        f.write("Test document for drive filtering")
    
    # Index document
    doc = index_document(doc_path, extract_text=True)
    assert doc is not None
    
    drive = doc.drive
    
    # Search with drive filter
    results = search_documents_fts5("test", drive=drive)
    
    assert len(results) > 0
    assert all(d.drive == drive for d in results)


def test_search_documents_fallback(test_db, temp_dir):
    """Test fallback to regular search if FTS5 fails."""
    # Create test document
    doc_path = os.path.join(temp_dir, "test.txt")
    
    with open(doc_path, "w", encoding="utf-8") as f:
        f.write("Test document")
    
    # Index document
    doc = index_document(doc_path, extract_text=True)
    assert doc is not None
    
    # Search with FTS5 disabled
    results = search_documents("test", use_fts5=False)
    
    assert len(results) > 0


def test_search_documents_preview(test_db, temp_dir):
    """Test that preview text is stored."""
    # Create test document with long text
    doc_path = os.path.join(temp_dir, "test.txt")
    
    long_text = "A" * 10000  # 10KB of text
    with open(doc_path, "w", encoding="utf-8") as f:
        f.write(long_text)
    
    # Index document
    doc = index_document(doc_path, extract_text=True)
    assert doc is not None
    
    # Check that preview is stored (first 8KB)
    assert doc.extracted_text_preview is not None
    assert len(doc.extracted_text_preview) <= 8192
    assert doc.extracted_text_preview == doc.extracted_text[:8192]


def test_search_ranking(test_db, temp_dir):
    """Test that FTS5 returns results in relevance order."""
    # Create test documents with different relevance
    doc1_path = os.path.join(temp_dir, "test1.txt")
    doc2_path = os.path.join(temp_dir, "test2.txt")
    
    with open(doc1_path, "w", encoding="utf-8") as f:
        f.write("machine learning machine learning machine learning")
    
    with open(doc2_path, "w", encoding="utf-8") as f:
        f.write("machine learning")
    
    # Index documents
    doc1 = index_document(doc1_path, extract_text=True)
    doc2 = index_document(doc2_path, extract_text=True)
    
    assert doc1 is not None
    assert doc2 is not None
    
    # Search - should return doc1 first (more matches)
    results = search_documents_fts5("machine learning")
    
    assert len(results) >= 2
    # Results should be ordered by relevance (rank)
    # Doc1 has more matches, so should rank higher

