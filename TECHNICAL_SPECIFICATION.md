# DocuSync - Technical Specification

## Version: 0.1.0
## Last Updated: 2024-12-19

---

## 1. Project Overview

**DocuSync** is a comprehensive document management system built with FastAPI that provides document synchronization, search, duplicate detection, and user management capabilities. The system supports multiple file formats, role-based access control, multi-language support, and comprehensive reporting.

### 1.1 Core Technologies
- **Backend Framework**: FastAPI 0.104.1
- **Database**: SQLite with SQLAlchemy ORM 2.0.23
- **Authentication**: JWT (python-jose) with bcrypt password hashing
- **Data Validation**: Pydantic 2.5.0
- **CLI**: Typer 0.9.0 with Rich for formatting
- **Testing**: pytest 7.4.3 with pytest-asyncio
- **Python Version**: >= 3.9

---

## 2. Architecture

### 2.1 Project Structure
```
DocSync/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application, routes, HTML pages
│   ├── database.py          # SQLAlchemy models and database setup
│   ├── config.py            # Application settings (Pydantic)
│   ├── auth.py              # Authentication and authorization
│   ├── file_scanner.py      # File system scanning and indexing
│   ├── search.py            # Basic search functionality
│   ├── search_fts5.py       # FTS5 full-text search
│   ├── sync.py              # Folder/drive synchronization logic
│   ├── reports.py           # Activity reporting and statistics
│   ├── corrupted_pdf.py     # Corrupted PDF detection and removal
│   ├── cli.py               # Command-line interface
│   ├── cli_reports.py       # CLI report commands
│   └── migrate_db.py        # Database migration utilities
├── tests/                   # Test suite
├── requirements.txt         # Python dependencies
├── pyproject.toml          # Project configuration
└── README.md               # User documentation
```

### 2.2 Database Schema

#### 2.2.1 Document Model
```python
class Document(Base):
    id: Integer (Primary Key)
    name: String(500) - indexed
    file_path: String(1000) - unique, indexed
    drive: String(10) - indexed
    directory: String(1000) - indexed
    author: String(500) - nullable
    size: BigInteger
    size_on_disc: BigInteger
    date_created: DateTime - nullable
    date_published: DateTime - nullable
    md5_hash: String(32) - indexed
    file_type: String(10) - indexed
    extracted_text: Text - nullable (full text content)
    extracted_text_preview: String(8192) - nullable (preview)
    is_duplicate: Boolean - indexed, default=False
    preferred_location: Boolean - indexed, default=False
    
    Indexes:
    - idx_drive_dir (drive, directory)
    - idx_md5_hash (md5_hash)
    - idx_name_author (name, author)
```

#### 2.2.2 User Model
```python
class User(Base):
    id: Integer (Primary Key)
    username: String(50) - unique, indexed
    hashed_password: String(255)
    role: String(20) - indexed, default='readonly'
        # Values: 'readonly', 'full', 'admin'
    is_active: Boolean - default=True
    created_at: DateTime - default=utcnow
    
    Relationship: activities (one-to-many with Activity)
```

#### 2.2.3 Activity Model
```python
class Activity(Base):
    id: Integer (Primary Key)
    user_id: Integer - ForeignKey(users.id), nullable, indexed
    activity_type: String(50) - indexed
        # Values: 'delete', 'move', 'sync', etc.
    description: Text
    document_path: String(1000) - nullable
    space_saved_bytes: BigInteger - default=0
    operation_count: Integer - default=1
    created_at: DateTime - default=utcnow, indexed
    
    Relationship: user (many-to-one with User)
    
    Indexes:
    - idx_activity_type_date (activity_type, created_at)
```

#### 2.2.4 FTS5 Virtual Table
```sql
CREATE VIRTUAL TABLE documents_fts USING fts5(
    doc_id UNINDEXED,
    full_text,
    name,
    author
);
```
- Automatically synced via triggers
- Used for fast full-text search

---

## 3. Authentication & Authorization

### 3.1 Authentication Flow
1. User submits username/password via `/api/auth/login` (OAuth2PasswordRequestForm)
2. Server validates credentials using bcrypt
3. JWT token generated with 30-minute expiration (configurable)
4. Token includes: username (sub), role, expiration
5. Token stored in localStorage on client side

### 3.2 Authorization Levels

#### 3.2.1 Roles
- **readonly**: View-only access, cannot modify or sync
- **full**: Can view, search, and perform sync operations
- **admin**: Full access including user management and reports

#### 3.2.2 Dependency Functions
- `get_current_user()`: Requires valid JWT token
- `require_admin()`: Requires admin role
- `require_full_or_admin()`: Requires full or admin role

