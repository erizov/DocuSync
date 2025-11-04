"""Integration tests for FastAPI endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import init_db


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
    return TestClient(app)


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


def test_search_endpoint(authenticated_client):
    """Test search endpoint."""
    response = authenticated_client.get("/api/search?q=test")

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_documents_endpoint(authenticated_client):
    """Test documents list endpoint."""
    response = authenticated_client.get("/api/documents")

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_stats_endpoint(authenticated_client):
    """Test statistics endpoint."""
    response = authenticated_client.get("/api/stats")

    assert response.status_code == 200
    data = response.json()
    assert "total_documents" in data


def test_duplicates_endpoint(authenticated_client):
    """Test duplicates endpoint."""
    response = authenticated_client.get("/api/duplicates")

    assert response.status_code == 200
    data = response.json()
    assert "total_groups" in data
    assert "duplicates" in data

