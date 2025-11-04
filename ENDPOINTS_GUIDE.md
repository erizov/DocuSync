# DocuSync - Endpoints & Frontend Guide

## Starting the Server

Start the FastAPI server:

```bash
uvicorn app.main:app --reload
```

The server will start at `http://localhost:8000`

## Frontend Pages

### 1. Login Page
**URL:** http://localhost:8000/login

- Default credentials:
  - Username: `admin`
  - Password: `admin`
- After login, token is saved in browser localStorage
- Automatically redirects to `/docs` after successful login

### 2. Sync Interface
**URL:** http://localhost:8000/sync

- Two-panel interface for folder synchronization
- Requires authentication (token from login page)
- Features:
  - Compare files between two folders/drives
  - Choose sync strategy (Keep Both, Keep Newest, Keep Largest)
  - Analyze before syncing
  - Execute sync operations

### 3. API Documentation (Swagger UI)
**URL:** http://localhost:8000/docs

- Interactive API documentation
- Test endpoints directly from browser
- Includes authentication support

### 4. Alternative API Docs (ReDoc)
**URL:** http://localhost:8000/redoc

- Alternative documentation interface

## Checking Endpoints

### Method 1: Using Browser

1. **Root endpoint:**
   ```
   http://localhost:8000/
   ```

2. **API Documentation (interactive):**
   ```
   http://localhost:8000/docs
   ```
   - Click "Try it out" on any endpoint
   - Enter parameters
   - Click "Execute"

### Method 2: Using curl (Command Line)

#### 1. Get Access Token (Login)

```bash
curl -X POST "http://localhost:8000/api/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin"
```

Response:
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "token_type": "bearer"
}
```

Save the token for subsequent requests.

#### 2. Search Documents

```bash
curl -X GET "http://localhost:8000/api/search?q=machine%20learning" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

With filters:
```bash
curl -X GET "http://localhost:8000/api/search?q=python&drive=D&search_content=true" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

#### 3. List Documents

```bash
curl -X GET "http://localhost:8000/api/documents?drive=D&limit=10" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

#### 4. Get Statistics

```bash
curl -X GET "http://localhost:8000/api/stats" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

#### 5. Find Duplicates

```bash
curl -X GET "http://localhost:8000/api/duplicates?duplicate_type=all" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

#### 6. Get Reports

Activities:
```bash
curl -X GET "http://localhost:8000/api/reports/activities" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

Space saved:
```bash
curl -X GET "http://localhost:8000/api/reports/space-saved?start_date=2024-01-01" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

#### 7. Sync Analysis

```bash
curl -X POST "http://localhost:8000/api/sync/analyze" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "folder1": "C:\\folder1",
    "folder2": "D:\\folder2"
  }'
```

#### 8. Execute Sync

```bash
curl -X POST "http://localhost:8000/api/sync/execute" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "folder1": "C:\\folder1",
    "folder2": "D:\\folder2",
    "strategy": "keep_newest",
    "dry_run": true
  }'
```

### Method 3: Using Python requests

```python
import requests

BASE_URL = "http://localhost:8000"

# 1. Login
response = requests.post(
    f"{BASE_URL}/api/auth/login",
    data={"username": "admin", "password": "admin"}
)
token = response.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# 2. Search
response = requests.get(
    f"{BASE_URL}/api/search",
    params={"q": "machine learning", "drive": "D"},
    headers=headers
)
print(response.json())

# 3. Get stats
response = requests.get(
    f"{BASE_URL}/api/stats",
    headers=headers
)
print(response.json())

# 4. List documents
response = requests.get(
    f"{BASE_URL}/api/documents",
    params={"drive": "D", "limit": 10},
    headers=headers
)
print(response.json())
```

### Method 4: Using HTTPie

Install HTTPie:
```bash
pip install httpie
```

Examples:

```bash
# Login
http POST localhost:8000/api/auth/login username=admin password=admin

# Search (with token from login)
http GET localhost:8000/api/search q=="machine learning" \
  "Authorization:Bearer YOUR_TOKEN_HERE"

# Get stats
http GET localhost:8000/api/stats \
  "Authorization:Bearer YOUR_TOKEN_HERE"
```

## Complete Endpoint List

### Public Endpoints (No Authentication)

