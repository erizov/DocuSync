"""FastAPI main application."""

import os
from fastapi import FastAPI, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse, FileResponse
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
    init_default_user
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


class LoginRequest(BaseModel):
    """Login request model."""

    username: str
    password: str


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
    """Root endpoint."""
    return {
        "message": "DocuSync API",
        "version": "0.1.0",
        "endpoints": {
            "/login": "Login page",
            "/docs": "API documentation",
            "/api/auth/login": "Login endpoint",
            "/api/search": "Search documents",
            "/api/documents": "List documents",
            "/api/stats": "Get statistics",
            "/api/duplicates": "Find duplicates",
            "/api/reports": "Get reports"
        }
    }


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
                        messageDiv.innerHTML += '<div class="success">Token saved. Redirecting...</div>';
                        setTimeout(() => {
                            window.location.href = '/docs';
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
    access_token = create_access_token(
        data={"sub": user.username}
    )
    return {"access_token": access_token, "token_type": "bearer"}


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


class SyncRequest(BaseModel):
    """Sync request model."""
    folder1: str
    folder2: str
    strategy: str = "keep_both"  # keep_both, keep_newest, keep_largest
    target_folder1: Optional[str] = None
    target_folder2: Optional[str] = None
    dry_run: bool = True


@app.post("/api/sync/analyze")
async def analyze_sync(
    request: SyncAnalysisRequest,
    current_user: User = Depends(get_current_user)
):
    """Analyze what needs to be synced between two folders or drives."""
    if request.folder1 and request.folder2:
        # Folder sync
        analysis = analyze_folder_sync(request.folder1, request.folder2)
        return {
            "type": "folder",
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
                        "date_created": doc.date_created.isoformat() if doc.date_created else None,
                    }
                    for doc in analysis["missing_in_folder1"][:100]  # Limit for frontend
                ],
                "missing_in_folder2": [
                    {
                        "id": doc.id,
                        "name": doc.name,
                        "file_path": doc.file_path,
                        "size": doc.size,
                        "date_created": doc.date_created.isoformat() if doc.date_created else None,
                    }
                    for doc in analysis["missing_in_folder2"][:100]
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
                                "date_created": doc.date_created.isoformat() if doc.date_created else None,
                            }
                            for doc in dup["folder1_docs"]
                        ],
                        "folder2_docs": [
                            {
                                "id": doc.id,
                                "name": doc.name,
                                "file_path": doc.file_path,
                                "size": doc.size,
                                "date_created": doc.date_created.isoformat() if doc.date_created else None,
                            }
                            for doc in dup["folder2_docs"]
                        ],
                    }
                    for dup in analysis["duplicates"][:100]  # Limit duplicates
                ],
            }
        }
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


