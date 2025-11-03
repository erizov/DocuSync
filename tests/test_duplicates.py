"""Tests for duplicate detection."""

import pytest
from app.file_scanner import find_duplicates, calculate_space_savings
from app.database import Document, get_db_session


def test_find_duplicates_empty(test_db):
    """Test finding duplicates with no documents."""
    duplicates = find_duplicates()

    assert isinstance(duplicates, dict)
    assert len(duplicates) == 0


def test_calculate_space_savings_empty():
    """Test calculating space savings with no duplicates."""
    savings = calculate_space_savings({}, "C:\\")

    assert savings == 0

