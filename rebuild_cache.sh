#!/bin/bash

echo "Rebuilding virtual environment and installing dependencies..."

# Recreate Python virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org --upgrade pip
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt

# Reinstall Electron app dependencies
echo "Installing Electron app dependencies..."
cd electron_app
npm install
cd ..

echo "Rebuilding complete. You may need to run your build script (e.g., build.sh) next."
