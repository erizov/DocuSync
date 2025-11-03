# DocuSync

**Simple, Robust Document Synchronization and Search Tool**

DocuSync is a powerful yet simple document management system that helps you organize, synchronize, and search through your document collection across multiple drives. Whether you have PDFs scattered across different drives or need to find a specific document quickly, DocuSync makes it easy.

## Features

### 📚 Document Discovery
- **Multi-Drive Scanning**: Automatically scan all drives or specific drives for documents
- **Multiple Formats**: Support for PDF, DOCX, TXT, and EPUB files
- **Metadata Extraction**: Captures document name, path, author, size, creation date, and more
- **MD5 Hash Calculation**: Unique identification for duplicate detection

### 🔍 Powerful Search
- **Full-Text Search**: Search inside document contents (PDFs, DOCX, TXT, EPUB)
- **Metadata Search**: Find documents by name, author, or file path
- **Drive Filtering**: Narrow search results to specific drives
- **Fast Database Queries**: Optimized SQLite database for instant results

### 🔄 Duplicate Detection & Management
- **Automatic Duplicate Detection**: Identifies duplicate files by MD5 hash
- **Space Savings Analysis**: See how much space you'll save before deleting
- **Smart Deletion**: Choose preferred location to keep files, delete the rest
- **Safe Operation**: Preview before deleting

### 📁 Drive Synchronization
- **Bidirectional Sync**: Synchronize files between any two drives
- **Space Analysis**: Know exactly how much space you need on each drive
- **Smart Copying**: Preserves directory structure and verifies file integrity
- **Dry-Run Mode**: Preview sync operations before executing

### 🗄️ Database Storage
- **SQLite Database**: Fast, local, no server required
- **Indexed Queries**: Optimized indexes for quick searches
- **Text Content Storage**: Optional storage of extracted text for faster searching
- **Metadata Preservation**: All document information in one place

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

Find and manage duplicate files:
```bash
python -m app.cli duplicates
```

### 5. Synchronize Drives

Sync files between two drives (dry-run):
```bash
python -m app.cli sync --drive1 D --drive2 E
```

Actually sync (be careful!):
```bash
python -m app.cli sync --drive1 D --drive2 E --no-dry-run
```

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
- API Documentation: http://localhost:8000/docs
- Search: `GET /api/search?q=query`
- List Documents: `GET /api/documents`
- Statistics: `GET /api/stats`
- Duplicates: `GET /api/duplicates`

## Project Structure

```
DocSync/
├── app/
│   ├── __init__.py          # Package initialization
│   ├── config.py            # Configuration settings
│   ├── database.py          # Database models and setup
│   ├── file_scanner.py      # File system scanning
│   ├── search.py            # Search functionality
│   ├── sync.py              # Drive synchronization
│   ├── cli.py               # Command-line interface
│   └── main.py              # FastAPI application
├── tests/                   # Test suite
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

With coverage:
```bash
pytest --cov=app --cov-report=html
```

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

2. **Database Size**: The extracted text can make the database large. Consider using content search only when needed.

3. **Incremental Scanning**: Only scan new drives or re-scan when files change.

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

