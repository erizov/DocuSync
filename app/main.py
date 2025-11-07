"""FastAPI main application."""

import os
import asyncio
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, Depends, HTTPException, Query, status, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, Response, StreamingResponse, JSONResponse
import traceback
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime, timedelta

from app.database import get_db, Document, init_db, User
from app.search import search_documents, get_document_statistics
from app.search_fts5 import (
    search_documents_fts5, search_documents_fts5_phrase,
    search_documents_fts5_boolean
)
from app.file_scanner import find_duplicates, find_all_duplicates
from app.auth import (
    authenticate_user, create_access_token, get_current_user,
    init_default_user, require_admin, require_full_or_admin
)
from app.reports import (
    get_activities, get_space_saved_report, get_operations_report,
    log_activity
)
from app.corrupted_pdf import (
    get_corrupted_pdf_report, find_corrupted_pdfs, remove_corrupted_pdf
)
from app.sync import (
    analyze_drive_sync, analyze_folder_sync, sync_folders
)

# In-memory progress store keyed by job_id
PROGRESS_STORE: dict = {}
# Thread pool executor for running blocking analysis tasks
ANALYSIS_EXECUTOR = ThreadPoolExecutor(max_workers=1)
from app.config import settings

app = FastAPI(title="DocuSync API", version="0.1.0")

# Initialize database and default user on startup
@app.on_event("startup")
async def startup_event():
    """Initialize database and default user on startup."""
    init_db()
    try:
        init_default_user()
    except Exception as e:
        print(f"Warning: Could not initialize default user: {e}")


class DocumentResponse(BaseModel):
    """Document response model."""

    id: int
    name: str
    file_path: str
    drive: str
    directory: str
    author: Optional[str]
    size: int
    size_on_disc: int
    date_created: Optional[str]
    date_published: Optional[str]
    md5_hash: str
    file_type: str

    class Config:
        """Pydantic config."""

        from_attributes = True


class Token(BaseModel):
    """Token response model."""

    access_token: str
    token_type: str
    role: str
    username: str


class LoginRequest(BaseModel):
    """Login request model."""

    username: str
    password: str


class UserCreate(BaseModel):
    """User creation model."""

    username: str
    password: str
    role: str  # readonly, full, admin


class UserResponse(BaseModel):
    """User response model."""

    id: int
    username: str
    role: str
    is_active: bool
    created_at: str

    class Config:
        """Pydantic config."""

        from_attributes = True


class ActivityResponse(BaseModel):
    """Activity response model."""

    id: int
    activity_type: str
    description: str
    document_path: Optional[str]
    space_saved_bytes: int
    operation_count: int
    created_at: str

    class Config:
        """Pydantic config."""

        from_attributes = True


@app.get("/")
async def root():
    """Root endpoint - redirects to login page."""
    return RedirectResponse(url="/login")


@app.get("/index.html", response_class=HTMLResponse)
async def index_page():
    """Index page that redirects to login."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>DocuSync</title>
        <meta http-equiv="refresh" content="0; url=/login">
        <script>
            window.location.href = '/login';
        </script>
    </head>
    <body>
        <p>Redirecting to <a href="/login">login page</a>...</p>
    </body>
    </html>
    """


@app.get("/.well-known/appspecific/com.chrome.devtools.json", include_in_schema=False)
async def chrome_devtools():
    """Handle Chrome DevTools request to prevent 404 errors in logs."""
    # Return empty JSON with 200 status to silence Chrome DevTools requests
    from fastapi.responses import JSONResponse
    return JSONResponse(content={}, status_code=200)


@app.get("/favicon.ico")
async def favicon() -> Response:
    """Serve a small inline SVG favicon to avoid 404s.

    Using inline SVG avoids adding a static file and works across browsers.
    """
    svg = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<svg xmlns='http://www.w3.org/2000/svg' width='64' height='64' viewBox='0 0 64 64'>"
        "<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>"
        "<stop offset='0%' stop-color='#667eea'/><stop offset='100%' stop-color='#764ba2'/></linearGradient></defs>"
        "<rect x='4' y='4' width='56' height='56' rx='12' fill='url(#g)'/>"
        "<text x='32' y='40' font-family='Segoe UI, Arial' font-size='24' text-anchor='middle' fill='white'>D</text>"
        "</svg>"
    )
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    """Serve login page."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>DocuSync Login</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            }
            .login-container {
                background: white;
                padding: 2rem;
                border-radius: 10px;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
                width: 300px;
            }
            h1 {
                text-align: center;
                color: #333;
                margin-bottom: 1.5rem;
            }
            form {
                display: flex;
                flex-direction: column;
            }
            label {
                margin-bottom: 0.5rem;
                color: #555;
            }
            input {
                padding: 0.75rem;
                margin-bottom: 1rem;
                border: 1px solid #ddd;
                border-radius: 5px;
                font-size: 1rem;
            }
            button {
                padding: 0.75rem;
                background: #667eea;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 1rem;
                cursor: pointer;
            }
            button:hover {
                background: #5568d3;
            }
            .error {
                color: red;
                margin-top: 1rem;
                text-align: center;
            }
            .success {
                color: green;
                margin-top: 1rem;
                text-align: center;
            }
        </style>
    </head>
    <body>
        <div class="login-container">
            <h1>DocuSync Login</h1>
            <form id="loginForm">
                <label for="username">Username:</label>
                <input type="text" id="username" name="username" required>
                
                <label for="password">Password:</label>
                <input type="password" id="password" name="password" required>
                
                <button type="submit">Login</button>
            </form>
            <div id="message"></div>
        </div>
        
        <script>
            document.getElementById('loginForm').addEventListener('submit', async function(e) {
                e.preventDefault();
                const username = document.getElementById('username').value;
                const password = document.getElementById('password').value;
                const messageDiv = document.getElementById('message');
                
                const formData = new URLSearchParams();
                formData.append('username', username);
                formData.append('password', password);
                
                try {
                    const response = await fetch('/api/auth/login', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/x-www-form-urlencoded',
                        },
                        body: formData
                    });
                    
                    const data = await response.json();
                    
                    if (response.ok) {
                        messageDiv.innerHTML = '<div class="success">Login successful! Token: ' + 
                            data.access_token.substring(0, 20) + '...</div>';
                        localStorage.setItem('access_token', data.access_token);
                        localStorage.setItem('user_role', data.role);
                        localStorage.setItem('username', data.username);
                        messageDiv.innerHTML += '<div class="success">Token saved. Redirecting...</div>';
                        setTimeout(() => {
                            window.location.href = '/sync';
                        }, 1000);
                    } else {
                        messageDiv.innerHTML = '<div class="error">Login failed: ' + 
                            (data.detail || 'Unknown error') + '</div>';
                    }
                } catch (error) {
                    messageDiv.innerHTML = '<div class="error">Error: ' + error.message + '</div>';
                }
            });
        </script>
    </body>
    </html>
    """


