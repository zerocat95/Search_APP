import sqlite3
import queue
import threading
from backend.config import config

class DatabaseManager:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(DatabaseManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, 'initialized'):
            self.db_path = config.get('DB_PATH')
            self.write_queue = queue.Queue()
            self.stop_event = threading.Event()
            self.worker_thread = threading.Thread(target=self._worker, daemon=True)
            self.initialized = True

    def _get_connection(self):
        """Creates a new database connection."""
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _worker(self):
        """The single-threaded worker that processes write operations from the queue."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        while not self.stop_event.is_set():
            try:
                query, params, future = self.write_queue.get(timeout=1)
                try:
                    cursor.execute(query, params)
                    conn.commit()
                    if future:
                        future.set_result(cursor.lastrowid)
                except Exception as e:
                    conn.rollback()
                    if future:
                        future.set_exception(e)
                finally:
                    self.write_queue.task_done()
            except queue.Empty:
                continue
        
        conn.close()

    def start(self):
        if not self.worker_thread.is_alive():
            self.worker_thread.start()

    def stop(self):
        self.stop_event.set()
        self.write_queue.join()
        if self.worker_thread.is_alive():
            self.worker_thread.join()

    def execute_write(self, query, params=()):
        from concurrent.futures import Future
        future = Future()
        self.write_queue.put((query, params, future))
        return future.result()

    def execute_read(self, query, params=()):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()
        finally:
            conn.close()

    def get_queue_size(self):
        return self.write_queue.qsize()

db_manager = DatabaseManager()