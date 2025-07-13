import uvicorn
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import sqlite3
import os
import sys
import datetime
import asyncio
from typing import List, Optional
import logging
from logging.handlers import TimedRotatingFileHandler

# Add project root to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

import shutil
import time
import importlib
import threading
from backend.config import config
from backend.database import init_db
from backend.db_manager import db_manager
from backend.state import indexer_state

# --- Logging Configuration ---
LOG_DIR = config.get('LOG_DIR', section='logging')
os.makedirs(LOG_DIR, exist_ok=True)

log_file_name = datetime.datetime.now().strftime("python_%Y%m%d.log")
log_file_path = os.path.join(LOG_DIR, log_file_name)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        TimedRotatingFileHandler(log_file_path, when="midnight", interval=1, backupCount=7, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# --- Backend State ---
backend_status = {
    "status": "loading",
    "message": "服务正在启动..."
}
db_write_lock = asyncio.Lock()

# To be populated by the background initialization
search_service = None
indexer_service = None

# --- FastAPI App Initialization ---
app = FastAPI(
    title="Semantic File Search API",
    description="API for managing and searching through file spaces.",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic Models ---
class SpaceBase(BaseModel):
    name: str

class SpaceCreate(SpaceBase):
    pass

class SpaceUpdate(BaseModel):
    name: str = None
    path: str = None

class Space(SpaceBase):
    id: int
    position: int = None
    status: str
    last_indexed_at: Optional[datetime.datetime] = None
    total_files_to_process: int = 0
    processed_files_count: int = 0

    class Config:
        from_attributes = True

class SpacePathBase(BaseModel):
    path: str

class SpacePathCreate(SpacePathBase):
    pass

class SpacePath(SpacePathBase):
    id: int
    space_id: int

    class Config:
        from_attributes = True

class SpaceReorder(BaseModel):
    space_ids: List[int]

class File(BaseModel):
    id: int
    path: str
    last_modified: datetime.datetime
    size: int
    space_id: int

    class Config:
        from_attributes = True

class SearchResultMetadata(BaseModel):
    file_path: str
    space_id: int
    score: float

class SearchResult(BaseModel):
    id: str
    document: str
    metadata: SearchResultMetadata
    match_type: str

class AppConfig(BaseModel):
    version: str
    backend_ip: str
    backend_port: int

# --- Helper Functions ---


# --- Background Initialization Task ---
async def initialize_backend():
    """
    Initializes the backend services in a non-blocking way by running
    blocking I/O operations in a separate thread pool.
    """
    global search_service, indexer_service, backend_status
    loop = asyncio.get_running_loop()
    try:
        backend_status.update({"status": "loading", "message": "正在初始化数据库..."})
        await loop.run_in_executor(None, init_db)
        
        # --- Startup State Cleanup ---
        # Reset any spaces that were in 'scanning' or 'indexing' status due to unexpected shutdown
        logger.info("Performing startup state cleanup...")
        spaces_to_reset = db_manager.execute_read("SELECT id FROM spaces WHERE status IN (?, ?)", ('scanning', 'indexing'))
        for space_row in spaces_to_reset:
            space_id = space_row[0]
            db_manager.execute_write("UPDATE spaces SET status = ?, scanned_files_count = 0, total_files_to_process = 0, processed_files_count = 0 WHERE id = ?", ('failed', space_id))
            logger.warning(f"Space {space_id} status reset to 'failed' due to previous unexpected shutdown.")
        # --- End Startup State Cleanup ---

        await asyncio.sleep(0.1)

        backend_status.update({"status": "loading", "message": "正在加载依赖模块..."})
        from backend import search, indexer
        await asyncio.sleep(0.1)

        search_service = search
        indexer_service = indexer

        backend_status.update({"status": "ready", "message": "服务已就绪"})
        logger.info("Backend initialization complete. Service is ready.")

    except Exception as e:
        logger.error(f"Backend initialization failed: {e}", exc_info=True)
        error_summary = "模型加载失败，请检查网络连接或模型名称是否正确。"
        error_details = str(e).split('\n')[0]
        backend_status.update({
            "status": "error",
            "message": f"{error_summary}\n技术原因: {error_details}"
        })

def check_backend_ready():
    if backend_status["status"] != "ready" or not search_service or not indexer_service:
        raise HTTPException(status_code=503, detail=f"Service not ready. Current status: {backend_status['message']}")

# --- API Endpoints ---

# 1. System & Statistics
@app.get("/api/status", tags=["System"])
async def get_status():
    return backend_status

@app.get("/api/health", tags=["System"])
async def health_check():
    check_backend_ready()
    return {"status": "ok"}

@app.get("/api/stats", tags=["System"])
async def get_global_stats():
    check_backend_ready()
    space_count = db_manager.execute_read("SELECT COUNT(id) FROM spaces")[0][0]
    total_indexed_files = db_manager.execute_read("SELECT COUNT(id) FROM files")[0][0]
    indexing_active = db_manager.execute_read("SELECT COUNT(id) FROM spaces WHERE status = 'indexing'")[0][0] > 0
    return {
        "space_count": space_count,
        "total_indexed_files": total_indexed_files,
        "is_indexing_active": indexing_active
    }

@app.get("/api/indexer/status", tags=["System"])
async def get_indexer_status():
    check_backend_ready()
    return {
        "queue_size": db_manager.get_queue_size(),
        "active_threads": indexer_state.active_threads
    }

@app.get("/api/app-config", response_model=AppConfig, tags=["System"])
async def get_app_config():
    return AppConfig(
        version=config.get('VERS', section='general'),
        backend_ip=config.get('LISTEN_IP', section='server'),
        backend_port=int(config.get('LISTEN_PORT', section='server'))
    )

@app.post("/api/system/sync", tags=["System"])
async def sync_database(background_tasks: BackgroundTasks):
    check_backend_ready()
    background_tasks.add_task(indexer_service.sync_deleted_files)
    return {"message": "Database sync started in the background."}

@app.post("/api/system/factory-reset", tags=["System"])
async def factory_reset():
    check_backend_ready()
    
    async with db_write_lock:
        try:
            logger.info("--- Factory Reset Initiated ---")

            # 1. Stop all background services gracefully
            with indexer_state.lock:
                active_executors = list(indexer_state.active_executors)
                logger.info(f"Found {len(active_executors)} active indexer(s) to shut down.")
                for executor in active_executors:
                    executor.stop()
            
            # 2. Physically delete the entire app data directory
            app_data_dir = os.path.expanduser("~/.Search_app")
            if os.path.exists(app_data_dir):
                try:
                    shutil.rmtree(app_data_dir)
                    logger.info(f"Successfully deleted app data directory: {app_data_dir}")
                except OSError as e:
                    logger.error(f"Error deleting app data directory {app_data_dir}: {e}")
                    raise HTTPException(status_code=500, detail=f"Failed to delete app data directory: {e}")

            # Add a small delay to ensure file system operations complete
            time.sleep(0.5)

            # 3. Re-initialize databases and directory structure
            logger.info("Re-initializing databases and directory structure...")
            init_db()

            # The most reliable way to ensure a clean state is to restart the application.
            logger.info("--- Factory Reset successful, triggering application exit for restart. ---")
            # Give the logger a moment to write the file
            time.sleep(1)
            sys.exit(0) # Exit gracefully to signal a restart is needed.
        except Exception as e:
            logger.error(f"Error during factory reset: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

# 2. Space Management
@app.post("/api/spaces", response_model=Space, status_code=201, tags=["Spaces"])
async def create_space(space: SpaceCreate):
    check_backend_ready()
    try:
        new_id = db_manager.execute_write(
            "INSERT INTO spaces (name, position) VALUES (?, (SELECT COALESCE(MAX(position), -1) + 1 FROM spaces))",
            (space.name,)
        )
        new_space_data = db_manager.execute_read("SELECT * FROM spaces WHERE id = ?", (new_id,))
        if not new_space_data:
            raise HTTPException(status_code=500, detail="Failed to create or retrieve space after creation.")
        return dict(new_space_data[0])
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail=f"Space with name '{space.name}' already exists.")

@app.get("/api/spaces", response_model=List[Space], tags=["Spaces"])
async def list_spaces():
    check_backend_ready()
    spaces_data = db_manager.execute_read("SELECT * FROM spaces ORDER BY position, name")
    return [dict(s) for s in spaces_data]

# ... (The rest of the endpoints will be similar, with check_backend_ready())

@app.get("/api/spaces/{space_id}", response_model=Space, tags=["Spaces"])
async def get_space(space_id: int):
    check_backend_ready()
    space_data = db_manager.execute_read("SELECT * FROM spaces WHERE id = ?", (space_id,))
    if not space_data:
        raise HTTPException(status_code=404, detail="Space not found.")
    return dict(space_data[0])

@app.patch("/api/spaces/{space_id}", response_model=Space, tags=["Spaces"])
async def update_space(space_id: int, space_update: SpaceUpdate):
    check_backend_ready()
    await get_space(space_id) # Ensure space exists
    if space_update.name:
        db_manager.execute_write("UPDATE spaces SET name = ? WHERE id = ?", (space_update.name, space_id))
    return await get_space(space_id)

@app.post("/api/spaces/reorder", tags=["Spaces"])
async def reorder_spaces(order: SpaceReorder):
    check_backend_ready()
    for i, space_id in enumerate(order.space_ids):
        db_manager.execute_write("UPDATE spaces SET position = ? WHERE id = ?", (i, space_id))
    return {"message": "Spaces reordered successfully"}

@app.delete("/api/spaces/{space_id}", tags=["Spaces"])
async def delete_space(space_id: int):
    check_backend_ready()
    await get_space(space_id) # Ensure space exists
    indexer_service.clear_space_from_index(space_id)
    db_manager.execute_write("DELETE FROM spaces WHERE id = ?", (space_id,))
    return {"message": "Space deleted"}

@app.get("/api/spaces/{space_id}/paths", response_model=List[SpacePath], tags=["Spaces"])
async def get_space_paths(space_id: int):
    check_backend_ready()
    await get_space(space_id) # Ensure space exists
    paths_data = db_manager.execute_read("SELECT * FROM space_paths WHERE space_id = ?", (space_id,))
    return [dict(p) for p in paths_data]

@app.post("/api/spaces/{space_id}/paths", response_model=SpacePath, status_code=201, tags=["Spaces"])
async def add_space_path(space_id: int, space_path: SpacePathCreate):
    check_backend_ready()
    await get_space(space_id) # Ensure space exists
    if not os.path.isdir(space_path.path):
        raise HTTPException(status_code=422, detail="Path does not exist or is not a directory.")
    try:
        new_id = db_manager.execute_write("INSERT INTO space_paths (space_id, path) VALUES (?, ?)", (space_id, space_path.path))
        new_path_data = db_manager.execute_read("SELECT * FROM space_paths WHERE id = ?", (new_id,))
        if not new_path_data:
            raise HTTPException(status_code=500, detail="Failed to create or retrieve space path after creation.")
        return dict(new_path_data[0])
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail=f"Path '{space_path.path}' already exists for this space.")

@app.delete("/api/spaces/{space_id}/paths/{path_id}", status_code=204, tags=["Spaces"])
async def delete_space_path(space_id: int, path_id: int):
    check_backend_ready()
    await get_space(space_id) # Ensure space exists
    db_manager.execute_write("DELETE FROM space_paths WHERE id = ? AND space_id = ?", (path_id, space_id))
    return

# 3. Indexing & File Management
@app.post("/api/spaces/{space_id}/index", status_code=202, tags=["Indexing"])
async def trigger_indexing(space_id: int, background_tasks: BackgroundTasks):
    check_backend_ready()
    space = await get_space(space_id)
    if space['status'] == 'indexing':
        raise HTTPException(status_code=409, detail="Indexing is already in progress for this space.")
    background_tasks.add_task(indexer_service.run_indexing_task, space_id)
    return {"message": "Indexing started"}

@app.get("/api/spaces/{space_id}/index/status", tags=["Indexing"])
async def get_indexing_status(space_id: int):
    check_backend_ready()
    space_data = await get_space(space_id)
    space = dict(space_data)
    
    processed_count = space.get('processed_files_count', 0)
    failed_count = space.get('failed_files_count', 0)
    completed_count = processed_count - failed_count

    return {
        "status": space['status'],
        "last_indexed_at": space['last_indexed_at'],
        "total_files_to_process": space.get('total_files_to_process', 0),
        "processed_files_count": processed_count,
        "completed_count": completed_count,
        "failed_count": failed_count
    }

@app.delete("/api/spaces/{space_id}/index", tags=["Indexing"])
async def clear_index(space_id: int):
    check_backend_ready()
    await get_space(space_id)
    indexer_service.clear_space_from_index(space_id)
    return {"message": "Index cleared for space"}

# 4. Search
@app.get("/api/search", response_model=List[SearchResult], tags=["Search"])
async def search(q: str, space_id: int = None, limit: int = 10):
    check_backend_ready()
    if not q:
        raise HTTPException(status_code=422, detail="Query parameter 'q' cannot be empty.")
    results = search_service.search(query=q, space_id=space_id, limit=limit)
    return results

@app.get("/api/search/filenames", response_model=List[File], tags=["Search"])
async def search_filenames(q: str, space_id: int = None, limit: int = 20):
    check_backend_ready()
    if not q:
        return []
    
    query = f"%{q}%"
    
    if space_id:
        sql = "SELECT id, path, last_modified, size, space_id FROM files WHERE path LIKE ? AND space_id = ? ORDER BY last_modified DESC LIMIT ?"
        params = (query, space_id, limit)
    else:
        sql = "SELECT id, path, last_modified, size, space_id FROM files WHERE path LIKE ? ORDER BY last_modified DESC LIMIT ?"
        params = (query, limit)
        
    try:
        file_records = db_manager.execute_read(sql, params)
        return [dict(file) for file in file_records]
    except Exception as e:
        logger.error(f"Filename search failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to search filenames.")

# --- Log Cleanup Function ---
def cleanup_old_logs():
    for filename in os.listdir(LOG_DIR):
        file_path = os.path.join(LOG_DIR, filename)
        if os.path.isfile(file_path) and filename.startswith("python_") and filename.endswith(".log"):
            file_date_str = filename[len("python_"):-len(".log")]
            try:
                file_date = datetime.datetime.strptime(file_date_str, "%Y%m%d").date()
                if (datetime.date.today() - file_date).days > 7:
                    os.remove(file_path)
                    logger.info(f"Deleted old log file: {filename}")
            except ValueError:
                # Ignore files that don't match the expected date format
                pass

# --- Main Execution ---
@app.on_event("startup")
async def on_startup():
    db_manager.start()
    asyncio.create_task(initialize_backend())
    cleanup_old_logs()

@app.on_event("shutdown")
def on_shutdown():
    logger.info("Application is shutting down. Stopping all background services.")
    
    # Stop all active indexer executors first
    with indexer_state.lock:
        active_executors = list(indexer_state.active_executors)
        logger.info(f"Found {len(active_executors)} active indexer(s) to shut down.")
        for executor in active_executors:
            executor.stop()
    
    # Then, stop the database manager
    logger.info("Stopping database manager.")
    db_manager.stop()
    logger.info("Shutdown complete.")

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=config.get('LISTEN_IP', section='server'),
        port=int(config.get('LISTEN_PORT', section='server')),
        log_level="info" if config.get('DEBUG_MODE', section='server').lower() == 'true' else "warning"
    )
