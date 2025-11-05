"""Drive and folder synchronization functionality."""

import os
import math
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

        def emit_progress(phase: str, extra: Optional[Dict] = None, force: bool = False) -> None:
            nonlocal last_emit_time
            if not progress_callback:
                return
            now = time.time()
            # Emit at least every 1 second, or immediately if forced
            # Force is used when we increment equals_count or needs_sync_count
            if force or now - last_emit_time >= 1.0:
                # Enforce invariant for reported numbers:
                # scanned == equals + needs_sync, and if equals == 0 then needs_sync == scanned
                displayed_equals = max(0, int(equals_count))
                base_scanned = max(0, int(scanned_indexed))
                # Derive needs from scanned - equals, but never below the counted needs
                derived_needs = max(0, base_scanned - displayed_equals)
                displayed_needs = max(int(needs_sync_count), derived_needs)
                displayed_scanned = displayed_equals + displayed_needs

                payload: Dict = {
                    "phase": phase,
                    "scanned": displayed_scanned,
                    "equals": displayed_equals,
                    "needs_sync": displayed_needs,
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
                doc = index_document(file_path, extract_text=False)
                scanned_indexed += 1
                # Show progress every 10 files (more frequent)
                if idx % 10 == 0 or idx == len(files1) - 1:
                    file_info = f"Indexing {os.path.basename(file_path)}..."
                    if doc and doc.md5_hash:
                        file_info += f" MD5: {doc.md5_hash[:16]}..."
                    emit_progress("scan_folder1", {
                        "file": file_info,
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
                doc = index_document(file_path, extract_text=False)
                scanned_indexed += 1
                # Show progress every 10 files (more frequent)
                if idx % 10 == 0 or idx == len(files2) - 1:
                    file_info = f"Indexing {os.path.basename(file_path)}..."
                    if doc and doc.md5_hash:
                        file_info += f" MD5: {doc.md5_hash[:16]}..."
                    emit_progress("scan_folder2", {
                        "file": file_info,
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
        
        # Group by filename (with extension) and MD5
        # Matching rule: files match if filename is the same and MD5 is the same
        folder1_dict = {}  # {filename: [docs]}
        folder2_dict = {}
        
        # Track progress for folder1
        total_files_folder1 = len(docs_folder1)
        for idx, doc in enumerate(docs_folder1):
            try:
                name_key = os.path.basename(doc.file_path)
                # Debug for target file
                if "Indexing R for Data Science" in name_key or "R for Data Science" in name_key:
                    print(f"[DEBUG TARGET] folder1 grouping: file_path='{doc.file_path}' basename='{name_key}'")
                if name_key not in folder1_dict:
                    folder1_dict[name_key] = []
                folder1_dict[name_key].append(doc)
            except ValueError:
                continue
        
        # Track progress for folder2
        total_files_folder2 = len(docs_folder2)
        for idx, doc in enumerate(docs_folder2):
            try:
                name_key = os.path.basename(doc.file_path)
                # Debug for target file
                if "Indexing R for Data Science" in name_key or "R for Data Science" in name_key:
                    print(f"[DEBUG TARGET] folder2 grouping: file_path='{doc.file_path}' basename='{name_key}'")
                if name_key not in folder2_dict:
                    folder2_dict[name_key] = []
                folder2_dict[name_key].append(doc)
            except ValueError:
                continue
        
        # Find files unique to each folder and duplicates with different content
        missing_in_folder2 = []  # Files in folder1 but not folder2
        missing_in_folder1 = []  # Files in folder2 but not folder1
        duplicates = []  # Same name, different MD5 (partial matches needing decision)
        suspected_duplicates = []  # Different name, same MD5 (possible rename)

        # Counters per new semantics
        equals_by_name_count = 0       # total pairs matched by name (equals)
        exact_match_count = 0          # subset of equals where md5 also matches
        partial_match_count = 0        # subset of equals where md5 differs
        uniques_count = 0              # files only on one side
        
        # Compare by filename and track progress
        compared_count = 0
        # Deterministic order: sort by basename
        names_all = sorted(set(folder1_dict.keys()) | set(folder2_dict.keys()))
        total_to_compare = len(names_all)

        # Build quick MD5 presence sets per folder for cross-name checks
        md5_set_f1 = set()
        for docs in folder1_dict.values():
            for d in docs:
                md5_set_f1.add(d.md5_hash)
        md5_set_f2 = set()
        for docs in folder2_dict.values():
            for d in docs:
                md5_set_f2.add(d.md5_hash)

        # Determine debug throttling to <= 50 messages based on bigger folder size
        bigger_folder_files = max(total_files_folder1, total_files_folder2)
        compare_log_step = max(1, int(math.ceil(bigger_folder_files / 50)))
        try:
            print(
                f"[DEBUG] ordered {len(folder1_dict)} files in folder1, ordered {len(folder2_dict)} files in folder2; "
                f"bigger_folder_files={bigger_folder_files}, log_step={compare_log_step}"
            )
        except Exception:
            pass

        # Track how many pairs we matched by name for each md5 so we can
        # later also match by md5 across different names without double-counting
        matched_by_name_per_md5 = {}

        for name_key in names_all:
            docs1_list = folder1_dict.get(name_key, [])
            docs2_list = folder2_dict.get(name_key, [])
            compared_count += 1

            # Special debug for the specific file mentioned by user
            is_target_file = "Indexing R for Data Science" in name_key or "R for Data Science" in name_key
            if is_target_file:
                print(f"[DEBUG TARGET] Processing file: '{name_key}'")
                print(f"[DEBUG TARGET] folder1_dict has {len(docs1_list)} files with this name")
                print(f"[DEBUG TARGET] folder2_dict has {len(docs2_list)} files with this name")
                if docs1_list:
                    print(f"[DEBUG TARGET] folder1 files:")
                    for d in docs1_list:
                        print(f"  - {d.file_path} MD5: {d.md5_hash[:16]}...")
                if docs2_list:
                    print(f"[DEBUG TARGET] folder2 files:")
                    for d in docs2_list:
                        print(f"  - {d.file_path} MD5: {d.md5_hash[:16]}...")

            if not docs2_list:
                # Files with this name only in folder1
                if is_target_file:
                    print(f"[DEBUG TARGET] File '{name_key}' NOT found in folder2 by name")
                    any_md5_matches = any(d.md5_hash in md5_set_f2 for d in docs1_list)
                    print(f"[DEBUG TARGET] MD5 matches in folder2: {any_md5_matches}")
                    if docs1_list:
                        for d in docs1_list:
                            print(f"[DEBUG TARGET] Checking MD5 {d.md5_hash[:16]}... in folder2 set: {d.md5_hash in md5_set_f2}")
                
                missing_in_folder2.extend(docs1_list)
                uniques_count += len(docs1_list)
                needs_sync_count += len(docs1_list)
                # Debug
                if (compared_count % compare_log_step == 0) or (compared_count == total_to_compare) or is_target_file:
                    try:
                        any_md5_matches = any(d.md5_hash in md5_set_f2 for d in docs1_list)
                        if any_md5_matches:
                            # Case 3
                            print(
                                f"[DEBUG] file {name_key} does NOT have an EXACT match in folder2 by name "
                                f"BUT MATCHED by MD5 so it PROBABLY DOES NOT need sync, it needs MERGE."
                            )
                        else:
                            # Case 1
                            print(
                                f"[DEBUG] file {name_key} does not have a match in folder2 by name and by md5 "
                                f"so it needs sync."
                            )
                    except Exception:
                        pass
                # Build file info with MD5 for progress display
                file_info = f"{name_key}"
                if docs1_list:
                    md5_list = [d.md5_hash[:16] + "..." for d in docs1_list[:3]]  # Show first 3 MD5s
                    file_info += f" | folder1 MD5: {', '.join(md5_list)}"
                emit_progress("compare", {
                    "file": file_info,
                    "scanned": equals_by_name_count + uniques_count,
                    "equals": equals_by_name_count,
                    "needs_sync": uniques_count,
                }, force=True)
            elif not docs1_list:
                # Files with this name only in folder2
                missing_in_folder1.extend(docs2_list)
                uniques_count += len(docs2_list)
                needs_sync_count += len(docs2_list)
                # Debug
                if (compared_count % compare_log_step == 0) or (compared_count == total_to_compare):
                    try:
                        print(f"[DEBUG] name-only in folder2: '{name_key}' count2={len(docs2_list)}")
                    except Exception:
                        pass
                # Build file info with MD5 for progress display
                file_info = f"{name_key}"
                if docs2_list:
                    md5_list = [d.md5_hash[:16] + "..." for d in docs2_list[:3]]  # Show first 3 MD5s
                    file_info += f" | folder2 MD5: {', '.join(md5_list)}"
                emit_progress("compare", {
                    "file": file_info,
                    "scanned": equals_by_name_count + uniques_count,
                    "equals": equals_by_name_count,
                    "needs_sync": uniques_count,
                }, force=True)
            else:
                # Same filename exists on both sides
                # Match files first by name (already grouped), then by MD5
                
                # Step 1: Match files by MD5 within the same name
                # Group files by MD5 for both folders
                f1_by_md5 = {}  # {md5: [docs]}
                f2_by_md5 = {}  # {md5: [docs]}
                
                for d in docs1_list:
                    if d.md5_hash not in f1_by_md5:
                        f1_by_md5[d.md5_hash] = []
                    f1_by_md5[d.md5_hash].append(d)
                
                for d in docs2_list:
                    if d.md5_hash not in f2_by_md5:
                        f2_by_md5[d.md5_hash] = []
                    f2_by_md5[d.md5_hash].append(d)
                
                if is_target_file:
                    print(f"[DEBUG TARGET] folder1 MD5 groups: {list(f1_by_md5.keys())}")
                    print(f"[DEBUG TARGET] folder2 MD5 groups: {list(f2_by_md5.keys())}")
                
                # Step 2: Match pairs by MD5 (same name + same MD5)
                exact_here = 0
                matched_pairs = []  # Track matched pairs for debugging
                unmatched_f1 = []  # Files from folder1 that weren't matched
                unmatched_f2 = []  # Files from folder2 that weren't matched
                
                # For each MD5 that exists in both folders, match the files
                for md5_hash in set(f1_by_md5.keys()) & set(f2_by_md5.keys()):
                    # Match pairs: take minimum count from both sides
                    pairs_count = min(len(f1_by_md5[md5_hash]), 
                                      len(f2_by_md5[md5_hash]))
                    exact_here += pairs_count
                    matched_by_name_per_md5[md5_hash] = matched_by_name_per_md5.get(md5_hash, 0) + pairs_count
                    
                    # Mark matched files
                    for i in range(pairs_count):
                        matched_pairs.append({
                            "folder1": f1_by_md5[md5_hash][i],
                            "folder2": f2_by_md5[md5_hash][i],
                            "md5": md5_hash
                        })
                    
                    # Track unmatched files
                    if len(f1_by_md5[md5_hash]) > pairs_count:
                        unmatched_f1.extend(f1_by_md5[md5_hash][pairs_count:])
                    if len(f2_by_md5[md5_hash]) > pairs_count:
                        unmatched_f2.extend(f2_by_md5[md5_hash][pairs_count:])
                
                # Step 3: Collect unmatched files (same name, different MD5)
                for md5_hash in f1_by_md5.keys():
                    if md5_hash not in f2_by_md5:
                        unmatched_f1.extend(f1_by_md5[md5_hash])
                
                for md5_hash in f2_by_md5.keys():
                    if md5_hash not in f1_by_md5:
                        unmatched_f2.extend(f2_by_md5[md5_hash])
                
                if is_target_file:
                    print(f"[DEBUG TARGET] exact_here (matched pairs): {exact_here}")
                    print(f"[DEBUG TARGET] unmatched_f1: {len(unmatched_f1)} files")
                    print(f"[DEBUG TARGET] unmatched_f2: {len(unmatched_f2)} files")
                
                # Count equals: exact matches (same name AND same MD5)
                equals_by_name_count += exact_here
                equals_count = equals_by_name_count
                exact_match_count += exact_here
                
                # Count partial matches and unmatched files as needing sync
                partial_here = len(unmatched_f1) + len(unmatched_f2)
                partial_match_count += partial_here
                
                if partial_here > 0:
                    duplicates.append({
                        "relative_path": name_key,
                        "folder1_docs": unmatched_f1 if unmatched_f1 else docs1_list,
                        "folder2_docs": unmatched_f2 if unmatched_f2 else docs2_list,
                        "matched_pairs": matched_pairs
                    })
                
                # Count unmatched files as needing sync
                uniques_count += partial_here
                needs_sync_count += partial_here

                scanned_disp = equals_by_name_count + uniques_count
                needs_disp = uniques_count
                if (compared_count % compare_log_step == 0) or (compared_count == total_to_compare):
                    try:
                        # Case 2: exact match by name and md5
                        if exact_here > 0:
                            print(
                                f"[DEBUG] file {name_key} does have a match in folder2 by name and by md5 "
                                f"so it DOES NOT need sync."
                            )
                        # Case 3: no exact by name, but md5 exists elsewhere on folder2
                        elif any(d.md5_hash in md5_set_f2 for d in docs1_list):
                            print(
                                f"[DEBUG] file {name_key} does NOT have an EXACT match in folder2 by name "
                                f"BUT MATCHED by MD5 so it PROBABLY DOES NOT need sync, it needs MERGE."
                            )
                        else:
                            # Case 1 fallback
                            print(
                                f"[DEBUG] file {name_key} does not have a match in folder2 by name and by md5 "
                                f"so it needs sync."
                            )
                    except Exception:
                        pass
                # Build file info with MD5 from both folders for progress display
                file_info = f"{name_key}"
                if docs1_list:
                    md5_list_f1 = [d.md5_hash[:16] + "..." for d in docs1_list[:2]]  # Show first 2 MD5s
                    file_info += f" | folder1 MD5: {', '.join(md5_list_f1)}"
                if docs2_list:
                    md5_list_f2 = [d.md5_hash[:16] + "..." for d in docs2_list[:2]]  # Show first 2 MD5s
                    file_info += f" | folder2 MD5: {', '.join(md5_list_f2)}"
                emit_progress("compare", {
                    "file": file_info,
                    "scanned": scanned_disp,
                    "equals": equals_by_name_count,
                    "needs_sync": needs_disp,
                }, force=True)

        # MD5-only suspected duplicates across different names
        md5_counts_f1 = {}
        names_by_md5_f1 = {}
        for name_key, docs in folder1_dict.items():
            for d in docs:
                md5_counts_f1[d.md5_hash] = md5_counts_f1.get(d.md5_hash, 0) + 1
                names_by_md5_f1.setdefault(d.md5_hash, set()).add(name_key)
        md5_counts_f2 = {}
        names_by_md5_f2 = {}
        for name_key, docs in folder2_dict.items():
            for d in docs:
                md5_counts_f2[d.md5_hash] = md5_counts_f2.get(d.md5_hash, 0) + 1
                names_by_md5_f2.setdefault(d.md5_hash, set()).add(name_key)

        suspected_count = 0
        for h in set(md5_counts_f1.keys()) & set(md5_counts_f2.keys()):
            # Skip MD5s that were already paired by same name for all occurrences
            total_pairs_possible = min(md5_counts_f1[h], md5_counts_f2[h])
            already_by_name = matched_by_name_per_md5.get(h, 0)
            remaining = max(0, total_pairs_possible - already_by_name)
            if remaining <= 0:
                continue
            names1 = names_by_md5_f1.get(h, set())
            names2 = names_by_md5_f2.get(h, set())
            # Only suspect if names do not intersect (i.e., different basenames)
            if names1.isdisjoint(names2):
                suspected_duplicates.append({
                    "md5": h,
                    "folder1_names": sorted(list(names1)),
                    "folder2_names": sorted(list(names2)),
                    "count_pairs": remaining,
                })
                suspected_count += remaining

        scanned_disp = equals_by_name_count + uniques_count + suspected_count
        needs_disp = uniques_count + suspected_count
        try:
            print(
                f"[DEBUG] suspected md5 duplicates across names: {suspected_count} "
                f"equals={equals_by_name_count} needs={needs_disp} scanned={scanned_disp}"
            )
        except Exception:
            pass
        emit_progress("compare", {
            "file": "Comparison completed",
            "scanned": scanned_disp,
            "equals": equals_by_name_count,
            "needs_sync": needs_disp,
        }, force=True)
        
        return {
            "folder1": folder1,
            "folder2": folder2,
            "missing_in_folder1": missing_in_folder1,
            "missing_in_folder2": missing_in_folder2,
            "duplicates": duplicates,
            "suspected_duplicates": suspected_duplicates,
            "equals_by_name_count": equals_by_name_count,
            "exact_match_count": exact_match_count,
            "partial_match_count": partial_match_count,
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

