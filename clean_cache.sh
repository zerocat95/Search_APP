#!/bin/bash

echo "Cleaning build artifacts, cache, and virtual environments..."

# Remove Python build artifacts and cache
find . -name "__pycache__" -type d -exec rm -rf {} +
find . -name "*.pyc" -type f -delete
find . -name "*.pyo" -type f -delete
find . -name "*.pyd" -type f -delete

# Remove virtual environments
rm -rf .venv/
rm -rf env/
rm -rf venv/

# Remove Node.js modules and logs
rm -rf electron_app/node_modules/
rm -f electron_app/npm-debug.log*
rm -f electron_app/yarn-debug.log*
rm -f electron_app/yarn-error.log*

# Remove common build/distribution directories
rm -rf build/
rm -rf dist/

# Remove database/cache directories
rm -rf chroma_db/

# Remove general log and temporary files
find . -name "*.log" -type f -delete
find . -name "*.tmp" -type f -delete
find . -name "*.swp" -type f -delete
find . -name "*.swo" -type f -delete

echo "Cleaning complete."
