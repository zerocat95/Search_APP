#!/bin/bash

# Get the directory where the script is located
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)

# Activate virtual environment
source "$SCRIPT_DIR/.venv/bin/activate"

# Set Hugging Face endpoint to mirror site for faster downloads
export HF_ENDPOINT="https://hf-mirror.com"

# Define the path to the configuration file
CONFIG_FILE="$SCRIPT_DIR/sa_config.cfg"

# Read LISTEN_IP and LISTEN_PORT from sa_config.cfg
LISTEN_IP=$(grep -E '^LISTEN_IP\s*=' "$CONFIG_FILE" | cut -d '=' -f2 | tr -d ' ')
LISTEN_PORT=$(grep -E '^LISTEN_PORT\s*=' "$CONFIG_FILE" | cut -d '=' -f2 | tr -d ' ')

# Kill any process using the configured port
lsof -ti:"$LISTEN_PORT" | xargs kill -9

# Start the FastAPI server
uvicorn main:app --host "$LISTEN_IP" --port "$LISTEN_PORT"
