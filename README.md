# DocuSync

**Simple, Robust Document Synchronization and Search Tool**

DocuSync is a powerful yet simple document management system that helps you organize, synchronize, and search through your document collection across multiple drives. Whether you have PDFs scattered across different drives or need to find a specific document quickly, DocuSync makes it easy.

## Features

### 📚 Document Discovery
- **Multi-Drive Scanning**: Automatically scan all drives or specific drives for documents
- **Multiple Formats**: Support for PDF, DOCX, TXT, EPUB, DJVU, ZIP, DOC, RAR, FB2, HTML, RTF, GIF, PPT, and MP3 files
- **Metadata Extraction**: Captures document name, path, author, size, creation date, and more
- **MD5 Hash Calculation**: Unique identification for duplicate detection

### 🔍 Powerful Search
- **Full-Text Search**: Search inside document contents (PDFs, DOCX, TXT, EPUB)
- **Metadata Search**: Find documents by name, author, or file path
- **Drive Filtering**: Narrow search results to specific drives
- **Fast Database Queries**: Optimized SQLite database for instant results

### 🔄 Duplicate Detection & Management
- **Two Types of Duplicate Detection**:
  1. **Same Content, Different Names**: Identifies files with identical content (same MD5 hash) but different filenames
  2. **Same Name, Different Content**: Identifies files with the same name but different content (different MD5 hash)
- **Interactive Selection**: For each duplicate group, choose which file to keep
- **Space Savings Analysis**: See how much space you'll save before deleting
- **Smart Deletion**: Preview all duplicates and decide which to keep
- **Safe Operation**: Preview before deleting, with confirmation prompts

### 📁 Drive & Folder Synchronization
- **Bidirectional Sync**: Synchronize files between any two drives or folders
- **Web-Based Sync Interface**: Visual two-panel interface for comparing and syncing
- **Smart Sync Strategies**: Choose how to handle conflicts:
  - **Keep Both**: Preserve both versions with suffixes
  - **Keep Newest**: Automatically keep the most recently modified file
  - **Keep Largest**: Keep the file with the larger size
- **Space Analysis**: Know exactly how much space you need on each drive/folder
- **Smart Copying**: Preserves directory structure and verifies file integrity
- **Duplicate Detection**: Identifies files with same name but different content
- **Dry-Run Mode**: Preview sync operations before executing
- **Path Mapping**: Specify custom target folders when exact paths don't exist
- **Tree Structure Preservation**: Maintains subfolder hierarchy when syncing (e.g., `sub1\sub2\file.pdf` in folder1 matches `sub1\sub2\file.pdf` in folder2)

### 👥 User Management & Security
- **Role-Based Access Control**: Three user roles (readonly, full, admin)
- **User Management Interface**: Admin can create, edit, and delete users
- **Password Management**: Change user passwords and manage accounts
- **Session Management**: 
  - Automatic logout after 1 hour of inactivity
  - Manual logout button in header
  - Secure token-based authentication
- **Activity Tracking**: Monitors user activity to enforce inactivity timeout

### 🌍 Multi-Language Support
- **6 Languages Supported**: English, German, French, Spanish, Italian, Russian
- **Dynamic Language Switching**: Change language on-the-fly without page reload
- **Fully Translated Interface**: All UI elements, buttons, messages, and forms
- **Language Persistence**: Selected language is saved in browser storage
- **Auto-Detection**: Automatically detects browser language on first visit

### 🗄️ Database Storage
- **SQLite Database**: Fast, local, no server required
- **Indexed Queries**: Optimized indexes for quick searches
- **Text Content Storage**: Optional storage of extracted text for faster searching
- **Metadata Preservation**: All document information in one place

## File Comparison Algorithm

DocuSync uses a sophisticated multi-phase algorithm to compare files between two folders while preserving the folder tree structure:

### Phase 1: Grouping by Relative Path

1. **Calculate Relative Paths**: For each file, compute its relative path from the base folder
   - Example: `D:\books\sub1\sub2\file.pdf` → relative path: `sub1\sub2\file.pdf`
   - This preserves the folder tree structure

2. **Build Dictionaries**: Create two dictionaries mapping `{relative_path: [documents]}` for each folder

### Phase 2: Comparison by Relative Path

For each relative path found in either folder, the algorithm determines one of three cases:

#### Case 1: File Exists Only in Folder1
- **Action**: File needs to be copied to folder2
- **Status**: Added to `missing_in_folder2` list
- **Note**: Also checks if the MD5 hash exists elsewhere in folder2 (possible rename)

#### Case 2: File Exists Only in Folder2
- **Action**: File needs to be copied to folder1
- **Status**: Added to `missing_in_folder1` list

#### Case 3: Same Relative Path Exists in Both Folders
- **Step 1**: Group files by MD5 hash within each folder
- **Step 2**: Match pairs by MD5 (same relative path + same MD5 = exact match)
  - These are **exact matches** - no sync needed ✓
