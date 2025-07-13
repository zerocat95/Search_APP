

import os
import sys
import jieba
from sentence_transformers import SentenceTransformer, util

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.db_manager import db_manager
from backend.config import config

model = None
MODEL_NAME = "BAAI/bge-small-zh-v1.5"

def get_model():
    global model
    if model is None:
        hf_endpoint = config.get('HF_ENDPOINT', section='models')
        if hf_endpoint:
            os.environ['HUGGINGFACE_HUB_ENDPOINT'] = hf_endpoint
        model = SentenceTransformer(MODEL_NAME)
    return model

def create_snippet(document: str, query: str, max_length: int = 250) -> str:
    """Creates a contextual snippet from the document around the query terms."""
    try:
        query_words = {q for q in jieba.cut(query, cut_all=False) if q.strip()}
        
        best_pos = -1
        # Find the first occurrence of any important query word
        for word in query_words:
            pos = document.find(word)
            if pos != -1:
                best_pos = pos
                break
        
        if best_pos != -1:
            start = max(0, best_pos - (max_length // 2))
            snippet = document[start : start + max_length]
            if start > 0:
                snippet = "..." + snippet
            if (start + max_length) < len(document):
                snippet = snippet + "..."
        else:
            # If no query terms are found, just take the beginning
            snippet = document[:max_length]
            if len(document) > max_length:
                snippet = snippet + "..."
        
        return snippet.replace('\n', ' ').replace('\r', ' ').strip()
    except Exception:
        # Fallback for any error
        return document[:max_length].replace('\n', ' ').replace('\r', ' ').strip() + "..."

def fts_search(query_terms: str, space_id: int = None, limit: int = 30) -> list[dict]:
    sql_query = """
        SELECT 
            f.id as file_id,
            f.path as file_path,
            f.original_content as document,
            f.space_id
        FROM files_fts fts
        JOIN files f ON fts.rowid = f.id
        WHERE fts.files_fts MATCH ?
    """
    params = [query_terms]

    if space_id is not None:
        sql_query += " AND f.space_id = ?"
        params.append(space_id)
    
    sql_query += " ORDER BY fts.rank LIMIT ?"
    params.append(limit)

    return db_manager.execute_read(sql_query, params)

def rerank_results(query: str, fts_results: list[dict]) -> list[dict]:
    if not fts_results:
        return []

    model = get_model()
    
    query_embedding = model.encode(query, convert_to_tensor=True)
    doc_contents = [res['document'] for res in fts_results]
    doc_embeddings = model.encode(doc_contents, convert_to_tensor=True)

    cosine_scores = util.cos_sim(query_embedding, doc_embeddings)[0]

    reranked_results = []
    for i, result in enumerate(fts_results):
        reranked_results.append({
            "id": f"reranked_{result['file_id']}",
            "document": result['document'],
            "metadata": {
                "file_path": result['file_path'],
                "space_id": result['space_id'],
                "score": float(cosine_scores[i])
            },
            "match_type": "content"
        })

    reranked_results.sort(key=lambda x: x['metadata']['score'], reverse=True)
    return reranked_results

def search(query: str, space_id: int = None, limit: int = 10) -> list[dict]:
    if not query:
        return []

    tokenized_query = " ".join(jieba.cut_for_search(query))
    
    fts_results = fts_search(tokenized_query, space_id, limit=30)

    if not fts_results:
        return []

    reranked_results = rerank_results(query, fts_results)

    # Create snippets for the final results before returning
    for result in reranked_results:
        result['document'] = create_snippet(result['document'], query)

    return reranked_results[:limit]
