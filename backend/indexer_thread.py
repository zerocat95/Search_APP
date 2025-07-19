import os
import sys
import datetime
import jieba
import logging
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import faiss

from backend.scanner import scan_directories
from backend.config import config
from pypdf import PdfReader
from docx import Document
import openpyxl
from pptx import Presentation
from backend.db_manager import db_manager
from backend.state import indexer_state
from backend.search import get_model, MODEL_NAME

logger = logging.getLogger(__name__)

class ThreadSafeModel:
    """线程安全的模型包装类"""
    def __init__(self):
        self._model = None
        self._lock = threading.Lock()
    
    def get_model(self):
        with self._lock:
            if self._model is None:
                self._model = get_model()
            return self._model

# 全局线程安全模型实例
thread_safe_model = ThreadSafeModel()

# 全局线程池管理器
_global_executor = None
_global_executor_lock = threading.Lock()

def get_global_executor(max_workers):
    """获取全局线程池执行器"""
    global _global_executor
    with _global_executor_lock:
        if _global_executor is None or _global_executor._shutdown:
            _global_executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='IndexerWorker')
        return _global_executor

def shutdown_global_executor(wait=True):
    """关闭全局线程池执行器"""
    global _global_executor
    with _global_executor_lock:
        if _global_executor is not None and not _global_executor._shutdown:
            _global_executor.shutdown(wait=wait)
            _global_executor = None

def get_text_from_file(file_path: str) -> str:
    """Extracts text content from a file based on its extension."""
    _, extension = os.path.splitext(file_path)
    text_parts = []
    
    # 检查文件大小，避免处理过大的文件
    try:
        file_size = os.path.getsize(file_path)
        if file_size > 50 * 1024 * 1024:  # 限制50MB
            logger.warning(f"File too large, skipping: {file_path} ({file_size} bytes)")
            return ""
    except OSError:
        return ""
    
    try:
        if extension == ".pdf":
            reader = PdfReader(file_path)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        elif extension == ".docx":
            doc = Document(file_path)
            for para in doc.paragraphs:
                text_parts.append(para.text)
        elif extension == ".xlsx":
            workbook = openpyxl.load_workbook(file_path, read_only=True)
            for sheet in workbook.worksheets:
                for row in sheet.iter_rows():
                    row_text = " ".join(str(cell.value) for cell in row if cell.value)
                    if row_text:
                        text_parts.append(row_text)
        elif extension == ".pptx":
            prs = Presentation(file_path)
            for slide in prs.slides:
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text:
                        text_parts.append(shape.text)
        elif extension in [".txt", ".md", ".py", ".js", ".html", ".css", ".json", ".xml", ".csv"]:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                # 分块读取大文本文件
                chunk_size = 1024 * 1024  # 1MB chunks
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    text_parts.append(chunk)
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}")
        return ""
    
    return "\n".join(text_parts)

def chunk_text(text, chunk_size=500, overlap=50):
    """Splits text into overlapping chunks."""
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks

def process_file_task(file_info, space_id):
    """Task for a single thread to perform."""
    file_path = file_info["path"]
    file_id = None
    
    try:
        text = get_text_from_file(file_path)
        if not text:
            return file_path, None, "no_text", "failed"

        # 限制文本长度，避免内存溢出
        if len(text) > 1000000:  # 限制1MB文本
            text = text[:1000000]
            logger.warning(f"Text truncated for file: {file_path}")

        chunks = chunk_text(text)
        if not chunks:
            return file_path, None, "no_chunks", "failed"

        # 限制chunk数量
        chunks = chunks[:100]  # 最多100个chunk
        
        # 获取模型（线程安全）
        model = thread_safe_model.get_model()
        
        try:
            # 中文文本增强处理
            enhanced_chunks = []
            for chunk in chunks:
                # 清理和标准化文本
                cleaned_chunk = chunk.strip()
                if len(cleaned_chunk) > 10:  # 确保有意义的文本长度
                    enhanced_chunks.append(cleaned_chunk)
            
            if not enhanced_chunks:
                return file_path, None, "no_valid_chunks", "failed"
                
            # 使用批处理来提高性能
            embeddings = model.encode(
                enhanced_chunks, 
                convert_to_tensor=False, 
                show_progress_bar=False,
                normalize_embeddings=True  # 归一化向量以提高搜索质量
            )
        except Exception as e:
            logger.error(f"Failed to generate embeddings for {file_path}: {e}")
            return file_path, None, "embedding_failed", "failed"
        
        if file_info["action"] == "insert":
            db_manager.increment_write_queue(1)
            try:
                file_id = db_manager.execute_write(
                    "INSERT INTO files (path, last_modified, size, md5, space_id) VALUES (?, ?, ?, ?, ?)",
                    (file_path, file_info["last_modified"], file_info["size"], file_info["md5"], space_id)
                )
            finally:
                db_manager.decrement_write_queue(1)
        elif file_info["action"] == "update":
            file_id = file_info["file_id"]
            db_manager.increment_write_queue(1)
            try:
                db_manager.execute_write("DELETE FROM chunks WHERE file_id = ?", (file_id,))
            finally:
                db_manager.decrement_write_queue(1)
        
        if file_id:
            # 增加写入队列计数
            db_manager.increment_write_queue(len(chunks))
            
            try:
                # 批量插入chunk，减少数据库操作
                chunk_data = []
                for i, chunk_text_content in enumerate(chunks):
                    if i < len(embeddings):  # 确保索引不越界
                        # 限制嵌入向量大小，避免内存问题
                        embedding = embeddings[i].astype(np.float32)
                        if len(embedding) > 512:  # 限制向量维度
                            embedding = embedding[:512]
                        embedding_bytes = embedding.tobytes()
                        chunk_data.append((file_id, chunk_text_content, embedding_bytes))
                
                if chunk_data:
                    for chunk in chunk_data:
                        db_manager.execute_write(
                            "INSERT INTO chunks (file_id, chunk_text, embedding) VALUES (?, ?, ?)",
                            chunk
                        )
            finally:
                # 减少写入队列计数
                db_manager.decrement_write_queue(len(chunks))
        else:
            return file_path, None, "no_file_id", "failed"

        # 清理内存
        del embeddings
        del chunks
        
        return file_path, len(chunk_data), None, "success"

    except Exception as e:
        logger.error(f"Error processing file {file_path} in worker: {e}")
        return file_path, None, str(e), "error"

