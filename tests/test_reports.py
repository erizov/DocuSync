"""Tests for report functionality."""

import pytest
from datetime import datetime, timedelta
from app.reports import (
    log_activity, get_activities, get_space_saved_report,
    get_operations_report
)
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

    from app.database import engine, Base, init_db
    # Drop and recreate to ensure clean schema
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    init_db()  # This initializes FTS5 and creates default user

    yield

    settings.database_url = original_url
    if os.path.exists(test_db_path):
        os.unlink(test_db_path)


def test_log_activity(test_db):
    """Test logging an activity."""
    activity = log_activity(
        activity_type="test",
        description="Test activity",
        document_path="/test/path.txt",
        space_saved_bytes=1024,
        operation_count=1,
        user_id=None
    )
    
    assert activity is not None
    assert activity.activity_type == "test"
    assert activity.description == "Test activity"
    assert activity.space_saved_bytes == 1024


def test_get_activities(test_db):
    """Test getting activities."""
    # Log some activities
    log_activity("delete", "Deleted file 1", space_saved_bytes=1024)
    log_activity("delete", "Deleted file 2", space_saved_bytes=2048)
    log_activity("sync", "Synced file", space_saved_bytes=0)
    
    # Get all activities
    activities = get_activities()
    
    assert len(activities) >= 3
    
    # Filter by type
    delete_activities = get_activities(activity_type="delete")
    assert len(delete_activities) >= 2
    assert all(a.activity_type == "delete" for a in delete_activities)


def test_get_activities_date_filter(test_db):
    """Test getting activities with date filter."""
    # Log activities
    log_activity("test", "Test activity 1")
    
    # Get activities from today
    start_date = datetime.now() - timedelta(days=1)
    end_date = datetime.now() + timedelta(days=1)
    
    activities = get_activities(start_date=start_date, end_date=end_date)
    
    assert len(activities) > 0


def test_get_space_saved_report(test_db):
    """Test space saved report."""
    # Log activities with space saved
    log_activity("delete", "Deleted file 1", space_saved_bytes=1024)
    log_activity("delete", "Deleted file 2", space_saved_bytes=2048)
    log_activity("delete_corrupted", "Removed corrupted PDF", 
                 space_saved_bytes=512)
    
    # Get report
    report = get_space_saved_report()
    
    assert report["total_space_saved_bytes"] >= 3584  # 1024 + 2048 + 512
    assert report["total_operations"] >= 3
    assert "delete" in report["breakdown"]
    assert "delete_corrupted" in report["breakdown"]


def test_get_operations_report(test_db):
    """Test operations report."""
    # Log different types of operations
    log_activity("delete", "Deleted file", operation_count=1)
    log_activity("sync", "Synced file", operation_count=1)
    log_activity("move", "Moved file", operation_count=1)
    
    # Get report
    report = get_operations_report()
    
    assert "delete" in report
    assert "sync" in report
    assert "move" in report
    assert report["delete"]["activity_count"] >= 1


def test_get_operations_report_date_filter(test_db):
    """Test operations report with date filter."""
    # Log activity
    log_activity("test", "Test operation")
    
    # Get report for today
    start_date = datetime.now() - timedelta(days=1)
    end_date = datetime.now() + timedelta(days=1)
    
    report = get_operations_report(start_date=start_date, end_date=end_date)
    
    assert isinstance(report, dict)


def test_activity_user_association(test_db):
    """Test that activities can be associated with users."""
    activity = log_activity(
        activity_type="test",
        description="Test with user",
        user_id=1
    )
    
    assert activity is not None
    assert activity.user_id == 1

