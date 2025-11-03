"""Integration tests for FastAPI endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import init_db

client = TestClient(app)


def test_root_endpoint():
    """Test root endpoint."""
    response = client.get("/")

    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert data["message"] == "DocuSync API"


def test_search_endpoint():
    """Test search endpoint."""
    response = client.get("/api/search?q=test")

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_documents_endpoint():
    """Test documents list endpoint."""
    response = client.get("/api/documents")

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_stats_endpoint():
    """Test statistics endpoint."""
    response = client.get("/api/stats")

    assert response.status_code == 200
    data = response.json()
    assert "total_documents" in data


def test_duplicates_endpoint():
    """Test duplicates endpoint."""
    response = client.get("/api/duplicates")

    assert response.status_code == 200
    data = response.json()
    assert "total_groups" in data
    assert "duplicates" in data

