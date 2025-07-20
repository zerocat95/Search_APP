#!/bin/bash

# 获取脚本所在目录
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)

# --- Python Virtual Environment Setup ---
VENV_DIR="$HOME/.search_app/.venv"
REQUIREMENTS_FILE="$SCRIPT_DIR/requirements.txt"

# Function to check for python3
check_python3() {
    if ! command -v python3 &> /dev/null; then
        echo "INIT_STATUS:ERROR: python3 is not installed. Please install Python 3.8 or higher."
        exit 1
    fi
}

# Check if venv exists, if not, create it and install packages
if [ ! -d "$VENV_DIR" ]; then
    echo "INIT_STATUS:正在准备Python虚拟环境,预计3-5分钟就绪..."
    check_python3
    python3 -m venv "$VENV_DIR"
    if [ $? -ne 0 ]; then
        echo "INIT_STATUS:ERROR: Failed to create Python virtual environment."
        exit 1
    fi
    
    echo "INIT_STATUS:正在安装依赖包,请稍候..."
    "$VENV_DIR/bin/pip" install --no-cache-dir -r "$REQUIREMENTS_FILE" -i https://pypi.tuna.tsinghua.edu.cn/simple
    if [ $? -ne 0 ]; then
        echo "INIT_STATUS:ERROR: Failed to install dependencies from requirements.txt."
        exit 1
    fi
    echo "INIT_STATUS:Python环境准备就绪!"
fi

# Activate virtual environment
source "$VENV_DIR/bin/activate"

# 设置Hugging Face镜像站点
export HF_ENDPOINT="https://hf-mirror.com"

# 读取配置文件
CONFIG_FILE="$SCRIPT_DIR/sa_config.cfg"

# 获取监听IP和端口
LISTEN_IP=$(grep -E '^LISTEN_IP\s*=' "$CONFIG_FILE" | cut -d '=' -f2 | tr -d ' ')
LISTEN_PORT=$(grep -E '^LISTEN_PORT\s*=' "$CONFIG_FILE" | cut -d '=' -f2 | tr -d ' ')

# 清理占用端口的进程
lsof -ti:"$LISTEN_PORT" 2>/dev/null | xargs kill -9 2>/dev/null || true

# 设置环境变量防止macOS特定问题
export KMP_DUPLICATE_LIB_OK=TRUE
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

# 设置日志目录
export LOG_DIR="$HOME/.search_app/logs"
mkdir -p "$LOG_DIR"

# 启动FastAPI服务器
echo "使用虚拟环境: $VENV_DIR"
echo "启动FastAPI服务器: http://$LISTEN_IP:$LISTEN_PORT"

# Launch the main Python application
# Launch the main Python application
echo "INIT_STATUS:正在加载AI模型,请稍候..."
exec python "$SCRIPT_DIR/main.py"
