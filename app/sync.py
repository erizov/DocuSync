"""Drive and folder synchronization functionality."""

import os
import shutil
from typing import Dict, List, Optional, Tuple
import time
from pathlib import Path
from datetime import datetime

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
        # Running counters for periodic progress updates
        scanned_indexed: int = 0
        equals_count: int = 0
        needs_sync_count: int = 0
        last_emit_time: float = 0.0

        def emit_progress(phase: str, extra: Optional[Dict] = None) -> None:
            nonlocal last_emit_time
            if not progress_callback:
                return
            now = time.time()
            if now - last_emit_time >= 2.0:
                payload: Dict = {
                    "phase": phase,
                    "scanned": scanned_indexed,
                    "equals": equals_count,
                    "needs_sync": needs_sync_count,
                }
                if extra:
                    payload.update(extra)
                progress_callback(payload)
                last_emit_time = now
        # Running counters for periodic progress updates
        scanned_indexed: int = 0
        equals_count: int = 0
        needs_sync_count: int = 0
        last_emit_time: float = 0.0

        def emit_progress(phase: str, extra: Optional[Dict] = None) -> None:
            nonlocal last_emit_time
            if not progress_callback:
                return
            now = time.time()
            if now - last_emit_time >= 2.0:
                payload: Dict = {
                    "phase": phase,
                    "scanned": scanned_indexed,
                    "equals": equals_count,
                    "needs_sync": needs_sync_count,
                }
                if extra:
                    payload.update(extra)
                progress_callback(payload)
                last_emit_time = now
        # Running counters for progress reporting (folder analysis)
        scanned_indexed: int = 0
        equals_count: int = 0
        needs_sync_count: int = 0
        last_emit_time: float = 0.0

        def emit_progress(phase: str, extra: Optional[Dict] = None) -> None:
            nonlocal last_emit_time
            if not progress_callback:
                return
            now = time.time()
            if now - last_emit_time >= 2.0:
                payload: Dict = {
                    "phase": phase,
                    "scanned": scanned_indexed,
                    "equals": equals_count,
                    "needs_sync": needs_sync_count,
                }
                if extra:
                    payload.update(extra)
                progress_callback(payload)
                last_emit_time = now
        # Running counters for progress reporting
        scanned_indexed: int = 0
        equals_count: int = 0
        needs_sync_count: int = 0
        last_emit_time: float = 0.0

        def emit_progress(phase: str, extra: Optional[Dict] = None):
            nonlocal last_emit_time
            if not progress_callback:
                return
            now = time.time()
            if now - last_emit_time >= 2.0:
                payload = {
                    "phase": phase,
                    "scanned": scanned_indexed,
                    "equals": equals_count,
                    "needs_sync": needs_sync_count,
                }
                if extra:
                    payload.update(extra)
                progress_callback(payload)
                last_emit_time = now
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


def scan_folder(folder_path: str) -> List[str]:
    """
    Scan a specific folder for documents.
    
    Args:
        folder_path: Path to the folder to scan
        
    Returns:
        List of file paths found
    """
    from app.config import settings
    
    folder_path = os.path.abspath(folder_path)
    if not os.path.exists(folder_path):
        raise ValueError(f"Folder {folder_path} does not exist")
    
    found_files = []
    file_extensions = settings.supported_extensions
    
    for root, dirs, files in os.walk(folder_path):
        # Skip hidden directories
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        
        for file in files:
            file_path = os.path.join(root, file)
            file_ext = os.path.splitext(file_path)[1].lower()
            
            if file_ext in file_extensions:
                found_files.append(file_path)
    
    return found_files


