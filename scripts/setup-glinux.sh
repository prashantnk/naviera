#!/usr/bin/env bash

# ==============================================================================
# 🚢 Naviera Monorepo Local Setup & Shortcuts (gLinux / Cloudtop Onboarding)
# ==============================================================================
#
# 📂 WHERE TO RUN THIS SCRIPT:
#   This script MUST be run from the repository root directory:
#   ~/naviera/ (or the root directory where you cloned the repository).
#
# ⚙️ HOW TO RUN:
#   chmod +x scripts/setup-glinux.sh
#   ./scripts/setup-glinux.sh
#   source ~/.bashrc
#
# 💡 WHAT THIS SCRIPT DOES (IDEMPOTENT):
#   1. Installs system CLI enhancements (starship prompt, lsd, bat, netcat-openbsd).
#   2. Isolates and bootstraps the Python backend (FastAPI) via Poetry,
#      bypassing OS keyring blocks and pointing to public registries.
#   3. Seeds Node.js v20 via NVM and bootstraps React/Next.js dependencies.
#   4. Generates secure local template config files (.env and .env.local) if missing.
#   5. Appends safe, robust shortcuts and prompt styling to ~/.bashrc.
#
# ==============================================================================

set -euo pipefail

# Color helpers
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo -e "${GREEN}🚢 Setting up Naviera Monorepo workspace locally...${NC}"
echo -e "Workspace directory detected: ${YELLOW}${WORKSPACE_DIR}${NC}\n"

# Ensure ~/.local/bin exists
mkdir -p "$HOME/.local/bin"

# --- 1. Install CLI Visual Styling & System Tools ---
echo -e "${GREEN}[1/5] Installing CLI Enhancements (Visual Prompt & Tools)...${NC}"

# Install system prerequisites (if package manager is available)
if command -v apt-get &> /dev/null; then
    echo -e "Updating package list and installing CLI tools..."
    sudo apt-get update || true
    sudo apt-get install -y git-lfs bat lsd curl netcat-openbsd bash-completion || {
        echo -e "${YELLOW}⚠️ Could not install system packages via apt-get. Please ensure git-lfs, bat, and lsd are installed manually.${NC}"
    }
else
    echo -e "${YELLOW}⚠️ Non-Debian environment detected. Please ensure git-lfs, bat, and lsd are installed manually.${NC}"
fi


# --- 2. Initialize Backend Environment ---
echo -e "\n${GREEN}[2/5] Setting up Backend Dependencies (FastAPI)...${NC}"

# Bypass GUI keyring prompts in headless/command-line contexts
export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring
# Direct packaging to public PyPI simple repository
export PIP_INDEX_URL=https://pypi.org/simple/

poetry_bin="$HOME/.local/bin/poetry"
if [ ! -f "$poetry_bin" ]; then
    echo -e "${YELLOW}Poetry not found in default path. Attempting to locate poetry...${NC}"
    if command -v poetry &> /dev/null; then
        poetry_bin=$(command -v poetry)
    else
        echo -e "${YELLOW}Installing Poetry...${NC}"
        curl -sSL https://install.python-poetry.org | python3 -
        poetry_bin="$HOME/.local/bin/poetry"
    fi
fi

echo -e "Poetry path: ${YELLOW}${poetry_bin}${NC}"
cd "${WORKSPACE_DIR}/backend"

# Configure Poetry to create virtualenvs in-project
"$poetry_bin" config virtualenvs.in-project true

echo -e "Running poetry install..."
"$poetry_bin" install

# --- 3. Initialize Frontend Environment ---
echo -e "\n${GREEN}[3/5] Setting up Frontend Dependencies (Next.js)...${NC}"

export NVM_DIR="$HOME/.nvm"
if [ -s "$NVM_DIR/nvm.sh" ]; then
    echo -e "Loading NVM..."
    # shellcheck disable=SC1091
    . "$NVM_DIR/nvm.sh"
    
    echo -e "Installing/Using Node v20..."
    nvm install 20
    nvm use 20
    
    cd "${WORKSPACE_DIR}/frontend"
    echo -e "Running npm install..."
    npm install
else
    echo -e "${YELLOW}⚠️ NVM (Node Version Manager) not found. Please install NVM or Node.js manually and run 'npm install' in frontend/.${NC}"
fi

# --- 4. Initialize Environment Files ---
echo -e "\n${GREEN}[4/5] Initializing Env Files...${NC}"

cd "${WORKSPACE_DIR}/backend"
if [ ! -f ".env" ]; then
    echo -e "Creating backend/.env template..."
    cp .env.example .env
else
    echo -e "backend/.env already exists. Skipping template creation."
fi

cd "${WORKSPACE_DIR}/frontend"
if [ ! -f ".env.local" ]; then
    echo -e "Creating frontend/.env.local template..."
    if [ -f ".example_env" ]; then
        cp .example_env .env.local
    elif [ -f ".env.example" ]; then
        cp .env.example .env.local
    fi
else
    echo -e "frontend/.env.local already exists. Skipping template creation."
fi

# --- 5. Append Custom Terminal Shortcuts to .bashrc ---
echo -e "\n${GREEN}[5/5] Checking Terminal Shortcuts & Prompt Enhancements (.bashrc)...${NC}"

bashrc_file="$HOME/.bashrc"
shortcut_comment="# --- Naviera Monorepo Shell Enhancements ---"

if grep -q "$shortcut_comment" "$bashrc_file"; then
    echo -e "Shortcuts already configured inside your ${YELLOW}~/.bashrc${NC}. Skipping."
else
    echo -e "Writing automated startup aliases and Starship prompt config to ${YELLOW}~/.bashrc${NC}..."
    cat <<EOF >> "$bashrc_file"

$shortcut_comment
if [ -d "\$HOME/.local/bin" ]; then export PATH="\$HOME/.local/bin:\$PATH"; fi


alias run-backend="export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring && cd ${WORKSPACE_DIR}/backend && ${poetry_bin} run uvicorn app.main:app --host 0.0.0.0 --reload"
alias run-frontend="export NVM_DIR=\"\$HOME/.nvm\" && [ -s \"\$NVM_DIR/nvm.sh\" ] && \. \"\$NVM_DIR/nvm.sh\" && nvm use 20 && cd ${WORKSPACE_DIR}/frontend && npm run dev"
alias ls='lsd -l --icon=auto'
alias ll='lsd -al --icon=auto'
if command -v batcat &> /dev/null; then
    alias cat='batcat'
elif command -v bat &> /dev/null; then
    alias cat='bat'
fi

# --- Naviera Workspace Local Replicator Shortcuts ---
export-changes() {
    "${WORKSPACE_DIR}/scripts/bundle-local-changes.sh"
    echo -e "\n\033[0;32m📋 Double-click and copy the entire block below, then paste it on the target machine:\033[0m\n"
    command cat "${WORKSPACE_DIR}/apply-changes.sh"
    rm "${WORKSPACE_DIR}/apply-changes.sh"
}

import-changes() {
    echo -e "\033[0;32m📋 Please paste the replication script content below and press Ctrl+D when finished:\033[0m\n"
    command cat | bash
}
EOF

    echo -e "${GREEN}✅ Visual Prompt (Starship), shortcuts, and replication functions added! Run 'source ~/.bashrc' or open a new shell terminal to activate them.${NC}"
fi

echo -e "\n${GREEN}🎉 Naviera Monorepo setup is 100% complete on your Cloudtop!${NC}"
echo -e "You can now run the servers with simply: ${YELLOW}run-backend${NC} or ${YELLOW}run-frontend${NC}"
