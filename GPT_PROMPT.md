# DocuSync - Complete Project Generation Prompt

## Instructions for AI Assistant

You are tasked with generating a complete, production-ready document management system called **DocuSync** based on the following comprehensive specification. Generate all files, maintain code quality, include proper error handling, and ensure the system is fully functional.

---

## Project Overview

**DocuSync** is a FastAPI-based document management system with the following core features:
- Document scanning and indexing across multiple drives
- Full-text search with FTS5 support
- Duplicate detection (same content different names, same name different content)
- Folder/drive synchronization with conflict resolution
- Role-based user management (readonly, full, admin)
- Multi-language support (English, German, French, Spanish, Italian, Russian)
- Activity logging and reporting
- Web-based UI with sync interface
- CLI interface for command-line operations

---

## Technology Stack

- **Framework**: FastAPI 0.104.1
- **Database**: SQLite with SQLAlchemy 2.0.23
- **Authentication**: JWT (python-jose) with bcrypt
- **Validation**: Pydantic 2.5.0
- **CLI**: Typer 0.9.0 with Rich
- **Testing**: pytest 7.4.3
- **Python**: >= 3.9

---

## Project Structure

Create the following directory structure:

```
DocSync/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, all routes, HTML pages
│   ├── database.py          # SQLAlchemy models (Document, User, Activity)
│   ├── config.py            # Pydantic settings
│   ├── auth.py              # JWT auth, password hashing, role checks
│   ├── file_scanner.py      # File system scanning
│   ├── search.py            # Basic search
│   ├── search_fts5.py      # FTS5 full-text search
│   ├── sync.py              # Sync logic
│   ├── reports.py           # Activity reporting
│   ├── corrupted_pdf.py     # Corrupted PDF detection
│   ├── cli.py               # CLI commands
│   ├── cli_reports.py       # CLI report commands
│   └── migrate_db.py        # DB migrations
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # Pytest fixtures
│   ├── test_file_scanner.py
│   ├── test_search.py
│   ├── test_search_fts5.py
│   ├── test_sync_frontend.py
│   ├── test_endpoints.py
│   ├── test_e2e.py
│   └── test_reports.py
├── requirements.txt
├── pyproject.toml
├── README.md
└── LICENSE
```

---

## Database Models

### Document Model
```python
class Document(Base):
    id: Integer (PK)
    name: String(500), indexed
    file_path: String(1000), unique, indexed
    drive: String(10), indexed
    directory: String(1000), indexed
    author: String(500), nullable
    size: BigInteger
    size_on_disc: BigInteger
    date_created: DateTime, nullable
    date_published: DateTime, nullable
    md5_hash: String(32), indexed
    file_type: String(10), indexed
    extracted_text: Text, nullable
    extracted_text_preview: String(8192), nullable
    is_duplicate: Boolean, indexed, default=False
    preferred_location: Boolean, indexed, default=False
```

### User Model
```python
class User(Base):
    id: Integer (PK)
    username: String(50), unique, indexed
    hashed_password: String(255)
    role: String(20), indexed, default='readonly'  # readonly, full, admin
    is_active: Boolean, default=True
    created_at: DateTime, default=utcnow
```

### Activity Model
```python
class Activity(Base):
    id: Integer (PK)
    user_id: Integer, FK(users.id), nullable, indexed
    activity_type: String(50), indexed
    description: Text
    document_path: String(1000), nullable
    space_saved_bytes: BigInteger, default=0
    operation_count: Integer, default=1
    created_at: DateTime, default=utcnow, indexed
```

### FTS5 Virtual Table
Create FTS5 table `documents_fts` with columns: doc_id, full_text, name, author
- Auto-sync via triggers on INSERT/UPDATE/DELETE

---

## API Endpoints

### Authentication
- `POST /api/auth/login` - OAuth2PasswordRequestForm, returns JWT token with role

### Documents
- `GET /api/documents?drive=D` - List documents (optional drive filter)
- `GET /api/search?q=query` - Search documents
- `GET /api/stats` - Statistics

### Duplicates
- `GET /api/duplicates?duplicate_type=content|name|all` - Find duplicates

### Sync
- `POST /api/sync/analyze` - Body: {folder1, folder2, strategy}
- `POST /api/sync/execute` - Body: {folder1, folder2, files_to_copy[]}
- `GET /api/sync/progress?job_id=xxx` - Get progress
- `POST /api/sync/delete-file` - Body: {file_path}

### User Management (Admin Only)
- `GET /api/users` - List users
- `POST /api/users` - Body: {username, password, role}
- `PUT /api/users/{user_id}` - Body: {password?, role?, is_active?}
- `DELETE /api/users/{user_id}` - Delete user