@app.post("/api/sync/execute")
async def execute_sync(
    request: SyncRequest,
    current_user: User = Depends(get_current_user)
):
    """Execute folder synchronization."""
    result = sync_folders(
        folder1=request.folder1,
        folder2=request.folder2,
        strategy=request.strategy,
        target_folder1=request.target_folder1,
        target_folder2=request.target_folder2,
        dry_run=request.dry_run
    )
    return result


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
        </style>
    </head>
    <body>
        <div class="header">
            <h1>DocuSync - Folder Synchronization</h1>
            <p>Compare and sync files between two folders or drives</p>
        </div>
        
        <div class="controls">
            <div class="controls-row">
                <label>Folder 1:</label>
                <input type="text" id="folder1" placeholder="C:\\folder1 or C">
            </div>
            <div class="controls-row">
                <label>Folder 2:</label>
                <input type="text" id="folder2" placeholder="D:\\folder2 or D">
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
                <button onclick="analyzeSync()">Analyze</button>
                <button onclick="executeSync()" id="executeBtn" disabled>Execute Sync</button>
            </div>
        </div>
        
        <div id="messages"></div>
        
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
            let currentAnalysis = null;
            let token = localStorage.getItem('access_token');
            
            if (!token) {
                window.location.href = '/login';
            }
            
            async function analyzeSync() {
                const folder1 = document.getElementById('folder1').value;
                const folder2 = document.getElementById('folder2').value;
                
                if (!folder1 || !folder2) {
                    showMessage('Please enter both folders', 'error');
                    return;
                }
                
                showMessage('Analyzing...', 'info');
                document.getElementById('executeBtn').disabled = true;
                
                try {
                    const response = await fetch('/api/sync/analyze', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': `Bearer ${token}`
                        },
                        body: JSON.stringify({
                            folder1: (folder1.length > 1 || folder1.includes('\\')) ? folder1 : null,
                            folder2: (folder2.length > 1 || folder2.includes('\\')) ? folder2 : null,
                            drive1: (folder1.length === 1 && !folder1.includes('\\')) ? folder1 : null,
                            drive2: (folder2.length === 1 && !folder2.includes('\\')) ? folder2 : null
                        })
                    });
                    
                    const data = await response.json();
                    
                    if (response.ok) {
                        currentAnalysis = data;
                        displayAnalysis(data);
                        document.getElementById('executeBtn').disabled = false;
                        showMessage('Analysis complete', 'success');
                    } else {
                        showMessage('Analysis failed: ' + (data.detail || 'Unknown error'), 'error');
                    }
                } catch (error) {
                    showMessage('Error: ' + error.message, 'error');
                }
            }
            
            function displayAnalysis(analysis) {
                const container = document.getElementById('syncContainer');
                container.style.display = 'grid';
                
                if (analysis.type === 'folder') {
                    const a = analysis.analysis;
                    
                    // Display folder 1 files
                    const panel1 = document.getElementById('panel1');
                    panel1.innerHTML = '';
                    
                    if (a.missing_in_folder2 && a.missing_in_folder2.length > 0) {
                        const header = document.createElement('div');
                        header.style.fontWeight = 'bold';
                        header.style.marginBottom = '10px';
                        header.textContent = `Files only in Folder 1 (${a.missing_in_folder2.length}):`;
                        panel1.appendChild(header);
                        
                        a.missing_in_folder2.forEach(file => {
                            const item = createFileItem(file, 'folder1');
                            panel1.appendChild(item);
                        });
                    }
                    
                    if (a.duplicates && a.duplicates.length > 0) {
                        const header = document.createElement('div');
                        header.style.fontWeight = 'bold';
                        header.style.marginTop = '20px';
                        header.style.marginBottom = '10px';
                        header.textContent = `Duplicates (${a.duplicates.length}):`;
                        panel1.appendChild(header);
                        
                        a.duplicates.forEach(dup => {
                            const item = document.createElement('div');
                            item.className = 'file-item';
                            item.innerHTML = `
                                <div class="file-name">${dup.relative_path}</div>
                                <div class="file-meta">Same name, different content</div>
                            `;
                            panel1.appendChild(item);
                        });
                    }
                    
                    // Display folder 2 files
                    const panel2 = document.getElementById('panel2');
                    panel2.innerHTML = '';
                    
                    if (a.missing_in_folder1 && a.missing_in_folder1.length > 0) {
                        const header = document.createElement('div');
                        header.style.fontWeight = 'bold';
                        header.style.marginBottom = '10px';
                        header.textContent = `Files only in Folder 2 (${a.missing_in_folder1.length}):`;
                        panel2.appendChild(header);
                        
                        a.missing_in_folder1.forEach(file => {
                            const item = createFileItem(file, 'folder2');
                            panel2.appendChild(item);
                        });
                    }
                    
                    // Stats
                    document.getElementById('stats1').innerHTML = `
                        <div class="stats-item">
                            <span>Files:</span>
                            <span>${a.missing_count_folder2}</span>
                        </div>
                        <div class="stats-item">
                            <span>Space needed:</span>
                            <span>${formatBytes(a.space_needed_folder2)}</span>
                        </div>
                    `;
                    
                    document.getElementById('stats2').innerHTML = `
                        <div class="stats-item">
                            <span>Files:</span>
                            <span>${a.missing_count_folder1}</span>
                        </div>
                        <div class="stats-item">
                            <span>Space needed:</span>
                            <span>${formatBytes(a.space_needed_folder1)}</span>
                        </div>
                    `;
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
            
            async function executeSync() {
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
                
                showMessage('Syncing...', 'info');
                document.getElementById('executeBtn').disabled = true;
                
                try {
                    const response = await fetch('/api/sync/execute', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': `Bearer ${token}`
                        },
                        body: JSON.stringify({
                            folder1: folder1,
                            folder2: folder2,
                            strategy: strategy,
                            dry_run: false
                        })
                    });
                    
                    const data = await response.json();
                    
                    if (response.ok) {
                        showMessage(
                            `Sync complete! Copied ${data.copied_to_folder1} to folder1, ` +
                            `${data.copied_to_folder2} to folder2, ` +
                            `resolved ${data.resolved_duplicates} duplicates.`,
                            'success'
                        );
                        if (data.errors && data.errors.length > 0) {
                            showMessage('Errors: ' + data.errors.join(', '), 'error');
                        }
                    } else {
                        showMessage('Sync failed: ' + (data.detail || 'Unknown error'), 'error');
                    }
                } catch (error) {
                    showMessage('Error: ' + error.message, 'error');
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
                
                setTimeout(() => {
                    msg.remove();
                }, 5000);
            }
        </script>
    </body>
    </html>
    """
