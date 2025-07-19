#!/usr/bin/env python3
"""
进程管理器：确保主进程结束时所有子进程都能被正确清理
"""

import os
import signal
import psutil
import logging
import threading
import time
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class ProcessManager:
    """管理所有后台进程和线程"""
    
    def __init__(self):
        self._cleanup_lock = threading.Lock()
        self._original_sig_handler = None
        self._setup_signal_handlers()
    
    def _setup_signal_handlers(self):
        """设置信号处理器"""
        try:
            # 保存原始信号处理器
            self._original_sig_handler = signal.getsignal(signal.SIGINT)
            
            # 设置新的信号处理器
            signal.signal(signal.SIGINT, self._graceful_shutdown)
            signal.signal(signal.SIGTERM, self._graceful_shutdown)
            
            # 设置异常钩子
            import sys
            sys.excepthook = self._exception_handler
            
            logger.info("Process signal handlers setup complete")
        except Exception as e:
            logger.warning(f"Failed to setup signal handlers: {e}")
    
    def _graceful_shutdown(self, signum, frame):
        """优雅关闭处理"""
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        
        with self._cleanup_lock:
            try:
                # 1. 关闭全局线程池
                try:
                    from backend.indexer_thread import shutdown_global_executor
                    shutdown_global_executor(wait=False)
                    logger.info("Global ThreadPoolExecutor shutdown initiated")
                except Exception as e:
                    logger.error(f"Error shutting down global executor: {e}")
                
                # 2. 杀死所有工作线程
                self._kill_all_threads()
                
                # 3. 取消所有待处理任务
                self._cancel_all_tasks()
                
                # 4. 强制终止当前进程
                self._force_terminate()
                
            except Exception as e:
                logger.error(f"Error during graceful shutdown: {e}")
                # 强制退出
                os._exit(1)
    
    def _exception_handler(self, exc_type, exc_value, exc_traceback):
        """异常处理钩子"""
        if exc_type is KeyboardInterrupt:
            logger.info("Keyboard interrupt detected, initiating shutdown...")
            self._graceful_shutdown(signal.SIGINT, None)
        else:
            # 记录异常并继续
            import traceback
            logger.error(f"Uncaught exception: {exc_value}")
            logger.error(traceback.format_exc())
    
    def _kill_all_threads(self):
        """强制终止所有工作线程"""
        try:
            import threading
            main_thread = threading.main_thread()
            
            for thread in threading.enumerate():
                if thread != main_thread and thread.is_alive():
                    logger.info(f"Interrupting thread: {thread.name}")
                    # 无法直接终止Python线程，但可以通过其他方式
                    if hasattr(thread, 'do_run'):
                        thread.do_run = False
        except Exception as e:
            logger.error(f"Error killing threads: {e}")
    
    def _cancel_all_tasks(self):
        """取消所有待处理任务"""
        try:
            # 这里可以添加取消任务的逻辑
            logger.info("Cancelling all pending tasks...")
        except Exception as e:
            logger.error(f"Error cancelling tasks: {e}")
    
    def _force_terminate(self):
        """强制终止当前进程"""
        try:
            current_process = psutil.Process()
            logger.info(f"Force terminating process {current_process.pid}")
            
            # 杀死所有子进程
            children = current_process.children(recursive=True)
            for child in children:
                try:
                    child.terminate()
                    child.wait(timeout=2)
                except psutil.TimeoutExpired:
                    child.kill()
            
            # 强制退出当前进程
            os._exit(0)
            
        except Exception as e:
            logger.error(f"Error force terminating: {e}")
            os._exit(1)
    
    def register_cleanup(self):
        """注册清理函数"""
        import atexit
        atexit.register(self._graceful_cleanup)
    
    def _graceful_cleanup(self):
        """进程退出时的清理"""
        logger.info("Process cleanup started...")
        self._graceful_shutdown(signal.SIGTERM, None)

# 全局进程管理器实例
process_manager = ProcessManager()

def ensure_cleanup():
    """确保清理函数被调用"""
    process_manager.register_cleanup()

def get_process_tree(pid=None):
    """获取进程树信息"""
    if pid is None:
        pid = os.getpid()
    
    try:
        process = psutil.Process(pid)
        tree = {
            'pid': pid,
            'name': process.name(),
            'children': []
        }
        
        for child in process.children(recursive=True):
            tree['children'].append({
                'pid': child.pid,
                'name': child.name()
            })
        
        return tree
    except psutil.NoSuchProcess:
        return None

def kill_process_tree(pid, sig=signal.SIGTERM):
    """杀死整个进程树"""
    try:
        process = psutil.Process(pid)
        children = process.children(recursive=True)
        
        for child in children:
            try:
                child.send_signal(sig)
                child.wait(timeout=2)
            except psutil.TimeoutExpired:
                child.kill()
        
        process.send_signal(sig)
        
    except psutil.NoSuchProcess:
        pass
    except Exception as e:
        logger.error(f"Error killing process tree: {e}")

if __name__ == "__main__":
    # 测试进程管理器
    process_manager = ProcessManager()
    print("Process manager initialized")