@app.post("/api/auth/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """Login endpoint."""
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )
    access_token = create_access_token(
        data={"sub": user.username}
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user.role,
        "username": user.username
    }


@app.get("/api/search", response_model=List[DocumentResponse])
async def search(
    q: str = Query(..., description="Search query"),
    drive: Optional[str] = Query(None, description="Filter by drive"),
    search_content: bool = Query(True, description="Search in content"),
    use_fts5: bool = Query(True, description="Use FTS5 for search"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Search documents."""
    results = search_documents(
        q,
        search_name=True,
        search_author=True,
        search_content=search_content,
        drive=drive.upper() if drive else None,
        use_fts5=use_fts5
    )
    return results


@app.get("/api/search/phrase", response_model=List[DocumentResponse])
async def search_phrase(
    q: str = Query(..., description="Phrase to search for"),
    drive: Optional[str] = Query(None, description="Filter by drive"),
    current_user: User = Depends(get_current_user)
):
    """Search documents by exact phrase using FTS5."""
    results = search_documents_fts5_phrase(
        phrase=q,
        drive=drive.upper() if drive else None
    )
    return results


@app.get("/api/search/boolean", response_model=List[DocumentResponse])
async def search_boolean(
    q: str = Query(..., description="Boolean query (e.g., 'machine AND learning')"),
    drive: Optional[str] = Query(None, description="Filter by drive"),
    current_user: User = Depends(get_current_user)
):
    """Search documents using boolean operators (AND, OR, NOT)."""
    results = search_documents_fts5_boolean(
        query=q,
        drive=drive.upper() if drive else None
    )
    return results


@app.get("/api/documents", response_model=List[DocumentResponse])
async def list_documents(
    drive: Optional[str] = Query(None, description="Filter by drive"),
    directory: Optional[str] = Query(None, description="Filter by directory"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List documents."""
    query = db.query(Document)

    if drive:
        query = query.filter(Document.drive == drive.upper())

    if directory:
        query = query.filter(Document.directory == directory)

    documents = query.order_by(Document.name).offset(skip).limit(limit).all()
    return documents


@app.get("/api/stats")
async def stats(current_user: User = Depends(get_current_user)):
    """Get document statistics."""
    return get_document_statistics()


@app.get("/api/duplicates")
async def get_duplicates(
    duplicate_type: Optional[str] = Query(None, description="Type: 'content' or 'name' or 'all'"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get duplicate documents."""
    if duplicate_type == "all" or duplicate_type is None:
        all_dups = find_all_duplicates()
        result = {
            "same_content_diff_name": {},
            "same_name_diff_content": {}
        }
        
        # Format same content, different names
        for hash_val, docs in all_dups["same_content_diff_name"].items():
            result["same_content_diff_name"][hash_val] = [
                {
                    "id": doc.id,
                    "name": doc.name,
                    "file_path": doc.file_path,
                    "drive": doc.drive,
                    "size": doc.size,
                    "date_created": doc.date_created.isoformat() if doc.date_created else None,
                }
                for doc in docs
            ]
        
        # Format same name, different content
        for name, docs in all_dups["same_name_diff_content"].items():
            result["same_name_diff_content"][name] = [
                {
                    "id": doc.id,
                    "name": doc.name,
                    "file_path": doc.file_path,
                    "drive": doc.drive,
                    "size": doc.size,
                    "md5_hash": doc.md5_hash,
                    "date_created": doc.date_created.isoformat() if doc.date_created else None,
                }
                for doc in docs
            ]
        
        return {
            "total_same_content_groups": len(all_dups["same_content_diff_name"]),
            "total_same_name_groups": len(all_dups["same_name_diff_content"]),
            "total_same_content_duplicates": all_dups["total_same_content"],
            "total_same_name_duplicates": all_dups["total_same_name"],
            "duplicates": result
        }
    elif duplicate_type == "content":
        duplicates = find_duplicates()
        result = {}
        for hash_val, docs in duplicates.items():
            result[hash_val] = [
                {
                    "id": doc.id,
                    "name": doc.name,
                    "file_path": doc.file_path,
                    "drive": doc.drive,
                    "size": doc.size
                }
                for doc in docs
            ]
        return {
            "type": "same_content_diff_name",
            "total_groups": len(duplicates),
            "total_duplicates": sum(len(docs) - 1 for docs in duplicates.values()),
            "duplicates": result
        }
    elif duplicate_type == "name":
        from app.file_scanner import find_duplicate_by_name
        duplicates = find_duplicate_by_name()
        result = {}
        for name, docs in duplicates.items():
            result[name] = [
                {
                    "id": doc.id,
                    "name": doc.name,
                    "file_path": doc.file_path,
                    "drive": doc.drive,
                    "size": doc.size,
                    "md5_hash": doc.md5_hash,
                    "date_created": doc.date_created.isoformat() if doc.date_created else None,
                }
                for doc in docs
            ]
        return {
            "type": "same_name_diff_content",
            "total_groups": len(duplicates),
            "total_duplicates": sum(len(docs) - 1 for docs in duplicates.values()),
            "duplicates": result
        }


@app.get("/api/reports/activities", response_model=List[ActivityResponse])
async def get_activities_report(
    activity_type: Optional[str] = Query(None, description="Filter by type"),
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(get_current_user)
):
    """Get activity report."""
    activities = get_activities(activity_type=activity_type, limit=limit)
    return activities


@app.get("/api/reports/space-saved")
async def get_space_saved_report(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    current_user: User = Depends(get_current_user)
):
    """Get space saved report."""
    start = datetime.fromisoformat(start_date) if start_date else None
    end = datetime.fromisoformat(end_date) if end_date else None
    return get_space_saved_report(start_date=start, end_date=end)


@app.get("/api/reports/operations")
async def get_operations_report(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    current_user: User = Depends(get_current_user)
):
    """Get operations report."""
    start = datetime.fromisoformat(start_date) if start_date else None
    end = datetime.fromisoformat(end_date) if end_date else None
    return get_operations_report(start_date=start, end_date=end)


@app.get("/api/reports/corrupted-pdfs")
async def get_corrupted_pdfs_report(
    drive: Optional[str] = Query(None, description="Filter by drive"),
    current_user: User = Depends(get_current_user)
):
    """Get corrupted PDF files report."""
    return get_corrupted_pdf_report(drive=drive)


@app.delete("/api/corrupted-pdfs/{file_id}")
async def delete_corrupted_pdf(
    file_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Remove a corrupted PDF file."""
    document = db.query(Document).filter(Document.id == file_id).first()
    if not document:
        raise HTTPException(
            status_code=404, detail="Document not found"
        )

    if document.file_type != ".pdf":
        raise HTTPException(
            status_code=400, detail="Document is not a PDF"
        )

    success = remove_corrupted_pdf(
        document.file_path, user_id=current_user.id
    )

    if success:
        return {"message": "Corrupted PDF removed successfully"}
    else:
        raise HTTPException(
            status_code=500, detail="Failed to remove corrupted PDF"
        )


@app.post("/api/corrupted-pdfs/remove-all")
async def remove_all_corrupted_pdfs(
    drive: Optional[str] = Query(None, description="Filter by drive"),
    current_user: User = Depends(get_current_user)
):
    """Remove all corrupted PDF files."""
    corrupted = find_corrupted_pdfs(drive=drive)

    removed_count = 0
    failed_count = 0
    total_space_saved = 0

    for doc in corrupted:
        if os.path.exists(doc.file_path):
            file_size = os.path.getsize(doc.file_path)
            if remove_corrupted_pdf(doc.file_path, user_id=current_user.id):
                removed_count += 1
                total_space_saved += file_size
            else:
                failed_count += 1

    return {
        "removed_count": removed_count,
        "failed_count": failed_count,
        "total_space_saved_bytes": total_space_saved
    }


class SyncAnalysisRequest(BaseModel):
    """Sync analysis request model."""
    folder1: Optional[str] = None
    folder2: Optional[str] = None
    drive1: Optional[str] = None
    drive2: Optional[str] = None
    job_id: Optional[str] = None


class SyncRequest(BaseModel):
    """Sync request model."""
    folder1: str
    folder2: str
    strategy: str = "keep_both"  # keep_both, keep_newest, keep_largest
    target_folder1: Optional[str] = None
    target_folder2: Optional[str] = None
    dry_run: bool = True


class CopyFileRequest(BaseModel):
    """Copy single file request model."""
    source_path: str
    target_path: str
    source_doc_id: int


@app.get("/api/sync/progress")
async def get_sync_progress(job_id: str, current_user: User = Depends(get_current_user)):
    print(f"[DEBUG] Progress request for job_id={job_id} (type: {type(job_id)})")
    print(f"[DEBUG] PROGRESS_STORE keys: {list(PROGRESS_STORE.keys())}")
    stored_data = PROGRESS_STORE.get(job_id)
    if stored_data:
        print(f"[DEBUG] Found data in store: scanned={stored_data.get('scanned')}, equals={stored_data.get('equals')}, needs_sync={stored_data.get('needs_sync')}")
    else:
        print(f"[DEBUG] No data found for job_id={job_id} in PROGRESS_STORE")
        # Check if there's a close match (maybe string encoding issue)
        for key in PROGRESS_STORE.keys():
            if key == job_id:
                print(f"[DEBUG] Exact match found: {key}")
            elif key.startswith(job_id) or job_id.startswith(key):
                print(f"[DEBUG] Partial match: store_key={key}, request_key={job_id}")
    
    data = stored_data or {
        "scanned": 0,
        "equals": 0,
        "needs_sync": 0,
        "phase": "idle",
        "updated_at": datetime.utcnow().isoformat()
    }
    print(f"[DEBUG] Returning: scanned={data.get('scanned')}, equals={data.get('equals')}, needs_sync={data.get('needs_sync')}")
    return data


def _get_locking_process(file_path: str) -> Optional[str]:
    """
    Try to get the name(s) of the process(es) that have a file locked on Windows.
    Returns a comma-separated string of process names if found, None otherwise.
    """
    try:
        import platform
        if platform.system() != 'Windows':
            return None
        
        processes = []
        
        # Normalize file path for comparison
        file_path_normalized = os.path.abspath(file_path).lower()
        file_path_normalized_alt = file_path_normalized.replace('/', '\\')
        
        # Method 0: Try to actually attempt to delete and catch the error
        # This helps us know the file is definitely locked, then we search more aggressively
        try:
            # Try to open the file with exclusive write access
            # If this fails, we know it's locked
            try:
                f = open(file_path, 'r+b')
                f.close()
            except (PermissionError, IOError, OSError):
                # File is locked, continue with detection
                pass
        except Exception:
            pass
        
        # Method 1: Try to use psutil if available (most reliable)
        try:
            import psutil
            # Get all processes and check their open files
            for proc in psutil.process_iter(['pid', 'name', 'exe']):
                try:
                    # Check open files - this shows files that are actually open
                    open_files = proc.open_files()
                    for item in open_files:
                        try:
                            # Normalize the path from open_files - handle both string and object
                            item_path_str = item.path if isinstance(item, (str, type)) else getattr(item, 'path', str(item))
                            if not item_path_str:
                                continue
                                
                            # Normalize the path
                            item_path = os.path.abspath(item_path_str).lower()
                            item_path_alt = item_path.replace('/', '\\')
                            
                            # Also try without normalization for comparison
                            item_path_raw = item_path_str.lower()
                            
                            # Compare normalized paths (try multiple variations)
                            if (item_path == file_path_normalized or 
                                item_path == file_path_normalized_alt or
                                item_path_alt == file_path_normalized or
                                item_path_alt == file_path_normalized_alt or
                                item_path_raw == file_path_normalized or
                                file_path_normalized in item_path or
                                file_path_normalized_alt in item_path):
                                proc_name = proc.info.get('name') or proc.info.get('exe', '')
                                if proc_name:
                                    # Extract just the executable name without path
                                    proc_name = os.path.basename(proc_name)
                                    # Remove .exe extension for cleaner display
                                    if proc_name.lower().endswith('.exe'):
                                        proc_name = proc_name[:-4]
                                    if proc_name and proc_name.lower() not in [p.lower() for p in processes]:
                                        processes.append(proc_name)
                        except Exception:
                            continue
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
                except Exception:
                    continue
            
            # Also check memory-mapped files (some apps use memory mapping)
            if not processes:
                try:
                    for proc in psutil.process_iter(['pid', 'name', 'exe']):
                        try:
                            # Check memory maps which might include the file
                            memory_maps = proc.memory_maps()
                            for mmap in memory_maps:
                                try:
                                    if hasattr(mmap, 'path') and mmap.path:
                                        mmap_path = os.path.abspath(mmap.path).lower()
                                        mmap_path_alt = mmap_path.replace('/', '\\')
                                        if (mmap_path == file_path_normalized or 
                                            mmap_path == file_path_normalized_alt or
                                            mmap_path_alt == file_path_normalized or
                                            mmap_path_alt == file_path_normalized_alt):
                                            proc_name = proc.info.get('name') or proc.info.get('exe', '')
                                            if proc_name:
                                                proc_name = os.path.basename(proc_name)
                                                if proc_name.lower().endswith('.exe'):
                                                    proc_name = proc_name[:-4]
                                                if proc_name and proc_name.lower() not in [p.lower() for p in processes]:
                                                    processes.append(proc_name)
                                except Exception:
                                    continue
                        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                            continue
                        except Exception:
                            continue
                except Exception:
                    pass
            
            # Also check process commandlines for the file path
            if not processes:
                try:
                    file_name_only = os.path.basename(file_path).lower()
                    for proc in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
                        try:
                            cmdline = proc.info.get('cmdline', [])
                            if cmdline:
                                cmdline_str = ' '.join(cmdline).lower()
                                # Check if filename or path appears in commandline
                                if (file_name_only in cmdline_str or 
                                    file_path_normalized in cmdline_str or
                                    file_path_normalized_alt in cmdline_str):
                                    proc_name = proc.info.get('name') or proc.info.get('exe', '')
                                    if proc_name:
                                        proc_name = os.path.basename(proc_name)
                                        if proc_name.lower().endswith('.exe'):
                                            proc_name = proc_name[:-4]
                                        if proc_name and proc_name.lower() not in [p.lower() for p in processes]:
                                            processes.append(proc_name)
                        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                            continue
                        except Exception:
                            continue
                except Exception:
                    pass
        except ImportError:
            # psutil not available, try alternative methods
            pass
        
        # Method 2: Try using wmic to check all processes for the file in their commandline
        if not processes:
            try:
                import subprocess
                file_name_only = os.path.basename(file_path)
                
                # Try wmic process where commandline contains file path or filename
                result = subprocess.run(
                    ['wmic', 'process', 'get', 'name,commandline', '/format:csv'],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                )
                if result.returncode == 0 and result.stdout:
                    lines = result.stdout.split('\n')
                    for line in lines:
                        line_lower = line.lower()
                        # Check if file path or filename appears in commandline
                        if (file_path_normalized in line_lower or 
                            file_path_normalized_alt in line_lower or
                            file_name_only.lower() in line_lower):
                            # Extract process name from CSV format
                            # Format: "Node,Name,Commandline"
                            parts = [p.strip().strip('"') for p in line.split(',')]
                            # Find the process name (usually second field)
                            if len(parts) >= 2:
                                for part in parts[1:]:
                                    if part and part.lower() not in ['name', 'commandline', '']:
                                        # Check if it's an executable
                                        if part.lower().endswith('.exe'):
                                            proc_name = os.path.basename(part)[:-4]
                                            if proc_name and proc_name.lower() not in [p.lower() for p in processes]:
                                                processes.append(proc_name)
                                                break
                                        elif '\\' in part or '/' in part:
                                            # Might be a path, extract executable name
                                            proc_name = os.path.basename(part)
                                            if proc_name.lower().endswith('.exe'):
                                                proc_name = proc_name[:-4]
                                            if proc_name and proc_name.lower() not in [p.lower() for p in processes]:
                                                processes.append(proc_name)
                                                break
            except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
                pass
        
        # Method 3: Try using handle.exe if available (Sysinternals tool)
        if not processes:
            try:
                import subprocess
                result = subprocess.run(
                    ['handle.exe', file_path],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                )
                if result.returncode == 0 and result.stdout:
                    # Parse handle.exe output to extract process names
                    lines = result.stdout.split('\n')
                    for line in lines:
                        if file_path_normalized in line.lower():
                            # Extract process name from handle.exe output
                            # Format: "process.exe pid: 1234 type: File"
                            parts = line.split()
                            if len(parts) > 0:
                                proc_name = parts[0]
                                if proc_name and proc_name.lower() not in [p.lower() for p in processes]:
                                    processes.append(proc_name)
            except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
                pass
        
        # Method 4: Try using openfiles command (Windows built-in)
        if not processes:
            try:
                import subprocess
                # Get the file's directory and name
                file_dir = os.path.dirname(file_path)
                file_name = os.path.basename(file_path)
                
                # Use openfiles to find processes
                result = subprocess.run(
                    ['openfiles', '/query', '/fo', 'csv'],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                )
                if result.returncode == 0 and result.stdout:
                    lines = result.stdout.split('\n')
                    for line in lines:
                        if file_path_normalized in line.lower() or file_name.lower() in line.lower():
                            # Parse CSV format: "ID,Accessed By,Type,Open File (Path\executable)"
                            parts = line.split(',')
                            if len(parts) >= 2:
                                proc_name = parts[1].strip().strip('"')
                                if proc_name and proc_name.lower() not in ['accessed by', '']:
                                    proc_name = os.path.basename(proc_name)
                                    if proc_name and proc_name.lower() not in [p.lower() for p in processes]:
                                        processes.append(proc_name)
            except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
                pass
        
        # Method 5: Last resort - try to get process from file handle using Windows API
        # This requires more advanced Windows API calls
        if not processes:
            try:
                import ctypes
                from ctypes import wintypes
                
                # Try using NtQuerySystemInformation to get file handles
                # This is complex, so we'll use a simpler approach
                # Try to use the file's directory to find likely processes
                try:
                    file_dir = os.path.dirname(file_path)
                    file_name = os.path.basename(file_path)
                    
                    # Use psutil to check processes that might have files in this directory
                    import psutil
                    for proc in psutil.process_iter(['pid', 'name', 'exe']):
                        try:
                            # Check if process name suggests it might be a PDF reader or document viewer
                            proc_name = proc.info.get('name', '') or proc.info.get('exe', '')
                            if proc_name:
                                proc_name_lower = os.path.basename(proc_name).lower()
                                # Common document viewers/editors
                                common_viewers = ['acrobat', 'acrord32', 'acrord64', 'sumatra', 'foxit', 
                                                 'adobe', 'reader', 'word', 'excel', 'powerpoint', 'notepad',
                                                 'notepad++', 'code', 'chrome', 'firefox', 'edge', 'msedge']
                                if any(viewer in proc_name_lower for viewer in common_viewers):
                                    # Check if this process has any files open in the same directory
                                    try:
                                        open_files = proc.open_files()
                                        for item in open_files:
                                            if os.path.dirname(item.path).lower() == file_dir.lower():
                                                # This process has a file in the same directory
                                                proc_display = os.path.basename(proc_name)
                                                if proc_display.lower().endswith('.exe'):
                                                    proc_display = proc_display[:-4]
                                                if proc_display and proc_display.lower() not in [p.lower() for p in processes]:
                                                    processes.append(proc_display)
                                                    break
                                    except Exception:
                                        continue
                        except Exception:
                            continue
                except Exception:
                    pass
            except Exception:
                pass
        
        # Method 6: Try using Windows Restart Manager API (most reliable for locked files)
        # This is the Windows API specifically designed to find which process has a file locked
        if not processes:
            try:
                import ctypes
                from ctypes import wintypes, Structure, POINTER, c_uint32, c_wchar_p
                
                # Define Restart Manager structures
                class RM_PROCESS_INFO(Structure):
                    _fields_ = [
                        ("Process", wintypes.DWORD),
                        ("AppStatus", wintypes.DWORD),
                        ("AppName", wintypes.HANDLE),
                        ("ServiceShortName", wintypes.HANDLE),
                        ("ApplicationType", wintypes.DWORD),
                        ("AppStatus", wintypes.DWORD),
                        ("TSSessionId", wintypes.DWORD),
                        ("Restartable", wintypes.BOOL),
                    ]
                
                try:
                    rstrtmgr = ctypes.windll.rstrtmgr
                    
                    # Start Restart Manager session
                    session_handle = wintypes.DWORD()
                    session_key = ctypes.create_unicode_buffer(260)
                    
                    result = rstrtmgr.RmStartSession(
                        ctypes.byref(session_handle),
                        0,
                        session_key
                    )
                    
                    if result == 0:  # Success
                        try:
                            # Register the file we want to check
                            file_paths = (c_wchar_p * 1)(file_path)
                            
                            result = rstrtmgr.RmRegisterResources(
                                session_handle,
                                1,
                                file_paths,
                                0,
                                None,
                                0,
                                None
                            )
                            
                            if result == 0:
                                # Get list of processes using the file
                                proc_info_needed = wintypes.DWORD()
                                proc_info_size = wintypes.DWORD()
                                reboot_reasons = wintypes.DWORD()
                                
                                # First call to get required size
                                result = rstrtmgr.RmGetList(
                                    session_handle,
                                    ctypes.byref(proc_info_needed),
                                    ctypes.byref(proc_info_size),
                                    None,
                                    ctypes.byref(reboot_reasons)
                                )
                                
                                if result == 0xEA or proc_info_needed.value > 0:
                                    # Allocate buffer for process info
                                    buffer_size = proc_info_needed.value
                                    if buffer_size == 0:
                                        buffer_size = 1024
                                    
                                    proc_info_buffer = (ctypes.c_byte * buffer_size)()
                                    proc_info_size.value = buffer_size
                                    
                                    result = rstrtmgr.RmGetList(
                                        session_handle,
                                        ctypes.byref(proc_info_needed),
                                        ctypes.byref(proc_info_size),
                                        ctypes.cast(proc_info_buffer, POINTER(RM_PROCESS_INFO)),
                                        ctypes.byref(reboot_reasons)
                                    )
                                    
                                    if result == 0:
                                        # Parse process info - this is complex, so we'll use psutil
                                        # to get process names from PIDs
                                        try:
                                            import psutil
                                            # The buffer contains process info, but parsing is complex
                                            # Instead, we'll use a simpler approach: check all processes
                                            # that might be document viewers
                                        except ImportError:
                                            pass
                        finally:
                            # End the session
                            rstrtmgr.RmEndSession(session_handle)
                except Exception:
                    pass
            except Exception:
                pass
        
        # If we still haven't found it, try one more heuristic:
        # Check all running processes and see if any have the filename in their commandline
        if not processes:
            try:
                import psutil
                file_name_only = os.path.basename(file_path).lower()
                
                for proc in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
                    try:
                        cmdline = proc.info.get('cmdline', [])
                        if cmdline:
                            cmdline_str = ' '.join(cmdline).lower()
                            # Check if filename appears in commandline
                            if file_name_only in cmdline_str or file_path_normalized in cmdline_str:
                                proc_name = proc.info.get('name') or proc.info.get('exe', '')
                                if proc_name:
                                    proc_name = os.path.basename(proc_name)
                                    if proc_name.lower().endswith('.exe'):
                                        proc_name = proc_name[:-4]
                                    if proc_name and proc_name.lower() not in [p.lower() for p in processes]:
                                        processes.append(proc_name)
                    except Exception:
                        continue
            except Exception:
                pass
        
        if processes:
            # Remove .exe extension for cleaner display
            processes_clean = [p.replace('.exe', '') if p.lower().endswith('.exe') else p for p in processes]
            return ', '.join(processes_clean)
        
    except Exception as e:
        # Log error but don't fail
        import logging
        logging.debug(f"Error detecting locking process: {str(e)}")
    
    return None


def _get_date_modified(file_path: str) -> Optional[str]:
    """Get modified date from file system safely."""
    try:
        if os.path.exists(file_path):
            return datetime.fromtimestamp(os.path.getmtime(file_path)).isoformat()
    except Exception:
        pass
    return None


@app.post("/api/sync/analyze")
async def analyze_sync(
    request: SyncAnalysisRequest,
    current_user: User = Depends(get_current_user)
):
    """Analyze what needs to be synced between two folders or drives."""
    if request.folder1 and request.folder2:
        try:
            # Folder sync
            # Store progress updates in a list
            progress_updates = []
            job_id = request.job_id or f"job-{datetime.utcnow().timestamp()}"
            print(f"[DEBUG] analyze_sync: received job_id={request.job_id}, using job_id={job_id}")
            # Initialize PROGRESS_STORE BEFORE starting analysis
            PROGRESS_STORE[job_id] = {
                "scanned": 0,
                "equals": 0,
                "needs_sync": 0,
                "phase": "starting",
                "message": "Starting analysis...",
                "updated_at": datetime.utcnow().isoformat()
            }
            print(f"[DEBUG] PROGRESS_STORE initialized with job_id={job_id}, keys={list(PROGRESS_STORE.keys())}")
            
            def progress_callback(update):
                # Append to returned list
                progress_updates.append(update)
                # Update shared store every callback
                entry = PROGRESS_STORE.get(job_id, {})
                # Always update with values from update dict if present, otherwise keep existing
                # Ensure values are integers
                scanned = update.get("scanned")
                equals = update.get("equals")
                needs_sync = update.get("needs_sync")
                entry.update({
                    "scanned": int(scanned) if scanned is not None else entry.get("scanned", 0),
                    "equals": int(equals) if equals is not None else entry.get("equals", 0),
                    "needs_sync": int(needs_sync) if needs_sync is not None else entry.get("needs_sync", 0),
                    "phase": update.get("phase", entry.get("phase", "running")),
                    "file": update.get("file")
                })
                entry["updated_at"] = datetime.utcnow().isoformat()
                PROGRESS_STORE[job_id] = entry
                # Debug: print to verify updates are happening
                print(f"[DEBUG] Progress update for {job_id}: scanned={entry['scanned']} (type: {type(entry['scanned'])}), equals={entry['equals']}, needs_sync={entry['needs_sync']}")
            
            # Run analysis in thread pool executor to avoid blocking event loop
            # This allows FastAPI to handle GET /api/sync/progress requests concurrently
            loop = asyncio.get_event_loop()
            analysis = await loop.run_in_executor(
                ANALYSIS_EXECUTOR,
                analyze_folder_sync,
                request.folder1,
                request.folder2,
                progress_callback
            )
            # Mark completion
            PROGRESS_STORE[job_id] = {
                **PROGRESS_STORE.get(job_id, {}),
                "phase": "completed",
                "updated_at": datetime.utcnow().isoformat()
            }
            return {
                "type": "folder",
                "job_id": job_id,
                "progress_updates": progress_updates,
                "analysis": {
                    "folder1": analysis["folder1"],
                    "folder2": analysis["folder2"],
                    "missing_count_folder1": analysis["missing_count_folder1"],
                    "missing_count_folder2": analysis["missing_count_folder2"],
                    "duplicate_count": analysis["duplicate_count"],
                    "space_needed_folder1": analysis["space_needed_folder1"],
                    "space_needed_folder2": analysis["space_needed_folder2"],
                    "missing_in_folder1": [
                        {
                            "id": doc.id,
                            "name": doc.name,
                            "file_path": doc.file_path,
                            "size": doc.size,
                            "md5_hash": doc.md5_hash,
                        }
                        for doc in analysis["missing_in_folder1"][:5000]  # Increased limit
                    ],
                    "missing_in_folder2": [
                        {
                            "id": doc.id,
                            "name": doc.name,
                            "file_path": doc.file_path,
                            "size": doc.size,
                            "md5_hash": doc.md5_hash,
                        }
                        for doc in analysis["missing_in_folder2"][:5000]  # Increased limit
                    ],
                    "duplicates": [
                        {
                            "relative_path": dup["relative_path"],
                            "folder1_docs": [
                                {
                                    "id": doc.id,
                                    "name": doc.name,
                                    "file_path": doc.file_path,
                                    "size": doc.size,
                                    "md5_hash": doc.md5_hash,
                                    "date_created": doc.date_created.isoformat() if doc.date_created else None,
                                    "date_modified": _get_date_modified(doc.file_path),
                                }
                                for doc in dup["folder1_docs"]
                            ],
                            "folder2_docs": [
                                {
                                    "id": doc.id,
                                    "name": doc.name,
                                    "file_path": doc.file_path,
                                    "size": doc.size,
                                    "md5_hash": doc.md5_hash,
                                    "date_created": doc.date_created.isoformat() if doc.date_created else None,
                                    "date_modified": _get_date_modified(doc.file_path),
                                }
                                for doc in dup["folder2_docs"]
                            ],
                        }
                        for dup in analysis["duplicates"][:5000]  # Increased limit
                    ],
                }
            }
        except Exception as e:
            # Mark job as error and return structured JSON error
            try:
                jid = locals().get('job_id')
                if jid:
                    PROGRESS_STORE[jid] = {
                        **PROGRESS_STORE.get(jid, {}),
                        "phase": "error",
                        "error": str(e),
                        "updated_at": datetime.utcnow().isoformat(),
                    }
            except Exception:
                pass
            return JSONResponse(status_code=500, content={"detail": str(e)})
    elif request.drive1 and request.drive2:
        # Drive sync
        analysis = analyze_drive_sync(request.drive1, request.drive2)
        return {
            "type": "drive",
            "analysis": {
                "drive1": analysis["drive1"],
                "drive2": analysis["drive2"],
                "missing_on_drive1": analysis["missing_on_drive1"],
                "missing_on_drive2": analysis["missing_on_drive2"],
                "space_needed_drive1": analysis["space_needed_drive1"],
                "space_needed_drive2": analysis["space_needed_drive2"],
            }
        }
    else:
        raise HTTPException(
            status_code=400,
            detail="Either folder1/folder2 or drive1/drive2 must be provided"
        )


@app.post("/api/sync/copy-file")
async def copy_file(
    request: CopyFileRequest,
    current_user: User = Depends(require_full_or_admin)
):
    """Copy a single file with confirmation."""
    from app.database import SessionLocal, Document
    from app.file_scanner import calculate_md5
    from app.sync import _index_copied_file
    from app.reports import log_activity
    import shutil
    import os
    
    db = SessionLocal()
    try:
        source_doc = db.query(Document).filter(Document.id == request.source_doc_id).first()
        if not source_doc:
            return {"success": False, "error": "Source document not found"}
        
        # Check if source file exists
        if not os.path.exists(request.source_path):
            return {"success": False, "error": f"Source file not found: {request.source_path}"}
        
        # Check if source file is readable
        if not os.access(request.source_path, os.R_OK):
            return {"success": False, "error": f"Source file is not readable: {request.source_path}"}
        
        # Get target directory
        target_dir = os.path.dirname(request.target_path)
        
        # Check if target directory exists, if not create it
        if not os.path.exists(target_dir):
            try:
                os.makedirs(target_dir, exist_ok=True)
            except PermissionError as e:
                return {"success": False, "error": f"Cannot create target directory: {target_dir}. Permission denied."}
            except Exception as e:
                return {"success": False, "error": f"Cannot create target directory: {target_dir}. Error: {str(e)}"}
        
        # Check if target directory is writable
        if not os.access(target_dir, os.W_OK):
            return {"success": False, "error": f"Target directory is not writable: {target_dir}. Check permissions."}
        
        # Check if target file already exists
        target_exists = os.path.exists(request.target_path)
        
        if target_exists:
            # Check if existing file has the same MD5 hash (same content)
            try:
                existing_hash = calculate_md5(request.target_path)
                if existing_hash == source_doc.md5_hash:
                    # File already exists with same content - skip copy
                    # Index the existing file if not already indexed
                    try:
                        _index_copied_file(request.target_path, source_doc)
                    except Exception:
                        pass  # Ignore indexing errors for existing files
                    
                    return {
                        "success": True,
                        "target_path": request.target_path,
                        "file_name": os.path.basename(request.target_path),
                        "skipped": True,
                        "message": "File already exists with same content - skipped"
                    }
            except Exception as e:
                # If we can't read the existing file, we'll try to overwrite it
                pass
            
            # File exists but has different content or we can't verify it
            # Check if target file is writable (if it exists, we might need to overwrite it)
            if not os.access(request.target_path, os.W_OK):
                return {
                    "success": False, 
                    "error": f"Target file exists and is locked: {request.target_path}. File may be open in another application. Please close it and try again."
                }
            
            # Try to remove existing file if it exists (for overwrite)
            try:
                os.remove(request.target_path)
            except PermissionError:
                return {
                    "success": False, 
                    "error": f"Cannot overwrite existing file: {request.target_path}. File may be open in another application. Please close it and try again."
                }
            except Exception as e:
                return {"success": False, "error": f"Cannot remove existing file: {request.target_path}. Error: {str(e)}"}
        
        # Copy file
        try:
            shutil.copy2(request.source_path, request.target_path)
        except PermissionError as e:
            return {
                "success": False, 
                "error": f"Permission denied when copying to {request.target_path}. File may be locked or directory permissions insufficient. Original error: {str(e)}"
            }
        except OSError as e:
            return {
                "success": False, 
                "error": f"OS error when copying: {str(e)}. Target: {request.target_path}"
            }
        
        # Verify MD5
        try:
            new_hash = calculate_md5(request.target_path)
            if new_hash != source_doc.md5_hash:
                return {"success": False, "error": "MD5 mismatch after copy - file may be corrupted"}
        except Exception as e:
            return {"success": False, "error": f"Cannot verify MD5: {str(e)}"}
        
        # Index the copied file
        try:
            _index_copied_file(request.target_path, source_doc)
        except Exception as e:
            # Log but don't fail the copy operation
            print(f"Warning: Could not index copied file: {e}")
        
        # Log activity
        try:
            log_activity(
                activity_type="sync",
                description=f"Synced file to {os.path.dirname(request.target_path)}",
                document_path=request.target_path,
                space_saved_bytes=0,
                operation_count=1,
                user_id=None
            )
        except Exception as e:
            # Log but don't fail the copy operation
            print(f"Warning: Could not log activity: {e}")
        
        return {
            "success": True,
            "target_path": request.target_path,
            "file_name": os.path.basename(request.target_path)
        }
    except Exception as e:
        return {"success": False, "error": f"Unexpected error: {str(e)}"}
    finally:
        db.close()


@app.post("/api/sync/check-file")
async def check_file(
    request: dict,
    current_user: User = Depends(get_current_user)
):
    """Check if target file exists and matches by name or MD5."""
    import os
    from app.file_scanner import calculate_md5
    
    target_path = request.get("target_path")
    source_md5 = request.get("source_md5")
    
    if not target_path:
        return {"exists": False, "matches_by_name": False, "matches_by_md5": False}
    
    exists = os.path.exists(target_path)
    matches_by_name = exists
    matches_by_md5 = False
    
    if exists and source_md5:
        try:
            existing_hash = calculate_md5(target_path)
            matches_by_md5 = (existing_hash == source_md5)
        except Exception:
            # If we can't read the file, assume it doesn't match
            matches_by_md5 = False
    
    return {
        "exists": exists,
        "matches_by_name": matches_by_name,
        "matches_by_md5": matches_by_md5
    }


@app.post("/api/sync/delete-file")
async def delete_file(
    request: dict,
    current_user: User = Depends(require_full_or_admin)
):
    """Delete a file (used for duplicate replacement)."""
    import os
    
    file_path = request.get("file_path")
    
    if not file_path:
        return {"success": False, "error": "File path not provided"}
    
    if not os.path.exists(file_path):
        return {"success": True, "message": "File does not exist (already deleted)"}
    
    try:
        # Check if file is writable (not locked)
        if not os.access(file_path, os.W_OK):
            return {
                "success": False,
                "error": f"File is locked and cannot be deleted: {file_path}. File may be open in another application."
            }
        
        os.remove(file_path)
        return {"success": True, "message": f"File deleted: {file_path}"}
    except PermissionError as e:
        return {
            "success": False,
            "error": f"Permission denied when deleting {file_path}. File may be open in another application."
        }
    except Exception as e:
        return {"success": False, "error": f"Error deleting file: {str(e)}"}


@app.post("/api/sync/eliminate-duplicates-folder")
async def eliminate_duplicates_folder(
    request: dict,
    current_user: User = Depends(require_full_or_admin),
    db: Session = Depends(get_db)
):
    """
    Eliminate duplicate files in a specific folder and keep only the latest file.
    
    For each duplicate group, finds the latest file (by date_modified or 
    date_created) and deletes all other files in the target folder.
    """
    from app.reports import log_activity
    
    duplicates = request.get("duplicates", [])
    target_folder = request.get("target_folder", 1)  # 1 or 2
    
    if not duplicates:
        return {
            "success": False,
            "error": "No duplicates provided"
        }
    
    deleted_count = 0
    kept_count = 0
    space_freed = 0
    errors = []
    
    try:
        for dup in duplicates:
            # Collect all files from both folders
            all_files = []
            
            # Add files from folder1
            for doc in dup.get("folder1_docs", []):
                all_files.append({
                    "file_path": doc.get("file_path"),
                    "id": doc.get("id"),
                    "date_modified": doc.get("date_modified"),
                    "date_created": doc.get("date_created"),
                    "size": doc.get("size", 0),
                    "folder": 1
                })
            
            # Add files from folder2
            for doc in dup.get("folder2_docs", []):
                all_files.append({
                    "file_path": doc.get("file_path"),
                    "id": doc.get("id"),
                    "date_modified": doc.get("date_modified"),
                    "date_created": doc.get("date_created"),
                    "size": doc.get("size", 0),
                    "folder": 2
                })
            
            if len(all_files) < 2:
                continue
            
            # Find the latest file
            latest_file = None
            latest_date = None
            
            for file_info in all_files:
                # Try to get date_modified from file system if not in response
                file_path = file_info["file_path"]
                if not file_info.get("date_modified") and os.path.exists(file_path):
                    try:
                        mtime = os.path.getmtime(file_path)
                        file_info["date_modified"] = datetime.fromtimestamp(mtime).isoformat()
                    except Exception:
                        pass
                
                # Determine the date to compare
                compare_date = None
                if file_info.get("date_modified"):
                    try:
                        compare_date = datetime.fromisoformat(file_info["date_modified"])
                    except Exception:
                        pass
                
                if not compare_date and file_info.get("date_created"):
                    try:
                        compare_date = datetime.fromisoformat(file_info["date_created"])
                    except Exception:
                        pass
                
                # If still no date, try to get from file system
                if not compare_date and os.path.exists(file_path):
                    try:
                        compare_date = datetime.fromtimestamp(os.path.getmtime(file_path))
                    except Exception:
                        try:
                            compare_date = datetime.fromtimestamp(os.path.getctime(file_path))
                        except Exception:
                            pass
                
                if compare_date:
                    if latest_date is None or compare_date > latest_date:
                        latest_date = compare_date
                        latest_file = file_info
            
            if not latest_file:
                # If no date available, keep the first file
                latest_file = all_files[0]
            
            # Delete files from target folder only (except the latest file)
            for file_info in all_files:
                # Only process files from target folder
                if file_info["folder"] != target_folder:
                    continue
                
                # Skip if this is the latest file
                if file_info["file_path"] == latest_file["file_path"]:
                    kept_count += 1
                    continue
                
                file_path = file_info["file_path"]
                
                if not os.path.exists(file_path):
                    continue
                
                try:
                    # Try to actually delete the file to see if it's locked
                    # This is more reliable than os.access()
                    try:
                        # Try to open the file with exclusive write access
                        # If this fails, the file is locked
                        test_file = open(file_path, 'r+b')
                        test_file.close()
                    except (PermissionError, IOError, OSError):
                        # File is locked, try to get the process name
                        process_names = _get_locking_process(file_path)
                        file_name = os.path.basename(file_path)
                        
                        # If we couldn't detect the process, try one more time with more aggressive search
                        if not process_names:
                            # Try to find any document viewer that might have files in the same directory
                            try:
                                import psutil
                                file_dir = os.path.dirname(file_path).lower()
                                common_viewers = ['acrobat', 'acrord32', 'acrord64', 'sumatra', 'foxit', 
                                                 'adobe', 'reader', 'word', 'excel', 'powerpoint', 'notepad',
                                                 'notepad++', 'code', 'chrome', 'firefox', 'edge', 'msedge',
                                                 'winword', 'excel', 'powerpnt', 'onenote', 'outlook']
                                
                                for proc in psutil.process_iter(['pid', 'name', 'exe']):
                                    try:
                                        proc_name = proc.info.get('name', '') or proc.info.get('exe', '')
                                        if proc_name:
                                            proc_name_lower = os.path.basename(proc_name).lower()
                                            if any(viewer in proc_name_lower for viewer in common_viewers):
                                                # Check if this process has any files open in the same directory
                                                try:
                                                    open_files = proc.open_files()
                                                    for item in open_files:
                                                        try:
                                                            item_path = item.path if hasattr(item, 'path') else str(item)
                                                            if os.path.dirname(item_path).lower() == file_dir:
                                                                proc_display = os.path.basename(proc_name)
                                                                if proc_display.lower().endswith('.exe'):
                                                                    proc_display = proc_display[:-4]
                                                                if proc_display:
                                                                    process_names = proc_display
                                                                    break
                                                        except Exception:
                                                            continue
                                                    if process_names:
                                                        break
                                                except Exception:
                                                    continue
                                    except Exception:
                                        continue
                            except Exception:
                                pass
                        
                        if process_names:
                            # Format message for single or multiple applications
                            if ',' in process_names:
                                errors.append(
                                    f"File '{file_name}' cannot be removed because it is open in the following application(s): {process_names}. "
                                    f"Close these applications and try again."
                                )
                            else:
                                errors.append(
                                    f"File '{file_name}' cannot be removed because it is open in {process_names}. "
                                    f"Close {process_names} and try again."
                                )
                        else:
                            errors.append(
                                f"File '{file_name}' cannot be removed because it is open in another application. "
                                f"Close the application that has the file open and try again."
                            )
                        continue
                    
                    # Get file size for logging
                    file_size = file_info.get("size", 0)
                    if not file_size:
                        try:
                            file_size = os.path.getsize(file_path)
                        except Exception:
                            pass
                    
                    # Delete the file
                    os.remove(file_path)
                    deleted_count += 1
                    space_freed += file_size
                    
                    # Remove from database
                    doc_id = file_info.get("id")
                    if doc_id:
                        try:
                            document = db.query(Document).filter(
                                Document.id == doc_id
                            ).first()
                            if document:
                                db.delete(document)
                                db.commit()
                        except Exception as e:
                            # Rollback the transaction if it failed
                            try:
                                db.rollback()
                            except Exception:
                                pass
                            errors.append(
                                f"Error removing file from database: {str(e)}"
                            )
                    
                    # Log activity
                    try:
                        log_activity(
                            activity_type="delete",
                            description=f"Deleted duplicate file: {file_path}",
                            document_path=file_path,
                            space_saved_bytes=file_size,
                            operation_count=1,
                            user_id=current_user.id if current_user else None
                        )
                    except Exception:
                        pass
                        
                except PermissionError as e:
                    errors.append(
                        f"Permission denied when deleting {file_path}. "
                        f"File may be open in another application."
                    )
                except Exception as e:
                    errors.append(f"Error deleting {file_path}: {str(e)}")
        
        # Clean up database entries for files that no longer exist on disk
        # This ensures the database is consistent with the file system
        try:
            folder1 = request.get("folder1", "")
            folder2 = request.get("folder2", "")
            target_folder_path = folder1 if target_folder == 1 else folder2
            
            if target_folder_path:
                # Normalize path
                target_folder_path = os.path.abspath(target_folder_path)
                if target_folder_path and len(target_folder_path) >= 2 and target_folder_path[1] == ':':
                    target_folder_path = target_folder_path[0].upper() + target_folder_path[1:]
                
                # Find all documents in the target folder
                docs_to_check = db.query(Document).filter(
                    Document.file_path.like(f"{target_folder_path}%")
                ).all()
                
                # Remove database entries for files that no longer exist
                # Silently handle database errors - don't show to user
                for doc in docs_to_check:
                    if not os.path.exists(doc.file_path):
                        try:
                            db.delete(doc)
                            db.commit()
                        except Exception as e:
                            # Rollback the transaction if it failed
                            try:
                                db.rollback()
                            except Exception:
                                pass
                            # Log database error but don't add to user-facing errors
                            # Database errors should be reconciled automatically without user involvement
                            import logging
                            logging.warning(f"Database error when removing deleted file from database: {doc.file_path}: {str(e)}")
        except Exception as e:
            # Log database cleanup error but don't show to user
            import logging
            logging.warning(f"Database cleanup error: {str(e)}")
        
        return {
            "success": True,
            "deleted_count": deleted_count,
            "kept_count": kept_count,
            "space_freed": space_freed,
            "errors": errors if errors else None
        }
    
    except Exception as e:
        return {
            "success": False,
            "error": f"Error eliminating duplicates: {str(e)}",
            "deleted_count": deleted_count,
            "kept_count": kept_count,
            "space_freed": space_freed
        }


@app.post("/api/sync/eliminate-duplicates")
async def eliminate_duplicates(
    request: dict,
    current_user: User = Depends(require_full_or_admin),
    db: Session = Depends(get_db)
):
    """
    Eliminate duplicate files and keep only the latest file.
    
    For each duplicate group, finds the latest file (by date_modified or 
    date_created) and deletes all other files.
    """
    from app.reports import log_activity
    
    duplicates = request.get("duplicates", [])
    
    if not duplicates:
        return {
            "success": False,
            "error": "No duplicates provided"
        }
    
    deleted_count = 0
    kept_count = 0
    errors = []
    
    try:
        for dup in duplicates:
            # Collect all files from both folders
            all_files = []
            
            # Add files from folder1
            for doc in dup.get("folder1_docs", []):
                all_files.append({
                    "file_path": doc.get("file_path"),
                    "id": doc.get("id"),
                    "date_modified": doc.get("date_modified"),
                    "date_created": doc.get("date_created"),
                    "size": doc.get("size", 0)
                })
            
            # Add files from folder2
            for doc in dup.get("folder2_docs", []):
                all_files.append({
                    "file_path": doc.get("file_path"),
                    "id": doc.get("id"),
                    "date_modified": doc.get("date_modified"),
                    "date_created": doc.get("date_created"),
                    "size": doc.get("size", 0)
                })
            
            if len(all_files) < 2:
                # Need at least 2 files to have duplicates
                continue
            
            # Find the latest file
            # Use date_modified if available, otherwise date_created
            latest_file = None
            latest_date = None
            
            for file_info in all_files:
                # Try to get date_modified from file system if not in response
                file_path = file_info["file_path"]
                if not file_info.get("date_modified") and os.path.exists(file_path):
                    try:
                        mtime = os.path.getmtime(file_path)
                        file_info["date_modified"] = datetime.fromtimestamp(mtime).isoformat()
                    except Exception:
                        pass
                
                # Determine the date to compare
                compare_date = None
                if file_info.get("date_modified"):
                    try:
                        compare_date = datetime.fromisoformat(file_info["date_modified"])
                    except Exception:
                        pass
                
                if not compare_date and file_info.get("date_created"):
                    try:
                        compare_date = datetime.fromisoformat(file_info["date_created"])
                    except Exception:
                        pass
                
                # If still no date, try to get from file system
                if not compare_date and os.path.exists(file_path):
                    try:
                        compare_date = datetime.fromtimestamp(os.path.getmtime(file_path))
                    except Exception:
                        try:
                            compare_date = datetime.fromtimestamp(os.path.getctime(file_path))
                        except Exception:
                            pass
                
                if compare_date:
                    if latest_date is None or compare_date > latest_date:
                        latest_date = compare_date
                        latest_file = file_info
            
            if not latest_file:
                # If no date available, keep the first file
                latest_file = all_files[0]
                errors.append(f"Could not determine latest file for {dup.get('relative_path', 'unknown')}, keeping first file")
            
            # Delete all other files
            for file_info in all_files:
                if file_info["file_path"] == latest_file["file_path"]:
                    kept_count += 1
                    continue
                
                file_path = file_info["file_path"]
                
                if not os.path.exists(file_path):
                    # File already deleted, skip
                    continue
                
                try:
                    # Try to actually delete the file to see if it's locked
                    # This is more reliable than os.access()
                    try:
                        # Try to open the file with exclusive write access
                        # If this fails, the file is locked
                        test_file = open(file_path, 'r+b')
                        test_file.close()
                    except (PermissionError, IOError, OSError):
                        # File is locked, try to get the process name
                        process_names = _get_locking_process(file_path)
                        file_name = os.path.basename(file_path)
                        
                        # If we couldn't detect the process, try one more time with more aggressive search
                        if not process_names:
                            # Try to find any document viewer that might have files in the same directory
                            try:
                                import psutil
                                file_dir = os.path.dirname(file_path).lower()
                                common_viewers = ['acrobat', 'acrord32', 'acrord64', 'sumatra', 'foxit', 
                                                 'adobe', 'reader', 'word', 'excel', 'powerpoint', 'notepad',
                                                 'notepad++', 'code', 'chrome', 'firefox', 'edge', 'msedge',
                                                 'winword', 'excel', 'powerpnt', 'onenote', 'outlook']
                                
                                for proc in psutil.process_iter(['pid', 'name', 'exe']):
                                    try:
                                        proc_name = proc.info.get('name', '') or proc.info.get('exe', '')
                                        if proc_name:
                                            proc_name_lower = os.path.basename(proc_name).lower()
                                            if any(viewer in proc_name_lower for viewer in common_viewers):
                                                # Check if this process has any files open in the same directory
                                                try:
                                                    open_files = proc.open_files()
                                                    for item in open_files:
                                                        try:
                                                            item_path = item.path if hasattr(item, 'path') else str(item)
                                                            if os.path.dirname(item_path).lower() == file_dir:
                                                                proc_display = os.path.basename(proc_name)
                                                                if proc_display.lower().endswith('.exe'):
                                                                    proc_display = proc_display[:-4]
                                                                if proc_display:
                                                                    process_names = proc_display
                                                                    break
                                                        except Exception:
                                                            continue
                                                    if process_names:
                                                        break
                                                except Exception:
                                                    continue
                                    except Exception:
                                        continue
                            except Exception:
                                pass
                        
                        if process_names:
                            # Format message for single or multiple applications
                            if ',' in process_names:
                                errors.append(
                                    f"File '{file_name}' cannot be removed because it is open in the following application(s): {process_names}. "
                                    f"Close these applications and try again."
                                )
                            else:
                                errors.append(
                                    f"File '{file_name}' cannot be removed because it is open in {process_names}. "
                                    f"Close {process_names} and try again."
                                )
                        else:
                            errors.append(
                                f"File '{file_name}' cannot be removed because it is open in another application. "
                                f"Close the application that has the file open and try again."
                            )
                        continue
                    
                    # Get file size for logging
                    file_size = file_info.get("size", 0)
                    if not file_size and os.path.exists(file_path):
                        try:
                            file_size = os.path.getsize(file_path)
                        except Exception:
                            pass
                    
                    # Delete the file
                    os.remove(file_path)
                    deleted_count += 1
                    
                    # Remove from database
                    doc_id = file_info.get("id")
                    if doc_id:
                        try:
                            document = db.query(Document).filter(
                                Document.id == doc_id
                            ).first()
                            if document:
                                db.delete(document)
                                db.commit()
                        except Exception as e:
                            # Rollback the transaction if it failed
                            try:
                                db.rollback()
                            except Exception:
                                pass
                            # Log database error but don't add to user-facing errors
                            # Database errors should be reconciled automatically without user involvement
                            import logging
                            logging.warning(f"Database error when removing file from database (id={doc_id}): {str(e)}")
                    
                    # Log activity
                    try:
                        log_activity(
                            activity_type="delete",
                            description=f"Deleted duplicate file: {file_path}",
                            document_path=file_path,
                            space_saved_bytes=file_size,
                            operation_count=1,
                            user_id=current_user.id if current_user else None
                        )
                    except Exception:
                        pass  # Don't fail if logging fails
                        
                except PermissionError as e:
                    # Try to get the process name(s) that have the file locked
                    process_names = _get_locking_process(file_path)
                    file_name = os.path.basename(file_path)
                    if process_names:
                        # Format message for single or multiple applications
                        if ',' in process_names:
                            errors.append(
                                f"File '{file_name}' cannot be removed because it is open in the following application(s): {process_names}. "
                                f"Close these applications and try again."
                            )
                        else:
                            errors.append(
                                f"File '{file_name}' cannot be removed because it is open in {process_names}. "
                                f"Close {process_names} and try again."
                            )
                    else:
                        errors.append(
                            f"File '{file_name}' cannot be removed because it is open in another application. "
                            f"Close the application that has the file open and try again."
                        )
                except Exception as e:
                    file_name = os.path.basename(file_path)
                    errors.append(f"Error deleting '{file_name}': {str(e)}")
        
        return {
            "success": True,
            "deleted_count": deleted_count,
            "kept_count": kept_count,
            "errors": errors if errors else None
        }
    
    except Exception as e:
        return {
            "success": False,
            "error": f"Error eliminating duplicates: {str(e)}",
            "deleted_count": deleted_count,
            "kept_count": kept_count
        }


@app.post("/api/sync/execute")
async def execute_sync(
    request: SyncRequest,
    current_user: User = Depends(require_full_or_admin)
):
    """Execute folder synchronization. Requires full or admin role."""
    result = sync_folders(
        folder1=request.folder1,
        folder2=request.folder2,
        strategy=request.strategy,
        target_folder1=request.target_folder1,
        target_folder2=request.target_folder2,
        dry_run=request.dry_run
    )
    return result


# User Management Endpoints (Admin only)
@app.get("/api/users", response_model=List[UserResponse])
async def list_users(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """List all users. Admin only."""
    users = db.query(User).all()
    return [
        UserResponse(
            id=user.id,
            username=user.username,
            role=user.role,
            is_active=user.is_active,
            created_at=user.created_at.isoformat() if user.created_at else ""
        )
        for user in users
    ]


@app.post("/api/users", response_model=UserResponse)
async def create_user(
    user_data: UserCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Create a new user. Admin only."""
    from app.auth import get_password_hash, get_user_by_username
    
    # Validate role
    if user_data.role not in ['readonly', 'full', 'admin']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid role. Must be 'readonly', 'full', or 'admin'"
        )
    
    # Check if user already exists
    existing_user = get_user_by_username(db, user_data.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists"
        )
    
    # Create new user
    hashed_password = get_password_hash(user_data.password)
    new_user = User(
        username=user_data.username,
        hashed_password=hashed_password,
        role=user_data.role,
        is_active=True
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return UserResponse(
        id=new_user.id,
        username=new_user.username,
        role=new_user.role,
        is_active=new_user.is_active,
        created_at=new_user.created_at.isoformat() if new_user.created_at else ""
    )


@app.delete("/api/users/{user_id}")
async def delete_user(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Delete a user. Admin only."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Prevent deleting yourself
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account"
        )
    
    db.delete(user)
    db.commit()
    return {"message": "User deleted successfully"}


@app.get("/sync", response_class=HTMLResponse)
async def sync_page():
    """Sync page with two side-by-side panels."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>DocuSync - Folder Sync</title>
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
                background: #f5f5f5;
                padding: 20px;
            }
            .header {
                background: white;
                padding: 20px;
                border-radius: 8px;
                margin-bottom: 20px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            .header h1 {
                color: #333;
                margin-bottom: 10px;
            }
            .header-top {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 10px;
            }
            .language-selector {
                display: flex;
                align-items: center;
                gap: 10px;
            }
            .language-selector label {
                font-weight: 500;
                font-size: 14px;
            }
            .language-selector select {
                padding: 6px 10px;
                border: 1px solid #ddd;
                border-radius: 4px;
                font-size: 14px;
                background: white;
                cursor: pointer;
            }
            .controls {
                background: white;
                padding: 20px;
                border-radius: 8px;
                margin-bottom: 20px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            .controls-row {
                display: flex;
                gap: 15px;
                margin-bottom: 15px;
                align-items: center;
            }
            .controls-row label {
                min-width: 120px;
                font-weight: 500;
            }
            .controls-row input, .controls-row select {
                flex: 1;
                padding: 8px 12px;
                border: 1px solid #ddd;
                border-radius: 4px;
                font-size: 14px;
            }
            .folder-input-group {
                flex: 1;
                display: flex;
                gap: 8px;
                align-items: center;
            }
            .folder-input-group input {
                flex: 1;
            }
            .browse-btn {
                padding: 8px 16px;
                background: #28a745;
                color: white;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-size: 14px;
                white-space: nowrap;
            }
            .browse-btn:hover {
                background: #218838;
            }
            .controls-row button {
                padding: 10px 20px;
                background: #007bff;
                color: white;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-size: 14px;
            }
            .controls-row button:hover {
                background: #0056b3;
            }
            .controls-row button:disabled {
                background: #ccc;
                cursor: not-allowed;
            }
            .sync-container {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 20px;
            }
            .panel {
                background: white;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                overflow: hidden;
            }
            .panel-header {
                background: #007bff;
                color: white;
                padding: 15px;
                font-weight: 600;
            }
            .panel-content {
                padding: 15px;
                max-height: 600px;
                overflow-y: auto;
            }
            .file-item {
                padding: 10px;
                border-bottom: 1px solid #eee;
                cursor: pointer;
            }
            .file-item:hover {
                background: #f8f9fa;
            }
            .file-item.selected {
                background: #e3f2fd;
            }
            .file-name {
                font-weight: 500;
                color: #333;
                margin-bottom: 5px;
            }
            .file-meta {
                font-size: 12px;
                color: #666;
            }
            .stats {
                background: #f8f9fa;
                padding: 15px;
                border-top: 1px solid #eee;
            }
            .stats-item {
                display: flex;
                justify-content: space-between;
                margin-bottom: 5px;
            }
            .message {
                padding: 15px;
                margin: 10px 0;
                border-radius: 4px;
            }
            .message.success {
                background: #d4edda;
                color: #155724;
                border: 1px solid #c3e6cb;
            }
            .message.error {
                background: #f8d7da;
                color: #721c24;
                border: 1px solid #f5c6cb;
            }
            .message.info {
                background: #d1ecf1;
                color: #0c5460;
                border: 1px solid #bee5eb;
            }
            .loading {
                text-align: center;
                padding: 20px;
                color: #666;
            }
            .progress-container {
                display: none;
                margin: 20px 0;
                background: white;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            .progress-container.show {
                display: block;
            }
            .progress-bar-wrapper {
                width: 100%;
                height: 24px;
                background: #e9ecef;
                border-radius: 12px;
                overflow: hidden;
                position: relative;
            }
            .progress-bar {
                height: 100%;
                background: linear-gradient(90deg, #007bff, #0056b3);
                width: 0%;
                transition: width 0.3s ease;
                animation: progress-animation 1.5s ease-in-out infinite;
            }
            .progress-bar-fill {
                position: absolute;
                top: 0;
                left: 0;
                height: 100%;
                width: 0%;
                background: linear-gradient(90deg, #007bff, #0056b3);
                transition: width 0.3s ease;
            }
            @keyframes progress-animation {
                0% {
                    background-position: 0% 50%;
                }
                50% {
                    background-position: 100% 50%;
                }
                100% {
                    background-position: 0% 50%;
                }
            }
            .progress-text {
                margin-top: 10px;
                text-align: center;
                color: #666;
                font-size: 14px;
            }
            .progress-file-list {
                margin-top: 10px;
                max-height: 150px;
                overflow-y: auto;
                background: #f8f9fa;
                padding: 10px;
                border-radius: 4px;
                font-size: 12px;
                color: #555;
            }
            .progress-file-item {
                padding: 4px 0;
                border-bottom: 1px solid #e9ecef;
            }
            .progress-file-item:last-child {
                border-bottom: none;
            }
            .confirm-dialog {
                display: none;
                position: fixed;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                background: white;
                padding: 30px;
                border-radius: 8px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.3);
                z-index: 10000;
                min-width: 400px;
                max-width: 600px;
            }
            .confirm-dialog.show {
                display: block;
            }
            .confirm-dialog-overlay {
                display: none;
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0,0,0,0.5);
                z-index: 9999;
            }
            .confirm-dialog-overlay.show {
                display: block;
            }
            .confirm-dialog h3 {
                margin: 0 0 15px 0;
                color: #333;
            }
            .confirm-dialog .file-info {
                margin: 15px 0;
                padding: 10px;
                background: #f8f9fa;
                border-radius: 4px;
                font-size: 14px;
            }
            .confirm-dialog .file-info strong {
                display: block;
                margin-bottom: 5px;
            }
            .confirm-dialog-buttons {
                display: flex;
                gap: 10px;
                margin-top: 20px;
                justify-content: flex-end;
            }
            .confirm-dialog-buttons button {
                padding: 10px 20px;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-size: 14px;
                font-weight: 500;
            }
            .confirm-dialog-buttons .btn-yes {
                background: #28a745;
                color: white;
            }
            .confirm-dialog-buttons .btn-yes:hover {
                background: #218838;
            }
            .confirm-dialog-buttons .btn-no {
                background: #dc3545;
                color: white;
            }
            .confirm-dialog-buttons .btn-no:hover {
                background: #c82333;
            }
            .confirm-dialog-buttons .btn-all {
                background: #007bff;
                color: white;
            }
            .confirm-dialog-buttons .btn-all:hover {
                background: #0056b3;
            }
            .confirm-dialog-buttons .btn-abort {
                background: #6c757d;
                color: white;
            }
            .confirm-dialog-buttons .btn-abort:hover {
                background: #5a6268;
            }
            .sync-status-panel {
                display: none;
                background: white;
                padding: 20px;
                border-radius: 8px;
                margin: 20px 0;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            .sync-status-panel.show {
                display: block;
            }
            .sync-status-header {
                font-size: 18px;
                font-weight: 600;
                color: #333;
                margin-bottom: 15px;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            .sync-status-current {
                background: #f8f9fa;
                padding: 15px;
                border-radius: 4px;
                margin: 15px 0;
                border-left: 4px solid #007bff;
            }
            .sync-status-current-file {
                font-weight: 600;
                color: #333;
                margin-bottom: 5px;
            }
            .sync-status-current-path {
                font-size: 12px;
                color: #666;
                margin: 5px 0;
            }
            .sync-status-progress {
                margin: 10px 0;
                font-size: 14px;
                color: #666;
            }
            .sync-status-stats {
                display: flex;
                gap: 20px;
                margin-top: 15px;
                padding-top: 15px;
                border-top: 1px solid #eee;
            }
            .sync-status-stat {
                flex: 1;
                text-align: center;
            }
            .sync-status-stat-label {
                font-size: 12px;
                color: #666;
                margin-bottom: 5px;
            }
            .sync-status-stat-value {
                font-size: 20px;
                font-weight: 600;
                color: #007bff;
            }
            .sync-status-confirm-inline {
                background: #fff3cd;
                border: 2px solid #ffc107;
                padding: 15px;
                border-radius: 4px;
                margin: 15px 0;
            }
            .sync-status-confirm-inline h4 {
                margin: 0 0 10px 0;
                color: #856404;
            }
            .sync-status-errors {
                display: none;
                background: #f8d7da;
                border: 1px solid #f5c6cb;
                padding: 15px;
                border-radius: 4px;
                margin: 15px 0;
                max-height: 300px;
                overflow-y: auto;
            }
            .sync-status-errors.show {
                display: block;
            }
            .sync-status-errors h4 {
                margin: 0 0 10px 0;
                color: #721c24;
                font-size: 14px;
            }
            .sync-status-error-list {
                list-style: none;
                padding: 0;
                margin: 0;
            }
            .sync-status-error-item {
                padding: 8px;
                margin: 5px 0;
                background: white;
                border-left: 3px solid #dc3545;
                border-radius: 3px;
                font-size: 12px;
                color: #721c24;
            }
            .sync-status-error-item strong {
                color: #721c24;
            }
        </style>
    </head>
    <body>
        <div class="header">
            <div class="header-top">
                <h1>DocuSync - Folder Synchronization</h1>
                <div class="language-selector">
                    <label for="languageSelect">Language:</label>
                    <select id="languageSelect">
                        <option value="en">English</option>
                        <option value="de">German</option>
                        <option value="fr">French</option>
                        <option value="es">Spanish</option>
                        <option value="it">Italian</option>
                        <option value="ru">Russian</option>
                    </select>
                </div>
            </div>
            <p>Compare and sync files between two folders or drives</p>
        </div>
        
        <div class="controls">
            <div class="controls-row">
                <label>Folder 1:</label>
                <div class="folder-input-group">
                    <input type="text" id="folder1" placeholder="C:/folder1 or C">
                    <button type="button" class="browse-btn" onclick="browseFolder('folder1')">Browse</button>
                </div>
            </div>
            <div class="controls-row">
                <label>Folder 2:</label>
                <div class="folder-input-group">
                    <input type="text" id="folder2" placeholder="D:/folder2 or D">
                    <button type="button" class="browse-btn" onclick="browseFolder('folder2')">Browse</button>
                </div>
            </div>
            <div class="controls-row">
                <label>Sync Strategy:</label>
                <select id="strategy">
                    <option value="keep_both">Keep Both</option>
                    <option value="keep_newest">Keep Newest</option>
                    <option value="keep_largest">Keep Largest</option>
                </select>
            </div>
            <div class="controls-row">
                <button id="analyzeBtn">Analyze</button>
                <button id="executeBtn" disabled>Execute Sync</button>
                <div id="eliminateButtonsContainer" style="display: none; margin-left: 10px;"></div>
            </div>
        </div>
        
        <div id="messages"></div>
        
        <div class="sync-status-panel" id="syncStatusPanel">
            <div class="sync-status-header">
                <span id="syncStatusTitle">Synchronization in Progress</span>
                <div style="display: flex; gap: 10px;">
                    <button onclick="abortSync()" id="abortBtn" style="padding: 5px 15px; background: #dc3545; color: white; border: none; border-radius: 4px; cursor: pointer;">Abort</button>
                    <button onclick="closeSyncStatus()" id="closeSyncBtn" style="padding: 5px 15px; background: #6c757d; color: white; border: none; border-radius: 4px; cursor: pointer; display: none;">Close</button>
                </div>
            </div>
            <div class="sync-status-current" id="syncStatusCurrent">
                <div class="sync-status-current-file" id="syncStatusFile">Waiting to start...</div>
                <div class="sync-status-current-path" id="syncStatusPath"></div>
                <div class="sync-status-progress" id="syncStatusProgress"></div>
            </div>
            <div class="sync-status-confirm-inline" id="syncStatusConfirm" style="display: none;">
                <h4>Confirm File Copy</h4>
                <div id="syncConfirmFileInfo"></div>
                <div class="confirm-dialog-buttons" style="margin-top: 15px;">
                    <button class="btn-yes" onclick="confirmChoice('yes')">Yes (Y)</button>
                    <button class="btn-no" onclick="confirmChoice('no')">No (N)</button>
                    <button class="btn-all" onclick="confirmChoice('all')">All (A)</button>
                    <button class="btn-abort" onclick="confirmChoice('abort')">Abort</button>
                </div>
            </div>
            <div class="sync-status-stats">
                <div class="sync-status-stat">
                    <div class="sync-status-stat-label">Copied</div>
                    <div class="sync-status-stat-value" id="syncStatCopied">0</div>
                </div>
                <div class="sync-status-stat">
                    <div class="sync-status-stat-label">Skipped</div>
                    <div class="sync-status-stat-value" id="syncStatSkipped" style="color: #6c757d;">0</div>
                </div>
                <div class="sync-status-stat">
                    <div class="sync-status-stat-label">Errors</div>
                    <div class="sync-status-stat-value" id="syncStatErrors" style="color: #dc3545;">0</div>
                </div>
                <div class="sync-status-stat">
                    <div class="sync-status-stat-label">Total</div>
                    <div class="sync-status-stat-value" id="syncStatTotal" style="color: #28a745;">0</div>
                </div>
            </div>
            <div class="sync-status-errors" id="syncStatusErrors">
                <h4>Error Details:</h4>
                <ul class="sync-status-error-list" id="syncErrorList"></ul>
            </div>
        </div>
        
        <div class="confirm-dialog-overlay" id="confirmOverlay"></div>
        <div class="confirm-dialog" id="confirmDialog">
            <h3>Confirm File Copy</h3>
            <div class="file-info" id="confirmFileInfo"></div>
            <div class="confirm-dialog-buttons">
                <button class="btn-yes" onclick="confirmChoice('yes')">Yes (Y)</button>
                <button class="btn-no" onclick="confirmChoice('no')">No (N)</button>
                <button class="btn-all" onclick="confirmChoice('all')">All (A)</button>
                <button class="btn-abort" onclick="confirmChoice('abort')">Abort</button>
            </div>
        </div>
        
        <div class="progress-container" id="progressContainer">
            <div class="progress-bar-wrapper">
                <div class="progress-bar" id="progressBar"></div>
            </div>
            <div class="progress-text" id="progressText">Scanning folders and analyzing...</div>
            <div class="progress-file-list" id="progressFileList" style="display: none;"></div>
        </div>
        
        <div class="sync-container" id="syncContainer" style="display: none;">
            <div class="panel">
                <div class="panel-header">Folder 1</div>
                <div class="panel-content" id="panel1"></div>
                <div class="stats" id="stats1"></div>
            </div>
            <div class="panel">
                <div class="panel-header">Folder 2</div>
                <div class="panel-content" id="panel2"></div>
                <div class="stats" id="stats2"></div>
            </div>
        </div>
        
        <script>
            // Language support
            const translations = {
                en: {
                    title: 'DocuSync - Folder Synchronization',
                    subtitle: 'Compare and sync files between two folders or drives',
                    folder1: 'Folder 1:',
                    folder2: 'Folder 2:',
                    syncStrategy: 'Sync Strategy:',
                    keepBoth: 'Keep Both',
                    keepNewest: 'Keep Newest',
                    keepLargest: 'Keep Largest',
                    analyze: 'Analyze',
                    executeSync: 'Execute Sync',
                    browse: 'Browse',
                    language: 'Language:',
                    numberOfFilesInBiggerFolder: 'Number of Files in bigger folder',
                    spaceNeededToSync: 'Space needed to sync',
                    duplicates: 'Duplicates',
                    foldersIdentical: 'Folder {0} and {1} are identical. Files of types: {2}',
                    folderHasLessFiles: 'Folder {0} has less files than {1}.',
                    noDifferencesFound: 'No differences found in {0}. All files match or folder is empty.',
                    analysisComplete: 'Analysis complete: {0} files only in {1}, {2} files only in {3}, {4} duplicates',
                    analysisCompleteSimple: 'Analysis complete',
                    analysisFailed: 'Analysis failed: {0}',
                    notAuthenticated: 'Not authenticated. Please login again.',
                    pleaseEnterBothFolders: 'Please enter both folders',
                    analyzing: 'Analyzing...',
                    sessionExpired: 'Session expired. Please login again.',
                    error: 'Error: {0}',
                    successfullyEliminated: 'Successfully eliminated {0} duplicate file(s). Kept {1} latest file(s).',
                    successfullyEliminatedFolder: 'Successfully eliminated {0} duplicate file(s) in {1}. Freed up {2}.',
                    confirmEliminate: 'Are you sure you want to eliminate {0} duplicate(s) and keep only the latest file? This action cannot be undone.',
                    confirmEliminateFolder: 'Are you sure you want to eliminate {0} duplicate file(s) in {1} and free up {2}? This action cannot be undone.',
                    eliminateDuplicates: 'Eliminate duplicates and keep only the latest file',
                    eliminateDuplicatesFolder: 'Eliminate {0} duplicate file{1} in {2} and free up {3} KB on disk {4}',
                    processing: 'Processing...',
                    refreshingAnalysis: 'Refreshing analysis...',
                    filesOnlyIn: 'Files only in {0} (showing {1} of {2}):',
                    filesOnlyInSimple: 'Files only in {0} ({1}):',
                    andMoreFiles: '... and {0} more files',
                    someFilesCouldNotBeDeleted: 'Some files could not be deleted:\\n\\n{0}',
                    failedToEliminate: 'Failed to eliminate duplicates'
                },
                de: {
                    title: 'DocuSync - Ordner-Synchronisation',
                    subtitle: 'Dateien zwischen zwei Ordnern oder Laufwerken vergleichen und synchronisieren',
                    folder1: 'Ordner 1:',
                    folder2: 'Ordner 2:',
                    syncStrategy: 'Synchronisationsstrategie:',
                    keepBoth: 'Beide behalten',
                    keepNewest: 'Neueste behalten',
                    keepLargest: 'Größte behalten',
                    analyze: 'Analysieren',
                    executeSync: 'Synchronisation ausführen',
                    browse: 'Durchsuchen',
                    language: 'Sprache:',
                    numberOfFilesInBiggerFolder: 'Anzahl der Dateien im größeren Ordner',
                    spaceNeededToSync: 'Benötigter Speicherplatz für Synchronisation',
                    duplicates: 'Duplikate',
                    foldersIdentical: 'Ordner {0} und {1} sind identisch. Dateitypen: {2}',
                    folderHasLessFiles: 'Ordner {0} hat weniger Dateien als {1}.',
                    noDifferencesFound: 'Keine Unterschiede in {0} gefunden. Alle Dateien stimmen überein oder der Ordner ist leer.',
                    analysisComplete: 'Analyse abgeschlossen: {0} Dateien nur in {1}, {2} Dateien nur in {3}, {4} Duplikate',
                    analysisCompleteSimple: 'Analyse abgeschlossen',
                    analysisFailed: 'Analyse fehlgeschlagen: {0}',
                    notAuthenticated: 'Nicht authentifiziert. Bitte erneut anmelden.',
                    pleaseEnterBothFolders: 'Bitte beide Ordner eingeben',
                    analyzing: 'Analysiere...',
                    sessionExpired: 'Sitzung abgelaufen. Bitte erneut anmelden.',
                    error: 'Fehler: {0}',
                    successfullyEliminated: 'Erfolgreich {0} doppelte Datei(en) entfernt. {1} neueste Datei(en) behalten.',
                    successfullyEliminatedFolder: 'Erfolgreich {0} doppelte Datei(en) in {1} entfernt. {2} freigegeben.',
                    confirmEliminate: 'Sind Sie sicher, dass Sie {0} Duplikat(e) entfernen und nur die neueste Datei behalten möchten? Diese Aktion kann nicht rückgängig gemacht werden.',
                    confirmEliminateFolder: 'Sind Sie sicher, dass Sie {0} doppelte Datei(en) in {1} entfernen und {2} freigeben möchten? Diese Aktion kann nicht rückgängig gemacht werden.',
                    eliminateDuplicates: 'Duplikate entfernen und nur die neueste Datei behalten',
                    eliminateDuplicatesFolder: 'Entferne {0} doppelte Datei{1} in {2} und gebe {3} KB auf Laufwerk {4} frei',
                    processing: 'Verarbeite...',
                    refreshingAnalysis: 'Aktualisiere Analyse...',
                    filesOnlyIn: 'Dateien nur in {0} (zeige {1} von {2}):',
                    filesOnlyInSimple: 'Dateien nur in {0} ({1}):',
                    andMoreFiles: '... und {0} weitere Dateien',
                    someFilesCouldNotBeDeleted: 'Einige Dateien konnten nicht gelöscht werden:\\n\\n{0}',
                    failedToEliminate: 'Duplikate entfernen fehlgeschlagen'
                },
                fr: {
                    title: 'DocuSync - Synchronisation de dossiers',
                    subtitle: 'Comparer et synchroniser les fichiers entre deux dossiers ou lecteurs',
                    folder1: 'Dossier 1:',
                    folder2: 'Dossier 2:',
                    syncStrategy: 'Stratégie de synchronisation:',
                    keepBoth: 'Garder les deux',
                    keepNewest: 'Garder le plus récent',
                    keepLargest: 'Garder le plus grand',
                    analyze: 'Analyser',
                    executeSync: 'Exécuter la synchronisation',
                    browse: 'Parcourir',
                    language: 'Langue:',
                    numberOfFilesInBiggerFolder: 'Nombre de fichiers dans le dossier le plus grand',
                    spaceNeededToSync: 'Espace nécessaire pour la synchronisation',
                    duplicates: 'Doublons',
                    foldersIdentical: 'Les dossiers {0} et {1} sont identiques. Types de fichiers: {2}',
                    folderHasLessFiles: 'Le dossier {0} a moins de fichiers que {1}.',
                    noDifferencesFound: 'Aucune différence trouvée dans {0}. Tous les fichiers correspondent ou le dossier est vide.',
                    analysisComplete: 'Analyse terminée: {0} fichiers uniquement dans {1}, {2} fichiers uniquement dans {3}, {4} doublons',
                    analysisCompleteSimple: 'Analyse terminée',
                    analysisFailed: 'Analyse échouée: {0}',
                    notAuthenticated: 'Non authentifié. Veuillez vous reconnecter.',
                    pleaseEnterBothFolders: 'Veuillez entrer les deux dossiers',
                    analyzing: 'Analyse en cours...',
                    sessionExpired: 'Session expirée. Veuillez vous reconnecter.',
                    error: 'Erreur: {0}',
                    successfullyEliminated: 'Suppression réussie de {0} fichier(s) en double. {1} fichier(s) le(s) plus récent(s) conservé(s).',
                    successfullyEliminatedFolder: 'Suppression réussie de {0} fichier(s) en double dans {1}. {2} libéré(s).',
                    confirmEliminate: 'Êtes-vous sûr de vouloir supprimer {0} doublon(s) et ne garder que le fichier le plus récent? Cette action ne peut pas être annulée.',
                    confirmEliminateFolder: 'Êtes-vous sûr de vouloir supprimer {0} fichier(s) en double dans {1} et libérer {2}? Cette action ne peut pas être annulée.',
                    eliminateDuplicates: 'Supprimer les doublons et ne garder que le fichier le plus récent',
                    eliminateDuplicatesFolder: 'Supprimer {0} fichier(s) en double dans {1} et libérer {2} Ko sur le disque {3}',
                    processing: 'Traitement en cours...',
                    refreshingAnalysis: 'Actualisation de l\'analyse...',
                    filesOnlyIn: 'Fichiers uniquement dans {0} (affichage de {1} sur {2}):',
                    filesOnlyInSimple: 'Fichiers uniquement dans {0} ({1}):',
                    andMoreFiles: '... et {0} autres fichiers',
                    someFilesCouldNotBeDeleted: 'Certains fichiers n\'ont pas pu être supprimés:\\n\\n{0}',
                    failedToEliminate: 'Échec de la suppression des doublons'
                },
                es: {
                    title: 'DocuSync - Sincronización de carpetas',
                    subtitle: 'Comparar y sincronizar archivos entre dos carpetas o unidades',
                    folder1: 'Carpeta 1:',
                    folder2: 'Carpeta 2:',
                    syncStrategy: 'Estrategia de sincronización:',
                    keepBoth: 'Mantener ambos',
                    keepNewest: 'Mantener el más reciente',
                    keepLargest: 'Mantener el más grande',
                    analyze: 'Analizar',
                    executeSync: 'Ejecutar sincronización',
                    browse: 'Examinar',
                    language: 'Idioma:',
                    numberOfFilesInBiggerFolder: 'Número de archivos en la carpeta más grande',
                    spaceNeededToSync: 'Espacio necesario para sincronizar',
                    duplicates: 'Duplicados',
                    foldersIdentical: 'Las carpetas {0} y {1} son idénticas. Tipos de archivos: {2}',
                    folderHasLessFiles: 'La carpeta {0} tiene menos archivos que {1}.',
                    noDifferencesFound: 'No se encontraron diferencias en {0}. Todos los archivos coinciden o la carpeta está vacía.',
                    analysisComplete: 'Análisis completo: {0} archivos solo en {1}, {2} archivos solo en {3}, {4} duplicados',
                    analysisCompleteSimple: 'Análisis completo',
                    analysisFailed: 'Análisis fallido: {0}',
                    notAuthenticated: 'No autenticado. Por favor, inicie sesión nuevamente.',
                    pleaseEnterBothFolders: 'Por favor, ingrese ambas carpetas',
                    analyzing: 'Analizando...',
                    sessionExpired: 'Sesión expirada. Por favor, inicie sesión nuevamente.',
                    error: 'Error: {0}',
                    successfullyEliminated: 'Eliminados exitosamente {0} archivo(s) duplicado(s). Se mantuvieron {1} archivo(s) más reciente(s).',
                    successfullyEliminatedFolder: 'Eliminados exitosamente {0} archivo(s) duplicado(s) en {1}. Se liberaron {2}.',
                    confirmEliminate: '¿Está seguro de que desea eliminar {0} duplicado(s) y mantener solo el archivo más reciente? Esta acción no se puede deshacer.',
                    confirmEliminateFolder: '¿Está seguro de que desea eliminar {0} archivo(s) duplicado(s) en {1} y liberar {2}? Esta acción no se puede deshacer.',
                    eliminateDuplicates: 'Eliminar duplicados y mantener solo el archivo más reciente',
                    eliminateDuplicatesFolder: 'Eliminar {0} archivo(s) duplicado(s) en {1} y liberar {2} KB en el disco {3}',
                    processing: 'Procesando...',
                    refreshingAnalysis: 'Actualizando análisis...',
                    filesOnlyIn: 'Archivos solo en {0} (mostrando {1} de {2}):',
                    filesOnlyInSimple: 'Archivos solo en {0} ({1}):',
                    andMoreFiles: '... y {0} archivos más',
                    someFilesCouldNotBeDeleted: 'Algunos archivos no pudieron ser eliminados:\\n\\n{0}',
                    failedToEliminate: 'Error al eliminar duplicados'
                },
                it: {
                    title: 'DocuSync - Sincronizzazione cartelle',
                    subtitle: 'Confronta e sincronizza file tra due cartelle o unità',
                    folder1: 'Cartella 1:',
                    folder2: 'Cartella 2:',
                    syncStrategy: 'Strategia di sincronizzazione:',
                    keepBoth: 'Mantieni entrambi',
                    keepNewest: 'Mantieni il più recente',
                    keepLargest: 'Mantieni il più grande',
                    analyze: 'Analizza',
                    executeSync: 'Esegui sincronizzazione',
                    browse: 'Sfoglia',
                    language: 'Lingua:',
                    numberOfFilesInBiggerFolder: 'Numero di file nella cartella più grande',
                    spaceNeededToSync: 'Spazio necessario per sincronizzare',
                    duplicates: 'Duplicati',
                    foldersIdentical: 'Le cartelle {0} e {1} sono identiche. Tipi di file: {2}',
                    folderHasLessFiles: 'La cartella {0} ha meno file di {1}.',
                    noDifferencesFound: 'Nessuna differenza trovata in {0}. Tutti i file corrispondono o la cartella è vuota.',
                    analysisComplete: 'Analisi completata: {0} file solo in {1}, {2} file solo in {3}, {4} duplicati',
                    analysisCompleteSimple: 'Analisi completata',
                    analysisFailed: 'Analisi fallita: {0}',
                    notAuthenticated: 'Non autenticato. Effettuare nuovamente l\'accesso.',
                    pleaseEnterBothFolders: 'Inserire entrambe le cartelle',
                    analyzing: 'Analisi in corso...',
                    sessionExpired: 'Sessione scaduta. Effettuare nuovamente l\'accesso.',
                    error: 'Errore: {0}',
                    successfullyEliminated: 'Eliminati con successo {0} file duplicato(i). Mantenuti {1} file più recente(i).',
                    successfullyEliminatedFolder: 'Eliminati con successo {0} file duplicato(i) in {1}. Liberati {2}.',
                    confirmEliminate: 'Sei sicuro di voler eliminare {0} duplicato(i) e mantenere solo il file più recente? Questa azione non può essere annullata.',
                    confirmEliminateFolder: 'Sei sicuro di voler eliminare {0} file duplicato(i) in {1} e liberare {2}? Questa azione non può essere annullata.',
                    eliminateDuplicates: 'Elimina duplicati e mantieni solo il file più recente',
                    eliminateDuplicatesFolder: 'Elimina {0} file duplicato(i) in {1} e libera {2} KB sul disco {3}',
                    processing: 'Elaborazione in corso...',
                    refreshingAnalysis: 'Aggiornamento analisi...',
                    filesOnlyIn: 'File solo in {0} (mostra {1} di {2}):',
                    filesOnlyInSimple: 'File solo in {0} ({1}):',
                    andMoreFiles: '... e {0} altri file',
                    someFilesCouldNotBeDeleted: 'Alcuni file non sono stati eliminati:\\n\\n{0}',
                    failedToEliminate: 'Eliminazione duplicati fallita'
                },
                ru: {
                    title: 'DocuSync - Синхронизация папок',
                    subtitle: 'Сравнение и синхронизация файлов между двумя папками или дисками',
                    folder1: 'Папка 1:',
                    folder2: 'Папка 2:',
                    syncStrategy: 'Стратегия синхронизации:',
                    keepBoth: 'Сохранить оба',
                    keepNewest: 'Сохранить самый новый',
                    keepLargest: 'Сохранить самый большой',
                    analyze: 'Анализировать',
                    executeSync: 'Выполнить синхронизацию',
                    browse: 'Обзор',
                    language: 'Язык:',
                    numberOfFilesInBiggerFolder: 'Количество файлов в большей папке',
                    spaceNeededToSync: 'Необходимое место для синхронизации',
                    duplicates: 'Дубликаты',
                    foldersIdentical: 'Папки {0} и {1} идентичны. Типы файлов: {2}',
                    folderHasLessFiles: 'В папке {0} меньше файлов, чем в {1}.',
                    noDifferencesFound: 'Различий в {0} не найдено. Все файлы совпадают или папка пуста.',
                    analysisComplete: 'Анализ завершен: {0} файлов только в {1}, {2} файлов только в {3}, {4} дубликатов',
                    analysisCompleteSimple: 'Анализ завершен',
                    analysisFailed: 'Анализ не удался: {0}',
                    notAuthenticated: 'Не авторизован. Пожалуйста, войдите снова.',
                    pleaseEnterBothFolders: 'Пожалуйста, введите обе папки',
                    analyzing: 'Анализ...',
                    sessionExpired: 'Сессия истекла. Пожалуйста, войдите снова.',
                    error: 'Ошибка: {0}',
                    successfullyEliminated: 'Успешно удалено {0} дубликат(ов) файла(ов). Сохранено {1} последних файл(ов).',
                    successfullyEliminatedFolder: 'Успешно удалено {0} дубликат(ов) файла(ов) в {1}. Освобождено {2}.',
                    confirmEliminate: 'Вы уверены, что хотите удалить {0} дубликат(ов) и оставить только последний файл? Это действие нельзя отменить.',
                    confirmEliminateFolder: 'Вы уверены, что хотите удалить {0} дубликат(ов) файла(ов) в {1} и освободить {2}? Это действие нельзя отменить.',
                    eliminateDuplicates: 'Удалить дубликаты и оставить только последний файл',
                    eliminateDuplicatesFolder: 'Удалить {0} дубликат(ов) файла(ов) в {1} и освободить {2} КБ на диске {3}',
                    processing: 'Обработка...',
                    refreshingAnalysis: 'Обновление анализа...',
                    filesOnlyIn: 'Файлы только в {0} (показано {1} из {2}):',
                    filesOnlyInSimple: 'Файлы только в {0} ({1}):',
                    andMoreFiles: '... и еще {0} файлов',
                    someFilesCouldNotBeDeleted: 'Некоторые файлы не удалось удалить:\\n\\n{0}',
                    failedToEliminate: 'Не удалось удалить дубликаты'
                }
            };
            
            // Helper function to format translated messages with placeholders
            function formatMessage(key, ...args) {
                const t = translations[currentLanguage] || translations.en;
                let message = t[key] || key;
                // Replace placeholders {0}, {1}, {2}, etc. with arguments
                args.forEach((arg, index) => {
                    message = message.replace(`{${index}}`, arg);
                });
                return message;
            }
            
            // Detect user's language from browser
            function detectUserLanguage() {
                // Check localStorage first
                const savedLang = localStorage.getItem('docuSync_language');
                if (savedLang && translations[savedLang]) {
                    return savedLang;
                }
                
                // Detect from browser
                const browserLang = navigator.language || navigator.userLanguage;
                const langCode = browserLang.split('-')[0].toLowerCase();
                
                // Map browser language to supported languages
                const langMap = {
                    'en': 'en',
                    'de': 'de',
                    'fr': 'fr',
                    'es': 'es',
                    'it': 'it',
                    'ru': 'ru'
                };
                
                return langMap[langCode] || 'en'; // Default to English
            }
            
            // Apply translations
            function applyTranslations(lang) {
                const t = translations[lang] || translations.en;
                
                // Update title
                const h1 = document.querySelector('.header h1');
                if (h1) h1.textContent = t.title;
                
                // Update subtitle
                const p = document.querySelector('.header p');
                if (p) p.textContent = t.subtitle;
                
                // Update labels
                const labels = document.querySelectorAll('.controls-row label');
                labels.forEach(label => {
                    const text = label.textContent.trim();
                    if (text.includes('Folder 1') || text.includes('Ordner 1') || text.includes('Dossier 1') || text.includes('Carpeta 1') || text.includes('Cartella 1') || text.includes('Папка 1')) {
                        label.textContent = t.folder1;
                    } else if (text.includes('Folder 2') || text.includes('Ordner 2') || text.includes('Dossier 2') || text.includes('Carpeta 2') || text.includes('Cartella 2') || text.includes('Папка 2')) {
                        label.textContent = t.folder2;
                    } else if (text.includes('Sync Strategy') || text.includes('Synchronisationsstrategie') || text.includes('Stratégie') || text.includes('Estrategia') || text.includes('Strategia') || text.includes('Стратегия')) {
                        label.textContent = t.syncStrategy;
                    }
                });
                
                // Update language selector label
                const langLabel = document.querySelector('.language-selector label');
                if (langLabel) langLabel.textContent = t.language;
                
                // Update buttons
                const analyzeBtn = document.getElementById('analyzeBtn');
                if (analyzeBtn) analyzeBtn.textContent = t.analyze;
                
                const executeBtn = document.getElementById('executeBtn');
                if (executeBtn) executeBtn.textContent = t.executeSync;
                
                // Update browse buttons
                const browseBtns = document.querySelectorAll('.browse-btn');
                browseBtns.forEach(btn => {
                    if (btn.textContent.includes('Browse') || btn.textContent.includes('Durchsuchen') || btn.textContent.includes('Parcourir') || btn.textContent.includes('Examinar') || btn.textContent.includes('Sfoglia') || btn.textContent.includes('Обзор')) {
                        btn.textContent = t.browse;
                    }
                });
                
                // Update select options
                const strategySelect = document.getElementById('strategy');
                if (strategySelect) {
                    const options = strategySelect.options;
                    if (options[0]) options[0].textContent = t.keepBoth;
                    if (options[1]) options[1].textContent = t.keepNewest;
                    if (options[2]) options[2].textContent = t.keepLargest;
                }
                
                // Update stats labels if analysis is already displayed
                const stats1 = document.getElementById('stats1');
                const stats2 = document.getElementById('stats2');
                
                if (stats1 && stats1.innerHTML) {
                    // Parse and update stats1
                    const stats1HTML = stats1.innerHTML;
                    const stats1Div = stats1;
                    const statsItems = stats1Div.querySelectorAll('.stats-item');
                    statsItems.forEach(item => {
                        const span = item.querySelector('span:first-child');
                        if (span) {
                            const text = span.textContent.trim();
                            // Check if it's a stats label that needs translation
                            if (text.includes('Number of Files in bigger folder') || 
                                text.includes('Anzahl der Dateien') ||
                                text.includes('Nombre de fichiers') ||
                                text.includes('Número de archivos') ||
                                text.includes('Numero di file') ||
                                text.includes('Количество файлов')) {
                                span.textContent = t.numberOfFilesInBiggerFolder + ':';
                            } else if (text.includes('Space needed to sync') || 
                                      text.includes('Benötigter Speicherplatz') ||
                                      text.includes('Espace nécessaire') ||
                                      text.includes('Espacio necesario') ||
                                      text.includes('Spazio necessario') ||
                                      text.includes('Необходимое место')) {
                                span.textContent = t.spaceNeededToSync + ':';
                            }
                        }
                    });
                }
                
                if (stats2 && stats2.innerHTML) {
                    // Parse and update stats2
                    const stats2Div = stats2;
                    const statsItems = stats2Div.querySelectorAll('.stats-item');
                    statsItems.forEach(item => {
                        const span = item.querySelector('span:first-child');
                        if (span) {
                            const text = span.textContent.trim();
                            // Check if it's a stats label that needs translation
                            if (text.includes('Number of Files in bigger folder') || 
                                text.includes('Anzahl der Dateien') ||
                                text.includes('Nombre de fichiers') ||
                                text.includes('Número de archivos') ||
                                text.includes('Numero di file') ||
                                text.includes('Количество файлов')) {
                                span.textContent = t.numberOfFilesInBiggerFolder + ':';
                            } else if (text.includes('Space needed to sync') || 
                                      text.includes('Benötigter Speicherplatz') ||
                                      text.includes('Espace nécessaire') ||
                                      text.includes('Espacio necesario') ||
                                      text.includes('Spazio necessario') ||
                                      text.includes('Необходимое место')) {
                                span.textContent = t.spaceNeededToSync + ':';
                            }
                        }
                    });
                }
                
                // Update duplicates headers if they exist
                const duplicatesHeaders = document.querySelectorAll('.panel-content > div');
                duplicatesHeaders.forEach(header => {
                    const text = header.textContent;
                    if ((text.includes('Duplicates') || text.includes('Duplikate') || 
                         text.includes('Doublons') || text.includes('Duplicados') || 
                         text.includes('Duplicati') || text.includes('Дубликаты')) &&
                        text.includes('(') && text.includes(')')) {
                        // Extract count from header
                        const match = text.match(/\((\d+)\)/);
                        if (match) {
                            header.textContent = `${t.duplicates} (${match[1]}):`;
                        }
                    }
                });
            }
            
            // Initialize language when DOM is ready
            let currentLanguage = detectUserLanguage();
            
            function initializeLanguage() {
                const languageSelect = document.getElementById('languageSelect');
                if (languageSelect) {
                    languageSelect.value = currentLanguage;
                    languageSelect.addEventListener('change', function() {
                        currentLanguage = this.value;
                        localStorage.setItem('docuSync_language', currentLanguage);
                        applyTranslations(currentLanguage);
                    });
                }
                applyTranslations(currentLanguage);
            }
            
            // Role-based UI visibility
            function setupRoleBasedUI() {
                const userRole = localStorage.getItem('user_role') || 'readonly';
                const username = localStorage.getItem('username') || '';
                
                // Show username and role in header
                const header = document.querySelector('.header');
                if (header && username) {
                    const userInfo = document.createElement('div');
                    userInfo.style.cssText = 'margin-top: 10px; font-size: 14px; color: #666;';
                    userInfo.textContent = `Logged in as: ${username} (${userRole})`;
                    header.appendChild(userInfo);
                }
                
                // Hide/show UI elements based on role
                const executeBtn = document.getElementById('executeBtn');
                if (executeBtn) {
                    if (userRole === 'readonly') {
                        executeBtn.style.display = 'none';
                    } else {
                        executeBtn.style.display = 'inline-block';
                    }
                }
                
                // Hide eliminate duplicates buttons for readonly users
                const eliminateContainer = document.getElementById('eliminateButtonsContainer');
                if (eliminateContainer && userRole === 'readonly') {
                    eliminateContainer.style.display = 'none';
                }
                
                // Add user management UI for admin
                if (userRole === 'admin') {
                    const controls = document.querySelector('.controls');
                    if (controls) {
                        const userMgmtBtn = document.createElement('button');
                        userMgmtBtn.id = 'userMgmtBtn';
                        userMgmtBtn.textContent = 'User Management';
                        userMgmtBtn.style.cssText = 'padding: 10px 20px; background: #6c757d; color: white; border: none; border-radius: 4px; cursor: pointer; margin-left: 10px;';
                        userMgmtBtn.onclick = showUserManagement;
                        controls.appendChild(userMgmtBtn);
                    }
                }
            }
            
            // User management UI (admin only)
            function showUserManagement() {
                const token = localStorage.getItem('access_token');
                if (!token) {
                    alert('Not authenticated');
                    window.location.href = '/login';
                    return;
                }
                
                // Create modal
                const modal = document.createElement('div');
                modal.style.cssText = 'position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; display: flex; justify-content: center; align-items: center;';
                modal.innerHTML = `
                    <div style="background: white; padding: 20px; border-radius: 8px; max-width: 600px; width: 90%; max-height: 80vh; overflow-y: auto;">
                        <h2>User Management</h2>
                        <div id="userList"></div>
                        <hr style="margin: 20px 0;">
                        <h3>Add New User</h3>
                        <form id="addUserForm" style="display: flex; flex-direction: column; gap: 10px;">
                            <input type="text" id="newUsername" placeholder="Username" required>
                            <input type="password" id="newPassword" placeholder="Password" required>
                            <select id="newRole" required>
                                <option value="readonly">Read Only</option>
                                <option value="full">Full Access</option>
                                <option value="admin">Admin</option>
                            </select>
                            <button type="submit">Add User</button>
                        </form>
                        <button onclick="this.closest('div[style*=\\"position: fixed\\"]').remove()" style="margin-top: 10px;">Close</button>
                    </div>
                `;
                document.body.appendChild(modal);
                
                // Load users
                loadUsers();
                
                // Handle form submission
                document.getElementById('addUserForm').addEventListener('submit', async (e) => {
                    e.preventDefault();
                    const username = document.getElementById('newUsername').value;
                    const password = document.getElementById('newPassword').value;
                    const role = document.getElementById('newRole').value;
                    
                    try {
                        const response = await fetch('/api/users', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'Authorization': 'Bearer ' + token
                            },
                            body: JSON.stringify({ username, password, role })
                        });
                        
                        if (response.ok) {
                            loadUsers();
                            document.getElementById('addUserForm').reset();
                            alert('User created successfully');
                        } else {
                            const data = await response.json();
                            alert('Error: ' + (data.detail || 'Failed to create user'));
                        }
                    } catch (error) {
                        alert('Error: ' + error.message);
                    }
                });
            }
            
            async function loadUsers() {
                const token = localStorage.getItem('access_token');
                if (!token) return;
                
                try {
                    const response = await fetch('/api/users', {
                        headers: {
                            'Authorization': 'Bearer ' + token
                        }
                    });
                    
                    if (response.ok) {
                        const users = await response.json();
                        const userList = document.getElementById('userList');
                        const currentUsername = localStorage.getItem('username') || '';
                        userList.innerHTML = '<h3>Users</h3><table style="width: 100%; border-collapse: collapse;"><tr><th>Username</th><th>Role</th><th>Active</th><th>Actions</th></tr>' +
                            users.map(user => `
                                <tr>
                                    <td>${user.username}</td>
                                    <td>${user.role}</td>
                                    <td>${user.is_active ? 'Yes' : 'No'}</td>
                                    <td>
                                        ${user.username !== currentUsername ? 
                                            `<button onclick="deleteUser(${user.id})" style="padding: 5px 10px; background: #dc3545; color: white; border: none; border-radius: 4px; cursor: pointer;">Delete</button>` : 
                                            '<span style="color: #999;">Current user</span>'}
                                    </td>
                                </tr>
                            `).join('') + '</table>';
                    }
                } catch (error) {
                    console.error('Error loading users:', error);
                }
            }
            
            async function deleteUser(userId) {
                if (!confirm('Are you sure you want to delete this user?')) return;
                
                const token = localStorage.getItem('access_token');
                if (!token) return;
                
                try {
                    const response = await fetch(`/api/users/${userId}`, {
                        method: 'DELETE',
                        headers: {
                            'Authorization': 'Bearer ' + token
                        }
                    });
                    
                    if (response.ok) {
                        loadUsers();
                        alert('User deleted successfully');
                    } else {
                        const data = await response.json();
                        alert('Error: ' + (data.detail || 'Failed to delete user'));
                    }
                } catch (error) {
                    alert('Error: ' + error.message);
                }
            }
            
            // Setup button event handlers (must be called after functions are defined)
            function setupButtonHandlers() {
                const analyzeBtn = document.getElementById('analyzeBtn');
                if (analyzeBtn) {
                    analyzeBtn.addEventListener('click', function() {
                        if (window.analyzeSync) {
                            window.analyzeSync();
                        } else {
                            console.error('analyzeSync function not defined');
                            alert('Error: analyzeSync function not loaded. Please refresh the page.');
                        }
                    });
                }
                
                const executeBtn = document.getElementById('executeBtn');
                if (executeBtn) {
                    executeBtn.addEventListener('click', function() {
                        if (window.executeSync) {
                            window.executeSync();
                        } else {
                            console.error('executeSync function not defined');
                            alert('Error: executeSync function not loaded. Please refresh the page.');
                        }
                    });
                }
            }
            
            // Apply translations on page load
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', function() {
                    initializeLanguage();
                    setupRoleBasedUI();
                });
            } else {
                // DOM is already ready
                initializeLanguage();
                setupRoleBasedUI();
            }
            
            let currentAnalysis = null;
            let token = localStorage.getItem('access_token');
            let currentFolderInput = null;
            
            if (!token) {
                window.location.href = '/login';
            }
            
            // Function to handle folder selection
            function handleFolderSelection(files, inputId) {
                if (!files || files.length === 0) {
                    return;
                }
                
                const input = document.getElementById(inputId);
                
                if (!input) {
                    return;
                }
                
                // Store original input value BEFORE any changes
                const originalInputValue = input.value || '';
                
                let folderPath = '';
                let detectedDrive = '';
                
                // Try to detect full path from file paths (if available)
                // Find the common root directory (the selected folder) from all files
                const backslash = String.fromCharCode(92);
                let allPaths = [];
                let commonRootPath = '';
                
                for (let i = 0; i < Math.min(files.length, 50); i++) {
                    const file = files[i];
                    if (file.path) {
                        // Extract drive letter from file path (e.g., "C:\\Users\\...")
                        const driveMatch = file.path.match(/^([A-Za-z]:)/i);
                        if (driveMatch) {
                            detectedDrive = driveMatch[1].toUpperCase();
                            // Extract directory path (the full folder path)
                            // This gives us the full path like "d:\\my\\local\\folder"
                            const dirPath = file.path.substring(0, 
                                Math.max(file.path.lastIndexOf(backslash), file.path.lastIndexOf('/')));
                            if (dirPath && dirPath.includes(backslash)) {
                                // Add the full directory path
                                allPaths.push(dirPath);
                            }
                        }
                    }
                }
                
                // Find the common root directory (the selected folder)
                // All files from the same selected folder will share the same directory prefix
                if (allPaths.length > 0) {
                    // Normalize all paths to lowercase for comparison
                    const normalizedPaths = allPaths.map(p => p.toLowerCase());
                    
                    // Find the longest common prefix
                    let commonPrefix = normalizedPaths[0];
                    for (let i = 1; i < normalizedPaths.length; i++) {
                        const currentPath = normalizedPaths[i];
                        let prefix = '';
                        const minLength = Math.min(commonPrefix.length, currentPath.length);
                        for (let j = 0; j < minLength; j++) {
                            if (commonPrefix[j] === currentPath[j]) {
                                prefix += commonPrefix[j];
                            } else {
                                break;
                            }
                        }
                        commonPrefix = prefix;
                    }
                    
                    // Get the original case from the first path
                    const firstPath = allPaths[0];
                    const commonPrefixLength = commonPrefix.length;
                    let originalCasePrefix = firstPath.substring(0, commonPrefixLength);
                    
                    // The common prefix should be the selected folder path
                    // Example: If files are in "d:\\my\\local\\folder" and "d:\\my\\local\\folder\\subfolder"
                    // Common prefix = "d:\\my\\local\\folder" (the selected folder)
                    // Use the common prefix as-is - it IS the full selected folder path
                    folderPath = originalCasePrefix;
                    
                    // Remove trailing slash if present
                    if (folderPath.endsWith(backslash) || folderPath.endsWith('/')) {
                        folderPath = folderPath.slice(0, -1);
                    }
                    
                    // Ensure we have a valid path (at least drive letter + folder)
                    if (!folderPath || folderPath.length < 3 || !folderPath.includes(backslash)) {
                        // Fallback: use the shortest path (likely the selected folder)
                        allPaths.sort((a, b) => a.length - b.length);
                        folderPath = allPaths[0];
                        // Remove trailing slash
                        if (folderPath.endsWith(backslash) || folderPath.endsWith('/')) {
                            folderPath = folderPath.slice(0, -1);
                        }
                    }
                }
                
                // If we found a path with drive letter, verify it's complete
                if (folderPath && detectedDrive) {
                    // Check if path looks complete (has drive letter and at least one folder)
                    const backslash = String.fromCharCode(92);
                    const hasFullPath = folderPath.includes(backslash) && folderPath.length > 3;
                    
                    if (hasFullPath) {
                        // Normalize and save - preserve FULL path structure
                        let normalizedPath = folderPath.trim();
                        
                        // Convert forward slashes to backslashes if needed
                        if (normalizedPath.includes('/') && !normalizedPath.includes(backslash)) {
                            normalizedPath = normalizedPath.replace(/\\//g, backslash);
                        }
                        
                        // Remove trailing slash
                        const trailingSlashRegex = new RegExp('[' + backslash + '/]+$');
                        normalizedPath = normalizedPath.replace(trailingSlashRegex, '');
                        
                        // Ensure drive letter is uppercase
                        const driveMatch = normalizedPath.match(/^([A-Za-z]:)/i);
                        if (driveMatch) {
                            normalizedPath = driveMatch[1].toUpperCase() + normalizedPath.substring(2);
                        }
                        
                        // Save FULL path - don't modify it further
                        input.value = normalizedPath;
                        showMessage('Folder path saved: ' + normalizedPath, 'success');
                        return;
                    } else {
                        // Path doesn't look complete - show prompt to get full path
                        const folderName = folderPath.split(backslash).pop() || folderPath;
                        const promptMessage = 'Please enter the full path to the selected folder:' + String.fromCharCode(10) + 
                                             'Folder name: ' + folderName + String.fromCharCode(10) + 
                                             'Example: ' + detectedDrive + backslash + 'my' + backslash + 'local' + backslash + folderName;
                        const userPath = prompt(promptMessage, folderPath);
                        
                        if (userPath && userPath.trim()) {
                            folderPath = userPath.trim();
                            // Continue to normalization below
                        } else {
                            showMessage('No path provided. Please enter the full folder path manually.', 'error');
                            return;
                        }
                    }
                }
                
                // If no full path available, construct path from available information
                const file = files[0];
                
                if (file.path) {
                    // Some browsers expose full path (older Chrome/Edge)
                    // Extract the full directory path (preserve entire structure)
                    const backslash = String.fromCharCode(92);
                    const dirPath = file.path.substring(0, 
                        Math.max(file.path.lastIndexOf(backslash), file.path.lastIndexOf('/')));
                    if (dirPath) {
                        // Use the full path from file.path (preserve entire structure)
                        const pathDriveMatch = dirPath.match(/^([A-Za-z]:)/i);
                        if (pathDriveMatch) {
                            // Full path with drive letter - use as-is
                            folderPath = dirPath;
                        } else if (detectedDrive) {
                            // Add drive letter if missing
                            folderPath = detectedDrive + backslash + dirPath;
                        } else {
                            // Use path as-is
                            folderPath = dirPath;
                        }
                    }
                } else if (file.webkitRelativePath) {
                    // webkitRelativePath is relative to the SELECTED folder
                    // Try to get full path from file.path first (most reliable)
                    const backslash = String.fromCharCode(92);
                    let fullPathFromFile = '';
                    let driveLetter = detectedDrive;
                    let bestPathDepth = 0;
                    
                    // Check ALL files for file.path to get the deepest full path
                    for (let i = 0; i < Math.min(files.length, 50); i++) {
                        const f = files[i];
                        if (f.path) {
                            const driveMatch = f.path.match(/^([A-Za-z]:)/i);
                            if (driveMatch) {
                                driveLetter = driveMatch[1].toUpperCase();
                                // Extract directory path (full folder path)
                                const dirPath = f.path.substring(0, 
                                    Math.max(f.path.lastIndexOf(backslash), f.path.lastIndexOf('/')));
                                if (dirPath && dirPath.includes(backslash)) {
                                    // Count path depth - use deepest path (preserves full structure)
                                    const pathDepth = (dirPath.match(new RegExp(backslash, 'g')) || []).length;
                                    if (pathDepth > bestPathDepth) {
                                        fullPathFromFile = dirPath;
                                        bestPathDepth = pathDepth;
                                    }
                                }
                            }
                        }
                    }
                    
                    // If we have a full path from file.path, use it (preserves full structure)
                    if (fullPathFromFile) {
                        folderPath = fullPathFromFile;
                    } else {
                        // Find the deepest folder structure from all files
                        // This gives us the full relative path structure within the selected folder
                        let maxDepth = 0;
                        let deepestRelativePath = '';
                        let selectedFolderName = '';
                        
                        for (let i = 0; i < Math.min(files.length, 50); i++) {
                            const f = files[i];
                            if (f.webkitRelativePath) {
                                const parts = f.webkitRelativePath.split('/');
                                if (parts.length > 0 && !selectedFolderName) {
                                    selectedFolderName = parts[0];
                                }
                                // Remove the filename (last part) to get the folder path
                                if (parts.length > 1) {
                                    const folderParts = parts.slice(0, -1);
                                    const folderPath = folderParts.join(backslash);
                                    if (folderParts.length > maxDepth) {
                                        maxDepth = folderParts.length;
                                        deepestRelativePath = folderPath;
                                    }
                                }
                            }
                        }
                        
                        // Construct full path: drive + folder structure
                        if (driveLetter) {
                            if (deepestRelativePath) {
                                // Use drive + relative path structure
                                folderPath = driveLetter + backslash + deepestRelativePath;
                            } else if (selectedFolderName) {
                                // Just drive + folder name
                                folderPath = driveLetter + backslash + selectedFolderName;
                            } else {
                                // Just drive
                                folderPath = driveLetter + backslash;
                            }
                        } else {
                            // No drive letter - use just the path structure
                            if (deepestRelativePath) {
                                folderPath = deepestRelativePath;
                            } else if (selectedFolderName) {
                                folderPath = selectedFolderName;
                            }
                        }
                    }
                } else {
                    // Fallback: Use detected drive or folder name only
                    if (detectedDrive) {
                        const backslash = String.fromCharCode(92);
                        folderPath = detectedDrive + backslash;
                    } else {
                        folderPath = '';
                    }
                }
                
                // Normalize and save the path
                if (folderPath) {
                    // Normalize path: replace forward slashes with backslashes for Windows
                    // But keep the format as user entered if it's valid
                    let normalizedPath = folderPath.trim();
                    
                    // Extract drive letter from entered path FIRST, before any processing
                    const pathDriveMatch = normalizedPath.match(/^([A-Za-z]:)/i);
                    const pathDriveLetter = pathDriveMatch ? pathDriveMatch[1].toUpperCase() : '';
                    
                    // If path doesn't have a drive letter, show prompt dialog to get full path
                    if (!pathDriveLetter && normalizedPath.length > 0) {
                        const backslash = String.fromCharCode(92);
                        const folderName = normalizedPath.split(backslash).pop() || normalizedPath.split('/').pop() || normalizedPath;
                        let suggestedDrive = detectedDrive || 'D';
                        let suggestedPath = suggestedDrive + backslash + normalizedPath.replace(/\\//g, backslash);
                        
                        const promptMessage = 'Please enter the full path including drive letter:' + String.fromCharCode(10) + 
                                             'Folder name: ' + folderName + String.fromCharCode(10) + 
                                             'Example: ' + suggestedPath;
                        const userPath = prompt(promptMessage, suggestedPath);
                        
                        if (userPath && userPath.trim()) {
                            normalizedPath = userPath.trim();
                            // Re-extract drive letter after user input
                            const newDriveMatch = normalizedPath.match(/^([A-Za-z]:)/i);
                            if (!newDriveMatch) {
                                showMessage('Warning: Path should include drive letter (e.g., D:\\\\folder). Please enter manually.', 'error');
                                return;
                            }
                        } else {
                            showMessage('No path provided. Please enter the full folder path manually.', 'error');
                            return;
                        }
                    }
                    
                    // If path uses forward slashes, convert to backslashes for Windows
                    // But preserve drive letter if present
                    if (normalizedPath.includes('/')) {
                        const backslash = String.fromCharCode(92);
                        // Convert forward slashes to backslashes
                        normalizedPath = normalizedPath.replace(/\\//g, backslash);
                    }
                    
                    // Remove trailing slash/backslash (but preserve drive letter)
                    const backslash = String.fromCharCode(92);
                    // Don't remove trailing slash if it's just after drive letter (e.g., D:\\)
                    if (!normalizedPath.match(/^[A-Za-z]:$/i)) {
                        const trailingSlashRegex = new RegExp('[' + backslash + '/]+$');
                        normalizedPath = normalizedPath.replace(trailingSlashRegex, '');
                    }
                    
                    // CRITICAL: Preserve the FULL path structure - don't extract only last folder
                    // Just ensure drive letter is present and uppercase
                    let driveLetter = pathDriveLetter;
                    if (!driveLetter && detectedDrive) {
                        driveLetter = detectedDrive;
                    }
                    
                    // Ensure drive letter is present and uppercase (if we have one)
                    if (driveLetter && !normalizedPath.match(/^[A-Za-z]:/i)) {
                        // Add drive letter if missing
                        normalizedPath = driveLetter + backslash + normalizedPath;
                    } else if (driveLetter && normalizedPath.match(/^[A-Za-z]:/i)) {
                        // Ensure drive letter is uppercase
                        const currentDrive = normalizedPath.match(/^([A-Za-z]:)/i)[1].toUpperCase();
                        normalizedPath = currentDrive + normalizedPath.substring(2);
                    }
                    
                    // Remove trailing slash
                    if (normalizedPath.length > 2 && (normalizedPath.endsWith(backslash) || normalizedPath.endsWith('/'))) {
                        normalizedPath = normalizedPath.slice(0, -1);
                    }
                    
                    // Validate final path has drive letter
                    if (!normalizedPath.match(/^[A-Za-z]:/i) && normalizedPath.length > 0) {
                        showMessage('Warning: Path does not include drive letter. Please enter full path manually.', 'error');
                    }
                    
                    // Save to input
                    input.value = normalizedPath;
                    showMessage('Folder path saved: ' + normalizedPath, 'success');
                }
            }
            
            // Make browseFolder globally accessible
            async function browseFolder(inputId) {
                // Try File System Access API first (if supported)
                if ('showDirectoryPicker' in window) {
                    try {
                        const dirHandle = await window.showDirectoryPicker({
                            mode: 'read'
                        });
                        
                        const input = document.getElementById(inputId);
                        if (!input) {
                            return;
                        }
                        
                        // Try to get full path by reading files from the directory
                        // Some browsers expose file.path even with File System Access API
                        let folderPath = '';
                        let detectedDrive = '';
                        const backslash = String.fromCharCode(92);
                        let allPaths = [];
                        
                        // Read files from directory to extract paths
                        try {
                            const files = [];
                            async function readDirectory(handle, depth = 0) {
                                if (depth > 3 || files.length > 100) return; // Limit depth and file count
                                for await (const entry of handle.values()) {
                                    if (entry.kind === 'file') {
                                        try {
                                            const file = await entry.getFile();
                                            files.push(file);
                                            if (files.length >= 20) break; // Get enough files for path detection
                                        } catch (e) {
                                            // Skip files we can't read
                                        }
                                    } else if (entry.kind === 'directory' && depth < 2) {
                                        await readDirectory(entry, depth + 1);
                                    }
                                    if (files.length >= 20) break;
                                }
                            }
                            await readDirectory(dirHandle);
                            
                            // Extract paths from files
                            for (let i = 0; i < files.length; i++) {
                                const file = files[i];
                                if (file.path) {
                                    const driveMatch = file.path.match(/^([A-Za-z]:)/i);
                                    if (driveMatch) {
                                        detectedDrive = driveMatch[1].toUpperCase();
                                        const dirPath = file.path.substring(0, 
                                            Math.max(file.path.lastIndexOf(backslash), file.path.lastIndexOf('/')));
                                        if (dirPath && dirPath.includes(backslash)) {
                                            allPaths.push(dirPath);
                                        }
                                    }
                                }
                            }
                            
                            // Find common root directory (the selected folder)
                            if (allPaths.length > 0) {
                                const normalizedPaths = allPaths.map(p => p.toLowerCase());
                                let commonPrefix = normalizedPaths[0];
                                for (let i = 1; i < normalizedPaths.length; i++) {
                                    const currentPath = normalizedPaths[i];
                                    let prefix = '';
                                    const minLength = Math.min(commonPrefix.length, currentPath.length);
                                    for (let j = 0; j < minLength; j++) {
                                        if (commonPrefix[j] === currentPath[j]) {
                                            prefix += commonPrefix[j];
                                        } else {
                                            break;
                                        }
                                    }
                                    commonPrefix = prefix;
                                }
                                
                                const firstPath = allPaths[0];
                                const commonPrefixLength = commonPrefix.length;
                                let originalCasePrefix = firstPath.substring(0, commonPrefixLength);
                                
                                if (originalCasePrefix.endsWith(backslash) || originalCasePrefix.endsWith('/')) {
                                    originalCasePrefix = originalCasePrefix.slice(0, -1);
                                }
                                
                                if (originalCasePrefix && originalCasePrefix.length >= 3 && originalCasePrefix.includes(backslash)) {
                                    folderPath = originalCasePrefix;
                                }
                            }
                        } catch (e) {
                            console.log('Could not read directory files for path extraction:', e);
                        }
                        
                        // If we couldn't get full path from files, show prompt dialog
                        if (!folderPath || !folderPath.includes(backslash)) {
                            const folderName = dirHandle.name || 'Selected Folder';
                            const currentValue = input.value || '';
                            
                            // Try to suggest a path from current value
                            let suggestedPath = '';
                            if (currentValue) {
                                const driveMatch = currentValue.match(/^([A-Za-z]:)/i);
                                if (driveMatch) {
                                    const drive = driveMatch[1].toUpperCase();
                                    suggestedPath = drive + backslash + folderName;
                                } else {
                                    suggestedPath = folderName;
                                }
                            } else {
                                suggestedPath = folderName;
                            }
                            
                            // Show prompt dialog to enter full path
                            const promptMessage = 'Please enter the full path to the selected folder:' + String.fromCharCode(10) + 
                                                 'Folder name: ' + folderName + String.fromCharCode(10) + 
                                                 'Example: D:\\\\my\\\\local\\\\folder';
                            const userPath = prompt(promptMessage, suggestedPath);
                            
                            if (userPath && userPath.trim()) {
                                folderPath = userPath.trim();
                            } else if (suggestedPath) {
                                folderPath = suggestedPath;
                            } else {
                                showMessage('No path provided. Please enter the full folder path manually.', 'error');
                                return;
                            }
                        }
                        
                        // Normalize and save the path
                        if (folderPath) {
                            let normalizedPath = folderPath.trim();
                            
                            // Extract drive letter from path
                            const pathDriveMatch = normalizedPath.match(/^([A-Za-z]:)/i);
                            const pathDriveLetter = pathDriveMatch ? pathDriveMatch[1].toUpperCase() : '';
                            
                            // If path uses forward slashes, convert to backslashes for Windows
                            if (normalizedPath.includes('/') && !normalizedPath.includes(backslash)) {
                                const forwardSlash = String.fromCharCode(47);
                                normalizedPath = normalizedPath.replace(new RegExp(forwardSlash, 'g'), backslash);
                            }
                            
                            // Remove trailing slash/backslash (but preserve drive letter)
                            if (!normalizedPath.match(/^[A-Za-z]:$/i)) {
                                const trailingSlashRegex = new RegExp('[' + backslash + '/]+$');
                                normalizedPath = normalizedPath.replace(trailingSlashRegex, '');
                            }
                            
                            // Ensure drive letter is uppercase
                            if (normalizedPath.match(/^[A-Za-z]:/i)) {
                                const driveMatch = normalizedPath.match(/^([A-Za-z]:)/i);
                                normalizedPath = driveMatch[1].toUpperCase() + normalizedPath.substring(2);
                            }
                            
                            // Validate that we have a proper Windows path
                            if (!normalizedPath.match(/^[A-Za-z]:/i) && normalizedPath.length > 0) {
                                showMessage('Warning: Path does not include drive letter. Please enter full path like D:\\\\folder', 'error');
                            }
                            
                            // Save to input
                            input.value = normalizedPath;
                            showMessage('Folder path saved: ' + normalizedPath, 'success');
                        }
                        return;
                    } catch (err) {
                        if (err.name === 'AbortError') {
                            // User cancelled, do nothing
                            return;
                        }
                        console.error('Error with File System API:', err);
                        // Fall through to file input fallback
                    }
                }
                
                // Fallback: Create file input dynamically for Yandex browser and others
                try {
                    // Remove any existing folder picker
                    const existingPicker = document.getElementById('folderPicker');
                    if (existingPicker) {
                        existingPicker.remove();
                    }
                    
                    // Create new file input element
                    const folderPicker = document.createElement('input');
                    folderPicker.type = 'file';
                    folderPicker.id = 'folderPicker';
                    folderPicker.setAttribute('webkitdirectory', '');
                    folderPicker.setAttribute('directory', '');
                    folderPicker.setAttribute('multiple', '');
                    folderPicker.style.position = 'fixed';
                    folderPicker.style.left = '-9999px';
                    folderPicker.style.top = '-9999px';
                    folderPicker.style.opacity = '0';
                    folderPicker.style.width = '1px';
                    folderPicker.style.height = '1px';
                    
                    // Add change handler
                    folderPicker.addEventListener('change', function(e) {
                        if (e.target.files && e.target.files.length > 0) {
                            handleFolderSelection(e.target.files, inputId);
                        }
                        // Clean up
                        setTimeout(() => {
                            if (folderPicker.parentNode) {
                                folderPicker.parentNode.removeChild(folderPicker);
                            }
                        }, 100);
                    });
                    
                    // Add to DOM
                    document.body.appendChild(folderPicker);
                    
                    // Trigger click - must be in user interaction context
                    // Use setTimeout to ensure DOM is ready
                    setTimeout(() => {
                        try {
                            // Try multiple methods to trigger
                            if (folderPicker.click) {
                                folderPicker.click();
                            } else if (folderPicker.dispatchEvent) {
                                const clickEvent = new MouseEvent('click', {
                                    bubbles: true,
                                    cancelable: true,
                                    view: window
                                });
                                folderPicker.dispatchEvent(clickEvent);
                            } else {
                                // Last resort: create event manually
                                const event = document.createEvent('MouseEvents');
                                event.initEvent('click', true, true);
                                folderPicker.dispatchEvent(event);
                            }
                        } catch (err) {
                            console.error('Error triggering folder picker:', err);
                            showMessage('Cannot open folder picker. Please enter path manually.', 'error');
                            if (folderPicker.parentNode) {
                                folderPicker.parentNode.removeChild(folderPicker);
                            }
                        }
                    }, 10);
                } catch (err) {
                    console.error('Error creating folder picker:', err);
                    showMessage('Cannot open folder picker. Please enter path manually.', 'error');
                }
            }
            
            // Also assign to window for explicit global access
            window.browseFolder = browseFolder;
            
            function showProgress() {
                const progressContainer = document.getElementById('progressContainer');
                const progressBar = document.getElementById('progressBar');
                const progressFileList = document.getElementById('progressFileList');
                if (progressContainer && progressBar) {
                    progressContainer.classList.add('show');
                    const progressText = document.getElementById('progressText');
                    if (progressText) {
                        progressText.textContent = 'Scanning folders and analyzing… — Scanned: 0  Equals: 0  Needs sync: 0';
                    }
                    if (progressFileList) {
                        progressFileList.style.display = 'block';
                        progressFileList.innerHTML = '';
                    }
                    // Animate progress bar (simulated progress)
                    let progress = 0;
                    const interval = setInterval(() => {
                        progress += Math.random() * 15;
                        if (progress > 90) {
                            progress = 90; // Don't go to 100% until done
                        }
                        progressBar.style.width = progress + '%';
                    }, 500);
                    
                    // Store interval ID to clear it later
                    progressContainer.dataset.intervalId = interval;
                }
            }
            
            function updateProgressFile(fileName, progress, total, percentage) {
                const progressFileList = document.getElementById('progressFileList');
                const progressText = document.getElementById('progressText');
                if (progressFileList) {
                    // Add file to list
                    const fileItem = document.createElement('div');
                    fileItem.className = 'progress-file-item';
                    fileItem.textContent = `Comparing: ${fileName} (${progress}/${total} - ${percentage}%)`;
                    progressFileList.insertBefore(fileItem, progressFileList.firstChild);
                    
                    // Keep only last 10 items
                    while (progressFileList.children.length > 10) {
                        progressFileList.removeChild(progressFileList.lastChild);
                    }
                }
                if (progressText) {
                    progressText.textContent = `Comparing files: ${progress} of ${total} (${percentage}%)`;
                }
            }
            
            function hideProgress() {
                const progressContainer = document.getElementById('progressContainer');
                const progressBar = document.getElementById('progressBar');
                if (progressContainer && progressBar) {
                    // Clear animation interval
                    if (progressContainer.dataset.intervalId) {
                        clearInterval(parseInt(progressContainer.dataset.intervalId));
                        delete progressContainer.dataset.intervalId;
                    }
                    // Complete the progress bar
                    progressBar.style.width = '100%';
                    // Hide after a short delay
                    setTimeout(() => {
                        progressContainer.classList.remove('show');
                        progressBar.style.width = '0%';
                    }, 300);
                }
            }
            
            // Make analyzeSync globally accessible
            window.analyzeSync = async function analyzeSync() {
                // Get fresh token from localStorage
                const currentToken = localStorage.getItem('access_token');
                
                if (!currentToken) {
                    showMessage('Not authenticated. Please login again.', 'error');
                    window.location.href = '/login';
                    return;
                }
                
                const folder1 = document.getElementById('folder1').value;
                const folder2 = document.getElementById('folder2').value;
                
                if (!folder1 || !folder2) {
                    showMessage(formatMessage('pleaseEnterBothFolders'), 'error');
                    return;
                }
                
                showMessage(formatMessage('analyzing'), 'info');
                document.getElementById('executeBtn').disabled = true;
                
                // Set up progress bar to show after 5 seconds
                let progressTimeout = null;
                const startTime = Date.now();
                
                try {
                    // Start timer to show progress bar after 5 seconds
                    progressTimeout = setTimeout(() => {
                        const elapsed = Date.now() - startTime;
                        if (elapsed >= 5000) {
                            showProgress();
                        }
                    }, 5000);
                    
                    // Assign a job id and start polling progress
                    const jobId = 'job-' + Date.now() + '-' + Math.floor(Math.random()*100000);
                    console.log('[DEBUG] analyzeSync: Starting with jobId:', jobId);
                    
                    const progressContainer = document.getElementById('progressContainer');
                    
                    // Ensure progress UI is visible immediately
                    showProgress();

                    // Declare pollId variable for cleanup
                    let pollId = null;

                    // Start polling every ~2 seconds
                    const pollFn = async () => {
                        try {
                            // Get fresh token on each poll in case it expires
                            const freshToken = localStorage.getItem('access_token');
                            if (!freshToken) {
                                console.error('[DEBUG] No access token found, stopping polling');
                                if (pollId) clearInterval(pollId);
                                return;
                            }
                            const url = '/api/sync/progress?job_id=' + encodeURIComponent(jobId);
                            console.log('[DEBUG] Polling progress for jobId:', jobId, 'URL:', url);
                            const r = await fetch(url, {
                                headers: { 'Authorization': 'Bearer ' + freshToken }
                            });
                            if (!r.ok) {
                                console.error('[DEBUG] Poll response not OK:', r.status, r.statusText);
                                if (r.status === 401) {
                                    console.error('[DEBUG] Authentication failed, stopping polling');
                                    if (pollId) clearInterval(pollId);
                                    showMessage(formatMessage('sessionExpired'), 'error');
                                }
                                return;
                            }
                            const p = await r.json();
                            console.log('[DEBUG] Progress poll response:', p, 'jobId:', jobId);
                            // Ensure values are numbers
                            const scanned = Number(p.scanned) || 0;
                            const equals = Number(p.equals) || 0;
                            const needsSync = Number(p.needs_sync) || 0;
                            console.log('[DEBUG] Parsed values:', {scanned, equals, needsSync});
                            const dots = '.'.repeat(Math.floor((Date.now()/1000)%4));
                            const line = 'Scanning folders and analyzing' + dots + '  —  Scanned: ' + scanned + '  Equals: ' + equals + '  Needs sync: ' + needsSync;
                            const progressTextEl = document.getElementById('progressText');
                            if (progressTextEl) {
                                progressTextEl.textContent = line;
                                console.log('[DEBUG] Updated progressText with:', line);
                            } else {
                                console.error('[DEBUG] progressTextEl not found!');
                            }
                            
                        } catch (e) {
                            console.error('[DEBUG] Progress poll error:', e, e.stack);
                        }
                    };
                    
                    // Start polling BEFORE sending the request, so it starts immediately
                    console.log('[DEBUG] Starting polling with jobId:', jobId);
                    // Wait a tiny bit to ensure backend has initialized PROGRESS_STORE
                    await new Promise(resolve => setTimeout(resolve, 200));
                    // Run once immediately so totals appear without waiting
                    await pollFn();
                    pollId = setInterval(pollFn, 2000);
                    console.log('[DEBUG] Polling started with interval ID:', pollId);
                    // Save to container for later cleanup
                    if (progressContainer) progressContainer.dataset.progressPollId = String(pollId);
                    
                    // Send the request (don't await yet - let it run in background)
                    console.log('[DEBUG] Sending analyze request with jobId:', jobId);
                    const response = await fetch('/api/sync/analyze', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': 'Bearer ' + currentToken
                        },
                        body: JSON.stringify({
                            folder1: (folder1.length > 1 || folder1.includes('/') || folder1.includes(String.fromCharCode(92))) ? folder1 : null,
                            folder2: (folder2.length > 1 || folder2.includes('/') || folder2.includes(String.fromCharCode(92))) ? folder2 : null,
                            drive1: (folder1.length === 1 && !folder1.includes('/') && !folder1.includes(String.fromCharCode(92))) ? folder1 : null,
                            drive2: (folder2.length === 1 && !folder2.includes('/') && !folder2.includes(String.fromCharCode(92))) ? folder2 : null,
                            job_id: jobId
                        })
                    });
                    console.log('[DEBUG] Analyze request completed, status:', response.status);
                    
                    // Clear timeout if response came quickly
                    if (progressTimeout) {
                        clearTimeout(progressTimeout);
                    }
                    
                    // Check if we should show progress bar based on elapsed time
                    const elapsed = Date.now() - startTime;
                    if (elapsed >= 5000) {
                        showProgress();
                    }
                    
                    const data = await response.json();
                    
                    // Display progress updates if available
                    if (data.progress_updates && Array.isArray(data.progress_updates)) {
                        data.progress_updates.forEach(update => {
                            if (update.file && update.progress && update.total) {
                                updateProgressFile(update.file, update.progress, update.total, update.percentage || 0);
                            }
                        });
                    }
                    
                    // Stop polling
                    try {
                        const progressContainer2 = document.getElementById('progressContainer');
                        if (progressContainer2 && progressContainer2.dataset.progressPollId) {
                            clearInterval(parseInt(progressContainer2.dataset.progressPollId));
                            delete progressContainer2.dataset.progressPollId;
                        }
                    } catch (e) {}
                    
                    // Hide progress bar after response
                    hideProgress();
                    
                    if (response.ok) {
                        // Debug: Log the response data
                        console.log('Analysis response:', data);
                        console.log('Analysis data:', data.analysis);
                        
                        currentAnalysis = data;
                        displayAnalysis(data);
                        document.getElementById('executeBtn').disabled = false;
                        
                        // Show summary message
                        if (data.analysis) {
                            // Normalize folder paths with uppercase drive letters
                            function normalizeFolderPath(path) {
                                if (!path || typeof path !== 'string') {
                                    return path;
                                }
                                const driveMatch = path.match(/^([A-Za-z]:)/i);
                                if (driveMatch) {
                                    return driveMatch[1].toUpperCase() + path.substring(2);
                                }
                                return path;
                            }
                            const folder1Path = normalizeFolderPath(data.analysis.folder1) || 'Folder 1';
                            const folder2Path = normalizeFolderPath(data.analysis.folder2) || 'Folder 2';
                            const total1 = data.analysis.missing_count_folder2 || 0;
                            const total2 = data.analysis.missing_count_folder1 || 0;
                            const dupCount = data.analysis.duplicate_count || 0;
                            showMessage(formatMessage('analysisComplete', total1, folder1Path, total2, folder2Path, dupCount), 'success');
                        } else {
                            showMessage(formatMessage('analysisCompleteSimple'), 'success');
                        }
                    } else {
                        if (response.status === 401) {
                            showMessage(formatMessage('sessionExpired'), 'error');
                            localStorage.removeItem('access_token');
                            setTimeout(() => {
                                window.location.href = '/login';
                            }, 2000);
                        } else {
                            showMessage(formatMessage('analysisFailed', data.detail || 'Unknown error'), 'error');
                        }
                    }
                } catch (error) {
                    // Hide progress bar on error
                    if (progressTimeout) {
                        clearTimeout(progressTimeout);
                    }
                    hideProgress();
                    showMessage(formatMessage('error', error.message), 'error');
                } finally {
                    document.getElementById('executeBtn').disabled = false;
                }
            }
            
            // Function to normalize folder path with uppercase drive letter
            function normalizeFolderPath(path) {
                if (!path || typeof path !== 'string') {
                    return path;
                }
                // Match drive letter at the start (e.g., "d:\books" or "D:\books")
                const driveMatch = path.match(/^([A-Za-z]:)/i);
                if (driveMatch) {
                    // Replace with uppercase drive letter
                    return driveMatch[1].toUpperCase() + path.substring(2);
                }
                return path;
            }
            
            function displayAnalysis(analysis) {
                const container = document.getElementById('syncContainer');
                container.style.display = 'grid';
                
                if (analysis.type === 'folder') {
                    const a = analysis.analysis;
                    
                    // Get actual folder paths and normalize drive letters to uppercase
                    const folder1Path = normalizeFolderPath(a.folder1) || 'Folder 1';
                    const folder2Path = normalizeFolderPath(a.folder2) || 'Folder 2';
                    
                    // Calculate duplicates per folder and space to free up
                    let folder1Duplicates = 0;
                    let folder1SpaceToFree = 0;
                    let folder2Duplicates = 0;
                    let folder2SpaceToFree = 0;
                    
                    if (a.duplicates && a.duplicates.length > 0) {
                        for (const dup of a.duplicates) {
                            // Collect all files from both folders
                            const allFiles = [];
                            
                            // Add files from folder1
                            if (dup.folder1_docs && dup.folder1_docs.length > 0) {
                                for (const doc of dup.folder1_docs) {
                                    allFiles.push({
                                        file_path: doc.file_path,
                                        size: doc.size || 0,
                                        date_modified: doc.date_modified,
                                        date_created: doc.date_created,
                                        folder: 1
                                    });
                                }
                            }
                            
                            // Add files from folder2
                            if (dup.folder2_docs && dup.folder2_docs.length > 0) {
                                for (const doc of dup.folder2_docs) {
                                    allFiles.push({
                                        file_path: doc.file_path,
                                        size: doc.size || 0,
                                        date_modified: doc.date_modified,
                                        date_created: doc.date_created,
                                        folder: 2
                                    });
                                }
                            }
                            
                            if (allFiles.length < 2) continue;
                            
                            // Find the latest file
                            let latestFile = null;
                            let latestDate = null;
                            
                            for (const fileInfo of allFiles) {
                                let compareDate = null;
                                if (fileInfo.date_modified) {
                                    try {
                                        compareDate = new Date(fileInfo.date_modified);
                                    } catch (e) {}
                                }
                                if (!compareDate && fileInfo.date_created) {
                                    try {
                                        compareDate = new Date(fileInfo.date_created);
                                    } catch (e) {}
                                }
                                
                                if (compareDate && (!latestDate || compareDate > latestDate)) {
                                    latestDate = compareDate;
                                    latestFile = fileInfo;
                                }
                            }
                            
                            // If no date available, keep first file
                            if (!latestFile) {
                                latestFile = allFiles[0];
                            }
                            
                            // Calculate space to free per folder
                            for (const fileInfo of allFiles) {
                                if (fileInfo.file_path !== latestFile.file_path) {
                                    if (fileInfo.folder === 1) {
                                        folder1Duplicates++;
                                        folder1SpaceToFree += fileInfo.size;
                                    } else if (fileInfo.folder === 2) {
                                        folder2Duplicates++;
                                        folder2SpaceToFree += fileInfo.size;
                                    }
                                }
                            }
                        }
                    }
                    
                    // Create eliminate buttons
                    const eliminateContainer = document.getElementById('eliminateButtonsContainer');
                    eliminateContainer.innerHTML = '';
                    
                    // Extract drive letter from folder paths
                    const getDriveLetter = (path) => {
                        const match = path.match(/^([A-Za-z]):/);
                        return match ? match[1].toUpperCase() + ':' : '';
                    };
                    
                    const drive1 = getDriveLetter(folder1Path);
                    const drive2 = getDriveLetter(folder2Path);
                    
                    // Button for Folder 1
                    if (folder1Duplicates > 0) {
                        const btn1 = document.createElement('button');
                        const spaceKB = Math.round(folder1SpaceToFree / 1024);
                        btn1.textContent = `Eliminate ${folder1Duplicates} duplicate file${folder1Duplicates > 1 ? 's' : ''} in Folder1 and free up ${spaceKB.toLocaleString()} KB on disk ${drive1 ? drive1 + '\\\\' : ''}`;
                        btn1.style.marginLeft = '10px';
                        btn1.style.padding = '8px 16px';
                        btn1.style.backgroundColor = '#dc3545';
                        btn1.style.color = 'white';
                        btn1.style.border = 'none';
                        btn1.style.borderRadius = '4px';
                        btn1.style.cursor = 'pointer';
                        btn1.style.fontSize = '14px';
                        btn1.onclick = async () => {
                            const token = localStorage.getItem('access_token');
                            if (!token) {
                                showMessage(formatMessage('notAuthenticated'), 'error');
                                window.location.href = '/login';
                                return;
                            }
                            
                            if (confirm(formatMessage('confirmEliminateFolder', folder1Duplicates, 'Folder1', formatBytes(folder1SpaceToFree)))) {
                                btn1.disabled = true;
                                btn1.textContent = formatMessage('processing');
                                try {
                                    const response = await fetch('/api/sync/eliminate-duplicates-folder', {
                                        method: 'POST',
                                        headers: {
                                            'Content-Type': 'application/json',
                                            'Authorization': 'Bearer ' + token
                                        },
                                        body: JSON.stringify({
                                            duplicates: a.duplicates,
                                            target_folder: 1,
                                            folder1: folder1Path,
                                            folder2: folder2Path
                                        })
                                    });
                                    const result = await response.json();
                                    if (result.success) {
                                        // Check if there are any errors (files that couldn't be deleted)
                                        if (result.errors && result.errors.length > 0) {
                                            // Show popup with specific error reasons
                                            const errorMessages = result.errors.join('\\n');
                                            alert(`Some files could not be deleted:\\n\\n${errorMessages}`);
                                        }
                                        
                                        showMessage(formatMessage('successfullyEliminatedFolder', result.deleted_count, 'Folder1', formatBytes(result.space_freed)), 'success');
                                        setTimeout(() => {
                                            const analyzeBtn = document.getElementById('analyzeBtn');
                                            if (analyzeBtn) {
                                                analyzeBtn.click();
                                            } else {
                                                analyzeSync();
                                            }
                                        }, 1000);
                                    } else {
                                        // Show popup with error message
                                        const errorMsg = result.error || formatMessage('failedToEliminate');
                                        alert(formatMessage('error', errorMsg));
                                        showMessage(formatMessage('error', errorMsg), 'error');
                                        btn1.disabled = false;
                                        const spaceKB1 = Math.round(folder1SpaceToFree / 1024);
                                        btn1.textContent = `Eliminate ${folder1Duplicates} duplicate file${folder1Duplicates > 1 ? 's' : ''} in Folder1 and free up ${spaceKB1.toLocaleString()} KB on disk ${drive1 ? drive1 + '\\\\' : ''}`;
                                    }
                                } catch (error) {
                                    showMessage(formatMessage('error', error.message), 'error');
                                    btn1.disabled = false;
                                    btn1.textContent = `Eliminate ${folder1Duplicates} duplicate file${folder1Duplicates > 1 ? 's' : ''} in Folder1 and free up ${formatBytes(folder1SpaceToFree)} on disk ${drive1 ? drive1 + '\\\\' : ''}`;
                                }
                            }
                        };
                        eliminateContainer.appendChild(btn1);
                    }
                    
                    // Button for Folder 2
                    if (folder2Duplicates > 0) {
                        const btn2 = document.createElement('button');
                        const spaceKB = Math.round(folder2SpaceToFree / 1024);
                        btn2.textContent = `Eliminate ${folder2Duplicates} duplicate file${folder2Duplicates > 1 ? 's' : ''} in Folder2 and free up ${spaceKB.toLocaleString()} KB on disk ${drive2 ? drive2 + '\\\\' : ''}`;
                        btn2.style.marginLeft = '10px';
                        btn2.style.padding = '8px 16px';
                        btn2.style.backgroundColor = '#dc3545';
                        btn2.style.color = 'white';
                        btn2.style.border = 'none';
                        btn2.style.borderRadius = '4px';
                        btn2.style.cursor = 'pointer';
                        btn2.style.fontSize = '14px';
                        btn2.onclick = async () => {
                            const token = localStorage.getItem('access_token');
                            if (!token) {
                                showMessage(formatMessage('notAuthenticated'), 'error');
                                window.location.href = '/login';
                                return;
                            }
                            
                            if (confirm(formatMessage('confirmEliminateFolder', folder2Duplicates, 'Folder2', formatBytes(folder2SpaceToFree)))) {
                                btn2.disabled = true;
                                btn2.textContent = formatMessage('processing');
                                try {
                                    const response = await fetch('/api/sync/eliminate-duplicates-folder', {
                                        method: 'POST',
                                        headers: {
                                            'Content-Type': 'application/json',
                                            'Authorization': 'Bearer ' + token
                                        },
                                        body: JSON.stringify({
                                            duplicates: a.duplicates,
                                            target_folder: 2,
                                            folder1: folder1Path,
                                            folder2: folder2Path
                                        })
                                    });
                                    const result = await response.json();
                                    if (result.success) {
                                        // Check if there are any errors (files that couldn't be deleted)
                                        if (result.errors && result.errors.length > 0) {
                                            // Show popup with specific error reasons
                                            const errorMessages = result.errors.join('\\n');
                                            alert(`Some files could not be deleted:\\n\\n${errorMessages}`);
                                        }
                                        
                                        showMessage(formatMessage('successfullyEliminatedFolder', result.deleted_count, 'Folder2', formatBytes(result.space_freed)), 'success');
                                        setTimeout(() => {
                                            const analyzeBtn = document.getElementById('analyzeBtn');
                                            if (analyzeBtn) {
                                                analyzeBtn.click();
                                            } else {
                                                analyzeSync();
                                            }
                                        }, 1000);
                                    } else {
                                        // Show popup with error message
                                        const errorMsg = result.error || formatMessage('failedToEliminate');
                                        alert(formatMessage('error', errorMsg));
                                        showMessage(formatMessage('error', errorMsg), 'error');
                                        btn2.disabled = false;
                                        const spaceKB2 = Math.round(folder2SpaceToFree / 1024);
                                        btn2.textContent = `Eliminate ${folder2Duplicates} duplicate file${folder2Duplicates > 1 ? 's' : ''} in Folder2 and free up ${spaceKB2.toLocaleString()} KB on disk ${drive2 ? drive2 + '\\\\' : ''}`;
                                    }
                                } catch (error) {
                                    showMessage(formatMessage('error', error.message), 'error');
                                    btn2.disabled = false;
                                    btn2.textContent = `Eliminate ${folder2Duplicates} duplicate file${folder2Duplicates > 1 ? 's' : ''} in Folder2 and free up ${formatBytes(folder2SpaceToFree)} on disk ${drive2 ? drive2 + '\\\\' : ''}`;
                                }
                            }
                        };
                        eliminateContainer.appendChild(btn2);
                    }
                    
                    // Show container if there are duplicates
                    if (folder1Duplicates > 0 || folder2Duplicates > 0) {
                        eliminateContainer.style.display = 'inline-block';
                    } else {
                        eliminateContainer.style.display = 'none';
                    }
                    
                    // Update panel headers with actual folder paths
                    const panel1Header = document.querySelector('#syncContainer .panel:first-child .panel-header');
                    const panel2Header = document.querySelector('#syncContainer .panel:last-child .panel-header');
                    if (panel1Header) {
                        panel1Header.textContent = folder1Path;
                    }
                    if (panel2Header) {
                        panel2Header.textContent = folder2Path;
                    }
                    
                    // Display folder 1 files
                    const panel1 = document.getElementById('panel1');
                    panel1.innerHTML = '';
                    
                    const panel2 = document.getElementById('panel2');
                    panel2.innerHTML = '';
                    
                    let hasContent = false;
                    
                    if (a.missing_in_folder2 && a.missing_in_folder2.length > 0) {
                        hasContent = true;
                        const header = document.createElement('div');
                        header.style.fontWeight = 'bold';
                        header.style.marginBottom = '10px';
                        const totalCount = a.missing_count_folder2 || a.missing_in_folder2.length;
                        const displayedCount = a.missing_in_folder2.length;
                            if (displayedCount < totalCount) {
                            header.textContent = formatMessage('filesOnlyIn', folder1Path, displayedCount, totalCount);
                        } else {
                            header.textContent = formatMessage('filesOnlyInSimple', folder1Path, totalCount);
                        }
                        panel1.appendChild(header);
                        
                        a.missing_in_folder2.forEach(file => {
                            const item = createFileItem(file, 'folder1');
                            panel1.appendChild(item);
                        });
                        
                        // Show indicator if there are more files
                        if (displayedCount < totalCount) {
                            const moreIndicator = document.createElement('div');
                            moreIndicator.style.padding = '10px';
                            moreIndicator.style.textAlign = 'center';
                            moreIndicator.style.color = '#666';
                            moreIndicator.style.fontStyle = 'italic';
                            moreIndicator.style.borderTop = '1px solid #eee';
                            moreIndicator.textContent = formatMessage('andMoreFiles', totalCount - displayedCount);
                            panel1.appendChild(moreIndicator);
                        }
                    }
                    
                    // Add visual separator between sections
                    if (hasContent && a.duplicates && a.duplicates.length > 0) {
                        const separator = document.createElement('div');
                        separator.style.height = '2px';
                        separator.style.backgroundColor = '#ddd';
                        separator.style.margin = '20px 0';
                        separator.style.borderRadius = '1px';
                        panel1.appendChild(separator);
                    }
                    
                    if (a.duplicates && a.duplicates.length > 0) {
                        // Filter duplicates for panel1 (only those where folder1 has a file that would be deleted)
                        // A duplicate should appear in panel1 if folder1 has a file that's older than folder2's file
                        const duplicatesPanel1 = a.duplicates.filter(dup => {
                            if (!dup.folder1_docs || dup.folder1_docs.length === 0) return false;
                            if (!dup.folder2_docs || dup.folder2_docs.length === 0) return false;
                            
                            // Get the latest file from both folders
                            const allFiles = [];
                            if (dup.folder1_docs && dup.folder1_docs.length > 0) {
                                for (const doc of dup.folder1_docs) {
                                    allFiles.push({
                                        file_path: doc.file_path,
                                        date_modified: doc.date_modified,
                                        date_created: doc.date_created,
                                        folder: 1
                                    });
                                }
                            }
                            if (dup.folder2_docs && dup.folder2_docs.length > 0) {
                                for (const doc of dup.folder2_docs) {
                                    allFiles.push({
                                        file_path: doc.file_path,
                                        date_modified: doc.date_modified,
                                        date_created: doc.date_created,
                                        folder: 2
                                    });
                                }
                            }
                            
                            if (allFiles.length < 2) return false;
                            
                            // Find the latest file
                            let latestFile = null;
                            let latestDate = null;
                            for (const fileInfo of allFiles) {
                                let compareDate = null;
                                if (fileInfo.date_modified) {
                                    try {
                                        compareDate = new Date(fileInfo.date_modified);
                                    } catch (e) {}
                                }
                                if (!compareDate && fileInfo.date_created) {
                                    try {
                                        compareDate = new Date(fileInfo.date_created);
                                    } catch (e) {}
                                }
                                if (compareDate && (!latestDate || compareDate > latestDate)) {
                                    latestDate = compareDate;
                                    latestFile = fileInfo;
                                }
                            }
                            
                            if (!latestFile) latestFile = allFiles[0];
                            
                            // Show in panel1 if folder1 has a file that's NOT the latest (i.e., would be deleted)
                            return allFiles.some(f => f.folder === 1 && f.file_path !== latestFile.file_path);
                        });
                        
                        if (duplicatesPanel1.length > 0) {
                            hasContent = true;
                            const header = document.createElement('div');
                            header.style.fontWeight = 'bold';
                            header.style.marginTop = '20px';
                            header.style.marginBottom = '10px';
                            header.style.paddingTop = '10px';
                            header.style.borderTop = '2px solid #007bff';
                            const t = translations[currentLanguage] || translations.en;
                            header.textContent = `${t.duplicates} (${duplicatesPanel1.length}):`;
                            panel1.appendChild(header);
                            
                            // Add button to eliminate duplicates
                            const eliminateBtn = document.createElement('button');
                            eliminateBtn.textContent = formatMessage('eliminateDuplicates');
                            eliminateBtn.style.marginBottom = '15px';
                            eliminateBtn.style.padding = '8px 16px';
                            eliminateBtn.style.backgroundColor = '#dc3545';
                            eliminateBtn.style.color = 'white';
                            eliminateBtn.style.border = 'none';
                            eliminateBtn.style.borderRadius = '4px';
                            eliminateBtn.style.cursor = 'pointer';
                            eliminateBtn.style.fontSize = '14px';
                            eliminateBtn.onclick = async () => {
                                // Get current token and folder paths
                                const token = localStorage.getItem('access_token');
                                const f1Path = normalizeFolderPath(a.folder1) || 'Folder 1';
                                const f2Path = normalizeFolderPath(a.folder2) || 'Folder 2';
                                
                                if (!token) {
                                    showMessage(formatMessage('notAuthenticated'), 'error');
                                    window.location.href = '/login';
                                    return;
                                }
                                
                                if (confirm(formatMessage('confirmEliminate', duplicatesPanel1.length))) {
                                    eliminateBtn.disabled = true;
                                    eliminateBtn.textContent = formatMessage('processing');
                                    try {
                                        const response = await fetch('/api/sync/eliminate-duplicates', {
                                            method: 'POST',
                                            headers: {
                                                'Content-Type': 'application/json',
                                                'Authorization': 'Bearer ' + token
                                            },
                                            body: JSON.stringify({
                                                duplicates: duplicatesPanel1,
                                                folder1: f1Path,
                                                folder2: f2Path
                                            })
                                        });
                                        const result = await response.json();
                                        if (result.success) {
                                            // Check if there are any errors (files that couldn't be deleted)
                                            if (result.errors && result.errors.length > 0) {
                                                // Show popup with specific error reasons
                                                const errorMessages = result.errors.join('\\n');
                                                alert(formatMessage('someFilesCouldNotBeDeleted', errorMessages));
                                            }
                                            
                                            showMessage(formatMessage('successfullyEliminated', result.deleted_count, result.kept_count), 'success');
                                            // Clear panel1 immediately to show that refresh is happening
                                            const panel1 = document.getElementById('panel1');
                                            if (panel1) {
                                                panel1.innerHTML = `<div style="padding: 20px; text-align: center; color: #666;">${formatMessage('refreshingAnalysis')}</div>`;
                                            }
                                            // Also clear panel2 for consistency
                                            const panel2 = document.getElementById('panel2');
                                            if (panel2) {
                                                panel2.innerHTML = `<div style="padding: 20px; text-align: center; color: #666;">${formatMessage('refreshingAnalysis')}</div>`;
                                            }
                                            // Reload analysis to refresh display
                                            setTimeout(() => {
                                                const analyzeBtn = document.getElementById('analyzeBtn');
                                                if (analyzeBtn) {
                                                    analyzeBtn.click();
                                                } else {
                                                    analyzeSync();
                                                }
                                            }, 500);
                                        } else {
                                            // Show popup with error message
                                            const errorMsg = result.error || 'Failed to eliminate duplicates';
                                            alert(`Error: ${errorMsg}`);
                                            showMessage(`Error: ${errorMsg}`, 'error');
                                            eliminateBtn.disabled = false;
                                            eliminateBtn.textContent = formatMessage('eliminateDuplicates');
                                        }
                                    } catch (error) {
                                        showMessage(formatMessage('error', error.message), 'error');
                                        eliminateBtn.disabled = false;
                                        eliminateBtn.textContent = formatMessage('eliminateDuplicates');
                                    }
                                }
                            };
                        panel1.appendChild(eliminateBtn);
                        }
                        
                        // Show duplicates in panel1 (only those with folder1_docs)
                        if (duplicatesPanel1 && duplicatesPanel1.length > 0) {
                            duplicatesPanel1.forEach(dup => {
                                const item1 = document.createElement('div');
                                item1.className = 'file-item';
                                
                                // Get first doc from each folder (for duplicates, typically one per folder)
                                const doc1 = dup.folder1_docs && dup.folder1_docs.length > 0 ? dup.folder1_docs[0] : null;
                                const doc2 = dup.folder2_docs && dup.folder2_docs.length > 0 ? dup.folder2_docs[0] : null;
                                
                                // Get file sizes (individual file size, not sum)
                                const size1 = doc1 ? (doc1.size || 0) : 0;
                                const size2 = doc2 ? (doc2.size || 0) : 0;
                                
                                // Get MD5 hashes to show why files are different
                                const md5_1 = doc1 && doc1.md5_hash ? doc1.md5_hash.substring(0, 16) + '...' : 'N/A';
                                const md5_2 = doc2 && doc2.md5_hash ? doc2.md5_hash.substring(0, 16) + '...' : 'N/A';
                                
                                // Check if MD5 hashes are the same (exact match) or different (duplicate)
                                const md5Match = doc1 && doc2 && doc1.md5_hash === doc2.md5_hash;
                                const duplicateType = md5Match 
                                    ? 'Same name, same content (MD5 match) - different dates only'
                                    : 'Same name, different content (different MD5 hash)';
                                
                                // If there are multiple files with same name, show count
                                const count1 = dup.folder1_docs ? dup.folder1_docs.length : 0;
                                const count2 = dup.folder2_docs ? dup.folder2_docs.length : 0;
                                
                                const date1Created = doc1 && doc1.date_created
                                    ? new Date(doc1.date_created).toLocaleDateString()
                                    : 'N/A';
                                const date1Modified = doc1 && doc1.date_modified
                                    ? new Date(doc1.date_modified).toLocaleDateString()
                                    : 'N/A';
                                const date2Created = doc2 && doc2.date_created
                                    ? new Date(doc2.date_created).toLocaleDateString()
                                    : 'N/A';
                                const date2Modified = doc2 && doc2.date_modified
                                    ? new Date(doc2.date_modified).toLocaleDateString()
                                    : 'N/A';
                                
                                // Build size display - show count if multiple files
                                const size1Display = count1 > 1 
                                    ? `${formatBytes(size1)} (${count1} files)`
                                    : formatBytes(size1);
                                const size2Display = count2 > 1 
                                    ? `${formatBytes(size2)} (${count2} files)`
                                    : formatBytes(size2);
                                
                                item1.innerHTML = `
                                    <div class="file-name">${dup.relative_path}</div>
                                    <div class="file-meta">
                                        ${duplicateType}<br>
                                        <strong>Folder 1:</strong> ${size1Display} | MD5: ${md5_1} | Created: ${date1Created} | Modified: ${date1Modified}<br>
                                        <strong>Folder 2:</strong> ${size2Display} | MD5: ${md5_2} | Created: ${date2Created} | Modified: ${date2Modified}
                                    </div>
                                `;
                                
                                panel1.appendChild(item1);
                            });
                        }
                    }
                    
                    // Check if folders are identical (no differences)
                    const totalMissing1 = a.missing_count_folder2 || 0;
                    const totalMissing2 = a.missing_count_folder1 || 0;
                    const totalDuplicates = a.duplicate_count || 0;
                    const isIdentical = totalMissing1 === 0 && totalMissing2 === 0 && totalDuplicates === 0;
                    
                    // Supported file types
                    const supportedTypes = ['.pdf', '.docx', '.txt', '.epub', '.djvu', '.zip', '.doc', '.rar', '.fb2', '.html', '.rtf', '.gif', '.ppt', '.mp3'];
                    const typesList = supportedTypes.join(', ');
                    
                    if (isIdentical) {
                        // Both folders are identical
                        const message = document.createElement('div');
                        message.style.padding = '20px';
                        message.style.textAlign = 'center';
                        message.style.color = '#28a745';
                        message.style.fontWeight = '500';
                        message.textContent = formatMessage('foldersIdentical', folder1Path, folder2Path, typesList);
                        panel1.appendChild(message);
                    } else if (!hasContent) {
                        // Panel 1 has no content but folders are not identical
                        // Check if folder1 has fewer files than folder2
                        const count1 = a.missing_count_folder2 || 0;
                        const count2 = a.missing_count_folder1 || 0;
                        if (count1 < count2) {
                            const message = document.createElement('div');
                            message.style.padding = '20px';
                            message.style.textAlign = 'center';
                            message.style.color = '#666';
                            message.textContent = formatMessage('folderHasLessFiles', folder1Path, folder2Path);
                            panel1.appendChild(message);
                        } else {
                            const message = document.createElement('div');
                            message.style.padding = '20px';
                            message.style.textAlign = 'center';
                            message.style.color = '#666';
                            message.textContent = formatMessage('noDifferencesFound', folder1Path);
                            panel1.appendChild(message);
                        }
                    }
                    
                    // Display folder 2 files
                    // panel2 is already defined above, just reset hasContent
                    hasContent = false;
                    
                    if (a.missing_in_folder1 && a.missing_in_folder1.length > 0) {
                        hasContent = true;
                        const header = document.createElement('div');
                        header.style.fontWeight = 'bold';
                        header.style.marginBottom = '10px';
                        const totalCount = a.missing_count_folder1 || a.missing_in_folder1.length;
                        const displayedCount = a.missing_in_folder1.length;
                        if (displayedCount < totalCount) {
                            header.textContent = `Files only in ${folder2Path} (showing ${displayedCount} of ${totalCount}):`;
                        } else {
                            header.textContent = `Files only in ${folder2Path} (${totalCount}):`;
                        }
                        panel2.appendChild(header);
                        
                        a.missing_in_folder1.forEach(file => {
                            const item = createFileItem(file, 'folder2');
                            panel2.appendChild(item);
                        });
                        
                        // Show indicator if there are more files
                        if (displayedCount < totalCount) {
                            const moreIndicator = document.createElement('div');
                            moreIndicator.style.padding = '10px';
                            moreIndicator.style.textAlign = 'center';
                            moreIndicator.style.color = '#666';
                            moreIndicator.style.fontStyle = 'italic';
                            moreIndicator.style.borderTop = '1px solid #eee';
                            moreIndicator.textContent = formatMessage('andMoreFiles', totalCount - displayedCount);
                            panel2.appendChild(moreIndicator);
                        }
                    }
                    
                    // Add visual separator between sections for panel2
                    if (hasContent && a.duplicates && a.duplicates.length > 0) {
                        const separator2 = document.createElement('div');
                        separator2.style.height = '2px';
                        separator2.style.backgroundColor = '#ddd';
                        separator2.style.margin = '20px 0';
                        separator2.style.borderRadius = '1px';
                        panel2.appendChild(separator2);
                    }
                    
                    // Add duplicates section to panel2 (only those where folder2 has a file that would be deleted)
                    if (a.duplicates && a.duplicates.length > 0) {
                        // Filter duplicates for panel2 (only those where folder2 has a file that would be deleted)
                        // A duplicate should appear in panel2 if folder2 has a file that's older than folder1's file
                        const duplicatesPanel2 = a.duplicates.filter(dup => {
                            if (!dup.folder1_docs || dup.folder1_docs.length === 0) return false;
                            if (!dup.folder2_docs || dup.folder2_docs.length === 0) return false;
                            
                            // Get the latest file from both folders
                            const allFiles = [];
                            if (dup.folder1_docs && dup.folder1_docs.length > 0) {
                                for (const doc of dup.folder1_docs) {
                                    allFiles.push({
                                        file_path: doc.file_path,
                                        date_modified: doc.date_modified,
                                        date_created: doc.date_created,
                                        folder: 1
                                    });
                                }
                            }
                            if (dup.folder2_docs && dup.folder2_docs.length > 0) {
                                for (const doc of dup.folder2_docs) {
                                    allFiles.push({
                                        file_path: doc.file_path,
                                        date_modified: doc.date_modified,
                                        date_created: doc.date_created,
                                        folder: 2
                                    });
                                }
                            }
                            
                            if (allFiles.length < 2) return false;
                            
                            // Find the latest file
                            let latestFile = null;
                            let latestDate = null;
                            for (const fileInfo of allFiles) {
                                let compareDate = null;
                                if (fileInfo.date_modified) {
                                    try {
                                        compareDate = new Date(fileInfo.date_modified);
                                    } catch (e) {}
                                }
                                if (!compareDate && fileInfo.date_created) {
                                    try {
                                        compareDate = new Date(fileInfo.date_created);
                                    } catch (e) {}
                                }
                                if (compareDate && (!latestDate || compareDate > latestDate)) {
                                    latestDate = compareDate;
                                    latestFile = fileInfo;
                                }
                            }
                            
                            if (!latestFile) latestFile = allFiles[0];
                            
                            // Show in panel2 if folder2 has a file that's NOT the latest (i.e., would be deleted)
                            return allFiles.some(f => f.folder === 2 && f.file_path !== latestFile.file_path);
                        });
                        
                        if (duplicatesPanel2.length > 0) {
                            hasContent = true;
                            const header2 = document.createElement('div');
                            header2.style.fontWeight = 'bold';
                            header2.style.marginTop = '20px';
                            header2.style.marginBottom = '10px';
                            header2.style.paddingTop = '10px';
                            header2.style.borderTop = '2px solid #007bff';
                            const t = translations[currentLanguage] || translations.en;
                            header2.textContent = `${t.duplicates} (${duplicatesPanel2.length}):`;
                            panel2.appendChild(header2);
                            
                            // Add button to eliminate duplicates for panel2
                            const eliminateBtn2 = document.createElement('button');
                            eliminateBtn2.textContent = 'Eliminate duplicates and keep only the latest file';
                            eliminateBtn2.style.marginBottom = '15px';
                            eliminateBtn2.style.padding = '8px 16px';
                            eliminateBtn2.style.backgroundColor = '#dc3545';
                            eliminateBtn2.style.color = 'white';
                            eliminateBtn2.style.border = 'none';
                            eliminateBtn2.style.borderRadius = '4px';
                            eliminateBtn2.style.cursor = 'pointer';
                            eliminateBtn2.style.fontSize = '14px';
                            eliminateBtn2.onclick = async () => {
                                // Get current token and folder paths
                                const token = localStorage.getItem('access_token');
                                const f1Path = normalizeFolderPath(a.folder1) || 'Folder 1';
                                const f2Path = normalizeFolderPath(a.folder2) || 'Folder 2';
                                
                                if (!token) {
                                    showMessage(formatMessage('notAuthenticated'), 'error');
                                    window.location.href = '/login';
                                    return;
                                }
                                
                                if (confirm(`Are you sure you want to eliminate ${duplicatesPanel2.length} duplicate(s) and keep only the latest file? This action cannot be undone.`)) {
                                    eliminateBtn2.disabled = true;
                                    eliminateBtn2.textContent = 'Processing...';
                                    try {
                                        const response = await fetch('/api/sync/eliminate-duplicates', {
                                            method: 'POST',
                                            headers: {
                                                'Content-Type': 'application/json',
                                                'Authorization': 'Bearer ' + token
                                            },
                                            body: JSON.stringify({
                                                duplicates: duplicatesPanel2,
                                                folder1: f1Path,
                                                folder2: f2Path
                                            })
                                        });
                                        const result = await response.json();
                                        if (result.success) {
                                            // Check if there are any errors (files that couldn't be deleted)
                                            if (result.errors && result.errors.length > 0) {
                                                // Show popup with specific error reasons
                                                const errorMessages = result.errors.join('\\n');
                                                alert(formatMessage('someFilesCouldNotBeDeleted', errorMessages));
                                            }
                                            
                                            showMessage(`Successfully eliminated ${result.deleted_count} duplicate file(s). Kept ${result.kept_count} latest file(s).`, 'success');
                                            // Clear panel2 immediately to show that refresh is happening
                                            const panel2 = document.getElementById('panel2');
                                            if (panel2) {
                                                panel2.innerHTML = '<div style="padding: 20px; text-align: center; color: #666;">Refreshing analysis...</div>';
                                            }
                                            // Also clear panel1 for consistency
                                            const panel1 = document.getElementById('panel1');
                                            if (panel1) {
                                                panel1.innerHTML = '<div style="padding: 20px; text-align: center; color: #666;">Refreshing analysis...</div>';
                                            }
                                            // Reload analysis to refresh display
                                            setTimeout(() => {
                                                const analyzeBtn = document.getElementById('analyzeBtn');
                                                if (analyzeBtn) {
                                                    analyzeBtn.click();
                                                } else {
                                                    analyzeSync();
                                                }
                                            }, 500);
                                        } else {
                                            // Show popup with error message
                                            const errorMsg = result.error || 'Failed to eliminate duplicates';
                                            alert(`Error: ${errorMsg}`);
                                            showMessage(`Error: ${errorMsg}`, 'error');
                                            eliminateBtn2.disabled = false;
                                            eliminateBtn2.textContent = 'Eliminate duplicates and keep only the latest file';
                                        }
                                    } catch (error) {
                                        showMessage(formatMessage('error', error.message), 'error');
                                        eliminateBtn2.disabled = false;
                                        eliminateBtn2.textContent = 'Eliminate duplicates and keep only the latest file';
                                    }
                                }
                            };
                            panel2.appendChild(eliminateBtn2);
                            
                            // Show duplicates in panel2 (only those with folder2_docs)
                            duplicatesPanel2.forEach(dup => {
                                const item2 = document.createElement('div');
                                item2.className = 'file-item';
                                
                                // Get first doc from each folder (for duplicates, typically one per folder)
                                const doc1 = dup.folder1_docs && dup.folder1_docs.length > 0 ? dup.folder1_docs[0] : null;
                                const doc2 = dup.folder2_docs && dup.folder2_docs.length > 0 ? dup.folder2_docs[0] : null;
                                
                                // Get file sizes (individual file size, not sum)
                                const size1 = doc1 ? (doc1.size || 0) : 0;
                                const size2 = doc2 ? (doc2.size || 0) : 0;
                                
                                // Get MD5 hashes to show why files are different
                                const md5_1 = doc1 && doc1.md5_hash ? doc1.md5_hash.substring(0, 16) + '...' : 'N/A';
                                const md5_2 = doc2 && doc2.md5_hash ? doc2.md5_hash.substring(0, 16) + '...' : 'N/A';
                                
                                // Check if MD5 hashes are the same (exact match) or different (duplicate)
                                const md5Match = doc1 && doc2 && doc1.md5_hash === doc2.md5_hash;
                                const duplicateType = md5Match 
                                    ? 'Same name, same content (MD5 match) - different dates only'
                                    : 'Same name, different content (different MD5 hash)';
                                
                                // If there are multiple files with same name, show count
                                const count1 = dup.folder1_docs ? dup.folder1_docs.length : 0;
                                const count2 = dup.folder2_docs ? dup.folder2_docs.length : 0;
                                
                                const date1Created = doc1 && doc1.date_created
                                    ? new Date(doc1.date_created).toLocaleDateString()
                                    : 'N/A';
                                const date1Modified = doc1 && doc1.date_modified
                                    ? new Date(doc1.date_modified).toLocaleDateString()
                                    : 'N/A';
                                const date2Created = doc2 && doc2.date_created
                                    ? new Date(doc2.date_created).toLocaleDateString()
                                    : 'N/A';
                                const date2Modified = doc2 && doc2.date_modified
                                    ? new Date(doc2.date_modified).toLocaleDateString()
                                    : 'N/A';
                                
                                // Build size display - show count if multiple files
                                const size1Display = count1 > 1 
                                    ? `${formatBytes(size1)} (${count1} files)`
                                    : formatBytes(size1);
                                const size2Display = count2 > 1 
                                    ? `${formatBytes(size2)} (${count2} files)`
                                    : formatBytes(size2);
                                
                                item2.innerHTML = `
                                    <div class="file-name">${dup.relative_path}</div>
                                    <div class="file-meta">
                                        ${duplicateType}<br>
                                        <strong>Folder 1:</strong> ${size1Display} | MD5: ${md5_1} | Created: ${date1Created} | Modified: ${date1Modified}<br>
                                        <strong>Folder 2:</strong> ${size2Display} | MD5: ${md5_2} | Created: ${date2Created} | Modified: ${date2Modified}
                                    </div>
                                `;
                                
                                panel2.appendChild(item2);
                            });
                        }
                    }
                    
                    if (isIdentical) {
                        // Both folders are identical
                        const message = document.createElement('div');
                        message.style.padding = '20px';
                        message.style.textAlign = 'center';
                        message.style.color = '#28a745';
                        message.style.fontWeight = '500';
                        message.textContent = formatMessage('foldersIdentical', folder1Path, folder2Path, typesList);
                        panel2.appendChild(message);
                    } else if (!hasContent) {
                        // Panel 2 has no content but folders are not identical
                        // Check if folder2 has fewer files than folder1
                        const count1 = a.missing_count_folder2 || 0;
                        const count2 = a.missing_count_folder1 || 0;
                        if (count2 < count1) {
                            const message = document.createElement('div');
                            message.style.padding = '20px';
                            message.style.textAlign = 'center';
                            message.style.color = '#666';
                            message.textContent = formatMessage('folderHasLessFiles', folder2Path, folder1Path);
                            panel2.appendChild(message);
                        } else {
                            const message = document.createElement('div');
                            message.style.padding = '20px';
                            message.style.textAlign = 'center';
                            message.style.color = '#666';
                            message.textContent = formatMessage('noDifferencesFound', folder2Path);
                            panel2.appendChild(message);
                        }
                    }
                    
                    // Determine which folder is bigger (has more missing files)
                    // missing_count_folder2 = files only in folder1 (not in folder2)
                    // missing_count_folder1 = files only in folder2 (not in folder1)
                    const count1 = a.missing_count_folder2 || 0;  // Files only in folder1
                    const count2 = a.missing_count_folder1 || 0;  // Files only in folder2
                    const biggerFolder = count1 >= count2 ? 1 : 2;
                    const biggerFolderCount = biggerFolder === 1 ? count1 : count2;
                    
                    // Space needed calculations:
                    // space_needed_folder1 = space needed TO folder1 FROM folder2 (files in folder2 that folder1 needs)
                    // space_needed_folder2 = space needed TO folder2 FROM folder1 (files in folder1 that folder2 needs)
                    
                    // Stats for panel 1 (folder1)
                    if (biggerFolder === 1) {
                        // Folder1 is bigger - show "Number of Files in bigger folder" and "Space needed to sync: 0"
                        const t = translations[currentLanguage] || translations.en;
                        document.getElementById('stats1').innerHTML = `
                            <div class="stats-item">
                                <span>${t.numberOfFilesInBiggerFolder}:</span>
                                <span>${biggerFolderCount}</span>
                            </div>
                            <div class="stats-item">
                                <span>${t.spaceNeededToSync}:</span>
                                <span>0</span>
                            </div>
                        `;
                    } else {
                        // Folder1 is smaller - show "Space needed to sync" with actual value
                        // Space needed to sync files FROM folder2 TO folder1
                        const t = translations[currentLanguage] || translations.en;
                        const spaceNeeded = a.space_needed_folder1 || 0;
                        document.getElementById('stats1').innerHTML = `
                            <div class="stats-item">
                                <span>${t.spaceNeededToSync}:</span>
                                <span>${formatBytes(spaceNeeded)}</span>
                            </div>
                        `;
                    }
                    
                    // Stats for panel 2 (folder2)
                    if (biggerFolder === 2) {
                        // Folder2 is bigger - show "Number of Files in bigger folder" and "Space needed to sync: 0"
                        const t = translations[currentLanguage] || translations.en;
                        document.getElementById('stats2').innerHTML = `
                            <div class="stats-item">
                                <span>${t.numberOfFilesInBiggerFolder}:</span>
                                <span>${biggerFolderCount}</span>
                            </div>
                            <div class="stats-item">
                                <span>${t.spaceNeededToSync}:</span>
                                <span>0</span>
                            </div>
                        `;
                    } else {
                        // Folder2 is smaller - show "Space needed to sync" with actual value
                        // Space needed to sync files FROM folder1 TO folder2
                        const t = translations[currentLanguage] || translations.en;
                        const spaceNeeded = a.space_needed_folder2 || 0;
                        document.getElementById('stats2').innerHTML = `
                            <div class="stats-item">
                                <span>${t.spaceNeededToSync}:</span>
                                <span>${formatBytes(spaceNeeded)}</span>
                            </div>
                        `;
                    }
                }
            }
            
            function createFileItem(file, source) {
                const item = document.createElement('div');
                item.className = 'file-item';
                item.innerHTML = `
                    <div class="file-name">${file.name}</div>
                    <div class="file-meta">
                        ${formatBytes(file.size)} | 
                        ${file.date_created ? new Date(file.date_created).toLocaleDateString() : 'N/A'}
                    </div>
                `;
                return item;
            }
            
            function formatBytes(bytes) {
                if (bytes === 0) return '0 Bytes';
                const k = 1024;
                const sizes = ['Bytes', 'KB', 'MB', 'GB'];
                const i = Math.floor(Math.log(bytes) / Math.log(k));
                return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
            }
            
            // Confirmation dialog state
            let confirmResolve = null;
            let copyAllRemaining = false;
            let syncAborted = false;
            
            function abortSync() {
                if (!confirm('Are you sure you want to abort the synchronization?')) {
                    return;
                }
                syncAborted = true;
                if (confirmResolve) {
                    confirmResolve('abort');
                    confirmResolve = null;
                }
                // Update UI to show aborting
                const statusTitle = document.getElementById('syncStatusTitle');
                if (statusTitle) {
                    statusTitle.textContent = 'Synchronization Aborting...';
                }
                const abortBtn = document.getElementById('abortBtn');
                if (abortBtn) {
                    abortBtn.disabled = true;
                    abortBtn.textContent = 'Aborting...';
                }
            }
            
            function closeSyncStatus() {
                const statusPanel = document.getElementById('syncStatusPanel');
                if (statusPanel) {
                    statusPanel.classList.remove('show');
                }
            }
            
            function confirmChoice(choice) {
                const dialog = document.getElementById('confirmDialog');
                const overlay = document.getElementById('confirmOverlay');
                const inlineConfirm = document.getElementById('syncStatusConfirm');
                
                dialog.classList.remove('show');
                overlay.classList.remove('show');
                inlineConfirm.style.display = 'none';
                
                if (choice === 'all') {
                    copyAllRemaining = true;
                    if (confirmResolve) confirmResolve('yes');
                } else if (choice === 'abort') {
                    syncAborted = true;
                    if (confirmResolve) confirmResolve('abort');
                } else {
                    if (confirmResolve) confirmResolve(choice);
                }
                confirmResolve = null;
            }
            
            function showConfirmDialog(fileInfo) {
                return new Promise((resolve) => {
                    const dialog = document.getElementById('confirmDialog');
                    const overlay = document.getElementById('confirmOverlay');
                    const fileInfoDiv = document.getElementById('confirmFileInfo');
                    const inlineConfirm = document.getElementById('syncStatusConfirm');
                    const inlineFileInfo = document.getElementById('syncConfirmFileInfo');
                    
                    const fileInfoHtml = `
                        <strong>File:</strong> ${fileInfo.name}
                        <br><strong>From:</strong> ${fileInfo.source_path}
                        <br><strong>To:</strong> ${fileInfo.target_path}
                        <br><strong>Size:</strong> ${formatBytes(fileInfo.size)}
                    `;
                    
                    // Show in both modal dialog and inline panel
                    fileInfoDiv.innerHTML = fileInfoHtml;
                    inlineFileInfo.innerHTML = fileInfoHtml;
                    
                    confirmResolve = resolve;
                    dialog.classList.add('show');
                    overlay.classList.add('show');
                    inlineConfirm.style.display = 'block';
                    
                    // Handle keyboard shortcuts
                    const handleKeyPress = (e) => {
                        if (e.key.toLowerCase() === 'y') {
                            e.preventDefault();
                            confirmChoice('yes');
                            document.removeEventListener('keydown', handleKeyPress);
                        } else if (e.key.toLowerCase() === 'n') {
                            e.preventDefault();
                            confirmChoice('no');
                            document.removeEventListener('keydown', handleKeyPress);
                        } else if (e.key.toLowerCase() === 'a') {
                            e.preventDefault();
                            confirmChoice('all');
                            document.removeEventListener('keydown', handleKeyPress);
                        } else if (e.key === 'Escape') {
                            e.preventDefault();
                            confirmChoice('abort');
                            document.removeEventListener('keydown', handleKeyPress);
                        }
                    };
                    document.addEventListener('keydown', handleKeyPress);
                });
            }
            
            function updateSyncStatus(file, current, total, copied, skipped, errors) {
                const statusPanel = document.getElementById('syncStatusPanel');
                const statusFile = document.getElementById('syncStatusFile');
                const statusPath = document.getElementById('syncStatusPath');
                const statusProgress = document.getElementById('syncStatusProgress');
                const statCopied = document.getElementById('syncStatCopied');
                const statSkipped = document.getElementById('syncStatSkipped');
                const statErrors = document.getElementById('syncStatErrors');
                const statTotal = document.getElementById('syncStatTotal');
                
                statusPanel.classList.add('show');
                
                if (file) {
                    statusFile.textContent = file.name;
                    statusPath.innerHTML = `
                        <strong>From:</strong> ${file.source_path}<br>
                        <strong>To:</strong> ${file.target_path}
                    `;
                    statusProgress.textContent = `Copying file ${current} of ${total}...`;
                } else {
                    statusFile.textContent = 'Waiting...';
                    statusPath.textContent = '';
                    statusProgress.textContent = '';
                }
                
                statCopied.textContent = copied;
                statSkipped.textContent = skipped;
                statErrors.textContent = errors;
                statTotal.textContent = total;
            }
            
            function displayError(fileName, sourcePath, targetPath, errorMsg) {
                const errorList = document.getElementById('syncErrorList');
                const errorPanel = document.getElementById('syncStatusErrors');
                
                if (!errorList || !errorPanel) return;
                
                // Show error panel
                errorPanel.classList.add('show');
                
                // Create error item
                const errorItem = document.createElement('li');
                errorItem.className = 'sync-status-error-item';
                errorItem.innerHTML = `
                    <strong>${fileName}</strong><br>
                    <strong>Source:</strong> ${sourcePath}<br>
                    <strong>Target:</strong> ${targetPath}<br>
                    <strong>Error:</strong> ${errorMsg}
                `;
                
                // Add to list
                errorList.appendChild(errorItem);
                
                // Scroll to bottom to show latest error
                errorPanel.scrollTop = errorPanel.scrollHeight;
            }
            
            async function copySingleFile(fileInfo, currentToken) {
                try {
                    const response = await fetch('/api/sync/copy-file', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': 'Bearer ' + currentToken
                        },
                        body: JSON.stringify({
                            source_path: fileInfo.source_path,
                            target_path: fileInfo.target_path,
                            source_doc_id: fileInfo.id
                        })
                    });
                    
                    const data = await response.json();
                    return data;
                } catch (error) {
                    return {success: false, error: error.message};
                }
            }
            
            // Make executeSync globally accessible
            window.executeSync = async function executeSync() {
                // Get fresh token from localStorage
                const currentToken = localStorage.getItem('access_token');
                
                if (!currentToken) {
                    showMessage('Not authenticated. Please login again.', 'error');
                    window.location.href = '/login';
                    return;
                }
                
                if (!currentAnalysis || currentAnalysis.type !== 'folder') {
                    showMessage('Please analyze first', 'error');
                    return;
                }
                
                const folder1 = document.getElementById('folder1').value;
                const folder2 = document.getElementById('folder2').value;
                const strategy = document.getElementById('strategy').value;
                
                if (!confirm('Are you sure you want to sync these folders?')) {
                    return;
                }
                
                showMessage('Preparing to sync files...', 'info');
                document.getElementById('executeBtn').disabled = true;
                
                // Reset state
                copyAllRemaining = false;
                syncAborted = false;
                
                // Show sync status panel
                const statusPanel = document.getElementById('syncStatusPanel');
                statusPanel.classList.add('show');
                
                try {
                    const a = currentAnalysis.analysis;
                    const filesToCopy = [];
                    
                    // Build list of files to copy from folder2 to folder1
                    // Use case-insensitive comparison for folder paths to handle Windows paths correctly
                    const normalizePathForComparison = (path) => {
                        // Normalize slashes for comparison (but preserve original for file paths)
                        const backslashChar = String.fromCharCode(92);
                        const forwardSlashChar = String.fromCharCode(47);
                        // Replace all backslashes with forward slashes
                        return path.split(backslashChar).join(forwardSlashChar).toLowerCase();
                    };
                    
                    // Function to check if target file already exists and matches
                    async function checkTargetFileExists(targetPath, sourceMd5) {
                        try {
                            // Check if file exists by making a lightweight API call
                            const response = await fetch('/api/sync/check-file', {
                                method: 'POST',
                                headers: {
                                    'Content-Type': 'application/json',
                                    'Authorization': 'Bearer ' + currentToken
                                },
                                body: JSON.stringify({
                                    target_path: targetPath,
                                    source_md5: sourceMd5
                                })
                            });
                            const data = await response.json();
                            return data.exists && (data.matches_by_name || data.matches_by_md5);
                        } catch (error) {
                            // If check fails, don't filter - let copy operation handle it
                            return false;
                        }
                    }
                    
                    const backslash = String.fromCharCode(92);
                    if (a.missing_in_folder1 && a.missing_in_folder1.length > 0) {
                        // Filter files that already exist in target
                        for (const file of a.missing_in_folder1) {
                            // Preserve ALL special characters, spaces, etc. in file paths
                            // Extract relative path by finding folder2 prefix (case-insensitive)
                            let relPath = file.file_path;
                            const folder2Lower = normalizePathForComparison(folder2);
                            const filePathLower = normalizePathForComparison(file.file_path);
                            
                            if (filePathLower.startsWith(folder2Lower)) {
                                // Find the actual character position where folder2 ends in original path
                                // Use the length of folder2 to find the relative portion
                                const backslashChar = String.fromCharCode(92);
                                const forwardSlashChar = String.fromCharCode(47);
                                const folder2Normalized = folder2.split(backslashChar).join(forwardSlashChar);
                                const filePathNormalized = file.file_path.split(backslashChar).join(forwardSlashChar);
                                
                                // Find the position where folder2 ends (case-insensitive)
                                let matchPos = -1;
                                for (let i = 0; i <= file.file_path.length - folder2.length; i++) {
                                    const substr = file.file_path.substring(i, i + folder2.length);
                                    if (normalizePathForComparison(substr) === folder2Lower) {
                                        matchPos = i;
                                        break;
                                    }
                                }
                                
                                if (matchPos >= 0) {
                                    relPath = file.file_path.substring(matchPos + folder2.length);
                                    // Remove leading slashes/backslashes
                                    relPath = relPath.replace(/^[\\\\/]+/, '');
                                }
                            }
                            
                            // Ensure folder1 ends with backslash, then append relative path
                            // Preserve all special characters in the relative path
                            const folder1End = folder1.endsWith(backslash) || folder1.endsWith('/') ? '' : backslash;
                            // Convert forward slashes to backslashes for Windows, but preserve all other characters
                            const forwardSlash = String.fromCharCode(47);
                            const relPathNormalized = relPath.split(forwardSlash).join(backslash);
                            const targetPath = folder1 + folder1End + relPathNormalized;
                            
                            // Check if target file already exists and matches (by name or MD5)
                            const fileExists = await checkTargetFileExists(targetPath, file.md5_hash || null);
                            if (!fileExists) {
                                filesToCopy.push({
                                    ...file,
                                    source_path: file.file_path,
                                    target_path: targetPath,
                                    direction: 'folder2_to_folder1'
                                });
                            }
                        }
                    }
                    
                    // Build list of files to copy from folder1 to folder2
                    if (a.missing_in_folder2 && a.missing_in_folder2.length > 0) {
                        // Filter files that already exist in target
                        for (const file of a.missing_in_folder2) {
                            // Preserve ALL special characters, spaces, etc. in file paths
                            // Extract relative path by finding folder1 prefix (case-insensitive)
                            let relPath = file.file_path;
                            const folder1Lower = normalizePathForComparison(folder1);
                            const filePathLower = normalizePathForComparison(file.file_path);
                            
                            if (filePathLower.startsWith(folder1Lower)) {
                                // Find the actual character position where folder1 ends in original path
                                const backslashChar = String.fromCharCode(92);
                                const forwardSlashChar = String.fromCharCode(47);
                                const folder1Normalized = folder1.split(backslashChar).join(forwardSlashChar);
                                const filePathNormalized = file.file_path.split(backslashChar).join(forwardSlashChar);
                                
                                // Find the position where folder1 ends (case-insensitive)
                                let matchPos = -1;
                                for (let i = 0; i <= file.file_path.length - folder1.length; i++) {
                                    const substr = file.file_path.substring(i, i + folder1.length);
                                    if (normalizePathForComparison(substr) === folder1Lower) {
                                        matchPos = i;
                                        break;
                                    }
                                }
                                
                                if (matchPos >= 0) {
                                    relPath = file.file_path.substring(matchPos + folder1.length);
                                    // Remove leading slashes/backslashes
                                    relPath = relPath.replace(/^[\\\\/]+/, '');
                                }
                            }
                            
                            // Ensure folder2 ends with backslash, then append relative path
                            // Preserve all special characters in the relative path
                            const folder2End = folder2.endsWith(backslash) || folder2.endsWith('/') ? '' : backslash;
                            // Convert forward slashes to backslashes for Windows, but preserve all other characters
                            const forwardSlash = String.fromCharCode(47);
                            const relPathNormalized = relPath.split(forwardSlash).join(backslash);
                            const targetPath = folder2 + folder2End + relPathNormalized;
                            
                            // Check if target file already exists and matches (by name or MD5)
                            const fileExists = await checkTargetFileExists(targetPath, file.md5_hash || null);
                            if (!fileExists) {
                                filesToCopy.push({
                                    ...file,
                                    source_path: file.file_path,
                                    target_path: targetPath,
                                    direction: 'folder1_to_folder2'
                                });
                            }
                        }
                    }
                    
                    // Handle duplicates (same name, different MD5) - ask user to keep bigger one
                    if (a.duplicates && a.duplicates.length > 0) {
                        for (const dup of a.duplicates) {
                            // Get the largest file from each folder
                            const doc1 = dup.folder1_docs[0];  // Take first doc from folder1
                            const doc2 = dup.folder2_docs[0];  // Take first doc from folder2
                            
                            // Determine which is bigger
                            const biggerDoc = doc1.size >= doc2.size ? doc1 : doc2;
                            const smallerDoc = doc1.size >= doc2.size ? doc2 : doc1;
                            const biggerFolder = doc1.size >= doc2.size ? folder1 : folder2;
                            const smallerFolder = doc1.size >= doc2.size ? folder2 : folder1;
                            
                            // Ask user which file to keep
                            const choice = confirm(
                                `Duplicate file found: ${dup.relative_path}\n` +
                                `Folder 1 (${folder1}): ${formatBytes(doc1.size)}\n` +
                                `Folder 2 (${folder2}): ${formatBytes(doc2.size)}\n\n` +
                                `Keep the larger file (${formatBytes(biggerDoc.size)}) from ${biggerFolder}?\n` +
                                `OK = Keep larger, Cancel = Skip this file`
                            );
                            
                            if (choice) {
                                // Keep the larger file - copy it to replace the smaller one
                                const relPath = dup.relative_path;
                                const targetPath = smallerFolder + (smallerFolder.endsWith(backslash) || smallerFolder.endsWith('/') ? '' : backslash) + relPath;
                                
                                // Check if target file already exists and matches MD5
                                const fileExists = await checkTargetFileExists(targetPath, biggerDoc.md5_hash || null);
                                if (!fileExists) {
                                    filesToCopy.push({
                                        id: biggerDoc.id,
                                        name: biggerDoc.name,
                                        file_path: biggerDoc.file_path,
                                        size: biggerDoc.size,
                                        md5_hash: biggerDoc.md5_hash,
                                        source_path: biggerDoc.file_path,
                                        target_path: targetPath,
                                        direction: 'duplicate_replacement',
                                        is_duplicate: true,
                                        replacing: smallerDoc.file_path
                                    });
                                }
                            }
                            // If user cancels, skip this duplicate file
                        }
                    }
                    
                    if (filesToCopy.length === 0) {
                        showMessage('No files to sync', 'info');
                        statusPanel.classList.remove('show');
                        document.getElementById('executeBtn').disabled = false;
                        return;
                    }
                    
                    // Initialize status
                    updateSyncStatus(null, 0, filesToCopy.length, 0, 0, 0);
                    
                    // Reset UI elements
                    let statusTitle = document.getElementById('syncStatusTitle');
                    let abortBtn = document.getElementById('abortBtn');
                    let closeBtn = document.getElementById('closeSyncBtn');
                    if (statusTitle) statusTitle.textContent = 'Synchronization in Progress';
                    if (abortBtn) {
                        abortBtn.style.display = 'block';
                        abortBtn.disabled = false;
                        abortBtn.textContent = 'Abort';
                    }
                    if (closeBtn) {
                        closeBtn.style.display = 'none';
                    }
                    
                    // Clear previous errors
                    const errorList = document.getElementById('syncErrorList');
                    if (errorList) {
                        errorList.innerHTML = '';
                    }
                    const errorPanel = document.getElementById('syncStatusErrors');
                    if (errorPanel) {
                        errorPanel.classList.remove('show');
                    }
                    
                    let copiedCount = 0;
                    let skippedCount = 0;
                    let errorCount = 0;
                    const errors = [];
                    
                    // Process files one by one
                    for (let i = 0; i < filesToCopy.length; i++) {
                        const file = filesToCopy[i];
                        
                        // Check if aborted
                        if (syncAborted) {
                            updateSyncStatus(null, i, filesToCopy.length, copiedCount, skippedCount, errorCount);
                            showMessage(`Sync aborted. Copied ${copiedCount} files, skipped ${skippedCount} files.`, 'info');
                            break;
                        }
                        
                        // Update status with current file
                        updateSyncStatus(file, i + 1, filesToCopy.length, copiedCount, skippedCount, errorCount);
                        
                        // Show confirmation for first 5 files, or if not "copy all"
                        let shouldCopy = false;
                        if (i < 5 && !copyAllRemaining) {
                            const choice = await showConfirmDialog(file);
                            if (choice === 'abort') {
                                updateSyncStatus(null, i, filesToCopy.length, copiedCount, skippedCount, errorCount);
                                showMessage(`Sync aborted. Copied ${copiedCount} files, skipped ${skippedCount} files.`, 'info');
                                break;
                            }
                            shouldCopy = (choice === 'yes');
                        } else {
                            // After first 5 files, or if "All" was selected, copy automatically
                            shouldCopy = true;
                        }
                        
                        if (shouldCopy) {
                            // Update status to show copying
                            updateSyncStatus(file, i + 1, filesToCopy.length, copiedCount, skippedCount, errorCount);
                            
                            // Check if this is a duplicate replacement - need to delete the old file first
                            if (file.is_duplicate && file.replacing) {
                                // Delete the old file before copying the new one
                                try {
                                    const deleteResponse = await fetch('/api/sync/delete-file', {
                                        method: 'POST',
                                        headers: {
                                            'Content-Type': 'application/json',
                                            'Authorization': 'Bearer ' + currentToken
                                        },
                                        body: JSON.stringify({
                                            file_path: file.replacing
                                        })
                                    });
                                    const deleteResult = await deleteResponse.json();
                                    if (!deleteResult.success) {
                                        errorCount++;
                                        const errorMsg = `Could not delete old file: ${deleteResult.error}`;
                                        errors.push({
                                            file: file.name,
                                            source: file.source_path,
                                            target: file.target_path,
                                            error: errorMsg
                                        });
                                        displayError(file.name, file.source_path, file.target_path, errorMsg);
                                        updateSyncStatus(file, i + 1, filesToCopy.length, copiedCount, skippedCount, errorCount);
                                        continue;  // Skip copying if deletion failed
                                    }
                                } catch (error) {
                                    errorCount++;
                                    const errorMsg = `Error deleting old file: ${error.message}`;
                                    errors.push({
                                        file: file.name,
                                        source: file.source_path,
                                        target: file.target_path,
                                        error: errorMsg
                                    });
                                    displayError(file.name, file.source_path, file.target_path, errorMsg);
                                    updateSyncStatus(file, i + 1, filesToCopy.length, copiedCount, skippedCount, errorCount);
                                    continue;  // Skip copying if deletion failed
                                }
                            }
                            
                            showMessage(`Copying ${file.name} (${i + 1}/${filesToCopy.length})...`, 'info');
                            
                            const result = await copySingleFile(file, currentToken);
                            
                            if (result.success) {
                                if (result.skipped) {
                                    // File already exists with same content - count as skipped
                                    skippedCount++;
                                    showMessage(`${file.name} already exists with same content - skipped`, 'info');
                                } else {
                                    copiedCount++;
                                }
                            } else {
                                errorCount++;
                                const errorMsg = result.error || 'Unknown error';
                                errors.push({
                                    file: file.name,
                                    source: file.source_path,
                                    target: file.target_path,
                                    error: errorMsg
                                });
                                // Display error immediately in the error list
                                displayError(file.name, file.source_path, file.target_path, errorMsg);
                            }
                            
                            // Update status after copy
                            updateSyncStatus(file, i + 1, filesToCopy.length, copiedCount, skippedCount, errorCount);
                        } else {
                            skippedCount++;
                            updateSyncStatus(file, i + 1, filesToCopy.length, copiedCount, skippedCount, errorCount);
                        }
                    }
                    
                    // Show final status
                    updateSyncStatus(null, filesToCopy.length, filesToCopy.length, copiedCount, skippedCount, errorCount);
                    
                    // Update header to show completion
                    statusTitle = document.getElementById('syncStatusTitle');
                    abortBtn = document.getElementById('abortBtn');
                    closeBtn = document.getElementById('closeSyncBtn');
                    
                    if (syncAborted) {
                        if (statusTitle) statusTitle.textContent = 'Synchronization Aborted';
                        showMessage(`Sync aborted. Copied ${copiedCount} files, skipped ${skippedCount} files.`, 'info');
                    } else {
                        if (statusTitle) statusTitle.textContent = 'Synchronization Complete';
                        showMessage(
                            `Sync complete! Copied ${copiedCount} files, skipped ${skippedCount} files.`,
                            'success'
                        );
                        if (errorCount > 0) {
                            showMessage(`Errors: ${errorCount} files failed. See error details below.`, 'error');
                            // Show error panel if it's hidden
                            const errorPanel = document.getElementById('syncStatusErrors');
                            if (errorPanel) {
                                errorPanel.classList.add('show');
                            }
                        }
                    }
                    
                    // Hide abort button and show close button
                    if (abortBtn) {
                        abortBtn.style.display = 'none';
                    }
                    if (closeBtn) {
                        closeBtn.style.display = 'block';
                    }
                    
                    // Update status to show completion
                    const statusFile = document.getElementById('syncStatusFile');
                    const statusProgress = document.getElementById('syncStatusProgress');
                    if (statusFile) {
                        statusFile.textContent = syncAborted ? 'Sync aborted' : 'Sync complete';
                    }
                    if (statusProgress) {
                        statusProgress.textContent = `Completed: ${copiedCount} copied, ${skippedCount} skipped, ${errorCount} errors`;
                    }
                } catch (error) {
                    showMessage('Error: ' + error.message, 'error');
                    statusPanel.classList.remove('show');
                } finally {
                    document.getElementById('executeBtn').disabled = false;
                }
            }
            
            function showMessage(text, type) {
                const messages = document.getElementById('messages');
                const msg = document.createElement('div');
                msg.className = `message ${type}`;
                msg.textContent = text;
                messages.appendChild(msg);
                
                // Keep errors visible until user navigates away; auto-hide others
                if (type !== 'error') {
                    setTimeout(() => {
                        msg.remove();
                    }, 5000);
                }
            }
        </script>
    </body>
    </html>
    """

