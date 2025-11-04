"""Database models and session management."""

from sqlalchemy import (
    create_engine, Column, String, Integer, DateTime,
    BigInteger, Text, Index, Boolean, ForeignKey, text
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from datetime import datetime
from typing import Optional

from app.config import settings

Base = declarative_base()


class Document(Base):
    """Document metadata model."""

    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(500), nullable=False, index=True)
    file_path = Column(String(1000), unique=True, nullable=False,
                       index=True)
    drive = Column(String(10), nullable=False, index=True)
    directory = Column(String(1000), nullable=False, index=True)
    author = Column(String(500), nullable=True)
    size = Column(BigInteger, nullable=False)
    size_on_disc = Column(BigInteger, nullable=False)
    date_created = Column(DateTime, nullable=True)
    date_published = Column(DateTime, nullable=True)
    md5_hash = Column(String(32), nullable=False, index=True)
    file_type = Column(String(10), nullable=False, index=True)
    extracted_text = Column(Text, nullable=True)
    extracted_text_preview = Column(String(8192), nullable=True)
    is_duplicate = Column(Boolean, default=False, index=True)
    preferred_location = Column(Boolean, default=False, index=True)

    __table_args__ = (
        Index('idx_drive_dir', 'drive', 'directory'),
        Index('idx_md5_hash', 'md5_hash'),
        Index('idx_name_author', 'name', 'author'),
    )

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"<Document(id={self.id}, name='{self.name[:50]}', "
            f"path='{self.file_path[:50]}...', md5='{self.md5_hash}')>"
        )


class User(Base):
    """User model for authentication."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    activities = relationship("Activity", back_populates="user")


class Activity(Base):
    """Activity log for tracking operations."""

    __tablename__ = "activities"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True,
                     index=True)
    activity_type = Column(String(50), nullable=False, index=True)
    description = Column(Text, nullable=False)
    document_path = Column(String(1000), nullable=True)
    space_saved_bytes = Column(BigInteger, default=0)
    operation_count = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User", back_populates="activities")

    __table_args__ = (
        Index('idx_activity_type_date', 'activity_type', 'created_at'),
    )


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False}
    if "sqlite" in settings.database_url else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db(db_engine=None) -> None:
    """Initialize database tables."""
    db_engine = db_engine or engine
    Base.metadata.create_all(bind=db_engine)
    init_fts5(db_engine)


def init_fts5(db_engine=None) -> None:
    """Initialize FTS5 virtual table for full-text search."""
    db_engine = db_engine or engine
    conn = db_engine.connect()
    try:
        # Create FTS5 virtual table if it doesn't exist
        # Simple FTS5 table without content option (easier to maintain)
        conn.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts 
            USING fts5(
                doc_id UNINDEXED,
                full_text,
                name,
                author
            );
        """))
        
        # Create triggers to keep FTS5 in sync with main table
        # FTS5 uses rowid, so we use INSERT with rowid
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS documents_fts_insert AFTER INSERT ON documents
            BEGIN
                INSERT INTO documents_fts(rowid, doc_id, full_text, name, author)
                VALUES (new.id, new.id,
                        COALESCE(new.extracted_text, ''),
                        COALESCE(new.name, ''),
                        COALESCE(new.author, ''));
            END;
        """))
        
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS documents_fts_delete AFTER DELETE ON documents
            BEGIN
                DELETE FROM documents_fts WHERE rowid = old.id;
            END;
        """))
        
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS documents_fts_update AFTER UPDATE ON documents
            BEGIN
                DELETE FROM documents_fts WHERE rowid = old.id;
                INSERT INTO documents_fts(rowid, doc_id, full_text, name, author)
                VALUES (new.id, new.id,
                        COALESCE(new.extracted_text, ''),
                        COALESCE(new.name, ''),
                        COALESCE(new.author, ''));
            END;
        """))
        
        conn.commit()
        
        # Populate FTS5 with existing documents (only if FTS5 table is empty)
        try:
            count_result = conn.execute(text(
                "SELECT COUNT(*) FROM documents_fts"
            )).scalar()
            if count_result == 0:
                conn.execute(text("""
                    INSERT INTO documents_fts(rowid, doc_id, full_text, name, author)
                    SELECT id, id,
                           COALESCE(extracted_text, ''),
                           COALESCE(name, ''),
                           COALESCE(author, '')
                    FROM documents;
                """))
                conn.commit()
        except Exception:
            # If FTS5 table doesn't exist or has issues, skip population
            pass
    except Exception as e:
        print(f"Warning: Could not initialize FTS5: {e}")
        conn.rollback()
    finally:
        conn.close()


def get_db() -> Session:
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_session() -> Session:
    """Get database session (non-generator version)."""
    return SessionLocal()