- **Step 3**: Collect unmatched files (same relative path, different MD5)
  - These are **partial matches** (duplicates) - user decision needed
  - Example: `sub1\file.pdf` with MD5 `A` in folder1 vs `sub1\file.pdf` with MD5 `B` in folder2

### Phase 3: Cross-Path MD5 Matching (Suspected Duplicates)

- **Purpose**: Detect files with same content but different locations (possible rename/move)
- **Method**: Find files with same MD5 hash but different relative paths
- **Condition**: Only flagged if relative paths don't intersect (different locations)
- **Exclusion**: MD5s already matched by relative path are excluded

### Matching Rules Summary

| Condition | Relative Path | MD5 Hash | Result |
|-----------|--------------|----------|--------|
| ✓ | Same | Same | **Exact Match** - No sync needed |
| ⚠️ | Same | Different | **Partial Match** - Duplicate, needs decision |
| ➕ | Different | Different | **Unique File** - Needs sync |
| 🔍 | Different | Same | **Suspected Duplicate** - Possible rename |

### Example

```
Folder1:                    Folder2:
├─ sub1\file.pdf (MD5: A)   ├─ sub1\file.pdf (MD5: A)  → Exact match ✓
├─ sub1\file.pdf (MD5: B)   ├─ sub1\file.pdf (MD5: C)  → Partial match (duplicate)
├─ sub2\doc.pdf (MD5: D)   └─ sub3\doc.pdf (MD5: D)   → Suspected duplicate
└─ sub3\new.pdf (MD5: E)                                → Unique to folder1
```

### Key Features

- **Tree Structure Preservation**: Files are matched by their relative path within the folder structure, not just filename
- **Subfolder Support**: If `folder1` has `subfolder1\file.pdf`, it compares to `folder2\subfolder1\file.pdf`
- **Display Format**: Shows full relative path like `sub1\sub2\sub3\filename.pdf` (without base folder name)
- **MD5 Verification**: Ensures content integrity when matching files

## Installation

### Prerequisites
- Python 3.9 or higher
- Windows (drive scanning optimized for Windows)

### Setup

1. Clone the repository:
```bash
git clone https://github.com/erizov/DocuSync.git
cd DocSync
```

