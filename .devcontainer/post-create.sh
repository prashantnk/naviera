#!/bin/bash

# Exit on error
set -e

# --- Install System Dependencies ---
echo "Updating package list and installing git-lfs..."
sudo apt-get update && sudo apt-get install git-lfs -y

# --- Install Global Tools ---
echo "Installing global tools: Poetry..."
pipx install poetry

# --- Configure Poetry ---
echo "Configuring Poetry to create virtual environments inside projects..."
poetry config virtualenvs.in-project true

# --- Setup Backend Dependencies ---
echo "Changing to backend directory..."
cd /workspaces/naviera/backend

echo "Installing backend Python dependencies with Poetry..."
poetry install

echo "Setup complete! Your environment is ready."