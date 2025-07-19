#!/usr/bin/env python3
"""
测试子进程清理功能的脚本
"""

import os
import sys
import multiprocessing
import time
import signal
import subprocess
import psutil

def worker_task(duration):
    """模拟工作进程任务"""
    print(f"Worker {os.getpid()} started, will run for {duration} seconds")
    try:
        for i in range(duration):
            time.sleep(1)
            print(f"Worker {os.getpid()} working... {i+1}/{duration}")
    except KeyboardInterrupt:
        print(f"Worker {os.getpid()} interrupted")
    except Exception as e:
        print(f"Worker {os.getpid()} error: {e}")
    finally:
        print(f"Worker {os.getpid()} exiting")

def test_multiprocessing_cleanup():
    """测试多进程清理"""
    print("Starting multiprocessing cleanup test...")
    
    # 创建进程池
    ctx = multiprocessing.get_context('spawn')
    with multiprocessing.Pool(processes=3, context=ctx) as pool:
        try:
            # 提交一些长时间运行的任务
            results = [pool.apply_async(worker_task, (10,)) for _ in range(3)]
            
            print(f"Parent PID: {os.getpid()}")
            print("Child processes started, sleeping for 5 seconds...")
            time.sleep(5)
            
            # 模拟主进程终止
            print("Terminating main process...")
            
        except KeyboardInterrupt:
            print("Keyboard interrupt received")
        finally:
            # 进程池会自动清理
            pool.terminate()
            pool.join()
            print("All child processes terminated")

def test_process_kill_tree():
    """测试进程树清理"""
    print("Testing process tree cleanup...")
    
    # 启动一个子进程
    cmd = [
        sys.executable, "-c", 
        "import time; print('Child started'); time.sleep(30); print('Child done')"
    ]
    
    proc = subprocess.Popen(cmd)
    print(f"Started child process: {proc.pid}")
    
    time.sleep(2)
    
    # 检查子进程是否存在
    if psutil.pid_exists(proc.pid):
        print(f"Child process {proc.pid} is running")
        
        # 终止进程树
        parent = psutil.Process()
        children = parent.children(recursive=True)
        print(f"Found {len(children)} child processes")
        
        for child in children:
            try:
                child.terminate()
                child.wait(timeout=2)
                print(f"Terminated child {child.pid}")
            except psutil.TimeoutExpired:
                child.kill()
                print(f"Killed child {child.pid}")
    else:
        print("Child process already terminated")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "test_mp":
            test_multiprocessing_cleanup()
        elif sys.argv[1] == "test_kill":
            test_process_kill_tree()
    else:
        print("Usage: python test_process_cleanup.py [test_mp|test_kill]")