### Reports (Admin Only)
- `GET /api/reports/activities?activity_type=X&limit=100`
  - Returns list of ActivityResponse objects
  - Filters out activities with zero space saved
  - Includes 'delete_duplicates' activity type
  - 60-second timeout
  - Handles empty results and None values gracefully
- `GET /api/reports/space-saved?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD`
  - Returns dict with total_space_saved_bytes, total_operations, breakdown
  - 60-second timeout
  - Handles None results when no activities match filter
- `GET /api/reports/operations?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD`
  - Returns dict with activity_type as keys
  - 60-second timeout
  - Handles None values in aggregate results
- `GET /api/reports/corrupted-pdfs?drive=D&limit=1000`
  - Checks database and file existence only (fast, no PDF opening)
  - Returns PDFs that don't exist on disk or have size 0
  - 60-second timeout
  - Query params: `drive` (optional), `limit` (1-5000, default 1000)

### Web Pages
- `GET /` - Redirect to /login
- `GET /login` - Login page HTML
- `GET /sync` - Sync interface HTML (large page with full UI)
- `GET /reports` - Reports page HTML (admin only)

---

## Authentication & Authorization

### JWT Token
- Secret key: "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"
- Algorithm: HS256
- Expiration: 30 minutes
- Payload: {sub: username, role: user_role, exp: expiration}

### Password Hashing
- Use bcrypt via passlib
- Hash passwords before storing
- Verify passwords on login

### Role-Based Access
- **readonly**: View only, no sync
- **full**: View + sync operations
- **admin**: Full access + user management + reports

### Dependencies
- `get_current_user()` - Requires valid token
- `require_admin()` - Requires admin role
- `require_full_or_admin()` - Requires full or admin role

### Session Management
- Client-side inactivity timeout: 1 hour
- Track: mousedown, mousemove, keypress, scroll, touchstart, click
- Auto-logout and redirect to /login

---

## Frontend Features

### Sync Page (`/sync`)
- Language selector (6 languages)
- Two folder input fields with browse buttons
- Sync strategy selector (keep_both, keep_newest, keep_largest)
- Analyze button
- Execute Sync button (full/admin only)
- Results display with two panels (folder1 vs folder2)
- Progress tracking with status panel
- Error display
- User management button (admin only)
- Reports button (admin only)
- Logout button
- "Logged in as" display

### Reports Page (`/reports`)
- Fully translated interface (uses language from localStorage)
- No language selector (managed from main sync page)
- Tabbed interface: Activities, Space Saved, Operations, Corrupted PDFs
- All buttons, labels, and text translated
- Filters: date ranges, activity types, drive filters
- Statistics cards
- Data tables
- Admin-only access check
- 60-second timeout for all report endpoints
- Optimized corrupted PDFs report (checks database only)

### User Management Modal
- User list table
- Add user form
- Edit user modal
- Delete confirmation
- Self-protection (cannot delete/deactivate self)

### Multi-Language Support
- Languages: en, de, fr, es, it, ru
- All UI elements translated
- Dynamic language switching
- localStorage persistence
- Placeholder support: formatMessage('key', arg1, arg2)

---

## Sync Algorithm

### Analysis Phase
1. Calculate relative paths from base folders
2. Build dictionaries: {relative_path: [documents]}
3. Compare:
   - Files only in folder1 → missing_in_folder2
   - Files only in folder2 → missing_in_folder1
   - Same path + same MD5 → exact match (no action)
   - Same path + different MD5 → duplicate (user decision)
4. Cross-path MD5 matching for renamed files

### Sync Strategies
- **keep_both**: Add suffixes (_copy, _copy2, etc.)
- **keep_newest**: Keep most recent modification date
- **keep_largest**: Keep larger file

### Execution
- Validate paths
- Check file existence and MD5
- Copy files one by one
- Track progress
- Log activities
- Handle errors gracefully

---

## Search Implementation

### Basic Search (`search.py`)
- Search in: name, author, file_path, extracted_text
- Case-insensitive
- Drive filtering

### FTS5 Search (`search_fts5.py`)
- Use FTS5 virtual table
- Phrase matching
- Boolean operators (AND, OR, NOT)
- Fast performance

---

## Duplicate Detection

### Types
1. Same content, different names (same MD5, different filename)
2. Same name, different content (same filename, different MD5)

### Implementation
- Group by MD5 for type 1
- Group by name for type 2
- Return groups for user decision

---

## Configuration (`config.py`)

```python
database_url: str = "sqlite:///docu_sync.db"
max_file_size_mb: int = 100
supported_extensions: list[str] = [".pdf", ".docx", ".txt", ".epub", ".djvu", ".zip", ".doc", ".rar", ".fb2", ".html", ".rtf", ".gif", ".ppt", ".mp3"]
enable_fulltext_search: bool = True
chunk_size: int = 8192
secret_key: str = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"
algorithm: str = "HS256"
access_token_expire_minutes: int = 30
default_username: str = "admin"
default_password: str = "admin"
max_test_files: int = 100
```

