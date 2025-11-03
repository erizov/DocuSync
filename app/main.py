"""FastAPI main application."""

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel

from app.database import get_db, Document
from app.search import search_documents, get_document_statistics
from app.file_scanner import find_duplicates

app = FastAPI(title="DocuSync API", version="0.1.0")


class DocumentResponse(BaseModel):
    """Document response model."""

    id: int
    name: str
    file_path: str
    drive: str
    directory: str
    author: Optional[str]
    size: int
    size_on_disc: int
    date_created: Optional[str]
    date_published: Optional[str]
    md5_hash: str
    file_type: str

    class Config:
        """Pydantic config."""

        from_attributes = True


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "DocuSync API",
        "version": "0.1.0",
        "endpoints": {
            "/docs": "API documentation",
            "/api/search": "Search documents",
            "/api/documents": "List documents",
            "/api/stats": "Get statistics",
            "/api/duplicates": "Find duplicates"
        }
    }


@app.get("/api/search", response_model=List[DocumentResponse])
async def search(
    q: str = Query(..., description="Search query"),
    drive: Optional[str] = Query(None, description="Filter by drive"),
    search_content: bool = Query(True, description="Search in content"),
    db: Session = Depends(get_db)
):
    """Search documents."""
    results = search_documents(
        q,
        search_name=True,
        search_author=True,
        search_content=search_content,
        drive=drive.upper() if drive else None
    )
    return results


@app.get("/api/documents", response_model=List[DocumentResponse])
async def list_documents(
    drive: Optional[str] = Query(None, description="Filter by drive"),
    directory: Optional[str] = Query(None, description="Filter by directory"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """List documents."""
    query = db.query(Document)

    if drive:
        query = query.filter(Document.drive == drive.upper())

    if directory:
        query = query.filter(Document.directory == directory)

    documents = query.order_by(Document.name).offset(skip).limit(limit).all()
    return documents


@app.get("/api/stats")
async def stats():
    """Get document statistics."""
    return get_document_statistics()


@app.get("/api/duplicates")
async def get_duplicates(db: Session = Depends(get_db)):
    """Get duplicate documents."""
    duplicates = find_duplicates()

    result = {}
    for hash_val, docs in duplicates.items():
        result[hash_val] = [
            {
                "id": doc.id,
                "name": doc.name,
                "file_path": doc.file_path,
                "drive": doc.drive,
                "size": doc.size
            }
            for doc in docs
        ]

    return {
        "total_groups": len(duplicates),
        "total_duplicates": sum(len(docs) - 1 for docs in duplicates.values()),
        "duplicates": result
    }

