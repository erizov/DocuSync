"""Search functionality for documents."""

from typing import List, Optional
from sqlalchemy import or_, func

from app.database import Document, SessionLocal


def search_documents(query: str,
                     search_name: bool = True,
                     search_author: bool = True,
                     search_content: bool = True,
                     drive: Optional[str] = None) -> List[Document]:
    """
    Search documents by name, author, or content.

    Args:
        query: Search query string
        search_name: Search in document names
        search_author: Search in author names
        search_content: Search in extracted text content
        drive: Filter by drive letter

    Returns:
        List of matching documents
    """
    db = SessionLocal()
    try:
        query_lower = query.lower()

        conditions = []

        if search_name:
            conditions.append(
                func.lower(Document.name).contains(query_lower)
            )

        if search_author:
            conditions.append(
                func.lower(Document.author).contains(query_lower)
            )

        if search_content:
            conditions.append(
                func.lower(Document.extracted_text).contains(query_lower)
            )

        if not conditions:
            return []

        query_obj = db.query(Document).filter(or_(*conditions))

        if drive:
            query_obj = query_obj.filter(Document.drive == drive.upper())

        results = query_obj.all()
        return results
    finally:
        db.close()


def search_by_md5(md5_hash: str) -> List[Document]:
    """
    Search documents by MD5 hash.

    Args:
        md5_hash: MD5 hash to search for

    Returns:
        List of documents with matching hash
    """
    db = SessionLocal()
    try:
        results = db.query(Document).filter(
            Document.md5_hash == md5_hash
        ).all()
        return results
    finally:
        db.close()


def get_documents_by_drive(drive: str) -> List[Document]:
    """Get all documents on a specific drive."""
    db = SessionLocal()
    try:
        results = db.query(Document).filter(
            Document.drive == drive.upper()
        ).all()
        return results
    finally:
        db.close()


def get_documents_by_directory(directory: str) -> List[Document]:
    """Get all documents in a specific directory."""
    db = SessionLocal()
    try:
        results = db.query(Document).filter(
            Document.directory == directory
        ).all()
        return results
    finally:
        db.close()


def get_document_statistics() -> dict:
    """Get statistics about indexed documents."""
    db = SessionLocal()
    try:
        total_docs = db.query(Document).count()
        total_size = db.query(func.sum(Document.size)).scalar() or 0

        by_drive = {}
        by_type = {}

        documents = db.query(Document).all()
        for doc in documents:
            by_drive[doc.drive] = by_drive.get(doc.drive, 0) + 1
            by_type[doc.file_type] = by_type.get(doc.file_type, 0) + 1

        duplicates = db.query(Document).filter(
            Document.is_duplicate == True
        ).count()

        return {
            "total_documents": total_docs,
            "total_size_bytes": total_size,
            "by_drive": by_drive,
            "by_type": by_type,
            "duplicates_count": duplicates,
        }
    finally:
        db.close()