def analyze_folder_sync(folder1: str, folder2: str, progress_callback=None) -> Dict:
    """
    Analyze what files need to be synced between two folders.
    
    Args:
        folder1: First folder path
        folder2: Second folder path
        
    Returns:
        Dictionary with sync analysis information
    """
    from app.file_scanner import index_document
    
    folder1 = os.path.abspath(folder1)
    folder2 = os.path.abspath(folder2)
    
    # Normalize drive letters to uppercase (e.g., "d:\books" -> "D:\books")
    if folder1 and len(folder1) >= 2 and folder1[1] == ':':
        folder1 = folder1[0].upper() + folder1[1:]
    if folder2 and len(folder2) >= 2 and folder2[1] == ':':
        folder2 = folder2[0].upper() + folder2[1:]
    
    if not os.path.exists(folder1):
        raise ValueError(f"Folder {folder1} does not exist")
    if not os.path.exists(folder2):
        raise ValueError(f"Folder {folder2} does not exist")
    
    db = SessionLocal()
    try:
        # Running counters for periodic progress updates
        scanned_indexed: int = 0
        equals_count: int = 0
        needs_sync_count: int = 0
        last_emit_time: float = time.time() - 1.0  # Start 1 second ago so first emit happens immediately

        def emit_progress(phase: str, extra: Optional[Dict] = None) -> None:
            nonlocal last_emit_time
            if not progress_callback:
                return
            now = time.time()
            # Emit at least every 1 second (more frequent updates)
            if now - last_emit_time >= 1.0:
                payload: Dict = {
                    "phase": phase,
                    "scanned": scanned_indexed,
                    "equals": equals_count,
                    "needs_sync": needs_sync_count,
                }
                if extra:
                    payload.update(extra)
                progress_callback(payload)
                last_emit_time = now

        # Always scan and refresh folders when Analyze is pressed
        # This ensures the database is up-to-date with the latest files
        
        # Emit initial progress
        emit_progress("starting", {"file": "Starting analysis..."})
        
        # Scan folder1 and index/update files
        try:
            if progress_callback:
                progress_callback({
                    "file": f"Scanning {folder1}...",
                    "progress": 0,
                    "total": 100,
                    "percentage": 0
                })
            files1 = scan_folder(folder1)
            print(f"[DEBUG] Found {len(files1)} files in folder1")
            for idx, file_path in enumerate(files1):
                index_document(file_path, extract_text=False)
                scanned_indexed += 1
                # Show progress every 10 files (more frequent)
                if idx % 10 == 0 or idx == len(files1) - 1:
                    emit_progress("scan_folder1", {
                        "file": f"Indexing {os.path.basename(file_path)}...",
                        "progress": idx + 1,
                        "total": len(files1),
                        "percentage": int(((idx + 1) / len(files1)) * 100) if len(files1) > 0 else 0
                    })
            # Emit final count after folder1 scan
            print(f"[DEBUG] Folder1 scan complete: scanned_indexed={scanned_indexed}")
            emit_progress("scan_folder1", {"file": f"Completed scanning {folder1}"})
            # Refresh session to see newly indexed files
            db.expire_all()
        except Exception as e:
            print(f"Warning: Could not scan folder1: {e}")
        
        # Scan folder2 and index/update files
        try:
            if progress_callback:
                progress_callback({
                    "file": f"Scanning {folder2}...",
                    "progress": 0,
                    "total": 100,
                    "percentage": 0
                })
            files2 = scan_folder(folder2)
            print(f"[DEBUG] Found {len(files2)} files in folder2")
            for idx, file_path in enumerate(files2):
                index_document(file_path, extract_text=False)
                scanned_indexed += 1
                # Show progress every 10 files (more frequent)
                if idx % 10 == 0 or idx == len(files2) - 1:
                    emit_progress("scan_folder2", {
                        "file": f"Indexing {os.path.basename(file_path)}...",
                        "progress": idx + 1,
                        "total": len(files2),
                        "percentage": int(((idx + 1) / len(files2)) * 100) if len(files2) > 0 else 0
                    })
            # Emit final count after folder2 scan
            print(f"[DEBUG] Folder2 scan complete: scanned_indexed={scanned_indexed}")
            emit_progress("scan_folder2", {"file": f"Completed scanning {folder2}"})
            # Refresh session to see newly indexed files
            db.expire_all()
        except Exception as e:
            print(f"Warning: Could not scan folder2: {e}")
        
        # Get documents from folder1 (after refresh)
        docs_folder1 = db.query(Document).filter(
            Document.file_path.like(f"{folder1}%")
        ).all()
        
        # Get documents from folder2 (after refresh)
        docs_folder2 = db.query(Document).filter(
            Document.file_path.like(f"{folder2}%")
        ).all()
        
        # Group by relative path and MD5
        folder1_dict = {}  # {relative_path: [docs]}
        folder2_dict = {}
        
        # Track progress for folder1
        total_files_folder1 = len(docs_folder1)
        for idx, doc in enumerate(docs_folder1):
            try:
                rel_path = os.path.relpath(doc.file_path, folder1)
                if rel_path not in folder1_dict:
                    folder1_dict[rel_path] = []
                folder1_dict[rel_path].append(doc)
            except ValueError:
                continue  # Skip if not relative
        
        # Track progress for folder2
        total_files_folder2 = len(docs_folder2)
        for idx, doc in enumerate(docs_folder2):
            try:
                rel_path = os.path.relpath(doc.file_path, folder2)
                if rel_path not in folder2_dict:
                    folder2_dict[rel_path] = []
                folder2_dict[rel_path].append(doc)
            except ValueError:
                continue  # Skip if not relative
        
        # Find files unique to each folder and duplicates with different content
        missing_in_folder2 = []  # Files in folder1 but not folder2
        missing_in_folder1 = []  # Files in folder2 but not folder1
        duplicates = []  # Same relative path but different MD5
        
        # Compare files and track progress
        compared_count = 0
        folder1_items = list(folder1_dict.items())
        total_to_compare = len(folder1_items) + len(folder2_dict)
        
        for rel_path, docs1_list in folder1_items:
            compared_count += 1
            if rel_path not in folder2_dict:
                # File exists only in folder1
                missing_in_folder2.extend(docs1_list)
                needs_sync_count += len(docs1_list)
                # Emit immediately after incrementing needs_sync
                if compared_count % 3 == 0 or compared_count == len(folder1_items):
                    emit_progress("compare", {})
            else:
                # File exists in both, check if same MD5
                docs2_list = folder2_dict[rel_path]
                hash1 = set(doc.md5_hash for doc in docs1_list)
                hash2 = set(doc.md5_hash for doc in docs2_list)
                
                # Check if any MD5 hashes match (files are identical)
                intersection = hash1 & hash2
                if intersection:  # Intersection - at least one MD5 matches
                    # Files with same MD5 exist in both folders - skip them (don't sync)
                    # They are already in sync
                    # Count matching files: count unique MD5 hashes that match
                    # For each matching MD5, count files in both folders
                    for matching_hash in intersection:
                        matching_docs1 = [d for d in docs1_list if d.md5_hash == matching_hash]
                        matching_docs2 = [d for d in docs2_list if d.md5_hash == matching_hash]
                        # Count the minimum (pairs that match)
                        equals_count += min(len(matching_docs1), len(matching_docs2))
                    # Emit immediately after incrementing equals
                    if compared_count % 3 == 0 or compared_count == len(folder1_items):
                        emit_progress("compare", {})
                else:
                    # Different content (different MD5) - same name but different content
                    # Add to duplicates for resolution
                    duplicates.append({
                        "relative_path": rel_path,
                        "folder1_docs": docs1_list,
                        "folder2_docs": docs2_list
                    })
                    # Needs sync: all files for this rel_path (take the larger side)
                    needs_sync_count += max(len(docs1_list), len(docs2_list))
                    # Emit immediately after incrementing needs_sync
                    if compared_count % 3 == 0 or compared_count == len(folder1_items):
                        emit_progress("compare", {})
            
            # Emit progress after each comparison to update needs_sync in real-time
            if compared_count % 5 == 0 or compared_count == len(folder1_items):
                if docs1_list:
                    file_name = os.path.basename(docs1_list[0].file_path) if docs1_list else rel_path
                    emit_progress("compare", {
                        "file": file_name,
                        "progress": compared_count,
                        "total": total_to_compare,
                        "percentage": int((compared_count / total_to_compare) * 100) if total_to_compare > 0 else 0
                    })
        
        for rel_path, docs2_list in folder2_dict.items():
            compared_count += 1
            if rel_path not in folder1_dict:
                # File exists only in folder2
                missing_in_folder1.extend(docs2_list)
                needs_sync_count += len(docs2_list)
                # Emit immediately after incrementing needs_sync
                if compared_count % 3 == 0 or compared_count == total_to_compare:
                    emit_progress("compare", {})
            
            # Emit progress after each comparison to update needs_sync in real-time
            if compared_count % 5 == 0 or compared_count == total_to_compare:
                if docs2_list:
                    file_name = os.path.basename(docs2_list[0].file_path) if docs2_list else rel_path
                    emit_progress("compare", {
                        "file": file_name,
                        "progress": compared_count,
                        "total": total_to_compare,
                        "percentage": int((compared_count / total_to_compare) * 100) if total_to_compare > 0 else 0
                    })
        
        # Emit final comparison results
        emit_progress("compare", {"file": "Comparison completed"})
        
        return {
            "folder1": folder1,
            "folder2": folder2,
            "missing_in_folder1": missing_in_folder1,
            "missing_in_folder2": missing_in_folder2,
            "duplicates": duplicates,
            "missing_count_folder1": len(missing_in_folder1),
            "missing_count_folder2": len(missing_in_folder2),
            "duplicate_count": len(duplicates),
            "space_needed_folder1": sum(doc.size for doc in missing_in_folder1),
            "space_needed_folder2": sum(doc.size for doc in missing_in_folder2),
        }
    finally:
        db.close()


