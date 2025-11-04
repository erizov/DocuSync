"""Tests for API endpoints."""

import pytest
import os
import tempfile
import shutil
from fastapi.testclient import TestClient

from app.main import app
from app.database import init_db, SessionLocal, Document, User
from app.auth import get_password_hash, init_default_user
from app.file_scanner import index_document
from app.reports import log_activity


@pytest.fixture(scope="function")
def test_db():
    """Create a test database."""
    import tempfile
    import os
    test_db_path = tempfile.mktemp(suffix=".db")
    from app.config import settings
    original_url = settings.database_url
    settings.database_url = f"sqlite:///{test_db_path}"

    from app.database import Base, init_db, User, engine, SessionLocal
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import app.database as db_module
    
    # Recreate engine with new database URL
    test_engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False}
    )
    # Drop and recreate to ensure clean schema
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    init_db(test_engine)  # This initializes FTS5
    
    # Patch the global engine and SessionLocal to use test database
    original_engine = db_module.engine
    original_session_local = db_module.SessionLocal
    db_module.engine = test_engine
    db_module.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    
    # Create default user manually to avoid bcrypt initialization issues
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = TestSessionLocal()
    try:
        import bcrypt
        hashed = bcrypt.hashpw("admin".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        user = User(
            username="admin",
            hashed_password=hashed,
            is_active=True
        )
        db.add(user)
        db.commit()
    finally:
        db.close()

    yield
    
    # Restore original engine and SessionLocal
    db_module.engine = original_engine
    db_module.SessionLocal = original_session_local
    
    # Close test engine connections
    test_engine.dispose()

    settings.database_url = original_url
    if os.path.exists(test_db_path):
        try:
            os.unlink(test_db_path)
        except PermissionError:
            pass  # File may be locked, ignore


@pytest.fixture
def client(test_db):
    """Create test client."""
    client = TestClient(app)
    return client


@pytest.fixture
def authenticated_client(client):
    """Create authenticated client."""
    # Login to get token
    response = client.post(
        "/api/auth/login",
        data={
            "username": "admin",
            "password": "admin"
        }
    )
    assert response.status_code == 200
    token = response.json()["access_token"]

    # Create client with token
    client.headers = {"Authorization": f"Bearer {token}"}
    return client


def test_root_endpoint(client):
    """Test root endpoint."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert data["message"] == "DocuSync API"


def test_login_endpoint(client):
    """Test login endpoint."""
    response = client.post(
        "/api/auth/login",
        data={
            "username": "admin",
            "password": "admin"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_page(client):
    """Test login page."""
    response = client.get("/login")
    assert response.status_code == 200
    assert "DocuSync Login" in response.text


def test_search_endpoint(authenticated_client, test_db):
    """Test search endpoint."""
    response = authenticated_client.get("/api/search?q=test")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_search_endpoint_fts5(authenticated_client, test_db):
    """Test search endpoint with FTS5."""
    response = authenticated_client.get(
        "/api/search?q=test&use_fts5=true"
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_search_phrase_endpoint(authenticated_client, test_db):
    """Test phrase search endpoint."""
    response = authenticated_client.get(
        "/api/search/phrase?q=test phrase"
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_search_boolean_endpoint(authenticated_client, test_db):
    """Test boolean search endpoint."""
    response = authenticated_client.get(
        "/api/search/boolean?q=test AND document"
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_documents_endpoint(authenticated_client):
    """Test documents list endpoint."""
    response = authenticated_client.get("/api/documents")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_documents_endpoint_pagination(authenticated_client):
    """Test documents endpoint with pagination."""
    response = authenticated_client.get("/api/documents?skip=0&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) <= 10


def test_stats_endpoint(authenticated_client):
    """Test statistics endpoint."""
    response = authenticated_client.get("/api/stats")
    assert response.status_code == 200
    data = response.json()
    assert "total_documents" in data
    assert "total_size_bytes" in data


def test_duplicates_endpoint(authenticated_client):
    """Test duplicates endpoint."""
    response = authenticated_client.get("/api/duplicates")
    assert response.status_code == 200
    data = response.json()
    assert "total_groups" in data
    assert "duplicates" in data


def test_activities_report_endpoint(authenticated_client, test_db):
    """Test activities report endpoint."""
    # Log some activities
    log_activity("test", "Test activity")
    
    response = authenticated_client.get("/api/reports/activities")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_space_saved_report_endpoint(authenticated_client, test_db):
    """Test space saved report endpoint."""
    # Log activity with space saved
    log_activity("delete", "Deleted file", space_saved_bytes=1024)
    
    response = authenticated_client.get("/api/reports/space-saved")
    assert response.status_code == 200
    data = response.json()
    assert "total_space_saved_bytes" in data
    assert "total_operations" in data


def test_operations_report_endpoint(authenticated_client, test_db):
    """Test operations report endpoint."""
    # Log some operations
    log_activity("delete", "Deleted file")
    
    response = authenticated_client.get("/api/reports/operations")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)


def test_corrupted_pdfs_report_endpoint(authenticated_client):
    """Test corrupted PDFs report endpoint."""
    response = authenticated_client.get("/api/reports/corrupted-pdfs")
    assert response.status_code == 200
    data = response.json()
    assert "total_corrupted" in data
    assert "files" in data


def test_protected_endpoints_require_auth(client):
    """Test that protected endpoints require authentication."""
    # Test search without auth
    response = client.get("/api/search?q=test")
    assert response.status_code == 401
    
    # Test documents without auth
    response = client.get("/api/documents")
    assert response.status_code == 401
    
    # Test stats without auth
    response = client.get("/api/stats")
    assert response.status_code == 401


def test_search_endpoint_drive_filter(authenticated_client, test_db):
    """Test search endpoint with drive filter."""
    response = authenticated_client.get("/api/search?q=test&drive=C")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    # All results should be from drive C
    if data:
        assert all(doc["drive"] == "C" for doc in data)


def test_search_endpoint_content_filter(authenticated_client, test_db):
    """Test search endpoint with content search disabled."""
    response = authenticated_client.get(
        "/api/search?q=test&search_content=false"
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)

