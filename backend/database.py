
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
        content TEXT,  -- Store pre-tokenized content for FTS
        original_content TEXT, -- Store original content for display
        FOREIGN KEY (space_id) REFERENCES spaces (id) ON DELETE CASCADE
    );
    """)
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_path_space_id ON files (path, space_id);")

    # Create FTS5 virtual table using a standard tokenizer
    cursor.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
        path,
        content,
        content='files',
        content_rowid='id',
        tokenize = 'unicode61 remove_diacritics 0' -- A robust, standard tokenizer
    );
    """)

    # Triggers to keep FTS table synchronized
    cursor.execute("""
    CREATE TRIGGER IF NOT EXISTS files_after_insert
    AFTER INSERT ON files
    BEGIN
        INSERT INTO files_fts(rowid, path, content) VALUES (new.id, new.path, new.content);
    END;
    """)
    cursor.execute("""
    CREATE TRIGGER IF NOT EXISTS files_after_delete
    AFTER DELETE ON files
    BEGIN
        INSERT INTO files_fts(files_fts, rowid, path, content) VALUES ('delete', old.id, old.path, old.content);
    END;
    """)
    cursor.execute("""
    CREATE TRIGGER IF NOT EXISTS files_after_update
    AFTER UPDATE ON files
    BEGIN
        INSERT INTO files_fts(files_fts, rowid, path, content) VALUES ('delete', old.id, old.path, old.content);
        INSERT INTO files_fts(rowid, path, content) VALUES (new.id, new.path, new.content);
    END;
    """)

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