2. Create a virtual environment:
```bash
python -m venv venv
venv\Scripts\activate  # On Windows
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Quick Start

### 1. Scan Your Drives

Scan all drives for documents:
```bash
python -m app.cli scan
```

Or scan a specific drive:
```bash
python -m app.cli scan --drive D
```

### 2. List Documents

View all indexed documents:
```bash
python -m app.cli list-documents
```

Filter by drive:
```bash
python -m app.cli list-documents --drive D
```

### 3. Search Documents

Search by name, author, or content:
```bash
python -m app.cli search "machine learning"
```

Search only in document names:
```bash
python -m app.cli search "Python" --no-content
```

### 4. Find Duplicates

Find and manage duplicate files (two types):
```bash
python -m app.cli duplicates
```

The tool will:
1. Show a summary of both types of duplicates:
   - Same content, different names (e.g., `document.pdf` and `document_copy.pdf` with same content)
   - Same name, different content (e.g., `report.pdf` with different versions)
2. Ask which type you want to handle (or both)
3. For each duplicate group, ask which file you want to keep
4. Delete the others and show space saved

### 5. Synchronize Drives or Folders

**Command Line:**
Sync files between two drives (dry-run):
```bash
python -m app.cli sync --drive1 D --drive2 E
```

Actually sync (be careful!):
```bash
python -m app.cli sync --drive1 D --drive2 E --no-dry-run
```

**Web Interface:**
1. Start the server:
```bash
uvicorn app.main:app --reload
```

2. Navigate to: http://localhost:8000/sync

3. Enter two folders or drives (e.g., `C:\folder1` or just `C` for a drive)

4. Choose a sync strategy:
   - **Keep Both**: Preserve both versions when conflicts occur
   - **Keep Newest**: Automatically keep the most recent file
   - **Keep Largest**: Keep the larger file

5. Click "Analyze" to preview what will be synced

6. Click "Execute Sync" to perform the synchronization

### 6. View Statistics

Get overview of your document collection:
```bash
python -m app.cli stats
```

## API Usage

Start the FastAPI server:
```bash
uvicorn app.main:app --reload
```

Then access:
- **Web Interface**: http://localhost:8000/sync (folder sync interface)
- **API Documentation**: http://localhost:8000/docs
- **Login Page**: http://localhost:8000/login

**Web Interface Features:**
- Multi-language support (English, German, French, Spanish, Italian, Russian)
- User management (admin only)
- Logout functionality
- Automatic inactivity timeout (1 hour)
- Role-based UI visibility

### API Endpoints

**Document Operations:**
- **Search**: `GET /api/search?q=query`
- **List Documents**: `GET /api/documents`
- **Statistics**: `GET /api/stats`
- **Duplicates**: `GET /api/duplicates`
- **Sync Analysis**: `POST /api/sync/analyze` (analyze sync requirements)
- **Sync Execute**: `POST /api/sync/execute` (perform sync operation)

**User Management (Admin only):**
- **List Users**: `GET /api/users`
- **Create User**: `POST /api/users`
- **Update User**: `PUT /api/users/{user_id}`
- **Delete User**: `DELETE /api/users/{user_id}`

**Authentication:**
- **Login**: `POST /api/auth/login`

### Authentication & User Management

**Default Credentials:**
- Username: `admin`
- Password: `admin`

**User Roles:**
- **readonly**: Can view and search documents, but cannot modify or sync
- **full**: Can view, search, and perform sync operations
- **admin**: Full access including user management

**Features:**
- JWT token-based authentication
- Role-based access control (readonly, full, admin)
- User management interface (admin only)
  - Create, edit, and delete users
  - Assign roles and manage active status
  - Change passwords
- Automatic logout after 1 hour of inactivity
- Logout button in the header

All API endpoints (except `/login`) require authentication via JWT token.

## Project Structure

```
DocSync/
├── app/
│   ├── __init__.py          # Package initialization
│   ├── config.py            # Configuration settings
│   ├── database.py          # Database models and setup
│   ├── file_scanner.py      # File system scanning
│   ├── search.py            # Search functionality
│   ├── search_fts5.py       # FTS5 full-text search
│   ├── sync.py              # Drive & folder synchronization
│   ├── cli.py               # Command-line interface
│   ├── cli_reports.py       # CLI report commands
│   ├── auth.py              # Authentication utilities
│   ├── reports.py           # Activity reporting
│   ├── corrupted_pdf.py     # Corrupted PDF detection
│   ├── migrate_db.py        # Database migration script
│   └── main.py              # FastAPI application
├── tests/                   # Test suite
│   ├── test_file_scanner.py
│   ├── test_search.py
│   ├── test_search_fts5.py
│   ├── test_sync_frontend.py
│   ├── test_endpoints.py
│   └── ...
├── requirements.txt         # Python dependencies
├── pyproject.toml          # Project configuration
└── README.md               # This file
```

## Database Schema

Documents are stored in a SQLite database with the following schema:

- **id**: Primary key
- **name**: Document name (indexed)
- **file_path**: Full file path (unique, indexed)
- **drive**: Drive letter (indexed)
- **directory**: Directory path (indexed)
- **author**: Document author
- **size**: File size in bytes
- **size_on_disc**: Size on disk
- **date_created**: Creation timestamp
- **date_published**: Publication date (from metadata)
- **md5_hash**: MD5 hash (indexed)
- **file_type**: File extension (indexed)
- **extracted_text**: Extracted text content (optional)
- **is_duplicate**: Duplicate flag
- **preferred_location**: Preferred location flag

## Testing

Run the test suite:
```bash
pytest -v
```

Run specific test categories:
```bash
pytest tests/test_sync_frontend.py -v  # Sync frontend tests
pytest tests/test_search_fts5.py -v    # FTS5 search tests
pytest tests/test_endpoints.py -v      # API endpoint tests
```

With coverage:
```bash
pytest --cov=app --cov-report=html
```

**Note**: Tests are configured to limit file operations to 100 files maximum and have a 30-minute timeout (whichever comes first) for performance. File operations (move/sync) are automatically reverted after tests complete.

## Configuration

Create a `.env` file to customize settings:
```
DATABASE_URL=sqlite:///docu_sync.db
MAX_FILE_SIZE_MB=100
ENABLE_FULLTEXT_SEARCH=true
```

## Performance Tips

1. **Text Extraction**: Disable text extraction for faster initial scanning:
   ```bash
   python -m app.cli scan --no-extract-text
   ```

2. **Database Size**: The extracted text can make the database large. First 8KB is stored in main table for previews, full text in FTS5 for fast search.

3. **Incremental Scanning**: Only scan new drives or re-scan when files change.

4. **FTS5 Search**: Full-text search uses SQLite FTS5 for 10-50x faster searches. Boolean operators (AND, OR, NOT) and phrase matching are supported.

## Migration

If you have an existing database, run the migration script to add the preview column and initialize FTS5:

```bash
python app/migrate_db.py
```

## Security Notes

- DocuSync only reads and copies files; it never modifies original documents
- Deletion operations require explicit confirmation
- MD5 verification ensures copied files are identical to originals
- All operations are logged for transparency

## Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes following PEP 8 style guide
4. Add tests for new functionality
5. Submit a pull request

## License

This project is open source and available under the MIT License.

## Author

Developed with simplicity and robustness in mind.

## Support

For issues and questions, please open an issue on GitHub:
https://github.com/erizov/DocuSync/issues

---

**Simple. Robust. Powerful.** That's DocuSync.

