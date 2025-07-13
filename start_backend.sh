#!/bin/bash

# Get the directory where the script is located
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)

# Activate virtual environment
source "$SCRIPT_DIR/.venv/bin/activate"

# Set Hugging Face endpoint to mirror site for faster downloads
export HF_ENDPOINT="https://hf-mirror.com"

# Kill any process using port 8233
lsof -ti:8233 | xargs kill -9

# Start the FastAPI server
uvicorn main:app --host 127.0.0.1 --port 8233
