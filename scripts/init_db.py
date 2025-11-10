#!/usr/bin/env python3
"""
Initialize database script.
Runs only once if database does not exist.
"""

import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError
from app.config import settings
from app.database import Base, init_db, migrate_add_role_column, init_fts5
from app.auth import get_password_hash
from app.database import User, SessionLocal


def check_database_exists() -> bool:
    """Check if database exists."""
    try:
        # Build database URL
        if settings.db_host:
            database_url = (
                f"postgresql://{settings.db_user}:{settings.db_password}"
                f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
            )
        else:
            database_url = settings.database_url
        
        # Try to connect to database
        engine = create_engine(database_url)
        inspector = inspect(engine)
        
        # Check if tables exist
        tables = inspector.get_table_names()
        
        # If tables exist, database is initialized
        if tables:
            print(f"Database already exists with {len(tables)} tables.")
            return True
        
        return False
    except OperationalError as e:
        # Database doesn't exist or connection failed
        print(f"Database check failed: {e}")
        return False
    except Exception as e:
        print(f"Error checking database: {e}")
        return False


def create_database_if_not_exists() -> bool:
    """Create PostgreSQL database if it doesn't exist."""
    if not settings.db_host:
        # SQLite - database file will be created automatically
        return True
    
    try:
        # Connect to PostgreSQL server (not specific database)
        admin_url = (
            f"postgresql://{settings.db_user}:{settings.db_password}"
            f"@{settings.db_host}:{settings.db_port}/postgres"
        )
        admin_engine = create_engine(admin_url)
        
        # Check if database exists
        with admin_engine.connect() as conn:
            result = conn.execute(text(
                f"SELECT 1 FROM pg_database WHERE datname = '{settings.db_name}'"
            ))
            exists = result.fetchone() is not None
            
            if not exists:
                # Create database
                conn.execute(text("COMMIT"))  # End any transaction
                conn.execute(text(f'CREATE DATABASE "{settings.db_name}"'))
                conn.commit()
                print(f"Database '{settings.db_name}' created successfully.")
                return True
            else:
                print(f"Database '{settings.db_name}' already exists.")
                return True
    except Exception as e:
        print(f"Error creating database: {e}")
        return False


def create_default_user() -> None:
    """Create default admin user if it doesn't exist."""
    db = SessionLocal()
    try:
        # Check if default user exists
        user = db.query(User).filter(
            User.username == settings.default_username
        ).first()
        
        if not user:
            # Create default admin user
            hashed_password = get_password_hash(settings.default_password)
            new_user = User(
                username=settings.default_username,
                hashed_password=hashed_password,
                role="admin",
                is_active=True
            )
            db.add(new_user)
            db.commit()
            print(
                f"Default admin user '{settings.default_username}' created."
            )
        else:
            print(
                f"Default admin user '{settings.default_username}' already exists."
            )
    except Exception as e:
        print(f"Error creating default user: {e}")
        db.rollback()
    finally:
        db.close()


def main() -> None:
    """Main initialization function."""
    print("Starting database initialization...")
    
    # Create database if it doesn't exist (PostgreSQL only)
    if not create_database_if_not_exists():
        print("Failed to create database. Exiting.")
        sys.exit(1)
    
    # Check if database is already initialized
    if check_database_exists():
        print("Database is already initialized. Skipping initialization.")
        # Still create default user if it doesn't exist
        create_default_user()
        return
    
    print("Initializing database...")
    
    # Build database URL
    if settings.db_host:
        database_url = (
            f"postgresql://{settings.db_user}:{settings.db_password}"
            f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
        )
    else:
        database_url = settings.database_url
    
    # Create engine and initialize database
    engine = create_engine(database_url)
    
    try:
        # Create all tables
        Base.metadata.create_all(bind=engine)
        print("Database tables created successfully.")
        
        # Run migrations (for SQLite compatibility)
        if "sqlite" in database_url:
            migrate_add_role_column(engine)
            init_fts5(engine)
        else:
            # For PostgreSQL, migrations will be handled by Alembic
            print("PostgreSQL detected. Run 'alembic upgrade head' for migrations.")
        
        # Create default user
        create_default_user()
        
        print("Database initialization completed successfully.")
    except Exception as e:
        print(f"Error initializing database: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