### 3.3 Session Management
- **Token Expiration**: 30 minutes (configurable)
- **Inactivity Timeout**: 1 hour (client-side)
- **Activity Tracking**: Mouse, keyboard, scroll, touch, click events
- **Auto-logout**: Redirects to `/login` after timeout

---

## 4. API Endpoints

### 4.1 Authentication
- `POST /api/auth/login` - Login (returns JWT token)

### 4.2 Documents
- `GET /api/documents` - List documents (filtered by drive, optional)
- `GET /api/search` - Search documents (query parameter)
- `GET /api/stats` - Document statistics

### 4.3 Duplicates
- `GET /api/duplicates` - Find duplicates
  - Query params: `duplicate_type` ('content', 'name', 'all')

### 4.4 Synchronization
- `POST /api/sync/analyze` - Analyze sync requirements
  - Body: `folder1`, `folder2`, `strategy` ('keep_both', 'keep_newest', 'keep_largest')
- `POST /api/sync/execute` - Execute sync operation
  - Body: `folder1`, `folder2`, `files_to_copy` (list)
- `GET /api/sync/progress` - Get sync progress (job_id parameter)
- `POST /api/sync/delete-file` - Delete file (for duplicate replacement)

### 4.5 User Management (Admin Only)
- `GET /api/users` - List all users
- `POST /api/users` - Create new user
  - Body: `username`, `password`, `role`
- `PUT /api/users/{user_id}` - Update user
  - Body: `password` (optional), `role` (optional), `is_active` (optional)
- `DELETE /api/users/{user_id}` - Delete user

### 4.6 Reports (Admin Only)
- `GET /api/reports/activities` - Activity log
  - Query params: `activity_type` (optional), `limit` (1-1000, default 100)
  - Returns: List of ActivityResponse objects
  - Filters out activities with zero space saved
  - Includes 'delete_duplicates' activity type
  - 60-second timeout using asyncio.wait_for
  - Error handling: Returns empty list if no activities, handles None values, timeout errors
- `GET /api/reports/space-saved` - Space saved report
  - Query params: `start_date`, `end_date` (YYYY-MM-DD format)
  - Returns: Dictionary with total_space_saved_bytes, total_operations, breakdown by activity_type
  - 60-second timeout using asyncio.wait_for
  - Error handling: Handles None results when no matching activities, timeout errors
- `GET /api/reports/operations` - Operations report
  - Query params: `start_date`, `end_date` (YYYY-MM-DD format)
  - Returns: Dictionary with activity_type as keys, activity_count and total_operations as values
  - 60-second timeout using asyncio.wait_for
  - Error handling: Handles None values in aggregate results, timeout errors
- `GET /api/reports/corrupted-pdfs` - Corrupted PDFs report
  - Query params: `drive` (optional), `limit` (1-5000, default 1000)
  - Returns: Dictionary with total_corrupted, total_size_bytes, by_drive, and files array
  - Checks database and file existence only (fast, no PDF opening)
  - Returns PDFs that don't exist on disk or have size 0
  - 60-second timeout using asyncio.wait_for
  - Error handling: Handles timeout errors, file access errors

### 4.7 Web Pages
- `GET /` - Redirects to `/login`
- `GET /login` - Login page (HTML)
- `GET /sync` - Sync interface page (HTML)
- `GET /reports` - Reports page (HTML, admin only)

---

## 5. Frontend Features

### 5.1 Sync Page (`/sync`)
- **Two-panel interface**: Folder1 vs Folder2 comparison
- **Language selector**: 6 languages (en, de, fr, es, it, ru) - available only on this page
- **Folder input**: Browse buttons for folder selection
- **Sync strategy selector**: Keep Both, Keep Newest, Keep Largest
- **Analyze button**: Analyzes differences between folders
- **Execute Sync button**: Performs synchronization (full/admin only)
- **Results display**: Shows files to copy, duplicates, conflicts
- **Progress tracking**: Real-time sync progress with status panel
- **Error handling**: Displays errors during sync operations
- **Language persistence**: Selected language saved in localStorage and shared across all pages

### 5.2 Reports Page (`/reports`)
- **Tabbed interface**: Activities, Space Saved, Operations, Corrupted PDFs
- **Filters**: Date ranges, activity types, drive filters
- **Statistics cards**: Total space saved, total operations
- **Data tables**: Formatted display of report data
- **Admin-only access**: Redirects non-admins
- **Fully translated**: All buttons, labels, and text translated (uses language from localStorage)
- **No language selector**: Language managed from main sync page
- **60-second timeout**: All report endpoints have timeout protection
- **Optimized corrupted PDFs**: Checks database only (fast, no file opening)

