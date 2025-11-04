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
    secret_key: str = (
        "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"
    )
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    default_username: str = "admin"
    default_password: str = "admin"
    max_test_files: int = 100  # Maximum files for tests

    class Config:
        """Pydantic config."""

        env_file = ".env"
        case_sensitive = False


settings = Settings()

