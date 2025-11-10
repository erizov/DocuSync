#!/usr/bin/env python3
"""
Database cleanup script.
Runs on schedule to clean up old activity logs and orphaned records.
"""

import sys
import os
import schedule
import time
from pathlib import Path
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.database import SessionLocal, Activity, Document
from sqlalchemy import text


def cleanup_old_activities() -> int:
    """Remove activity logs older than retention period."""
    if not settings.cleanup_enabled:
        return 0
    
    db = SessionLocal()
    try:
        # Calculate cutoff date
        cutoff_date = datetime.utcnow() - timedelta(
            days=settings.cleanup_retention_days
        )
        
        # Delete old activities
        result = db.query(Activity).filter(
            Activity.created_at < cutoff_date
        ).delete()
        
        db.commit()
        
        print(
            f"[{datetime.now()}] Cleaned up {result} old activity logs "
            f"(older than {settings.cleanup_retention_days} days)."
        )
        return result
    except Exception as e:
        print(f"Error cleaning up activities: {e}")
        db.rollback()
        return 0
    finally:
        db.close()


def cleanup_orphaned_documents() -> int:
    """Remove document records for files that no longer exist."""
    if not settings.cleanup_enabled:
        return 0
    
    db = SessionLocal()
    try:
        # Get all documents
        documents = db.query(Document).all()
        orphaned_count = 0
        
        for doc in documents:
            if not os.path.exists(doc.file_path):
                # File doesn't exist - mark for deletion
                db.delete(doc)
                orphaned_count += 1
        
        if orphaned_count > 0:
            db.commit()
            print(
                f"[{datetime.now()}] Cleaned up {orphaned_count} orphaned "
                "document records."
            )
        
        return orphaned_count
    except Exception as e:
        print(f"Error cleaning up orphaned documents: {e}")
        db.rollback()
        return 0
    finally:
        db.close()


def run_cleanup() -> None:
    """Run all cleanup tasks."""
    print(f"[{datetime.now()}] Starting database cleanup...")
    
    activities_cleaned = cleanup_old_activities()
    documents_cleaned = cleanup_orphaned_documents()
    
    print(
        f"[{datetime.now()}] Cleanup completed: "
        f"{activities_cleaned} activities, {documents_cleaned} documents."
    )


def parse_schedule(schedule_str: str) -> None:
    """Parse schedule string and set up job."""
    schedule_str = schedule_str.strip()
    
    if schedule_str.startswith("*/"):
        # Every N hours format: "*/6" means every 6 hours
        try:
            hours = int(schedule_str[2:])
            schedule.every(hours).hours.do(run_cleanup)
            print(f"Cleanup scheduled to run every {hours} hours.")
        except ValueError:
            print(f"Invalid schedule format: {schedule_str}")
            sys.exit(1)
    elif ":" in schedule_str:
        # Daily time format: "02:00" means daily at 2 AM
        try:
            hour, minute = map(int, schedule_str.split(":"))
            schedule.every().day.at(f"{hour:02d}:{minute:02d}").do(run_cleanup)
            print(f"Cleanup scheduled to run daily at {hour:02d}:{minute:02d}.")
        except ValueError:
            print(f"Invalid schedule format: {schedule_str}")
            sys.exit(1)
    else:
        print(f"Invalid schedule format: {schedule_str}")
        print("Use 'HH:MM' for daily or '*/N' for every N hours.")
        sys.exit(1)


def main() -> None:
    """Main cleanup scheduler."""
    if not settings.cleanup_enabled:
        print("Database cleanup is disabled. Exiting.")
        return
    
    print("Starting database cleanup scheduler...")
    print(f"Retention period: {settings.cleanup_retention_days} days")
    print(f"Schedule: {settings.cleanup_schedule}")
    
    # Parse and set up schedule
    parse_schedule(settings.cleanup_schedule)
    
    # Run cleanup once immediately if requested
    if os.getenv("RUN_ONCE", "false").lower() == "true":
        print("Running cleanup once immediately...")
        run_cleanup()
        return
    
    # Run scheduler loop
    print("Scheduler started. Press Ctrl+C to stop.")
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
    except KeyboardInterrupt:
        print("\nScheduler stopped.")


if __name__ == "__main__":
    main()