### 5.3 User Management (Modal on Sync Page)
- **User list table**: Shows all users with role and active status
- **Add user form**: Create new users (admin only)
- **Edit user modal**: Update user details (admin only)
- **Delete confirmation**: Prevents accidental deletion
- **Self-protection**: Cannot delete/deactivate self or change own role from admin

### 5.4 Multi-Language Support
- **Languages**: English, German, French, Spanish, Italian, Russian
- **Translation keys**: All UI elements, buttons, messages, forms across all pages
- **Dynamic switching**: Changes language without page reload
- **Language selector**: Available only on main sync page (`/sync`)
- **Language persistence**: Selected language saved in localStorage (`docuSync_language` key)
- **Shared across pages**: All pages (sync, reports) use the same language preference
- **Auto-detection**: Detects browser language on first visit
- **Persistence**: Language preference stored in localStorage
- **Formatting**: Supports placeholder replacement (e.g., `{0}`, `{1}`)

---

## 6. File Synchronization Algorithm

### 6.1 Analysis Phase
1. **Calculate Relative Paths**: Convert absolute paths to relative paths from base folder
2. **Build Dictionaries**: Create `{relative_path: [documents]}` mappings for each folder
3. **Compare by Relative Path**:
   - Files only in folder1 → `missing_in_folder2`
   - Files only in folder2 → `missing_in_folder1`
   - Same relative path, same MD5 → exact match (no action)
   - Same relative path, different MD5 → duplicate (user decision)
4. **Cross-Path MD5 Matching**: Detect renamed/moved files (same content, different location)

### 6.2 Sync Strategies
- **keep_both**: Preserve both versions with suffixes (`_copy`, `_copy2`, etc.)
- **keep_newest**: Automatically keep most recently modified file
- **keep_largest**: Automatically keep larger file

### 6.3 Execution Phase
1. Validate target paths exist
2. Check file existence and MD5 before copying
3. Copy files one by one with progress tracking
4. Handle errors gracefully (continue on failure)
5. Log activities for reporting

---

## 7. Search Functionality

### 7.1 Basic Search (`search.py`)
- Searches in: name, author, file_path, extracted_text
- Case-insensitive matching
- Drive filtering support

### 7.2 FTS5 Search (`search_fts5.py`)
- **Full-text search**: Uses SQLite FTS5 virtual table
- **Phrase matching**: Exact phrase search
- **Boolean operators**: AND, OR, NOT support
- **Performance**: 10-50x faster than basic search
- **Indexed fields**: full_text, name, author

---

## 8. Duplicate Detection

### 8.1 Types of Duplicates
1. **Same Content, Different Names**: Same MD5 hash, different filenames
2. **Same Name, Different Content**: Same filename, different MD5 hash

### 8.2 Detection Process
- Groups files by MD5 hash (type 1)
- Groups files by name (type 2)
- Returns duplicate groups for user decision

---

## 9. Configuration

### 9.1 Settings (`config.py`)
```python
database_url: str = "sqlite:///docu_sync.db"
max_file_size_mb: int = 100
supported_extensions: list[str] = [".pdf", ".docx", ".txt", ...]
enable_fulltext_search: bool = True
chunk_size: int = 8192
secret_key: str = "..."  # JWT secret
algorithm: str = "HS256"
access_token_expire_minutes: int = 30
default_username: str = "admin"
default_password: str = "admin"
max_test_files: int = 100
```

### 9.2 Environment Variables
- Can override settings via `.env` file
- Uses Pydantic Settings for validation

---

## 10. CLI Commands

### 10.1 Document Management
- `python -m app.cli scan [--drive D]` - Scan drives for documents
- `python -m app.cli list-documents [--drive D]` - List indexed documents
- `python -m app.cli search "query" [--no-content]` - Search documents
- `python -m app.cli stats` - Show statistics

### 10.2 Duplicates
- `python -m app.cli duplicates` - Find and manage duplicates

### 10.3 Synchronization
- `python -m app.cli sync --drive1 D --drive2 E [--no-dry-run]` - Sync drives

### 10.4 Reports
- `python -m app.cli reports activities [--type TYPE] [--limit N]` - Activity report
- `python -m app.cli reports space-saved [--start DATE] [--end DATE]` - Space saved
- `python -m app.cli reports operations [--start DATE] [--end DATE]` - Operations

---

## 11. Testing

### 11.1 Test Structure
- **Location**: `tests/` directory
- **Framework**: pytest with pytest-asyncio
- **Fixtures**: Database setup, authenticated clients, temp directories
- **Coverage**: pytest-cov for code coverage

