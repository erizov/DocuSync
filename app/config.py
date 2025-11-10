"""Configuration settings for DocuSync."""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings."""

    # Server configuration
    host: str = "0.0.0.0"  # Bind address (0.0.0.0 for Docker, 127.0.0.1 for local)
    port: int = 8000  # Server port
    api_url: Optional[str] = None  # API base URL (e.g., http://localhost:8000)
    frontend_url: Optional[str] = None  # Frontend URL for CORS (if needed)
    environment: str = "development"  # development, production

    # Database configuration
    database_url: str = "sqlite:///docu_sync.db"
    # For Docker/PostgreSQL: postgresql://user:password@db:5432/docu_sync

    # Application settings
    max_file_size_mb: int = 100
    supported_extensions: list[str] = [
        ".pdf", ".docx", ".txt", ".epub", ".djvu", ".zip", ".doc", ".rar",
        ".fb2", ".html", ".rtf", ".gif", ".ppt", ".mp3"
    ]
    enable_fulltext_search: bool = True
    chunk_size: int = 8192

    # Security settings
    secret_key: str = (
        "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"
    )
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # Default user settings
    default_username: str = "admin"
    default_password: str = "admin"

    # Testing settings
    max_test_files: int = 100  # Maximum files for tests

    class Config:
        """Pydantic config."""

        env_file = ".env"
        case_sensitive = False


settings = Settings()

