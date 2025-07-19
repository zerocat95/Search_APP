import os
import sys
from sentence_transformers import SentenceTransformer
import numpy as np
import faiss
import logging
import threading
import jieba

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.db_manager import db_manager
from backend.config import config

logger = logging.getLogger(__name__)

model = None
MODEL_NAME = "BAAI/bge-small-zh-v1.5"
faiss_indexes = {}
_faiss_lock = threading.Lock()  # 用于线程安全的Faiss操作

def get_model():
    global model
    if model is None:
        hf_endpoint = config.get('HF_ENDPOINT', section='models')
        if hf_endpoint:
            os.environ['HUGGINGFACE_HUB_ENDPOINT'] = hf_endpoint
        model = SentenceTransformer(MODEL_NAME)
    return model

def load_faiss_index(space_id: int):
    global faiss_indexes
    index_path = os.path.join(os.path.dirname(config.get('DB_PATH')), f"space_{space_id}.faiss_index")
    if os.path.exists(index_path):
        try:
            with _faiss_lock:
                # 在macOS上强制使用单线程以避免段错误
                import platform
                if platform.system() == 'Darwin':
                    faiss.omp_set_num_threads(1)
                else:
                    faiss.omp_set_num_threads(min(4, (os.cpu_count() or 1)))
                
                faiss_indexes[space_id] = faiss.read_index(index_path)
                logger.info(f"Faiss index for space {space_id} loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load Faiss index for space {space_id}: {e}")
            faiss_indexes[space_id] = None
    else:
        logger.warning(f"Faiss index not found for space {space_id} at {index_path}")
        faiss_indexes[space_id] = None

