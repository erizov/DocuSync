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
    db_host: Optional[str] = None  # PostgreSQL host (e.g., db or localhost)
    db_port: int = 5432  # PostgreSQL port
    db_name: str = "docu_sync"  # Database name
    db_user: str = "postgres"  # Database user
    db_password: str = "postgres"  # Database password

    # Database cleanup schedule (cron-like format)
    # Format: "HH:MM" for daily, or "*/N" for every N hours
    # Examples: "02:00" (daily at 2 AM), "*/6" (every 6 hours)
    cleanup_schedule: str = "02:00"  # Default: daily at 2 AM
    cleanup_enabled: bool = True  # Enable/disable cleanup
    cleanup_retention_days: int = 90  # Keep activity logs for N days

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

