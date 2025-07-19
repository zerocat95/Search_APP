#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
from backend.db_manager import db_manager
from backend.config import config
import faiss

def test_search_simple(keyword):
    """测试搜索功能，不加载模型"""
    print("=== 数据库内容检查 ===")
    
    try:
        db_manager.start()
        
        # 检查文件
        files = db_manager.execute_read("SELECT id, path FROM files WHERE space_id = 1")
        print(f"找到 {len(files)} 个文件")
        
        # 检查chunks
        chunks = db_manager.execute_read("SELECT COUNT(*) FROM chunks c JOIN files f ON c.file_id = f.id WHERE f.space_id = 1")
        print(f"找到 {chunks[0][0]} 个文本块")
        
        # 检查实际内容
        content = db_manager.execute_read("SELECT c.chunk_text, f.path FROM chunks c JOIN files f ON c.file_id = f.id WHERE f.space_id = 1 AND c.chunk_text LIKE ? LIMIT 3", (f'%{keyword}%',))
        print(f"包含'{keyword}'的内容: {len(content)} 条")
        
        for text, path in content:
            print(f"文件: {path}")
            print(f"内容: {text[:100]}...")
            print()
        
        db_manager.stop()
        
    except Exception as e:
        print("数据库错误:", e)

def test_faiss_index():
    """测试Faiss索引"""
    print("\n=== Faiss索引检查 ===")
    
    try:
        index_path = os.path.join(os.path.dirname(config.get('DB_PATH')), 'space_1.faiss_index')
        if os.path.exists(index_path):
            index = faiss.read_index(index_path)
            print(f"索引维度: {index.d}")
            print(f"向量数量: {index.ntotal}")
            
            # 测试空查询
            dummy = np.zeros((1, index.d), dtype='float32')
            distances, ids = index.search(dummy, 3)
            print(f"测试查询结果: {len(ids[0])} 个")
            print(f"最近距离: {min(distances[0]) if len(distances[0]) > 0 else 'N/A'}")
            
        else:
            print("索引文件不存在")
            
    except Exception as e:
        print("Faiss错误:", e)

if __name__ == "__main__":
    keyword = "脑裂" if len(sys.argv) == 1 else sys.argv[1]
    test_search_simple(keyword)
    test_faiss_index()