def build_faiss_index(space_id: int):
    logger.info(f"Building Faiss index for space {space_id}...")
    try:
        results = db_manager.execute_read("SELECT c.id, c.embedding FROM chunks c JOIN files f ON c.file_id = f.id WHERE f.space_id = ?", (space_id,))
        
        if not results:
            logger.warning(f"No embeddings found for space {space_id}. Skipping Faiss index creation.")
            return

        chunk_ids = np.array([res['id'] for res in results])
        embeddings = np.array([np.frombuffer(res['embedding'], dtype=np.float32) for res in results])
        
        if embeddings.ndim == 1:
            embeddings = np.vstack(embeddings)

        # 确保嵌入维度一致
        dimension = embeddings.shape[1]
        if dimension > 512:  # 限制维度
            embeddings = embeddings[:, :512]
            dimension = 512
            
        index = faiss.IndexIDMap(faiss.IndexFlatL2(dimension))
        
        # 在macOS上强制使用单线程以避免段错误
        import platform
        if platform.system() == 'Darwin':
            faiss.omp_set_num_threads(1)
        else:
            faiss.omp_set_num_threads(min(4, (os.cpu_count() or 1)))
        
        try:
            index.add_with_ids(embeddings, chunk_ids)
            
            index_path = os.path.join(os.path.dirname(config.get('DB_PATH')), f"space_{space_id}.faiss_index")
            faiss.write_index(index, index_path)
            logger.info(f"Faiss index for space {space_id} built and saved to {index_path}")
        except Exception as e:
            logger.error(f"Error during Faiss index operations for space {space_id}: {e}")
            raise

    except Exception as e:
        logger.error(f"Failed to build Faiss index for space {space_id}: {e}")