def sync_folders(
    folder1: str,
    folder2: str,
    strategy: str = "keep_both",
    target_folder1: Optional[str] = None,
    target_folder2: Optional[str] = None,
    dry_run: bool = True
) -> Dict:
    """
    Synchronize files between two folders.
    
    Args:
        folder1: First folder path
        folder2: Second folder path
        strategy: Sync strategy - "keep_both", "keep_newest", "keep_largest"
        target_folder1: Target folder for files from folder2 (if None, use folder1)
        target_folder2: Target folder for files from folder1 (if None, use folder2)
        dry_run: If True, only show what would be done
        
    Returns:
        Dictionary with sync results
    """
    folder1 = os.path.abspath(folder1)
    folder2 = os.path.abspath(folder2)
    
    if target_folder1 is None:
        target_folder1 = folder1
    if target_folder2 is None:
        target_folder2 = folder2
    
    analysis = analyze_folder_sync(folder1, folder2)
    
    if dry_run:
        return {
            "status": "dry_run",
            "analysis": analysis,
            "message": "Dry run completed. No files were copied."
        }
    
    copied_to_folder1 = []
    copied_to_folder2 = []
    resolved_duplicates = []
    errors = []
    
    # Copy files unique to folder2 to folder1
    for doc in analysis["missing_in_folder1"]:
        try:
            rel_path = os.path.relpath(doc.file_path, folder2)
            target_path = os.path.join(target_folder1, rel_path)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            shutil.copy2(doc.file_path, target_path)
            
            # Verify MD5
            new_hash = calculate_md5(target_path)
            if new_hash == doc.md5_hash:
                copied_to_folder1.append(target_path)
                _index_copied_file(target_path, doc)
                from app.reports import log_activity
                log_activity(
                    activity_type="sync",
                    description=f"Synced file to {target_folder1}",
                    document_path=target_path,
                    space_saved_bytes=0,
                    operation_count=1,
                    user_id=None
                )
            else:
                errors.append(f"MD5 mismatch for {target_path}")
        except Exception as e:
            errors.append(f"Error copying {doc.file_path}: {e}")
    
    # Copy files unique to folder1 to folder2
    for doc in analysis["missing_in_folder2"]:
        try:
            rel_path = os.path.relpath(doc.file_path, folder1)
            target_path = os.path.join(target_folder2, rel_path)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            shutil.copy2(doc.file_path, target_path)
            
            # Verify MD5
            new_hash = calculate_md5(target_path)
            if new_hash == doc.md5_hash:
                copied_to_folder2.append(target_path)
                _index_copied_file(target_path, doc)
                from app.reports import log_activity
                log_activity(
                    activity_type="sync",
                    description=f"Synced file to {target_folder2}",
                    document_path=target_path,
                    space_saved_bytes=0,
                    operation_count=1,
                    user_id=None
                )
            else:
                errors.append(f"MD5 mismatch for {target_path}")
        except Exception as e:
            errors.append(f"Error copying {doc.file_path}: {e}")
    
    # Resolve duplicates based on strategy
    for dup_info in analysis["duplicates"]:
        rel_path = dup_info["relative_path"]
        docs1 = dup_info["folder1_docs"]
        docs2 = dup_info["folder2_docs"]
        
        doc1 = docs1[0]  # Take first doc from each
        doc2 = docs2[0]
        
        if strategy == "keep_both":
            # Keep both - copy to opposite folder with suffix
            try:
                # Copy folder2 version to folder1 with suffix
                target1 = os.path.join(target_folder1, f"{rel_path}.folder2")
                os.makedirs(os.path.dirname(target1), exist_ok=True)
                shutil.copy2(doc2.file_path, target1)
                copied_to_folder1.append(target1)
                
                # Copy folder1 version to folder2 with suffix
                target2 = os.path.join(target_folder2, f"{rel_path}.folder1")
                os.makedirs(os.path.dirname(target2), exist_ok=True)
                shutil.copy2(doc1.file_path, target2)
                copied_to_folder2.append(target2)
                
                resolved_duplicates.append({
                    "relative_path": rel_path,
                    "action": "keep_both",
                    "folder1_copy": target1,
                    "folder2_copy": target2
                })
            except Exception as e:
                errors.append(f"Error resolving duplicate {rel_path}: {e}")
        
        elif strategy == "keep_newest":
            # Keep the newest file
            date1 = doc1.date_created or datetime.fromtimestamp(0)
            date2 = doc2.date_created or datetime.fromtimestamp(0)
            
            if date2 > date1:
                # Keep folder2 version, copy to folder1
                try:
                    target = os.path.join(target_folder1, rel_path)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    shutil.copy2(doc2.file_path, target)
                    copied_to_folder1.append(target)
                    resolved_duplicates.append({
                        "relative_path": rel_path,
                        "action": "keep_newest_folder2",
                        "target": target
                    })
                except Exception as e:
                    errors.append(f"Error resolving duplicate {rel_path}: {e}")
            else:
                # Keep folder1 version, copy to folder2
                try:
                    target = os.path.join(target_folder2, rel_path)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    shutil.copy2(doc1.file_path, target)
                    copied_to_folder2.append(target)
                    resolved_duplicates.append({
                        "relative_path": rel_path,
                        "action": "keep_newest_folder1",
                        "target": target
                    })
                except Exception as e:
                    errors.append(f"Error resolving duplicate {rel_path}: {e}")
        
        elif strategy == "keep_largest":
            # Keep the largest file
            if doc2.size > doc1.size:
                # Keep folder2 version, copy to folder1
                try:
                    target = os.path.join(target_folder1, rel_path)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    shutil.copy2(doc2.file_path, target)
                    copied_to_folder1.append(target)
                    resolved_duplicates.append({
                        "relative_path": rel_path,
                        "action": "keep_largest_folder2",
                        "target": target
                    })
                except Exception as e:
                    errors.append(f"Error resolving duplicate {rel_path}: {e}")
            else:
                # Keep folder1 version, copy to folder2
                try:
                    target = os.path.join(target_folder2, rel_path)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    shutil.copy2(doc1.file_path, target)
                    copied_to_folder2.append(target)
                    resolved_duplicates.append({
                        "relative_path": rel_path,
                        "action": "keep_largest_folder1",
                        "target": target
                    })
                except Exception as e:
                    errors.append(f"Error resolving duplicate {rel_path}: {e}")
    
    return {
        "status": "completed",
        "copied_to_folder1": len(copied_to_folder1),
        "copied_to_folder2": len(copied_to_folder2),
        "resolved_duplicates": len(resolved_duplicates),
        "errors": errors,
    }

