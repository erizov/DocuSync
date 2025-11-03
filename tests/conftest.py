"""Pytest configuration and fixtures."""

import pytest
import os
import tempfile
import shutil
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, Document
from app.config import Settings


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

    from app.database import engine, Base, init_db, SessionLocal
    Base.metadata.create_all(bind=engine)
    init_db()  # This initializes FTS5 and creates default user

    SessionLocal = sessionmaker(autocommit=False, autoflush=False,
                                bind=engine)
    session = SessionLocal()

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

