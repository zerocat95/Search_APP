#!/bin/bash

# 安全的后端启动脚本，支持优雅终止

# Get the directory where the script is located
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)

# 激活虚拟环境
source "$SCRIPT_DIR/.venv/bin/activate"

# 设置环境变量
export HF_ENDPOINT="https://hf-mirror.com"
export KMP_DUPLICATE_LIB_OK=TRUE
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

# 定义配置文件路径
CONFIG_FILE="$SCRIPT_DIR/sa_config.cfg"

# 从配置文件中读取监听IP和端口
LISTEN_IP=$(grep -E '^LISTEN_IP\s*=' "$CONFIG_FILE" | cut -d '=' -f2 | tr -d ' ')
LISTEN_PORT=$(grep -E '^LISTEN_PORT\s*=' "$CONFIG_FILE" | cut -d '=' -f2 | tr -d ' ')

# 杀死任何使用配置端口的进程
echo "Cleaning up existing processes on port $LISTEN_PORT..."
lsof -ti:"$LISTEN_PORT" | xargs kill -9 2>/dev/null || true

# 创建PID文件存储进程ID
PID_FILE="$SCRIPT_DIR/backend.pid"

# 如果PID文件存在，检查进程是否还在运行
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "Killing old backend process $OLD_PID..."
        kill -TERM "$OLD_PID" 2>/dev/null || kill -KILL "$OLD_PID" 2>/dev/null || true
        sleep 2
    fi
    rm -f "$PID_FILE"
fi

# 启动 FastAPI 服务器，并将PID写入文件
echo "Starting backend server on $LISTEN_IP:$LISTEN_PORT..."
cd "$SCRIPT_DIR"
nohup uvicorn main:app --host "$LISTEN_IP" --port "$LISTEN_PORT" > backend.log 2>&1 &
NEW_PID=$!
echo $NEW_PID > "$PID_FILE"

echo "Backend server started with PID: $NEW_PID"
echo "PID saved to: $PID_FILE"
echo "Logs are being written to: backend.log"

# 等待进程启动
sleep 2

# 检查进程是否成功启动
if ps -p "$NEW_PID" > /dev/null 2>&1; then
    echo "Backend server is running successfully!"
    echo "To stop the server, run: kill -TERM $NEW_PID"
else
    echo "Failed to start backend server. Check backend.log for details."
    rm -f "$PID_FILE"
    exit 1
fi