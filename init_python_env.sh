#!/bin/bash

# 初始化Python虚拟环境的脚本
# 使用方式: ./init_python_env.sh requirements.txt

set -e

# 获取参数
REQUIREMENTS_FILE="$1"
if [ -z "$REQUIREMENTS_FILE" ]; then
    echo "用法: $0 <requirements.txt路径>"
    exit 1
fi

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 设置虚拟环境路径
VENV_DIR="$HOME/.search_app/.venv"
LOG_FILE="$HOME/.search_app/init_python_env.log"

# 创建日志目录
mkdir -p "$HOME/.search_app/logs"
mkdir -p "$(dirname "$VENV_DIR")"

# 记录开始时间
echo "$(date): 开始初始化Python环境" >> "$LOG_FILE"

# 检测Python命令
PYTHON_CMD=""
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo "错误: 未找到Python命令" | tee -a "$LOG_FILE"
    exit 1
fi

# 检测系统架构
ARCH=$(uname -m)
echo "$(date): 系统架构: $ARCH" >> "$LOG_FILE"
echo "$(date): Python版本: $($PYTHON_CMD --version)" >> "$LOG_FILE"

# 创建虚拟环境
echo "创建Python虚拟环境 ($ARCH)..." | tee -a "$LOG_FILE"
if [ -d "$VENV_DIR" ]; then
    echo "虚拟环境已存在，正在删除重建..." | tee -a "$LOG_FILE"
    rm -rf "$VENV_DIR"
fi

$PYTHON_CMD -m venv "$VENV_DIR"

# 激活虚拟环境
source "$VENV_DIR/bin/activate"

# 升级pip
echo "升级pip..." | tee -a "$LOG_FILE"
python -m pip install --upgrade pip

# 安装依赖
echo "安装依赖包..." | tee -a "$LOG_FILE"
if [ -f "$REQUIREMENTS_FILE" ]; then
    pip install -r "$REQUIREMENTS_FILE"
else
    echo "警告: 未找到requirements.txt文件，使用默认安装" | tee -a "$LOG_FILE"
    pip install fastapi uvicorn[standard] sqlite3 fts5
fi

echo "$(date): Python环境初始化完成" >> "$LOG_FILE"
echo "虚拟环境路径: $VENV_DIR"
echo "激活命令: source $VENV_DIR/bin/activate"