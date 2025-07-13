

import os
import sys
import datetime
import jieba
import logging
import time
import threading
import multiprocessing
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from backend.scanner import scan_directories
from backend.config import config
from pypdf import PdfReader
from docx import Document
import openpyxl
from backend.db_manager import db_manager

logger = logging.getLogger(__name__)

import os
import sys
import datetime
import jieba
import logging
import time
import threading
import multiprocessing
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from backend.scanner import scan_directories
from backend.config import config
from pypdf import PdfReader
from docx import Document
import openpyxl
from backend.db_manager import db_manager
from backend.state import indexer_state

logger = logging.getLogger(__name__)

class DynamicThreadPoolExecutor:
    def __init__(self, min_workers=1, max_workers=None):
        self.min_workers = min_workers
        self.cpu_count = multiprocessing.cpu_count()
        self.max_workers = max_workers or self.cpu_count * 4

        initial_workers = self.cpu_count * 2
        self._executor = ThreadPoolExecutor(max_workers=initial_workers)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._monitor_thread = threading.Thread(target=self._adjust_pool_size, daemon=True)

        with indexer_state.lock:
            indexer_state.active_executors.add(self)
        
        indexer_state.active_threads = initial_workers

    def _adjust_pool_size(self):
        """Periodically checks the queue size and adjusts the thread pool size."""
        while not self._stop_event.is_set():
            queue_size = db_manager.get_queue_size()
            current_workers = self._executor._max_workers

            if queue_size <= 20:
                new_size = self.cpu_count * 2
            elif 21 <= queue_size <= 40:
                new_size = self.cpu_count
            elif 41 <= queue_size <= 60:
                new_size = max(1, self.cpu_count // 2)
            else: # queue_size > 60
                new_size = 1
            
            new_size = max(self.min_workers, min(new_size, self.max_workers))

            if current_workers != new_size:
                with self._lock:
                    logger.info(f"DB write queue size: {queue_size}. Adjusting worker threads from {current_workers} to {new_size}.")
                    self._executor._max_workers = new_size
                    indexer_state.active_threads = new_size
            else:
                logger.info(f"DB write queue size: {queue_size}. Worker threads remain at {current_workers}.")
                indexer_state.active_threads = current_workers

            time.sleep(5)

    def start(self):
        if not self._monitor_thread.is_alive():
            self._monitor_thread.start()

    def stop(self):
        self._stop_event.set()
        indexer_state.active_threads = 0
        if self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5)
        self._executor.shutdown(wait=True)

        with indexer_state.lock:
            if self in indexer_state.active_executors:
                indexer_state.active_executors.remove(self)

    def submit(self, fn, *args, **kwargs):
        return self._executor.submit(fn, *args, **kwargs)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

def get_text_from_file(file_path: str) -> str:
    """Extracts text content from a file based on its extension."""
    logger.info(f"Worker thread started for file: {file_path}")
    _, extension = os.path.splitext(file_path)
    text = ""
    try:
        if extension == ".pdf":
            reader = PdfReader(file_path)
            for page in reader.pages:
                text += page.extract_text() or ""
        elif extension == ".docx":
            doc = Document(file_path)
            for para in doc.paragraphs:
                text += para.text + "\n"
        elif extension == ".xlsx":
            workbook = openpyxl.load_workbook(file_path)
            for sheet in workbook.worksheets:
                for row in sheet.iter_rows():
                    for cell in row:
                        if cell.value:
                            text += str(cell.value) + " "
                    text += "\n"
        elif extension in [".txt", ".md", ".py", ".js", ".html", ".css", ".json", ".xml", ".csv"]:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}")
        return ""
    logger.info(f"Worker thread finished for file: {file_path}")
    return text

def run_indexing_task(space_id: int):
    try:
        db_manager.execute_write("UPDATE spaces SET status = ?, scanned_files_count = 0, total_files_to_process = 0, processed_files_count = 0, failed_files_count = 0 WHERE id = ?", ('scanning', space_id))
        
        paths = db_manager.execute_read("SELECT path FROM space_paths WHERE space_id = ?", (space_id,))
        if not paths:
            db_manager.execute_write("UPDATE spaces SET status = ?, last_indexed_at = ? WHERE id = ?", ('completed', datetime.datetime.now(), space_id))
            return
        
        path_list = [p['path'] for p in paths]
        files_to_process = scan_directories(path_list, space_id=space_id, ignored_dirs=[".venv", "node_modules", "dist", "build"])
        
        db_manager.execute_write("UPDATE spaces SET status = ?, total_files_to_process = ? WHERE id = ?", ('indexing', len(files_to_process), space_id))

        with DynamicThreadPoolExecutor() as executor:
            for file_info in files_to_process:
                file_path = file_info["path"]
                logger.info(f"[Indexer] Submitting file for processing: {file_path}")
                
                future = executor.submit(get_text_from_file, file_path)
                
                try:
                    original_content = future.result(timeout=120)
                    if original_content:
                        tokenized_content = " ".join(jieba.cut_for_search(original_content))
                        
                        if file_info["action"] == "insert":
                            db_manager.execute_write(
                                "INSERT INTO files (path, last_modified, size, md5, space_id, content, original_content) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                (file_path, file_info["last_modified"], file_info["size"], file_info["md5"], space_id, tokenized_content, original_content)
                            )
                        elif file_info["action"] == "update":
                            db_manager.execute_write(
                                "UPDATE files SET last_modified = ?, size = ?, md5 = ?, content = ?, original_content = ? WHERE id = ?",
                                (file_info["last_modified"], file_info["size"], file_info["md5"], tokenized_content, original_content, file_info["file_id"])
                            )

                except (FuturesTimeoutError, Exception) as e:
                    if isinstance(e, FuturesTimeoutError):
                        logger.error(f"[Indexer] Timeout processing file {file_path} after 120 seconds.")
                    else:
                        logger.error(f"[Indexer] A worker failed to process file {file_path}: {e}")
                    # Update failed count
                    db_manager.execute_write("UPDATE spaces SET failed_files_count = failed_files_count + 1 WHERE id = ?", (space_id,))
                finally:
                    # Always update the total processed count
                    db_manager.execute_write("UPDATE spaces SET processed_files_count = processed_files_count + 1 WHERE id = ?", (space_id,))

        db_manager.execute_write("UPDATE spaces SET status = ?, last_indexed_at = ? WHERE id = ?", ('completed', datetime.datetime.now(), space_id))

    except Exception as e:
        logger.error(f"Error during indexing for space {space_id}: {e}")
        db_manager.execute_write("UPDATE spaces SET status = ? WHERE id = ?", ('failed', space_id))