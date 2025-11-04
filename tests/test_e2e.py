"""End-to-end tests for DocuSync."""

import pytest
import os
import tempfile
import shutil
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app
from app.database import init_db, SessionLocal, User
from app.auth import get_password_hash, init_default_user
from app.file_scanner import index_document


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


def test_e2e_login_flow(client):
    """Test complete login flow."""
    # Test login page
    response = client.get("/login")
    assert response.status_code == 200
    assert "DocuSync Login" in response.text

    # Test login endpoint
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


def test_e2e_protected_endpoints(client, authenticated_client):
    """Test that protected endpoints require authentication."""
    # Test without authentication
    response = client.get("/api/search?q=test")
    assert response.status_code == 401

    # Test with authentication
    response = authenticated_client.get("/api/search?q=test")
    assert response.status_code == 200


def test_e2e_document_workflow(temp_dir, authenticated_client):
    """Test complete document workflow."""
    # Create a test document
    test_file = os.path.join(temp_dir, "test_document.txt")
    with open(test_file, "w") as f:
        f.write("This is a test document for e2e testing.")

    # Index the document
    doc = index_document(test_file, extract_text=True)
    assert doc is not None

    # Search for the document
    response = authenticated_client.get(
        f"/api/search?q=test"
    )
    assert response.status_code == 200
    results = response.json()
    assert len(results) > 0

    # Get document statistics
    response = authenticated_client.get("/api/stats")
    assert response.status_code == 200
    stats = response.json()
    assert stats["total_documents"] > 0

    # Get duplicates (should be none for single file)
    response = authenticated_client.get("/api/duplicates")
    assert response.status_code == 200
    duplicates = response.json()
    assert duplicates["total_groups"] == 0


def test_e2e_activity_tracking(temp_dir, authenticated_client):
    """Test activity tracking."""
    from app.reports import log_activity, get_activities

    # Log an activity
    activity = log_activity(
        activity_type="test",
        description="Test activity for e2e testing",
        document_path=os.path.join(temp_dir, "test.txt"),
        space_saved_bytes=1024,
        operation_count=1,
        user_id=None
    )
    assert activity is not None

    # Get activities
    activities = get_activities(limit=10)
    assert len(activities) > 0

    # Check API endpoint
    response = authenticated_client.get("/api/reports/activities")
    assert response.status_code == 200
    activities_data = response.json()
    assert isinstance(activities_data, list)


def test_e2e_reports(authenticated_client):
    """Test reports endpoints."""
    # Test space saved report
    response = authenticated_client.get("/api/reports/space-saved")
    assert response.status_code == 200
    report = response.json()
    assert "total_space_saved_bytes" in report
    assert "total_operations" in report

    # Test operations report
    response = authenticated_client.get("/api/reports/operations")
    assert response.status_code == 200
    report = response.json()
    assert isinstance(report, dict)


def test_e2e_full_workflow(temp_dir, authenticated_client):
    """Test full workflow: scan, search, delete, report."""
    # Create test files
    file1 = os.path.join(temp_dir, "test1.txt")
    file2 = os.path.join(temp_dir, "test2.txt")

    with open(file1, "w") as f:
        f.write("Test document 1")
    with open(file2, "w") as f:
        f.write("Test document 2")

    # Index documents
    doc1 = index_document(file1, extract_text=True)
    doc2 = index_document(file2, extract_text=True)

    assert doc1 is not None
    assert doc2 is not None

    # Search
    response = authenticated_client.get("/api/search?q=test")
    assert response.status_code == 200
    results = response.json()
    assert len(results) >= 2

    # Get stats
    response = authenticated_client.get("/api/stats")
    assert response.status_code == 200
    stats = response.json()
    assert stats["total_documents"] >= 2

    # Delete a file and log activity
    from app.reports import log_activity
    import os

    if os.path.exists(file2):
        os.remove(file2)
        log_activity(
            activity_type="delete",
            description=f"Deleted test file: {file2}",
            document_path=file2,
            space_saved_bytes=20,
            operation_count=1,
            user_id=None
        )

    # Check reports
    response = authenticated_client.get("/api/reports/activities")
    assert response.status_code == 200
    activities = response.json()
    assert len(activities) > 0

    # Check space saved report
    response = authenticated_client.get("/api/reports/space-saved")
    assert response.status_code == 200
    space_report = response.json()
    assert space_report["total_space_saved_bytes"] >= 0

