"""Activity tracking and reporting."""

from typing import List, Optional, Dict
from datetime import datetime, timedelta
from sqlalchemy import func, and_
from sqlalchemy.orm import Session

from app.database import Activity, SessionLocal


def log_activity(activity_type: str,
                 description: str,
                 document_path: Optional[str] = None,
                 space_saved_bytes: int = 0,
                 operation_count: int = 1,
                 user_id: Optional[int] = None) -> Activity:
    """
    Log an activity.

    Args:
        activity_type: Type of activity (e.g., 'delete', 'move', 'sync')
        description: Description of the activity
        document_path: Path to the document involved
        space_saved_bytes: Amount of space saved in bytes
        operation_count: Number of operations
        user_id: User ID who performed the action

    Returns:
        Created Activity object
    """
    db = SessionLocal()
    try:
        activity = Activity(
            user_id=user_id,
            activity_type=activity_type,
            description=description,
            document_path=document_path,
            space_saved_bytes=space_saved_bytes,
            operation_count=operation_count
        )
        db.add(activity)
        db.commit()
        db.refresh(activity)
        return activity
    finally:
        db.close()


def get_activities(
    activity_type: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = 100
) -> List[Activity]:
    """
    Get activity logs.

    Args:
        activity_type: Filter by activity type
        start_date: Filter by start date
        end_date: Filter by end date
        limit: Maximum number of results

    Returns:
        List of activities
    """
    db = SessionLocal()
    try:
        query = db.query(Activity)

        if activity_type:
            query = query.filter(Activity.activity_type == activity_type)

        if start_date:
            query = query.filter(Activity.created_at >= start_date)

        if end_date:
            query = query.filter(Activity.created_at <= end_date)

        return query.order_by(Activity.created_at.desc()).limit(limit).all()
    finally:
        db.close()


def get_space_saved_report(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
) -> Dict:
    """
    Get space saved report.

    Args:
        start_date: Start date for report
        end_date: End date for report

    Returns:
        Dictionary with space saved statistics
    """
    db = SessionLocal()
    try:
        query = db.query(
            func.sum(Activity.space_saved_bytes).label("total_saved"),
            func.count(Activity.id).label("total_operations")
        )

        if start_date:
            query = query.filter(Activity.created_at >= start_date)

        if end_date:
            query = query.filter(Activity.created_at <= end_date)

        result = query.filter(
            Activity.space_saved_bytes > 0
        ).first()

        total_saved = result.total_saved or 0
        total_operations = result.total_operations or 0

        # Get breakdown by activity type
        breakdown = db.query(
            Activity.activity_type,
            func.sum(Activity.space_saved_bytes).label("saved"),
            func.count(Activity.id).label("count")
        )

        if start_date:
            breakdown = breakdown.filter(Activity.created_at >= start_date)

        if end_date:
            breakdown = breakdown.filter(Activity.created_at <= end_date)

        breakdown = breakdown.filter(
            Activity.space_saved_bytes > 0
        ).group_by(Activity.activity_type).all()

        breakdown_dict = {
            item.activity_type: {
                "space_saved_bytes": item.saved or 0,
                "operation_count": item.count or 0
            }
            for item in breakdown
        }

        return {
            "total_space_saved_bytes": total_saved,
            "total_operations": total_operations,
            "breakdown": breakdown_dict
        }
    finally:
        db.close()


def get_operations_report(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
) -> Dict:
    """
    Get operations report (moves, deletes, etc.).

    Args:
        start_date: Start date for report
        end_date: End date for report

    Returns:
        Dictionary with operation statistics
    """
    db = SessionLocal()
    try:
        query = db.query(
            Activity.activity_type,
            func.count(Activity.id).label("count"),
            func.sum(Activity.operation_count).label("total_operations")
        )

        if start_date:
            query = query.filter(Activity.created_at >= start_date)

        if end_date:
            query = query.filter(Activity.created_at <= end_date)

        results = query.group_by(Activity.activity_type).all()

        return {
            item.activity_type: {
                "activity_count": item.count or 0,
                "total_operations": item.total_operations or 0
            }
            for item in results
        }
    finally:
        db.close()


def get_recent_activities(limit: int = 50) -> List[Activity]:
    """Get recent activities."""
    return get_activities(limit=limit)

