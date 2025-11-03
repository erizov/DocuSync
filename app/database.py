"""Database models and session management."""

from sqlalchemy import (
    create_engine, Column, String, Integer, DateTime,
    BigInteger, Text, Index, Boolean
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
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


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False}
    if "sqlite" in settings.database_url else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Initialize database tables."""
    Base.metadata.create_all(bind=engine)


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

