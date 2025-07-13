#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

echo "Starting the build process..."

# --- Pre-build Checks ---
if [ ! -f "requirements.txt" ]; then
    echo "Error: requirements.txt not found. Please ensure it exists in the project root."
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "Virtual environment not found. Creating and installing dependencies..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
else
    echo "Virtual environment found. Activating..."
    source .venv/bin/activate
fi

# --- Electron App Build ---
echo "Navigating to electron_app directory..."
cd electron_app

# Check if package.json exists
if [ ! -f "package.json" ]; then
    echo "Error: package.json not found in electron_app/. Please ensure it exists."
    exit 1
fi

# Install Electron app dependencies
echo "Installing Electron app dependencies..."
npm install --registry=https://registry.npmmirror.com || {
    echo "Error: npm install failed. Please check your network connection or npm configuration."
    exit 1
}

# Build Electron application
echo "Building Electron application..."
npm run build || {
    echo "Error: npm run build failed. Please check Electron app build configuration."
    exit 1
}

echo "Returning to project root directory..."
cd ..

echo "Build process completed successfully!"