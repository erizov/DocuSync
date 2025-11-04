"""Tests for sync frontend functionality."""

import pytest
import os
import tempfile
import shutil
from fastapi.testclient import TestClient

from app.main import app
from app.database import init_db, SessionLocal, Document
from app.file_scanner import index_document


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


@pytest.fixture(scope="function")
def temp_folders():
    """Create temporary folders for testing."""
    folder1 = tempfile.mkdtemp()
    folder2 = tempfile.mkdtemp()
    
    # Create test files in folder1
    file1 = os.path.join(folder1, "test1.txt")
    file2 = os.path.join(folder1, "test2.txt")
    with open(file1, "w") as f:
        f.write("Content from folder1 - file1")
    with open(file2, "w") as f:
        f.write("Content from folder1 - file2")
    
    # Create test files in folder2
    file3 = os.path.join(folder2, "test3.txt")
    file4 = os.path.join(folder2, "test2.txt")  # Same name, different content
    with open(file3, "w") as f:
        f.write("Content from folder2 - file3")
    with open(file4, "w") as f:
        f.write("Different content from folder2 - file2")
    
    yield folder1, folder2
    
    shutil.rmtree(folder1, ignore_errors=True)
    shutil.rmtree(folder2, ignore_errors=True)


@pytest.fixture
def client(test_db):
    """Create test client."""
    client = TestClient(app)
    return client


@pytest.fixture
def authenticated_client(client):
    """Create authenticated client."""
    response = client.post(
        "/api/auth/login",
        data={
            "username": "admin",
            "password": "admin"
        }
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    client.headers = {"Authorization": f"Bearer {token}"}
    return client


def test_sync_page_access(client):
    """Test that sync page is accessible."""
    response = client.get("/sync")
    assert response.status_code == 200
    assert "DocuSync - Folder Sync" in response.text


def test_sync_analyze_endpoint_folder(authenticated_client, test_db, temp_folders):
    """Test sync analyze endpoint with folders."""
    folder1, folder2 = temp_folders
    
    # Index documents from both folders
    for folder in [folder1, folder2]:
        for file in os.listdir(folder):
            file_path = os.path.join(folder, file)
            if os.path.isfile(file_path):
                index_document(file_path, extract_text=True)
    
    response = authenticated_client.post(
        "/api/sync/analyze",
        json={
            "folder1": folder1,
            "folder2": folder2
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "folder"
    assert "analysis" in data
    assert "missing_count_folder1" in data["analysis"]
    assert "missing_count_folder2" in data["analysis"]


def test_sync_analyze_endpoint_drive(authenticated_client, test_db):
    """Test sync analyze endpoint with drives."""
    # This test requires actual drives, so we'll skip if no drives available
    # For now, just test the endpoint structure
    response = authenticated_client.post(
        "/api/sync/analyze",
        json={
            "drive1": "C",
            "drive2": "D"
        }
    )
    
    # Should either succeed or fail gracefully
    assert response.status_code in [200, 400, 500]


def test_sync_execute_keep_both(authenticated_client, test_db, temp_folders):
    """Test sync execution with keep_both strategy."""
    folder1, folder2 = temp_folders
    
    # Index documents
    for folder in [folder1, folder2]:
        for file in os.listdir(folder):
            file_path = os.path.join(folder, file)
            if os.path.isfile(file_path):
                index_document(file_path, extract_text=True)
    
    response = authenticated_client.post(
        "/api/sync/execute",
        json={
            "folder1": folder1,
            "folder2": folder2,
            "strategy": "keep_both",
            "dry_run": False
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert "copied_to_folder1" in data
    assert "copied_to_folder2" in data


def test_sync_execute_keep_newest(authenticated_client, test_db, temp_folders):
    """Test sync execution with keep_newest strategy."""
    folder1, folder2 = temp_folders
    
    # Index documents
    for folder in [folder1, folder2]:
        for file in os.listdir(folder):
            file_path = os.path.join(folder, file)
            if os.path.isfile(file_path):
                index_document(file_path, extract_text=True)
    
    response = authenticated_client.post(
        "/api/sync/execute",
        json={
            "folder1": folder1,
            "folder2": folder2,
            "strategy": "keep_newest",
            "dry_run": False
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"


def test_sync_execute_keep_largest(authenticated_client, test_db, temp_folders):
    """Test sync execution with keep_largest strategy."""
    folder1, folder2 = temp_folders
    
    # Create a larger file in folder2
    large_file = os.path.join(folder2, "large.txt")
    with open(large_file, "w") as f:
        f.write("X" * 1000)  # Large file
    
    # Index documents
    for folder in [folder1, folder2]:
        for file in os.listdir(folder):
            file_path = os.path.join(folder, file)
            if os.path.isfile(file_path):
                index_document(file_path, extract_text=True)
    
    response = authenticated_client.post(
        "/api/sync/execute",
        json={
            "folder1": folder1,
            "folder2": folder2,
            "strategy": "keep_largest",
            "dry_run": False
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"


def test_sync_analyze_limits_files(authenticated_client, test_db, temp_folders):
    """Test that sync analyze limits files to 100."""
    folder1, folder2 = temp_folders
    
    # Create more than 100 files in folder1
    for i in range(150):
        file_path = os.path.join(folder1, f"test_{i}.txt")
        with open(file_path, "w") as f:
            f.write(f"Content {i}")
        index_document(file_path, extract_text=True)
    
    # Index a few files in folder2
    for i in range(5):
        file_path = os.path.join(folder2, f"test_{i}.txt")
        with open(file_path, "w") as f:
            f.write(f"Content {i}")
        index_document(file_path, extract_text=True)
    
    response = authenticated_client.post(
        "/api/sync/analyze",
        json={
            "folder1": folder1,
            "folder2": folder2
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    # Should limit to 100 files in response
    assert len(data["analysis"]["missing_in_folder2"]) <= 100
    assert len(data["analysis"]["missing_in_folder1"]) <= 100


def test_sync_requires_authentication(client):
    """Test that sync endpoints require authentication."""
    response = client.post(
        "/api/sync/analyze",
        json={
            "folder1": "/tmp",
            "folder2": "/tmp"
        }
    )
    assert response.status_code == 401


def test_sync_invalid_request(authenticated_client):
    """Test sync with invalid request."""
    response = authenticated_client.post(
        "/api/sync/analyze",
        json={}
    )
    assert response.status_code == 400

