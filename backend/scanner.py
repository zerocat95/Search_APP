import os
import sys
import hashlib
import time

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.config import config
from backend.db_manager import db_manager

SUPPORTED_EXTENSIONS = [".docx", ".xlsx", ".pptx", ".pdf", ".txt", ".md", ".py", ".js", ".html", ".css", ".json", ".xml", ".csv"]

def get_file_md5(file_path):
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
    except (FileNotFoundError, PermissionError):
        return None
    return hash_md5.hexdigest()

def scan_directories(directories: list[str], space_id: int, ignored_dirs: list[str] = None) -> list:
    if ignored_dirs is None:
        ignored_dirs = []

    files_to_process = []
    scanned_count = 0
    
    # 批量更新扫描计数，避免频繁数据库操作
    update_interval = 50  # 每50个文件更新一次

    for directory in directories:
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if d not in ignored_dirs]
            for file in files:
                # Check for supported extensions
                if not any(file.lower().endswith(ext) for ext in SUPPORTED_EXTENSIONS):
                    continue

                file_path = os.path.join(root, file)
                try:
                    stat = os.stat(file_path)
                    last_modified = stat.st_mtime
                    size = stat.st_size
                    md5 = get_file_md5(file_path)
                    if md5 is None: # Skip if file could not be read
                        continue

                    scanned_count += 1
                    # 批量更新，减少数据库操作
                    if scanned_count % update_interval == 0:
                        db_manager.execute_write("UPDATE spaces SET scanned_files_count = ? WHERE id = ?", (scanned_count, space_id))

                    # Check if file exists in DB and if it needs updating
                    result = db_manager.execute_read("SELECT id, last_modified, md5, size FROM files WHERE path = ? AND space_id = ?", (file_path, space_id))

                    if result:
                        file_id, db_last_modified, db_md5, db_size = result[0]
                        # Check if the file has any chunks associated with it
                        chunk_count = db_manager.execute_read("SELECT COUNT(*) as cnt FROM chunks WHERE file_id = ?", (file_id,))[0]['cnt']
                        
                        # 更精确的变化检测：同时检查时间戳、MD5和文件大小
                        # 容差：时间戳差异在2秒内认为相同（避免文件系统精度问题）
                        time_diff = abs(db_last_modified - last_modified)
                        has_changed = (
                            time_diff > 2.0 or  # 2秒容差
                            db_md5 != md5 or 
                            db_size != size or
                            chunk_count == 0
                        )
                        
                        if has_changed:
                            files_to_process.append({
                                "file_id": file_id,
                                "path": file_path,
                                "last_modified": last_modified,
                                "size": size,
                                "md5": md5,
                                "action": "update"
                            })
                    else:
                        # New file, needs insertion
                        files_to_process.append({
                            "file_id": None,
                            "path": file_path,
                            "last_modified": last_modified,
                            "size": size,
                            "md5": md5,
                            "action": "insert"
                        })

                except (FileNotFoundError, PermissionError) as e:
                    print(f"Error accessing {file_path}: {e}")

    # 最后更新一次扫描计数
    if scanned_count % update_interval != 0:  # 如果还有未更新的计数
        db_manager.execute_write("UPDATE spaces SET scanned_files_count = ? WHERE id = ?", (scanned_count, space_id))
    
    return files_to_process