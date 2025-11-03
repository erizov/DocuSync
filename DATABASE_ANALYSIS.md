# Database Design Analysis and Recommendations

## 1. Text Splitting: First 8KB in Main Table vs Separate Table

### Current Implementation
- All extracted text stored in single `extracted_text` column (Text type)
- SQLite handles large text fields efficiently
- Simple query pattern with `LIKE` or `contains()` operations

### Proposed: Split Text (8KB preview + separate table)

#### ✅ **Pros:**
1. **Faster Queries**: Main table stays smaller, faster to load metadata
2. **Preview Snippets**: Can show first 8KB without loading full text
3. **Better Indexing**: Smaller fields can be indexed more efficiently
4. **Reduced Memory**: Don't load full text when browsing documents

#### ❌ **Cons:**
1. **Additional JOIN**: Every search requires joining two tables
2. **Complexity**: More complex queries, potential for bugs
3. **SQLite Limitations**: SQLite doesn't have great full-text search without FTS5
4. **Performance Overhead**: JOIN overhead might negate benefits
5. **Maintenance**: Two tables to keep in sync

### 💡 **Recommendation: NOT RECOMMENDED for SQLite**

**Reason**: SQLite with current approach is fine for most use cases. The split would add complexity without significant benefit unless you:
- Have millions of documents
- Need sub-second search on very large text fields
- Want to implement pagination of search results

**Better Alternative**: Use SQLite FTS5 (Full-Text Search) virtual table instead.

---

## 2. Database Options for Search Performance

### Current: SQLite with LIKE/contains()

**Performance**: ⭐⭐⭐ (Good for <100K documents)
- Simple setup, no server required
- Adequate for small to medium collections
- Current implementation uses `LIKE` which scans full text

### Option A: SQLite with FTS5 (Recommended Upgrade)

**Performance**: ⭐⭐⭐⭐ (Good for <500K documents)

**Pros:**
- Built into SQLite, no additional dependencies
- Fast full-text search with ranking
- Supports boolean operators, phrase matching
- No server required (stays local)
- Can implement alongside current schema

**Cons:**
- Still SQLite limitations (single writer)
- Virtual table requires separate FTS table
- Need to sync between main table and FTS table

**Implementation Effort**: Medium (2-3 days)
**Performance Gain**: 10-50x faster searches

**Example Query:**
```sql
SELECT * FROM documents_fts 
WHERE documents_fts MATCH 'machine learning'
ORDER BY rank;
```

### Option B: PostgreSQL with pg_trgm/GIN

**Performance**: ⭐⭐⭐⭐⭐ (Excellent for millions of documents)

**Pros:**
- Excellent full-text search with GIN indexes
- Trigram similarity search (fuzzy matching)
- Concurrent read/write
- Advanced features (facets, aggregations)
- Better for production environments

**Cons:**
- Requires PostgreSQL server setup
- More complex deployment
- Not "zero-config" like SQLite

**Implementation Effort**: High (1 week)
**Performance Gain**: 50-500x faster searches

**Example Query:**
```sql
SELECT * FROM documents 
WHERE to_tsvector('english', extracted_text) 
      @@ to_tsquery('english', 'machine & learning');
```

### Option C: MongoDB with Text Indexes

**Performance**: ⭐⭐⭐⭐ (Good for document-oriented data)

**Pros:**
- Native document storage (good fit for metadata + text)
- Built-in text search
- Good for unstructured data
- Horizontal scaling possible

**Cons:**
- Requires MongoDB server
- Different query language
- More complex setup
- Overkill for structured metadata

**Implementation Effort**: High (1 week)
**Performance Gain**: 20-100x faster searches

**Example Query:**
```javascript
db.documents.find({$text: {$search: "machine learning"}})
```

### Option D: Elasticsearch (Separate Search Engine)

**Performance**: ⭐⭐⭐⭐⭐ (Best for very large datasets)

**Pros:**
- Best-in-class full-text search
- Advanced features (fuzzy, faceting, highlighting)
- Excellent for large-scale deployments
- Real-time search capabilities

**Cons:**
- Separate service to maintain
- High memory requirements
- Complex setup and configuration
- Overkill for most users

**Implementation Effort**: Very High (2 weeks)
**Performance Gain**: 100-1000x faster searches

---

## 3. Recommended Approach

### **Phase 1: Immediate (Current Setup)**
✅ Keep current SQLite implementation
- Add FTS5 virtual table for full-text search
- Split: First 8KB in main table for previews (optional, low priority)
- Rest of text in FTS5 table for search

### **Phase 2: If Needed (Performance Issues)**
🔄 Migrate to PostgreSQL
- When collection exceeds 100K documents
- When multiple concurrent users
- When need advanced search features

