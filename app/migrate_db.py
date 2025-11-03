"""Database migration script to add preview column and initialize FTS5."""

from app.database import engine, Base, Document
from sqlalchemy import text


def migrate_database() -> None:
    """Migrate existing database to add preview column and FTS5."""
    conn = engine.connect()
    try:
        # Check if preview column exists
        result = conn.execute(text("""
            SELECT COUNT(*) FROM pragma_table_info('documents') 
            WHERE name = 'extracted_text_preview'
        """))
        
        has_preview = result.scalar() > 0
        
        if not has_preview:
            print("Adding extracted_text_preview column...")
            conn.execute(text("""
                ALTER TABLE documents 
                ADD COLUMN extracted_text_preview VARCHAR(8192)
            """))
            
            # Populate preview column from existing extracted_text
            conn.execute(text("""
                UPDATE documents 
                SET extracted_text_preview = SUBSTR(extracted_text, 1, 8192)
                WHERE extracted_text IS NOT NULL
            """))
            
            conn.commit()
            print("Preview column added and populated.")
        
        # Initialize FTS5 (will skip if already exists)
        from app.database import init_fts5
        init_fts5()
        print("FTS5 initialized.")
        
    except Exception as e:
        print(f"Migration error: {e}")
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    migrate_database()

