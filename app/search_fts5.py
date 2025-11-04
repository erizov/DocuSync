"""FTS5-based full-text search functionality."""

from typing import List, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import Document, SessionLocal


def search_documents_fts5(
    query: str,
    search_name: bool = True,
    search_author: bool = True,
    search_content: bool = True,
    drive: Optional[str] = None,
    limit: int = 100
) -> List[Document]:
    """
    Search documents using FTS5 full-text search.

    Args:
        query: Search query string (supports FTS5 syntax)
        search_name: Search in document names
        search_author: Search in author names
        search_content: Search in extracted text content
        drive: Filter by drive letter
        limit: Maximum number of results

    Returns:
        List of matching documents ordered by relevance
    """
    db = SessionLocal()
    try:
        # Build FTS5 query
        fts_conditions = []
        
        if search_content:
            fts_conditions.append(f"full_text MATCH :query")
        if search_name:
            fts_conditions.append(f"name MATCH :query")
        if search_author:
            fts_conditions.append(f"author MATCH :query")
        
        if not fts_conditions:
            return []
        
        # Combine with OR
        fts_where = " OR ".join(fts_conditions)
        
        # Build SQL query with ranking
        # FTS5 uses rowid as the primary identifier
        sql_query = f"""
            SELECT d.id, 
                   bm25(documents_fts) as rank
            FROM documents d
            JOIN documents_fts ON d.id = documents_fts.rowid
            WHERE ({fts_where})
        """
        
        params = {"query": query}
        
        if drive:
            sql_query += " AND d.drive = :drive"
            params["drive"] = drive.upper()
        
        sql_query += " ORDER BY rank LIMIT :limit"
        params["limit"] = limit
        
        result = db.execute(text(sql_query), params)
        
        # Get document IDs and ranks from results
        rows = result.fetchall()
        # Sort by rank (ascending - lower is better in BM25)
        sorted_rows = sorted(rows, key=lambda x: x[1])
        doc_ids = [row[0] for row in sorted_rows]
        
        if not doc_ids:
            return []
        
        # Fetch full document objects
        documents = db.query(Document).filter(
            Document.id.in_(doc_ids)
        ).all()
        
        # Maintain order from FTS5 ranking
        doc_dict = {doc.id: doc for doc in documents}
        return [doc_dict[did] for did in doc_ids if did in doc_dict]
        
    except Exception as e:
        # Fallback to regular search if FTS5 fails (disable FTS5 to prevent recursion)
        from app.search import search_documents
        return search_documents(
            query,
            search_name=search_name,
            search_author=search_author,
            search_content=search_content,
            drive=drive,
            use_fts5=False  # Disable FTS5 to prevent infinite recursion
        )[:limit]
    finally:
        db.close()


def search_documents_fts5_phrase(
    phrase: str,
    drive: Optional[str] = None,
    limit: int = 100
) -> List[Document]:
    """
    Search documents using FTS5 phrase matching.

    Args:
        phrase: Phrase to search for (use quotes for exact phrase)
        drive: Filter by drive letter
        limit: Maximum number of results

    Returns:
        List of matching documents
    """
    # Add quotes for phrase matching if not already quoted
    if not (phrase.startswith('"') and phrase.endswith('"')):
        query = f'"{phrase}"'
    else:
        query = phrase
    
    return search_documents_fts5(
        query=query,
        search_content=True,
        search_name=False,
        search_author=False,
        drive=drive,
        limit=limit
    )


def search_documents_fts5_boolean(
    query: str,
    drive: Optional[str] = None,
    limit: int = 100
) -> List[Document]:
    """
    Search documents using FTS5 boolean operators.

    Args:
        query: Boolean query (e.g., "machine AND learning", "python OR java")
        drive: Filter by drive letter
        limit: Maximum number of results

    Returns:
        List of matching documents
    """
    return search_documents_fts5(
        query=query,
        search_content=True,
        search_name=True,
        search_author=True,
        drive=drive,
        limit=limit
    )