### **Phase 3: Enterprise (If Required)**
🚀 Add Elasticsearch
- When collection exceeds 1M documents
- When need advanced analytics
- When need distributed search

---

## 4. Hybrid Approach: Best of Both Worlds

### Recommended Schema Design:

```python
class Document(Base):
    # ... existing fields ...
    extracted_text_preview = Column(String(8192), nullable=True)  # First 8KB
    # ... rest of fields ...

class DocumentFullText(Base):
    """FTS5 virtual table for full-text search"""
    __tablename__ = "documents_fts"
    
    rowid = Column(Integer, primary_key=True)
    doc_id = Column(Integer, ForeignKey("documents.id"))
    full_text = Column(Text)  # Full extracted text
    
    # FTS5 automatically creates search indexes
```

### Benefits:
1. **Fast Metadata Queries**: Main table stays small
2. **Preview Support**: First 8KB readily available
3. **Fast Search**: FTS5 handles full-text efficiently
4. **Flexibility**: Can upgrade to PostgreSQL later

### Implementation Strategy:
1. Keep current schema for compatibility
2. Add FTS5 table for search
3. Optionally add preview column
4. Sync data between tables on insert/update

---

## 5. Performance Comparison

| Approach | Setup Complexity | Query Speed | Scalability | Recommendation |
|----------|-----------------|-------------|-------------|----------------|
| Current SQLite | ⭐ Low | ⭐⭐ 1x | ⭐⭐ <100K docs | ✅ Good for now |
| SQLite + FTS5 | ⭐⭐ Medium | ⭐⭐⭐⭐ 10-50x | ⭐⭐⭐ <500K docs | ✅ **Best upgrade** |
| PostgreSQL | ⭐⭐⭐ High | ⭐⭐⭐⭐⭐ 50-500x | ⭐⭐⭐⭐⭐ Millions | ✅ If needed |
| MongoDB | ⭐⭐⭐ High | ⭐⭐⭐⭐ 20-100x | ⭐⭐⭐⭐ Millions | ⚠️ Overkill |
| Elasticsearch | ⭐⭐⭐⭐ Very High | ⭐⭐⭐⭐⭐ 100-1000x | ⭐⭐⭐⭐⭐ Very Large | ⚠️ Enterprise only |

---

## 6. Final Recommendation

### ✅ **DO: Implement SQLite FTS5**
- Best performance gain for effort
- No server required
- Maintains simplicity
- Can show previews from main table
- Full text in FTS5 for search

### ⚠️ **CONSIDER: Text Splitting (Low Priority)**
- Only if you need preview snippets
- Add preview column, keep full text in FTS5
- Don't create separate table for rest of text

### ❌ **DON'T: Switch to NoSQL Yet**
- Wait until you hit performance limits
- Current SQLite approach is fine for most users
- PostgreSQL is better upgrade path than MongoDB

### 📊 **Migration Path:**
1. **Now**: SQLite (current)
2. **Next**: SQLite + FTS5 (easy upgrade)
3. **Future**: PostgreSQL (if needed)
4. **Enterprise**: Elasticsearch (if scale requires)

---

## 7. Code Example: SQLite FTS5 Implementation

```python
# In database.py
from sqlalchemy import event

class DocumentFTS(Base):
    """FTS5 virtual table for full-text search"""
    __tablename__ = "documents_fts"
    
    rowid = Column(Integer, primary_key=True)
    doc_id = Column(Integer)
    full_text = Column(Text)
    
    # FTS5 syntax for virtual table
    __table_args__ = (
        {'sqlite_autoincrement': True},
    )

# Create FTS5 table
def init_fts5():
    """Initialize FTS5 virtual table"""
    engine = create_engine(settings.database_url)
    with engine.connect() as conn:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts 
            USING fts5(doc_id, full_text);
        """)
        conn.commit()

# Search function
def search_with_fts5(query: str):
    """Search using FTS5"""
    db = SessionLocal()
    try:
        # FTS5 search with ranking
        results = db.execute("""
            SELECT d.*, rank 
            FROM documents d
            JOIN documents_fts fts ON d.id = fts.doc_id
            WHERE documents_fts MATCH :query
            ORDER BY rank
            LIMIT 100
        """, {"query": query})
        return results.fetchall()
    finally:
        db.close()
```

---

## Summary

**Your Text Splitting Idea**: ⚠️ **Partially Good**
- ✅ First 8KB for previews: Good idea
- ❌ Separate table for rest: Unnecessary complexity
- ✅ Better: Use FTS5 for full text search

**Database Upgrade**: ✅ **SQLite FTS5 First**
- Best performance/effort ratio
- No server required
- Maintains simplicity
- Can upgrade to PostgreSQL later if needed