### 11.2 Test Files
- `test_file_scanner.py` - File scanning tests
- `test_search.py` - Basic search tests
- `test_search_fts5.py` - FTS5 search tests
- `test_sync_frontend.py` - Sync functionality tests
- `test_endpoints.py` - API endpoint tests
- `test_e2e.py` - End-to-end tests
- `test_reports.py` - Reporting tests

### 11.2 Test Configuration
- **Timeout**: 30 minutes (1800 seconds)
- **Max test files**: 100 files
- **Test database**: Separate SQLite database for tests

---

## 12. Security Features

### 12.1 Password Security
- **Hashing**: bcrypt with passlib
- **Salt**: Automatic salt generation
- **Verification**: Secure password verification

### 12.2 Token Security
- **Algorithm**: HS256 (HMAC-SHA256)
- **Expiration**: 30 minutes
- **Storage**: Client-side localStorage
- **Validation**: Server-side token validation on each request

### 12.3 Access Control
- **Role-based**: Three-tier access control
- **Endpoint protection**: All endpoints except `/login` require authentication
- **Admin-only**: User management and reports require admin role
- **Self-protection**: Users cannot delete/deactivate themselves

---

## 13. Activity Logging

### 13.1 Logged Activities
- File deletions
- File moves/copies
- Synchronization operations
- User management actions

### 13.2 Activity Data
- Activity type
- Description
- Document path (if applicable)
- Space saved (bytes)
- Operation count
- User ID (who performed action)
- Timestamp

---

## 14. Supported File Formats

- PDF (`.pdf`)
- Word Documents (`.docx`, `.doc`)
- Text Files (`.txt`)
- EPUB (`.epub`)
- DJVU (`.djvu`)
- Archives (`.zip`, `.rar`)
- FB2 (`.fb2`)
- HTML (`.html`)
- RTF (`.rtf`)
- Images (`.gif`)
- PowerPoint (`.ppt`)
- Audio (`.mp3`)

---

## 15. Error Handling

### 15.1 API Errors
- **401 Unauthorized**: Invalid or missing token
- **403 Forbidden**: Insufficient permissions
- **404 Not Found**: Resource not found
- **400 Bad Request**: Invalid input data
- **500 Internal Server Error**: Server errors

### 15.2 Frontend Error Handling
- Try-catch blocks for async operations
- User-friendly error messages
- Error display in UI
- Graceful degradation

---

## 16. Performance Considerations

### 16.1 Database Optimization
- **Indexes**: Strategic indexes on frequently queried columns
- **FTS5**: Fast full-text search using virtual tables
- **Connection pooling**: SQLAlchemy connection management

### 16.2 File Operations
- **Async operations**: Background tasks for long-running operations
- **Progress tracking**: Real-time progress updates
- **Chunked processing**: Process files in batches

### 16.3 Frontend Optimization
- **Lazy loading**: Load data on demand
- **Client-side caching**: localStorage for tokens and preferences
- **Efficient DOM updates**: Minimal re-renders

---

## 17. Deployment

### 17.1 Server Requirements
- Python 3.9+
- SQLite database (file-based)
- No external dependencies (self-contained)

### 17.2 Running the Application
```bash
# Install dependencies
pip install -r requirements.txt

# Run server
uvicorn app.main:app --reload

# Access
# Web UI: http://localhost:8000/sync
# API Docs: http://localhost:8000/docs
# Login: http://localhost:8000/login
```

### 17.3 Default Credentials
- Username: `admin`
- Password: `admin`
- **Important**: Change default password in production!

---

## 18. Future Enhancements

### 18.1 Potential Features
- Database migration system
- Export/import functionality
- Scheduled sync operations
- Email notifications
- Advanced search filters
- Document preview
- Version control
- Cloud storage integration

---

## 19. Known Limitations

1. **SQLite**: Single-file database (not suitable for high concurrency)
2. **File Size**: Max 100MB per file (configurable)
3. **Inactivity Timeout**: Client-side only (can be bypassed)
4. **Language Support**: Fixed set of 6 languages
5. **Windows Focus**: Optimized for Windows file paths

---

## 20. Maintenance

### 20.1 Database Maintenance
- Regular backups recommended
- FTS5 table auto-syncs via triggers
- Migration scripts available in `migrate_db.py`

### 20.2 Code Maintenance
- Follow PEP 8 style guide
- Type hints where applicable
- Comprehensive docstrings
- Unit tests for new features

---

## 21. License

MIT License - See LICENSE file for details

---

## 22. Contact & Support

- **Issues**: GitHub Issues
- **Documentation**: README.md
- **API Documentation**: `/docs` endpoint (Swagger UI)

---

**End of Technical Specification**

