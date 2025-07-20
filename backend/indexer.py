

import os
import sys
import datetime
import jieba
import logging
import time
import multiprocessing
from concurrent.futures import as_completed, TimeoutError as FuturesTimeoutError
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

def worker_init():
    """Initializer for each worker process."""
    global model
    
    # 限制worker进程的内存使用
    try:
        import resource
        # 限制内存使用为2GB
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024 * 1024 * 1024, 2 * 1024 * 1024 * 1024))
    except (ImportError, OSError):
        pass  # Windows系统不支持resource模块
    
    # 延迟加载模型，减少内存占用
    try:
        model = get_model()
    except Exception as e:
        logger.error(f"Failed to load model in worker: {e}")
        model = None
    
    # 设置工作进程的信号处理
    import signal
    def signal_handler(signum, frame):
        logger.info(f"Worker process {os.getpid()} received signal {signum}, exiting...")
        # 清理资源
        global model
        if model is not None:
            del model
            model = None
        sys.exit(0)
    
    try:
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    except (ValueError, OSError):
        # 在某些环境中可能无法设置信号处理
        pass

def process_file_task(file_info, space_id):
    """Task for a single worker process to perform."""
    file_path = file_info["path"]
    file_id = None
    
    # 检查模型是否加载成功
    if model is None:
        return file_path, None, "model_not_loaded", "failed"
    
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
        
        try:
            embeddings = model.encode(chunks, convert_to_tensor=False, show_progress_bar=False)
        except Exception as e:
            logger.error(f"Failed to generate embeddings for {file_path}: {e}")
            return file_path, None, "embedding_failed", "failed"
        
        if file_info["action"] == "insert":
            file_id = db_manager.execute_write(
                "INSERT INTO files (path, last_modified, size, md5, space_id) VALUES (?, ?, ?, ?, ?)",
                (file_path, file_info["last_modified"], file_info["size"], file_info["md5"], space_id)
            )
        elif file_info["action"] == "update":
            file_id = file_info["file_id"]
            db_manager.execute_write("DELETE FROM chunks WHERE file_id = ?", (file_id,))
        
        if file_id:
            # 批量插入chunk，减少数据库操作
            chunk_data = []
            for i, chunk_text_content in enumerate(chunks):
                if i < len(embeddings):  # 确保索引不越界
                    embedding_bytes = embeddings[i].astype(np.float32).tobytes()
                    chunk_data.append((file_id, chunk_text_content, embedding_bytes))
            
            if chunk_data:
                db_manager.execute_write(
                    "INSERT INTO chunks (file_id, chunk_text, embedding) VALUES (?, ?, ?)",
                    chunk_data[0]  # 先插入第一个
                )
                # 批量插入剩余的
                for chunk in chunk_data[1:]:
                    db_manager.execute_write(
                        "INSERT INTO chunks (file_id, chunk_text, embedding) VALUES (?, ?, ?)",
                        chunk
                    )
        else:
            return file_path, None, "no_file_id", "failed"

        # 清理内存
        del embeddings
        del chunks
        
        return file_path, len(chunk_data), None, "success"

    except Exception as e:
        logger.error(f"Error processing file {file_path} in worker: {e}")
        return file_path, None, str(e), "error"

