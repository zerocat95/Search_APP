
import sqlite3
import threading
import os
import logging
from backend.config import config

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        self.db_path = config.get('DB_PATH')
        self._local = threading.local()
        self._pid = os.getpid()
        self._lock = threading.Lock()
        self._write_queue_count = 0
        self._write_queue_lock = threading.Lock()

    def _get_connection(self):
        """
        Provides a database connection that is safe for both multi-threading and
        multi-processing. It stores the connection in thread-local storage
        and re-initializes it if the process has forked.
        """
        current_pid = os.getpid()
        if self._pid != current_pid:
            with self._lock:
                # Double-check after acquiring the lock to prevent race conditions
                if self._pid != current_pid:
                    logger.info(f"Process fork detected. Re-initializing DB state for new PID: {current_pid} (parent was {self._pid})")
                    self._local = threading.local()  # Reset thread-local storage for the new process
                    self._pid = current_pid
        
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            try:
                # This part is thread-safe because self._local is a threading.local()
                # check_same_thread=False is crucial for use with thread pools like in FastAPI
                self._local.conn = sqlite3.connect(self.db_path, timeout=20.0, check_same_thread=False)
                self._local.conn.row_factory = sqlite3.Row
                self._local.conn.execute("PRAGMA journal_mode=WAL")
                self._local.conn.execute("PRAGMA foreign_keys = ON")
                logger.info(f"New DB connection created for process {os.getpid()} thread {threading.get_ident()}")
            except Exception as e:
                logger.error(f"Failed to create DB connection for process {os.getpid()}: {e}")
                self._local.conn = None
        
        return self._local.conn

    def execute_write(self, query, params=()):
        conn = self._get_connection()
        if not conn:
            raise Exception("Database connection is not available.")
        
        try:
            cursor = conn.cursor()
            cursor = conn.cursor()
            # Support for executemany for batch operations
            if isinstance(params, list) and params and isinstance(params[0], tuple):
                cursor.executemany(query, params)
            else:
                cursor.execute(query, params)
            conn.commit()
            return cursor.lastrowid
        except sqlite3.Error as e:
            logger.error(f"DB Write Error: {e} in process {os.getpid()}. Query: {query}")
            if conn:
                conn.rollback()
            raise e

    def execute_read(self, query, params=()):
        conn = self._get_connection()
        if not conn:
            raise Exception("Database connection is not available.")
            
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()
        except sqlite3.Error as e:
            logger.error(f"DB Read Error: {e} in process {os.getpid()}. Query: {query}")
            raise e
    
    def get_queue_size(self):
        """Returns the number of items in the database write queue."""
        with self._write_queue_lock:
            return self._write_queue_count
    
    def increment_write_queue(self, count=1):
        """Increments the database write queue counter."""
        with self._write_queue_lock:
            self._write_queue_count += count
    
    def decrement_write_queue(self, count=1):
        """Decrements the database write queue counter."""
        with self._write_queue_lock:
            self._write_queue_count = max(0, self._write_queue_count - count)
    
    def reset_write_queue(self):
        """Resets the database write queue counter to zero."""
        with self._write_queue_lock:
            self._write_queue_count = 0

    def create_tables(self):
        """Creates or updates the necessary database tables."""
        conn = self._get_connection()
        if not conn:
            logger.error("Cannot create tables, DB connection is not available.")
            return

        try:
            cursor = conn.cursor()
            
            # Files table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                last_modified REAL NOT NULL,
                size INTEGER NOT NULL,
                md5 TEXT NOT NULL,
                space_id INTEGER NOT NULL,
                FOREIGN KEY (space_id) REFERENCES spaces (id) ON DELETE CASCADE
            );
            """)

            # Chunks table for text and embeddings
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER NOT NULL,
                chunk_text TEXT NOT NULL,
                embedding BLOB NOT NULL,
                FOREIGN KEY (file_id) REFERENCES files (id) ON DELETE CASCADE
            );
            """)

            # FTS5 table for keyword search on chunks
            cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                chunk_text,
                content='chunks',
                content_rowid='id'
            );
            """)

            # Triggers to keep FTS table in sync
            cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS chunks_after_insert AFTER INSERT ON chunks
            BEGIN
                INSERT INTO chunks_fts(rowid, chunk_text) VALUES (new.id, new.chunk_text);
            END;
            """)
            cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS chunks_after_delete AFTER DELETE ON chunks
            BEGIN
                DELETE FROM chunks_fts WHERE rowid=old.id;
            END;
            """)
            cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS chunks_after_update AFTER UPDATE ON chunks
            BEGIN
                UPDATE chunks_fts SET chunk_text = new.chunk_text WHERE rowid=old.id;
            END;
            """)

            conn.commit()
            logger.info("Database tables created or verified successfully.")
        except Exception as e:
            logger.error(f"Error creating tables: {e}")
            if conn:
                conn.rollback()

    def start(self):
        self.create_tables()

    def stop(self):
        # Close the connection if it exists for the current thread/process
        if hasattr(self._local, 'conn') and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None
            logger.info(f"DB connection closed for process {os.getpid()} thread {threading.get_ident()}")

db_manager = DatabaseManager()
