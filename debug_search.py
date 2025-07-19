#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, '.')

from backend.search import faiss_indexes, load_faiss_index, get_model
from backend.db_manager import db_manager
import numpy as np
import time

def debug_search():
    print("=== Debug Search Performance ===")
    
    # Ensure index is loaded
    print("Loading Faiss index...")
    load_faiss_index(1)
    
    if 1 not in faiss_indexes:
        print("ERROR: Faiss index not loaded")
        return
    
    index = faiss_indexes[1]
    print(f"Index loaded: True")
    print(f"Index ntotal: {index.ntotal}")
    
    # Test model loading
    print("\nTesting model loading...")
    start_time = time.time()
    try:
        model = get_model()
        print(f"Model loaded in {time.time() - start_time:.2f}s")
        
        # Test vector generation
        print("Testing vector generation...")
        start_time = time.time()
        query = "脑裂"
        query_embedding = model.encode([query], convert_to_tensor=False, show_progress_bar=False)
        print(f"Vector generated in {time.time() - start_time:.2f}s")
        print(f"Vector shape: {query_embedding.shape}")
        
        # Test Faiss search
        print("Testing Faiss search...")
        start_time = time.time()
        query_vector = np.expand_dims(query_embedding[0], axis=0).astype('float32')
        distances, indices = index.search(query_vector, 5)
        search_time = time.time() - start_time
        print(f"Search completed in {search_time:.3f}s")
        
        print(f"Found {len([i for i in indices[0] if i != -1])} results")
        print("Indices:", indices[0])
        print("Distances:", distances[0])
        
        # Get actual results
        db_manager.start()
        for i, (idx, dist) in enumerate(zip(indices[0], distances[0])):
            if idx != -1:
                chunk = db_manager.execute_read('SELECT c.chunk_text, f.path FROM chunks c JOIN files f ON c.file_id = f.id WHERE c.id = ?', (int(idx),))
                if chunk:
                    print(f"\nResult {i+1}:")
                    print(f"  File: {chunk[0][1]}")
                    print(f"  Distance: {dist}")
                    print(f"  Preview: {chunk[0][0][:100]}...")
        db_manager.stop()
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_search()