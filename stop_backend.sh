#!/bin/bash

# 安全停止后端服务脚本

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
PID_FILE="$SCRIPT_DIR/backend.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "Stopping backend server with PID: $PID"
        
        # 先尝试优雅终止
        kill -TERM "$PID" 2>/dev/null
        
        # 等待最多5秒
        COUNT=0
        while ps -p "$PID" > /dev/null 2>&1 && [ $COUNT -lt 10 ]; do
            echo "Waiting for process to terminate... ($COUNT/10)"
            sleep 0.5
            COUNT=$((COUNT + 1))
        done
        
        # 如果还在运行，强制终止
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "Force killing process $PID"
            kill -KILL "$PID" 2>/dev/null
        fi
        
        rm -f "$PID_FILE"
        echo "Backend server stopped successfully"
    else
        echo "Backend server is not running"
        rm -f "$PID_FILE"
    fi
else
    echo "PID file not found, checking for running uvicorn processes..."
    
    # 从配置文件中读取端口
    CONFIG_FILE="$SCRIPT_DIR/sa_config.cfg"
    LISTEN_PORT=$(grep -E '^LISTEN_PORT\s*=' "$CONFIG_FILE" | cut -d '=' -f2 | tr -d ' ')
    
    # 查找使用该端口的进程
    PID=$(lsof -ti:"$LISTEN_PORT" 2>/dev/null)
    if [ -n "$PID" ]; then
        echo "Found process using port $LISTEN_PORT: $PID"
        kill -TERM "$PID" 2>/dev/null || kill -KILL "$PID" 2>/dev/null
        echo "Process stopped"
    else
        echo "No backend server found running"
    fi
fi