- `GET /` - Root endpoint with API info
- `GET /login` - Login page (HTML)
- `POST /api/auth/login` - Login endpoint

### Protected Endpoints (Require Authentication)

#### Search
- `GET /api/search` - General search
  - Query params: `q`, `drive`, `search_content`, `use_fts5`
- `GET /api/search/phrase` - Phrase search (FTS5)
  - Query params: `q`, `drive`
- `GET /api/search/boolean` - Boolean search (FTS5)
  - Query params: `q`, `drive`
  - Example: `q=machine AND learning`

#### Documents
- `GET /api/documents` - List documents
  - Query params: `drive`, `directory`, `skip`, `limit`

#### Statistics
- `GET /api/stats` - Get document statistics

#### Duplicates
- `GET /api/duplicates` - Find duplicates
  - Query params: `duplicate_type` (content/name/all)

#### Reports
- `GET /api/reports/activities` - Activity report
  - Query params: `activity_type`, `limit`
- `GET /api/reports/space-saved` - Space saved report
  - Query params: `start_date`, `end_date`
- `GET /api/reports/operations` - Operations report
  - Query params: `start_date`, `end_date`
- `GET /api/reports/corrupted-pdfs` - Corrupted PDFs report
  - Query params: `drive`

#### Corrupted PDFs
- `DELETE /api/corrupted-pdfs/{file_id}` - Remove corrupted PDF
- `POST /api/corrupted-pdfs/remove-all` - Remove all corrupted PDFs
  - Query params: `drive`

#### Sync
- `POST /api/sync/analyze` - Analyze sync requirements
  - Body: `SyncAnalysisRequest` (folder1, folder2, drive1, drive2)
- `POST /api/sync/execute` - Execute sync
  - Body: `SyncRequest` (folder1, folder2, strategy, dry_run, etc.)

#### Frontend Pages
- `GET /sync` - Sync interface (HTML, requires auth token)

## Quick Test Script

Create a file `test_endpoints.py`:

```python
"""Quick test script for endpoints."""

import requests

BASE_URL = "http://localhost:8000"

def test_endpoints():
    """Test all endpoints."""
    print("1. Testing login...")
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        data={"username": "admin", "password": "admin"}
    )
    if response.status_code != 200:
        print(f"Login failed: {response.status_code}")
        return
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("✓ Login successful")
    
    print("\n2. Testing root endpoint...")
    response = requests.get(f"{BASE_URL}/")
    print(f"✓ Root: {response.json()}")
    
    print("\n3. Testing search...")
    response = requests.get(
        f"{BASE_URL}/api/search",
        params={"q": "test"},
        headers=headers
    )
    print(f"✓ Search: {len(response.json())} results")
    
    print("\n4. Testing stats...")
    response = requests.get(
        f"{BASE_URL}/api/stats",
        headers=headers
    )
    print(f"✓ Stats: {response.json()}")
    
    print("\n5. Testing documents list...")
    response = requests.get(
        f"{BASE_URL}/api/documents",
        params={"limit": 5},
        headers=headers
    )
    print(f"✓ Documents: {len(response.json())} results")
    
    print("\nAll tests completed!")

if __name__ == "__main__":
    test_endpoints()
```

Run it:
```bash
python test_endpoints.py
```

## Troubleshooting

### Authentication Errors

If you get `401 Unauthorized`:
1. Make sure you're including the `Authorization` header
2. Check that the token is valid (not expired)
3. Re-login to get a new token

### Server Not Starting

1. Check if port 8000 is already in use:
   ```bash
   netstat -ano | findstr :8000
   ```
2. Use a different port:
   ```bash
   uvicorn app.main:app --reload --port 8001
   ```

### CORS Issues

If accessing from a different origin, you may need to configure CORS in `app/main.py`.

## Frontend Workflow

1. **Start server:**
   ```bash
   uvicorn app.main:app --reload
   ```

2. **Open browser:**
   - Go to http://localhost:8000/login
   - Login with `admin`/`admin`

3. **Access sync interface:**
   - Go to http://localhost:8000/sync
   - Enter two folder paths
   - Click "Analyze"
   - Review results
   - Click "Execute Sync" to perform sync

4. **Explore API:**
   - Go to http://localhost:8000/docs
   - Try endpoints interactively