def create_snippet(document: str, query: str, max_length: int = 250) -> str:
    """Creates a contextual snippet from the document around the query terms."""
    try:
        # 使用jieba进行中文分词
        import jieba
        query_words = {q for q in jieba.cut(query, cut_all=False) if q.strip()}
        
        # 查找所有匹配位置
        positions = []
        for word in query_words:
            pos = document.lower().find(word.lower())
            if pos != -1:
                positions.append(pos)
        
        if positions:
            # 使用第一个匹配位置
            best_pos = positions[0]
            start = max(0, best_pos - (max_length // 3))
            end = min(len(document), start + max_length)
            
            # 确保不截断单词
            if start > 0:
                # 找到最近的句子边界
                while start > 0 and document[start] not in '。！？.!?\n\r':
                    start -= 1
                if start > 0:
                    start += 1
            
            if end < len(document):
                # 找到最近的句子边界
                while end < len(document) and document[end] not in '。！？.!?\n\r':
                    end += 1
            
            snippet = document[start:end]
            
            # 高亮查询词
            highlighted_snippet = snippet
            for word in query_words:
                if len(word) > 1:  # 忽略单字符
                    highlighted_snippet = highlighted_snippet.replace(
                        word, f"**{word}**"
                    )
            
            if start > 0:
                highlighted_snippet = "..." + highlighted_snippet
            if end < len(document):
                highlighted_snippet = highlighted_snippet + "..."
                
            return highlighted_snippet.replace('\n', ' ').replace('\r', ' ').strip()
        else:
            # 如果没有找到匹配，返回开头部分
            snippet = document[:max_length]
            if len(document) > max_length:
                snippet = snippet + "..."
            return snippet.replace('\n', ' ').replace('\r', ' ').strip()
            
    except Exception as e:
        logger.error(f"Error creating snippet: {e}")
        return document[:max_length].replace('\n', ' ').replace('\r', ' ').strip() + "..."

def search(query: str, space_id: int = None, limit: int = 10) -> list[dict]:
    if not query:
        return []

    model = get_model()
    
    # 中文查询预处理
    query = query.strip()
    
    if space_id is not None:
        space_ids_to_search = [space_id]
    else:
        all_spaces = db_manager.execute_read("SELECT id FROM spaces")
        space_ids_to_search = [s['id'] for s in all_spaces]

    all_results = []
    
    # 使用更大的搜索范围来提高召回率
    search_limit = min(limit * 3, 100)
    
    for current_space_id in space_ids_to_search:
        if current_space_id not in faiss_indexes:
            load_faiss_index(current_space_id)
        
        index = faiss_indexes.get(current_space_id)
        if index is None:
            logger.warning(f"Skipping search for space {current_space_id} as index is not loaded.")
            continue

        # 增强查询向量化，使用不同的编码策略
        try:
            # 使用更简单的查询处理
            query_embedding = model.encode([query], convert_to_tensor=False, show_progress_bar=False)[0]
            query_embedding = np.expand_dims(query_embedding, axis=0).astype('float32')

            # 使用线程锁确保Faiss操作的线程安全
            with _faiss_lock:
                try:
                    # 在macOS上强制使用单线程以避免段错误
                    import platform
                    if platform.system() == 'Darwin':
                        faiss.omp_set_num_threads(1)
                    else:
                        faiss.omp_set_num_threads(min(4, (os.cpu_count() or 1)))
                    
                    distances, chunk_ids = index.search(query_embedding, search_limit)
                except Exception as e:
                    logger.error(f"Faiss search failed for space {current_space_id}: {e}")
                    continue
            
            if len(chunk_ids[0]) == 0:
                continue

            found_chunk_ids = tuple(c_id for c_id in chunk_ids[0] if c_id != -1)
            if not found_chunk_ids:
                continue

            sql_query = f"""
                SELECT c.id as chunk_id, c.chunk_text, f.path as file_path, f.space_id
                FROM chunks c JOIN files f ON c.file_id = f.id
                WHERE c.id IN ({','.join(['?']*len(found_chunk_ids))})
            """
            
            db_results = db_manager.execute_read(sql_query, found_chunk_ids)
            results_map = {res['chunk_id']: res for res in db_results}

            for i, chunk_id in enumerate(found_chunk_ids):
                if chunk_id in results_map:
                    res = results_map[chunk_id]
                    score = float(distances[0][i])
                    
                    all_results.append({
                        "id": f"vector_{chunk_id}",
                        "document": create_snippet(res['chunk_text'], query),
                        "metadata": {
                            "file_path": res['file_path'],
                            "space_id": res['space_id'],
                            "score": score
                        },
                        "match_type": "content"
                    })

        except Exception as e:
            logger.error(f"Error processing search for space {current_space_id}: {e}")
            continue

    # 如果向量搜索没有结果，使用关键词搜索作为回退
    if not all_results:
        logger.info(f"Vector search returned no results, falling back to keyword search for '{query}'")
        return keyword_search_fallback(query, space_id, limit)

    # 按分数排序并去重
    seen_chunks = set()
    unique_results = []
    for result in sorted(all_results, key=lambda x: x['metadata']['score']):
        chunk_id = result['id']
        if chunk_id not in seen_chunks:
            seen_chunks.add(chunk_id)
            unique_results.append(result)
            if len(unique_results) >= limit:
                break

    logger.info(f"Vector search for '{query}' returned {len(unique_results)} results")
    return unique_results

def keyword_search_fallback(query: str, space_id: int = None, limit: int = 10) -> list[dict]:
    """关键词搜索回退机制，当向量搜索无结果时使用"""
    try:
        if not query:
            return []
        
        if space_id is not None:
            space_ids_to_search = [space_id]
        else:
            all_spaces = db_manager.execute_read("SELECT id FROM spaces")
            space_ids_to_search = [s['id'] for s in all_spaces]
        
        results = []
        
        for current_space_id in space_ids_to_search:
            # 使用LIKE搜索包含关键词的chunk
            search_pattern = f'%{query}%'
            sql_query = """
                SELECT c.id as chunk_id, c.chunk_text, f.path as file_path, f.space_id
                FROM chunks c JOIN files f ON c.file_id = f.id
                WHERE f.space_id = ? AND c.chunk_text LIKE ?
                ORDER BY LENGTH(c.chunk_text) ASC
                LIMIT ?
            """
            
            db_results = db_manager.execute_read(sql_query, (current_space_id, search_pattern, limit))
            
            for res in db_results:
                # 计算关键词匹配分数（出现次数和位置）
                text_lower = res['chunk_text'].lower()
                query_lower = query.lower()
                
                # 简单的分数计算：关键词出现次数
                keyword_count = text_lower.count(query_lower)
                if keyword_count > 0:
                    # 分数：关键词出现次数 / 文本长度（归一化）
                    score = keyword_count / len(text_lower)
                    
                    results.append({
                        "id": f"keyword_{res['chunk_id']}",
                        "document": create_snippet(res['chunk_text'], query),
                        "metadata": {
                            "file_path": res['file_path'],
                            "space_id": res['space_id'],
                            "score": score
                        },
                        "match_type": "keyword"
                    })
        
        # 按分数降序排序
        results.sort(key=lambda x: x['metadata']['score'], reverse=True)
        
        # 返回最多limit个结果
        return results[:limit]
        
    except Exception as e:
        logger.error(f"Keyword search failed: {e}")
        return []