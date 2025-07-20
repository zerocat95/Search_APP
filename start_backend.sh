#!/bin/bash

# 获取脚本所在目录
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)

# 设置虚拟环境路径（在用户目录下）
VENV_DIR="$HOME/.search_app/.venv"

# 检查虚拟环境是否存在
if [ ! -d "$VENV_DIR" ]; then
    echo "错误: Python虚拟环境不存在，请先运行初始化脚本"
    echo "虚拟环境路径: $VENV_DIR"
    exit 1
fi

# 激活虚拟环境
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

exec python "$SCRIPT_DIR/main.py"
