"""Test utilities for file operations."""

import os
import shutil
import tempfile
from typing import List, Tuple, Dict
from contextlib import contextmanager
from pathlib import Path


class FileOperationTracker:
    """Tracks file operations for reverting after tests."""
    
    def __init__(self):
        self.moved_files: List[Tuple[str, str]] = []  # (source, target)
        self.copied_files: List[str] = []  # List of copied file paths
        self.temp_dirs: List[str] = []
    
    def track_move(self, source: str, target: str):
        """Track a file move operation."""
        self.moved_files.append((source, target))
    
    def track_copy(self, file_path: str):
        """Track a file copy operation."""
        self.copied_files.append(file_path)
    
    def create_temp_dir(self) -> str:
        """Create a temporary directory and track it."""
        temp_dir = tempfile.mkdtemp()
        self.temp_dirs.append(temp_dir)
        return temp_dir
    
    def revert_all(self):
        """Revert all tracked operations."""
        # Revert moves (move back from target to source)
        for source, target in reversed(self.moved_files):
            try:
                if os.path.exists(target):
                    if os.path.exists(source):
                        # If source exists, remove target (it was a move)
                        os.remove(target)
                    else:
                        # Move back from target to source
                        shutil.move(target, source)
            except Exception as e:
                print(f"Warning: Could not revert move {target} -> {source}: {e}")
        
        # Remove copied files
        for file_path in self.copied_files:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    # Try to remove empty parent directories
                    parent = os.path.dirname(file_path)
                    try:
                        if os.path.exists(parent) and not os.listdir(parent):
                            os.rmdir(parent)
                    except:
                        pass
            except Exception as e:
                print(f"Warning: Could not remove copied file {file_path}: {e}")
        
        # Remove temp directories
        for temp_dir in self.temp_dirs:
            try:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception as e:
                print(f"Warning: Could not remove temp dir {temp_dir}: {e}")
        
        # Clear tracking
        self.moved_files.clear()
        self.copied_files.clear()
        self.temp_dirs.clear()


# Global tracker instance for tests
_operation_tracker = FileOperationTracker()


@contextmanager
def temporary_file_operations():
    """Context manager for temporary file operations that auto-revert."""
    tracker = FileOperationTracker()
    try:
        yield tracker
    finally:
        tracker.revert_all()


def get_operation_tracker() -> FileOperationTracker:
    """Get the global operation tracker for tests."""
    return _operation_tracker

