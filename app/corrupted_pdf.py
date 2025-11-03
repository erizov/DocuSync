"""Functions for detecting and managing corrupted PDF files."""

import os
from typing import List, Optional
from sqlalchemy.orm import Session

from app.database import Document, SessionLocal
from app.file_scanner import extract_pdf_text, extract_pdf_author


def is_pdf_corrupted(file_path: str) -> bool:
    """
    Check if a PDF file is corrupted.

    Args:
        file_path: Path to the PDF file

    Returns:
        True if PDF is corrupted, False otherwise
    """
    if not os.path.exists(file_path):
        return True

    if not file_path.lower().endswith('.pdf'):
        return False

    try:
        # Try to extract text and author
        text = extract_pdf_text(file_path)
        author = extract_pdf_author(file_path)

        # If both fail, it's likely corrupted
        # But we also check if the file can be opened at all
        import PyPDF2
        try:
            with open(file_path, "rb") as f:
                pdf_reader = PyPDF2.PdfReader(f, strict=False)
                # Try to access metadata or pages
                _ = pdf_reader.metadata
                if len(pdf_reader.pages) == 0:
                    return True  # PDF with no pages is suspicious
                # Try to access first page
                _ = pdf_reader.pages[0]
        except Exception:
            return True

        # If we got here, PDF seems okay
        return False

    except Exception:
        # Any exception means the PDF is likely corrupted
        return True


def find_corrupted_pdfs(drive: Optional[str] = None) -> List[Document]:
    """
    Find corrupted PDF files in the database.

    Args:
        drive: Filter by drive letter

    Returns:
        List of Document objects that are corrupted PDFs
    """
    db = SessionLocal()
    try:
        query = db.query(Document).filter(
            Document.file_type == ".pdf"
        )

        if drive:
            query = query.filter(Document.drive == drive.upper())

        pdf_documents = query.all()
        corrupted = []

        for doc in pdf_documents:
            if os.path.exists(doc.file_path):
                if is_pdf_corrupted(doc.file_path):
                    corrupted.append(doc)

        return corrupted
    finally:
        db.close()


def check_and_mark_corrupted(file_path: str) -> bool:
    """
    Check if a PDF is corrupted and update database if needed.

    Args:
        file_path: Path to the PDF file

    Returns:
        True if PDF is corrupted, False otherwise
    """
    if is_pdf_corrupted(file_path):
        # Update database to mark as corrupted
        db = SessionLocal()
        try:
            doc = db.query(Document).filter(
                Document.file_path == file_path
            ).first()

            if doc:
                # We could add a 'is_corrupted' field to Document model
                # For now, we'll just log it
                pass

            return True
        finally:
            db.close()

    return False


def remove_corrupted_pdf(file_path: str,
                        user_id: Optional[int] = None) -> bool:
    """
    Remove a corrupted PDF file and log the activity.

    Args:
        file_path: Path to the corrupted PDF
        user_id: User ID who performed the deletion

    Returns:
        True if file was removed, False otherwise
    """
    try:
        if os.path.exists(file_path):
            # Get file size for reporting
            file_size = os.path.getsize(file_path)

            # Remove the file
            os.remove(file_path)

            # Remove from database
            db = SessionLocal()
            try:
                doc = db.query(Document).filter(
                    Document.file_path == file_path
                ).first()

                if doc:
                    db.delete(doc)
                    db.commit()

                # Log activity
                from app.reports import log_activity
                log_activity(
                    activity_type="delete_corrupted",
                    description=f"Removed corrupted PDF: {file_path}",
                    document_path=file_path,
                    space_saved_bytes=file_size,
                    operation_count=1,
                    user_id=user_id
                )

            finally:
                db.close()

            return True

        return False

    except Exception as e:
        print(f"Error removing corrupted PDF {file_path}: {e}")
        return False


def get_corrupted_pdf_report(drive: Optional[str] = None) -> dict:
    """
    Get a report of corrupted PDF files.

    Args:
        drive: Filter by drive letter

    Returns:
        Dictionary with corrupted PDF statistics
    """
    corrupted = find_corrupted_pdfs(drive=drive)

    total_size = sum(
        os.path.getsize(doc.file_path)
        for doc in corrupted
        if os.path.exists(doc.file_path)
    )

    by_drive = {}
    for doc in corrupted:
        by_drive[doc.drive] = by_drive.get(doc.drive, 0) + 1

    return {
        "total_corrupted": len(corrupted),
        "total_size_bytes": total_size,
        "by_drive": by_drive,
        "files": [
            {
                "id": doc.id,
                "name": doc.name,
                "file_path": doc.file_path,
                "drive": doc.drive,
                "size": os.path.getsize(doc.file_path)
                if os.path.exists(doc.file_path) else 0,
                "date_created": doc.date_created.isoformat()
                if doc.date_created else None
            }
            for doc in corrupted
        ]
    }

