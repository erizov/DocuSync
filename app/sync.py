"""Drive synchronization functionality."""

import os
import shutil
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from app.database import Document, SessionLocal
from app.file_scanner import scan_drive, calculate_md5


def analyze_drive_sync(drive1: str, drive2: str) -> Dict:
    """
    Analyze what files need to be synced between two drives.

    Args:
        drive1: First drive letter
        drive2: Second drive letter

    Returns:
        Dictionary with sync analysis information
    """
    db = SessionLocal()
    try:
        docs_drive1 = db.query(Document).filter(
            Document.drive == drive1.upper()
        ).all()

        docs_drive2 = db.query(Document).filter(
            Document.drive == drive2.upper()
        ).all()

        # Group by MD5 hash
        hash_to_docs1 = {}
        hash_to_docs2 = {}

        for doc in docs_drive1:
            if doc.md5_hash not in hash_to_docs1:
                hash_to_docs1[doc.md5_hash] = []
            hash_to_docs1[doc.md5_hash].append(doc)

        for doc in docs_drive2:
            if doc.md5_hash not in hash_to_docs2:
                hash_to_docs2[doc.md5_hash] = []
            hash_to_docs2[doc.md5_hash].append(doc)

        # Find files that exist on drive1 but not drive2
        missing_on_drive2 = []
        for hash_val, docs in hash_to_docs1.items():
            if hash_val not in hash_to_docs2:
                missing_on_drive2.extend(docs)

        # Find files that exist on drive2 but not drive1
        missing_on_drive1 = []
        for hash_val, docs in hash_to_docs2.items():
            if hash_val not in hash_to_docs1:
                missing_on_drive1.extend(docs)

        # Calculate space needed
        space_needed_drive1 = sum(doc.size for doc in missing_on_drive1)
        space_needed_drive2 = sum(doc.size for doc in missing_on_drive2)

        return {
            "drive1": drive1.upper(),
            "drive2": drive2.upper(),
            "missing_on_drive1": len(missing_on_drive1),
            "missing_on_drive2": len(missing_on_drive2),
            "space_needed_drive1": space_needed_drive1,
            "space_needed_drive2": space_needed_drive2,
            "files_to_copy_drive1": missing_on_drive1,
            "files_to_copy_drive2": missing_on_drive2,
        }
    finally:
        db.close()


def sync_drives(drive1: str, drive2: str,
                target_dir_drive1: str = "",
                target_dir_drive2: str = "",
                dry_run: bool = True) -> Dict:
    """
    Synchronize files between two drives.

    Args:
        drive1: First drive letter
        drive2: Second drive letter
        target_dir_drive1: Target directory on drive1
        target_dir_drive2: Target directory on drive2
        dry_run: If True, only show what would be done

    Returns:
        Dictionary with sync results
    """
    analysis = analyze_drive_sync(drive1, drive2)

    if dry_run:
        return {
            "status": "dry_run",
            "analysis": analysis,
            "message": "Dry run completed. No files were copied."
        }

    copied_to_drive1 = []
    copied_to_drive2 = []
    errors = []

    # Copy files to drive1
    for doc in analysis["files_to_copy_drive1"]:
        try:
            target_path = _get_target_path(
                doc.file_path, drive1, target_dir_drive1
            )
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            shutil.copy2(doc.file_path, target_path)

            # Verify MD5
            new_hash = calculate_md5(target_path)
            if new_hash == doc.md5_hash:
                copied_to_drive1.append(target_path)
                # Update database
                _index_copied_file(target_path, doc)
                # Log activity
                from app.reports import log_activity
                log_activity(
                    activity_type="sync",
                    description=f"Synced file to {drive1}:\\{target_path}",
                    document_path=target_path,
                    space_saved_bytes=0,
                    operation_count=1,
                    user_id=None
                )
            else:
                errors.append(
                    f"MD5 mismatch for {target_path}"
                )
        except Exception as e:
            errors.append(f"Error copying {doc.file_path}: {e}")

    # Copy files to drive2
    for doc in analysis["files_to_copy_drive2"]:
        try:
            target_path = _get_target_path(
                doc.file_path, drive2, target_dir_drive2
            )
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            shutil.copy2(doc.file_path, target_path)

            # Verify MD5
            new_hash = calculate_md5(target_path)
            if new_hash == doc.md5_hash:
                copied_to_drive2.append(target_path)
                # Update database
                _index_copied_file(target_path, doc)
                # Log activity
                from app.reports import log_activity
                log_activity(
                    activity_type="sync",
                    description=f"Synced file to {drive2}:\\{target_path}",
                    document_path=target_path,
                    space_saved_bytes=0,
                    operation_count=1,
                    user_id=None
                )
            else:
                errors.append(
                    f"MD5 mismatch for {target_path}"
                )
        except Exception as e:
            errors.append(f"Error copying {doc.file_path}: {e}")

    return {
        "status": "completed",
        "copied_to_drive1": len(copied_to_drive1),
        "copied_to_drive2": len(copied_to_drive2),
        "errors": errors,
    }


def _get_target_path(source_path: str, target_drive: str,
                     target_dir: str) -> str:
    """Generate target path for copied file."""
    path_obj = Path(source_path)

    if target_dir:
        # Use specified target directory
        target_dir_path = Path(f"{target_drive}:\\{target_dir}")
        return str(target_dir_path / path_obj.name)

    # Preserve directory structure on target drive
    relative_path = path_obj.relative_to(path_obj.drive)
    return f"{target_drive}:\\{relative_path}"


def _index_copied_file(file_path: str, source_doc: Document) -> None:
    """Index a copied file in the database."""
    from app.file_scanner import index_document

    new_doc = index_document(file_path, extract_text=False)
    if new_doc and source_doc.extracted_text:
        # Copy extracted text from source if available
        db = SessionLocal()
        try:
            new_doc.extracted_text = source_doc.extracted_text
            db.commit()
        finally:
            db.close()