---

## CLI Commands

Implement in `cli.py`:
- `scan [--drive D]` - Scan drives
- `list-documents [--drive D]` - List documents
- `search "query" [--no-content]` - Search
- `stats` - Statistics
- `duplicates` - Find duplicates
- `sync --drive1 D --drive2 E [--no-dry-run]` - Sync drives
- `reports activities|space-saved|operations [options]` - Reports

---

## File Formats Supported

PDF, DOCX, DOC, TXT, EPUB, DJVU, ZIP, RAR, FB2, HTML, RTF, GIF, PPT, MP3

---

## Activity Logging

Log all operations:
- File deletions
- File moves/copies
- Sync operations
- User management

Include: type, description, path, space_saved_bytes, operation_count, user_id, timestamp

---

## Error Handling

- 401: Unauthorized (invalid token)
- 403: Forbidden (insufficient permissions)
- 404: Not Found
- 400: Bad Request (invalid input)
- 500: Internal Server Error

Frontend: Try-catch, user-friendly messages, error display

---

## Testing

Create comprehensive tests:
- File scanning
- Search (basic and FTS5)
- Sync operations
- API endpoints
- Authentication
- User management
- Reports
- E2E workflows

Use pytest fixtures for database setup, authenticated clients, temp directories.

---

## Requirements.txt

```
fastapi==0.104.1
uvicorn[standard]==0.24.0
sqlalchemy==2.0.23
pydantic==2.5.0
pydantic-settings==2.1.0
typer==0.9.0
rich==13.7.0
pyyaml==6.0.1
pypdf2==3.0.1
pdfplumber==0.10.3
python-multipart==0.0.6
pytest==7.4.3
pytest-asyncio==0.21.1
pytest-cov==4.1.0
pytest-timeout==2.2.0
httpx==0.25.2
python-docx==1.1.0
ebooklib==0.18
EPubLib==0.1.0
beautifulsoup4==4.12.2
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
bcrypt<4.0.0
jinja2==3.1.2
aiofiles==23.2.1
```

---

## Implementation Guidelines

1. **Code Quality**: Follow PEP 8, use type hints, add docstrings
2. **Error Handling**: Comprehensive try-catch blocks, user-friendly messages
3. **Security**: Validate all inputs, sanitize outputs, secure password handling
4. **Performance**: Use indexes, optimize queries, async where appropriate
5. **UI/UX**: Responsive design, clear error messages, loading states
6. **Testing**: Write tests for all major functionality
7. **Documentation**: Include README with setup instructions

---

## Key Implementation Details

### Default User
- Username: `admin`
- Password: `admin`
- Role: `admin`
- Auto-created on startup if doesn't exist

### Database Initialization
- Create tables on startup
- Initialize FTS5 table and triggers
- Migrate existing databases (add role column if missing)

### File Scanning
- Recursively scan directories
- Extract metadata (name, size, dates, author)
- Calculate MD5 hash
- Extract text content (for supported formats)
- Store in database

### Sync Progress
- Use in-memory PROGRESS_STORE dictionary
- Key: job_id, Value: {status, progress, current_file, etc.}
- Update via background tasks

### Multi-Language
- Store translations in JavaScript object
- Keys: en, de, fr, es, it, ru
- Function: formatMessage(key, ...args) for placeholders
- Update UI elements dynamically

---

## Critical Requirements

1. **All endpoints must be protected** except `/login`
2. **Admin-only endpoints** must use `require_admin` dependency
3. **Sync operations** require `require_full_or_admin`
4. **User management** must prevent self-deletion/deactivation
5. **Inactivity timeout** must be implemented client-side
6. **FTS5 table** must auto-sync via triggers
7. **Default admin user** must be created on startup
8. **All UI elements** must support multi-language
9. **Error handling** must be comprehensive
10. **Progress tracking** must work for long operations

---

## Generation Instructions

1. Generate all files in the specified structure
2. Implement all features as described
3. Include proper error handling and validation
4. Add comprehensive docstrings
5. Ensure code follows PEP 8
6. Include all translations for 6 languages
7. Implement all API endpoints
8. Create complete HTML pages for sync and reports
9. Add CLI commands
10. Include test files with fixtures

---

## Final Checklist

- [ ] All database models implemented
- [ ] All API endpoints implemented
- [ ] Authentication and authorization working
- [ ] Sync algorithm implemented
- [ ] Search (basic and FTS5) working
- [ ] Duplicate detection working
- [ ] User management (admin only) working
- [ ] Reports (admin only) working
- [ ] Multi-language support complete
- [ ] Frontend UI complete
- [ ] CLI commands implemented
- [ ] Tests written
- [ ] Error handling comprehensive
- [ ] Documentation complete

---

**Generate the complete project now, ensuring all features are implemented and the system is fully functional.**

