
import sqlite3
import os
from backend.config import config

# No longer need a custom tokenizer class

def init_db():
    db_path = config.get('DB_PATH')
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create spaces table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS spaces (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        position INTEGER,
        status TEXT NOT NULL DEFAULT 'idle',
        last_indexed_at REAL,
        total_files_to_process INTEGER DEFAULT 0,
        processed_files_count INTEGER DEFAULT 0,
        scanned_files_count INTEGER DEFAULT 0,
        failed_files_count INTEGER DEFAULT 0
    );
    """)

    # Create space_paths table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS space_paths (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        space_id INTEGER NOT NULL,
        path TEXT NOT NULL UNIQUE,
        FOREIGN KEY (space_id) REFERENCES spaces (id) ON DELETE CASCADE
    );
    """)

    # Create files table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT NOT NULL,
        last_modified REAL NOT NULL,
        size INTEGER NOT NULL,
        md5 TEXT NOT NULL,
        space_id INTEGER NOT NULL,
        FOREIGN KEY (space_id) REFERENCES spaces (id) ON DELETE CASCADE
    );
    """)
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_path_space_id ON files (path, space_id);")

    # Create chunks table for text and embeddings
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER NOT NULL,
        chunk_text TEXT NOT NULL,
        embedding BLOB NOT NULL,
        FOREIGN KEY (file_id) REFERENCES files (id) ON DELETE CASCADE
    );
    """)

    # Create FTS5 table for keyword search on chunks
    cursor.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
        chunk_text,
        content='chunks',
        content_rowid='id'
    );
    """);

    # Triggers to keep FTS table in sync
    cursor.execute("""
    CREATE TRIGGER IF NOT EXISTS chunks_after_insert AFTER INSERT ON chunks
    BEGIN
        INSERT INTO chunks_fts(rowid, chunk_text) VALUES (new.id, new.chunk_text);
    END;
    """);
    cursor.execute("""
    CREATE TRIGGER IF NOT EXISTS chunks_after_delete AFTER DELETE ON chunks
    BEGIN
        DELETE FROM chunks_fts WHERE rowid=old.id;
    END;
    """);
    cursor.execute("""
    CREATE TRIGGER IF NOT EXISTS chunks_after_update AFTER UPDATE ON chunks
    BEGIN
        UPDATE chunks_fts SET chunk_text = new.chunk_text WHERE rowid=old.id;
    END;
    """);

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
