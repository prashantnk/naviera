#!/bin/sh

# Exit immediately if a command exits with a non-zero status.
set -e

# --- 1. Install System Dependencies ---
echo "Updating package list and installing prerequisites..."
sudo apt-get update
# Added netcat-openbsd for network debugging if needed
sudo apt-get install -y git-lfs bat bash-completion curl netcat-openbsd

# --- 2. Install Tools Manually ---
echo "Installing Starship, and LSD manually..."
curl -sS https://starship.rs/install.sh | sh -s -- --yes
curl -Lo lsd.deb https://github.com/lsd-rs/lsd/releases/download/v1.1.2/lsd_1.1.2_amd64.deb
sudo dpkg -i lsd.deb
rm lsd.deb

# --- 3. Setup Backend Project ---
echo "Configuring Poetry and installing backend dependencies..."
poetry config virtualenvs.in-project true
cd /workspaces/naviera/backend && poetry install

# --- 4. Setup Frontend Project (NEW SECTION) ---
echo "Checking for Frontend dependencies..."
if [ -d "/workspaces/naviera/frontend" ]; then
    echo "Installing frontend dependencies..."
    cd /workspaces/naviera/frontend && npm install
else
    echo "Frontend folder not found yet. Skipping npm install."
fi

# --- 5. Customize the Bash Shell ---
echo "Applying shell customizations to .bashrc..."
if ! grep -q "# --- Shell Enhancements & Aliases ---" /home/vscode/.bashrc; then
  cat <<'EOF' >> /home/vscode/.bashrc

# --- Shell Enhancements & Aliases ---
eval "$(starship init bash)"
if [ -f /etc/bash_completion ]; then . /etc/bash_completion; fi
alias reload="source ~/.bashrc && echo 'Bash configuration reloaded!'"
alias run-backend="cd /workspaces/naviera/backend && poetry run uvicorn app.main:app --host 0.0.0.0 --reload"
# --- NEW ALIAS ---
alias run-frontend="cd /workspaces/naviera/frontend && npm run dev" 
alias ls='lsd -l --icon=auto'
alias ll='lsd -al --icon=auto'
alias rebase='unset && git config --global alias.sync-dev "!git checkout master && git pull && git checkout dev && git reset --hard master" && git sync-dev && git push -f origin dev'
alias cat='batcat'

# --- Naviera Workspace Local Replicator Shortcuts ---
export-changes() {
    "/workspaces/naviera/scripts/bundle-local-changes.sh"
    echo -e "\n\033[0;32m📋 Double-click and copy the entire block below, then paste it on the target machine:\033[0m\n"
    command cat "/workspaces/naviera/apply-changes.sh"
    rm "/workspaces/naviera/apply-changes.sh"
}

import-changes() {
    echo -e "\033[0;32m📋 Please paste the replication script content below and press Ctrl+D when finished:\033[0m\n"
    command cat | bash
}
EOF
fi

echo "✅ Setup complete! Open a new terminal to see changes."