def run_indexing_task(space_id: int):
    """使用线程池的版本，避免多进程问题"""
    try:
        db_manager.start()
        db_manager.reset_write_queue()  # 重置写入队列计数器
        db_manager.execute_write("UPDATE spaces SET status = ?, scanned_files_count = 0, total_files_to_process = 0, processed_files_count = 0, failed_files_count = 0 WHERE id = ?", ('scanning', space_id))
        
        paths = db_manager.execute_read("SELECT path FROM space_paths WHERE space_id = ?", (space_id,))
        if not paths:
            db_manager.execute_write("UPDATE spaces SET status = ?, last_indexed_at = ? WHERE id = ?", ('completed', datetime.datetime.now(), space_id))
            return
        
        path_list = [p['path'] for p in paths]
        files_to_process = scan_directories(path_list, space_id=space_id, ignored_dirs=[".venv", "node_modules", "dist", "build"])
        
        db_manager.execute_write("UPDATE spaces SET status = ?, total_files_to_process = ? WHERE id = ?", ('indexing', len(files_to_process), space_id))

        # 预加载模型
        logger.info("Pre-loading embedding model...")
        thread_safe_model.get_model()
        logger.info("Embedding model loaded.")

        # 使用线程池而不是进程池
        max_workers = min(2, (os.cpu_count() or 1))  # 减少线程数，避免macOS段错误
        
        # 更新活跃线程计数
        import backend.state as state_module
        state_module.indexer_state.active_threads = max_workers
        
        executor = get_global_executor(max_workers)
        try:
            # 创建任务
            futures = {executor.submit(process_file_task, file_info, space_id): file_info 
                      for file_info in files_to_process}
                
            # 处理任务结果
            completed = 0
            total = len(futures)
            
            for future in as_completed(futures, timeout=1800):  # 30分钟超时，减少长时间占用
                if threading.current_thread().name.startswith('MainThread') and not threading.main_thread().is_alive():
                    logger.warning("Main thread is dead, cancelling remaining tasks")
                    break
                    
                file_info = futures[future]
                file_path = file_info['path']
                try:
                    file_path_result, chunks_count, error, status = future.result(timeout=60)  # 减少单个文件超时
                    if status == "success":
                        logger.info(f"Successfully processed {file_path_result} ({completed+1}/{total}) with {chunks_count} chunks")
                    else:
                        logger.error(f"Failed to process {file_path}: {status} - {error}")
                        db_manager.execute_write("UPDATE spaces SET failed_files_count = failed_files_count + 1 WHERE id = ?", (space_id,))
                except Exception as e:
                    logger.error(f"A future failed for file {file_path}: {e}")
                    db_manager.execute_write("UPDATE spaces SET failed_files_count = failed_files_count + 1 WHERE id = ?", (space_id,))
                finally:
                    completed += 1
                    db_manager.execute_write("UPDATE spaces SET processed_files_count = processed_files_count + 1 WHERE id = ?", (space_id,))
        except KeyboardInterrupt:
            logger.info("Indexing interrupted by user")
            # 取消所有未完成的任务
            for future in futures:
                future.cancel()
            raise
        except Exception as e:
            logger.error(f"Indexing task error: {e}")
            # 取消所有未完成的任务
            for future in futures:
                future.cancel()
        finally:
            # 重置线程计数
            state_module.indexer_state.active_threads = 0

        build_faiss_index(space_id)

        db_manager.execute_write("UPDATE spaces SET status = ?, last_indexed_at = ? WHERE id = ?", ('completed', datetime.datetime.now(), space_id))

    except Exception as e:
        logger.error(f"Error during indexing for space {space_id}: {e}")
        db_manager.execute_write("UPDATE spaces SET status = ? WHERE id = ?", ('failed', space_id))
        
        # 确保重置线程计数
        try:
            import backend.state as state_module
            state_module.indexer_state.active_threads = 0
        except:
            pass
    finally:
        db_manager.stop()

def clear_space_from_index(space_id: int):
    """Clears all index data for a given space."""
    logger.info(f"Clearing index for space {space_id}")
    try:
        db_manager.start()
        
        # Delete all chunks associated with files in the space
        db_manager.execute_write("""
            DELETE FROM chunks WHERE file_id IN (
                SELECT id FROM files WHERE space_id = ?
            )
        """, (space_id,))
        
        # Delete all files in the space
        db_manager.execute_write("DELETE FROM files WHERE space_id = ?", (space_id,))
        
        # Reset space status
        db_manager.execute_write("UPDATE spaces SET status = 'idle', last_indexed_at = NULL WHERE id = ?", (space_id,))
        
        # Delete the Faiss index file
        index_path = os.path.join(os.path.dirname(config.get('DB_PATH')), f"space_{space_id}.faiss_index")
        if os.path.exists(index_path):
            os.remove(index_path)
            
    except Exception as e:
        logger.error(f"Error clearing index for space {space_id}: {e}")
    finally:
        db_manager.stop()

def sync_deleted_files():
    """Removes entries for files that no longer exist on disk."""
    logger.info("Syncing deleted files...")
    try:
        db_manager.start()
        
        # Get all files in the database
        all_files = db_manager.execute_read("SELECT id, path, space_id FROM files")
        
        deleted_count = 0
        for file_id, file_path, space_id in all_files:
            if not os.path.exists(file_path):
                logger.info(f"File no longer exists, removing from index: {file_path}")
                db_manager.execute_write("DELETE FROM chunks WHERE file_id = ?", (file_id,))
                db_manager.execute_write("DELETE FROM files WHERE id = ?", (file_id,))
                deleted_count += 1
                
        if deleted_count > 0:
            # Rebuild affected Faiss indices
            affected_spaces = set([f[2] for f in all_files if not os.path.exists(f[1])])
            for space_id in affected_spaces:
                build_faiss_index(space_id)
                
        logger.info(f"Synced {deleted_count} deleted files")
        
    except Exception as e:
        logger.error(f"Error syncing deleted files: {e}")
    finally:
        db_manager.stop()