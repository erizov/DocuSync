"""FastAPI main application."""

from fastapi import FastAPI, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime, timedelta

from app.database import get_db, Document, init_db, User
from app.search import search_documents, get_document_statistics
from app.file_scanner import find_duplicates
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Search documents."""
    results = search_documents(
        q,
        search_name=True,
        search_author=True,
        search_content=search_content,
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get duplicate documents."""
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
