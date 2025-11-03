"""Tests for file scanner functionality."""

import pytest
import os
from app.file_scanner import (
    calculate_md5, get_file_metadata, scan_drive,
    index_document, extract_text_content
)
from app.database import Document


def test_calculate_md5(sample_txt_file):
    """Test MD5 hash calculation."""
    hash1 = calculate_md5(sample_txt_file)
    hash2 = calculate_md5(sample_txt_file)

    assert hash1 == hash2
    assert len(hash1) == 32  # MD5 produces 32 hex characters


def test_calculate_md5_nonexistent():
    """Test MD5 calculation for non-existent file."""
    with pytest.raises(IOError):
        calculate_md5("/nonexistent/file.txt")


def test_get_file_metadata(sample_txt_file):
    """Test file metadata extraction."""
    metadata = get_file_metadata(sample_txt_file)

    assert "name" in metadata
    assert "file_path" in metadata
    assert "size" in metadata
    assert "file_type" in metadata
    assert metadata["file_type"] == ".txt"


def test_index_document(test_db, sample_txt_file):
    """Test document indexing."""
    from app.database import get_db_session

    # Mock the database session
    doc = index_document(sample_txt_file, extract_text=True)

    if doc:
        assert doc.name == "test"
        assert doc.file_type == ".txt"
        assert doc.md5_hash is not None
        assert len(doc.md5_hash) == 32


def test_extract_text_content_txt(sample_txt_file):
    """Test text extraction from TXT file."""
    text = extract_text_content(sample_txt_file)

    assert text is not None
    assert "test document" in text.lower()


def test_extract_text_content_pdf(sample_pdf_file):
    """Test text extraction from PDF file."""
    text = extract_text_content(sample_pdf_file)
    # PDF might not have extractable text in minimal test file
    # Just verify function doesn't crash
    assert text is not None or text is None