def run_indexing_task(space_id: int):
    try:
        db_manager.start()
        
        # 清理已删除的文件记录（避免数据库无限增长）
        cleanup_deleted_files(space_id)
        
        db_manager.execute_write("UPDATE spaces SET status = ?, scanned_files_count = 0, total_files_to_process = 0, processed_files_count = 0, failed_files_count = 0 WHERE id = ?", ('scanning', space_id))
        
        paths = db_manager.execute_read("SELECT path FROM space_paths WHERE space_id = ?", (space_id,))
        if not paths:
            db_manager.execute_write("UPDATE spaces SET status = ?, last_indexed_at = ? WHERE id = ?", ('completed', datetime.datetime.now(), space_id))
            return
        
        path_list = [p['path'] for p in paths]
        files_to_process = scan_directories(path_list, space_id=space_id, ignored_dirs=[".venv", "node_modules", "dist", "build"])
        
        db_manager.execute_write("UPDATE spaces SET status = ?, total_files_to_process = ? WHERE id = ?", ('indexing', len(files_to_process), space_id))

        # Pre-load the model in the main process to avoid race conditions in workers
        logger.info("Pre-loading embedding model...")
        get_model()
        logger.info("Embedding model loaded.")

        # 限制并发数，避免系统资源耗尽
        max_workers = min(multiprocessing.cpu_count(), 4)  # 最多4个进程
        from concurrent.futures import ProcessPoolExecutor
        
        # 更新活跃线程/进程计数
        import backend.state as state_module
        state_module.indexer_state.active_threads = max_workers
        
        # 创建进程池时设置 daemon=True 确保子进程随主进程退出
        ctx = multiprocessing.get_context('spawn')
        executor = ProcessPoolExecutor(
            max_workers=max_workers,
            initializer=worker_init,
            mp_context=ctx
        )
        
        try:
            # 创建任务并添加超时处理
            futures = {executor.submit(process_file_task, file_info, space_id): file_info 
                      for file_info in files_to_process}
            
            # 处理任务结果
            completed = 0
            total = len(futures)
            
            for future in as_completed(futures, timeout=3600):  # 1小时超时
                file_info = futures[future]
                file_path = file_info['path']
                try:
                    file_path_result, chunks_count, error, status = future.result(timeout=300)  # 5分钟任务超时
                    if status == "success":
                        logger.info(f"Successfully processed {file_path_result} ({completed+1}/{total}) with {chunks_count} chunks")
                    else:
                        logger.error(f"Failed to process {file_path}: {status} - {error}")
                        db_manager.execute_write("UPDATE spaces SET failed_files_count = failed_files_count + 1 WHERE id = ?", (space_id,))
                except FuturesTimeoutError:
                    logger.error(f"Timeout processing file {file_path}")
                    db_manager.execute_write("UPDATE spaces SET failed_files_count = failed_files_count + 1 WHERE id = ?", (space_id,))
                except Exception as e:
                    logger.error(f"A future failed for file {file_path}: {e}")
                    db_manager.execute_write("UPDATE spaces SET failed_files_count = failed_files_count + 1 WHERE id = ?", (space_id,))
                finally:
                    completed += 1
                    db_manager.execute_write("UPDATE spaces SET processed_files_count = processed_files_count + 1 WHERE id = ?", (space_id,))
        
        except Exception as e:
            logger.error(f"Error during indexing execution: {e}")
            raise
        finally:
            # 强制关闭进程池，使用更短的超时
            try:
                # 取消所有未完成的任务
                executor.shutdown(wait=True, cancel_futures=True)
                logger.info("Process pool shutdown completed")
                
                # 重置线程计数
                import backend.state as state_module
                state_module.indexer_state.active_threads = 0
                
            except Exception as e:
                logger.error(f"Error during executor shutdown: {e}")
                # 强制清理
                import gc
                gc.collect()
                
                # 尝试强制终止所有子进程
                try:
                    import psutil
                    current_process = psutil.Process()
                    children = current_process.children(recursive=True)
                    for child in children:
                        try:
                            child.kill()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                except ImportError:
                    pass

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

def cleanup_deleted_files(space_id: int):
    """清理已删除的文件记录，释放数据库空间"""
    try:
        logger.info(f"开始清理space {space_id}的已删除文件记录...")
        
        # 获取所有数据库中的文件路径
        db_files = db_manager.execute_read("SELECT id, path FROM files WHERE space_id = ?", (space_id,))
        deleted_count = 0
        
        for file_record in db_files:
            file_id, file_path = file_record['id'], file_record['path']
            if not os.path.exists(file_path):
                # 文件已删除，清理相关数据
                db_manager.execute_write("DELETE FROM chunks WHERE file_id = ?", (file_id,))
                db_manager.execute_write("DELETE FROM files WHERE id = ?", (file_id,))
                deleted_count += 1
        
        if deleted_count > 0:
            logger.info(f"已清理 {deleted_count} 个已删除文件的记录")
            # 执行数据库压缩
            db_manager.execute_write("VACUUM")
            logger.info("数据库已压缩")
            
    except Exception as e:
        logger.error(f"清理已删除文件时出错: {e}")

def compact_database():
    """手动压缩数据库"""
    try:
        logger.info("开始手动压缩数据库...")
        db_manager.execute_write("VACUUM")
        logger.info("数据库压缩完成")
    except Exception as e:
        logger.error(f"数据库压缩失败: {e}")

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

        dimension = embeddings.shape[1]
        index = faiss.IndexIDMap(faiss.IndexFlatL2(dimension))
        index.add_with_ids(embeddings, chunk_ids)

        index_path = os.path.join(os.path.dirname(config.get('DB_PATH')), f"space_{space_id}.faiss_index")
        faiss.write_index(index, index_path)
        logger.info(f"Faiss index for space {space_id} built and saved to {index_path}")

    except Exception as e:
        logger.error(f"Failed to build Faiss index for space {space_id}: {e}")
