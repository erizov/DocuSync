"""Configuration settings for DocuSync."""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings."""

    database_url: str = "sqlite:///docu_sync.db"
    max_file_size_mb: int = 100
    supported_extensions: list[str] = [
        ".pdf", ".docx", ".txt", ".epub"
    ]
    enable_fulltext_search: bool = True
    chunk_size: int = 8192

    class Config:
        """Pydantic config."""

        env_file = ".env"
        case_sensitive = False


settings = Settings()

