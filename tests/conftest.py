"""Pytest configuration and fixtures."""

import pytest
import os
import tempfile
import shutil
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, Document, User
from app.config import Settings, settings


@pytest.fixture(scope="function")
def temp_dir():
    """Create a temporary directory."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(scope="function")
def test_db():
    """Create a test database."""
    test_db_path = tempfile.mktemp(suffix=".db")
    from app.config import settings
    original_url = settings.database_url
    settings.database_url = f"sqlite:///{test_db_path}"

    from app.database import Base, init_db
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    
    # Recreate engine with new database URL
    test_engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=test_engine)
    init_db(test_engine)  # This initializes FTS5
    
    # Create default user manually to avoid bcrypt initialization issues
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = TestSessionLocal()
    try:
        existing_user = db.query(User).filter(User.username == "admin").first()
        if not existing_user:
            # Use bcrypt directly to avoid passlib initialization issues
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
    
    session = TestSessionLocal()

    yield session

    session.close()
    settings.database_url = original_url
    if os.path.exists(test_db_path):
        os.unlink(test_db_path)


@pytest.fixture
def sample_pdf_file(temp_dir):
    """Create a sample PDF file for testing."""
    pdf_path = os.path.join(temp_dir, "test.pdf")
    # Create a minimal PDF file
    pdf_content = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>
endobj
xref
0 4
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
trailer
<< /Size 4 /Root 1 0 R >>
startxref
174
%%EOF"""
    with open(pdf_path, "wb") as f:
        f.write(pdf_content)
    return pdf_path


@pytest.fixture
def sample_txt_file(temp_dir):
    """Create a sample TXT file for testing."""
    txt_path = os.path.join(temp_dir, "test.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("This is a test document.\nIt contains multiple lines.")
    return txt_path


@pytest.fixture(autouse=True)
def limit_test_files(monkeypatch):
    """Automatically limit scan operations to max_test_files in tests."""
    max_files = settings.max_test_files
    
    # Patch scan_drive to use max_files limit
    from app import file_scanner
    original_scan_drive = file_scanner.scan_drive
    
    def limited_scan_drive(drive_letter, file_extensions=None, max_files_param=None):
        """Wrapper that applies test limit if max_files not explicitly set."""
        if max_files_param is None:
            max_files_param = max_files
        return original_scan_drive(
            drive_letter, file_extensions, max_files_param
        )
    
    monkeypatch.setattr(file_scanner, "scan_drive", limited_scan_drive)
    
    # Patch scan_all_drives to use max_files limit
    original_scan_all_drives = file_scanner.scan_all_drives
    
    def limited_scan_all_drives(file_extensions=None, max_files_param=None):
        """Wrapper that applies test limit if max_files not explicitly set."""
        if max_files_param is None:
            max_files_param = max_files
        return original_scan_all_drives(
            file_extensions, max_files_param
        )
    
    monkeypatch.setattr(
        file_scanner, "scan_all_drives", limited_scan_all_drives
    )


@pytest.fixture(autouse=True)
def temporary_file_operations(monkeypatch):
    """Automatically patch move and sync operations to be temporary in tests."""
    from tests.test_utils import get_operation_tracker
    import shutil
    
    # Patch move_document to track and allow revert
    from app import file_scanner
    original_move_document = file_scanner.move_document
    
    def tracked_move_document(source_path, target_path, user_id=None):
        """Wrapper that tracks move operations for reverting."""
        tracker = get_operation_tracker()
        
        # Store original file content if source exists
        if os.path.exists(source_path):
            # Create a backup copy before moving
            backup_path = source_path + ".test_backup"
            if os.path.exists(backup_path):
                os.remove(backup_path)
            shutil.copy2(source_path, backup_path)
            tracker.moved_files.append((source_path, backup_path))
        
        # Perform the move
        result = original_move_document(source_path, target_path, user_id)
        
        # Track the move for reverting
        tracker.track_move(source_path, target_path)
        
        return result
    
    monkeypatch.setattr(file_scanner, "move_document", tracked_move_document)
    
    # Patch sync_drives to track copied files
    from app import sync
    original_sync_drives = sync.sync_drives
    original_shutil_copy2 = shutil.copy2
    
    def tracked_copy2(src, dst, *args, **kwargs):
        """Wrapper that tracks copy operations."""
        tracker = get_operation_tracker()
        result = original_shutil_copy2(src, dst, *args, **kwargs)
        tracker.track_copy(dst)
        return result
    
    def tracked_sync_drives(drive1, drive2, target_dir_drive1="", 
                            target_dir_drive2="", dry_run=True):
        """Wrapper that tracks sync operations."""
        tracker = get_operation_tracker()
        
        # If not dry run, patch shutil.copy2 temporarily
        if not dry_run:
            monkeypatch.setattr(shutil, "copy2", tracked_copy2)
        
        try:
            result = original_sync_drives(
                drive1, drive2, target_dir_drive1, target_dir_drive2, dry_run
            )
            return result
        finally:
            if not dry_run:
                monkeypatch.setattr(shutil, "copy2", original_shutil_copy2)
    
    monkeypatch.setattr(sync, "sync_drives", tracked_sync_drives)
    
    # Revert all operations after test
    yield
    
    tracker = get_operation_tracker()
    tracker.revert_all()

