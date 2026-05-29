#!/bin/sh

# Exit immediately if a command exits with a non-zero status.
set -e

# --- 1. Install System Dependencies ---
echo "Updating package list and installing prerequisites..."
sudo apt-get update
# Added netcat-openbsd for network debugging if needed
sudo apt-get install -y git-lfs bat bash-completion curl netcat-openbsd

# --- 2. Install Tools Manually ---
echo "Installing LSD manually..."
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
    if [ -f "/workspaces/naviera/apply-changes.sh" ]; then
        # Encode the replication script to base64 and output OSC 52 copy sequence
        local b64_payload
        b64_payload=\$(base64 -w 0 "/workspaces/naviera/apply-changes.sh" 2>/dev/null || base64 "/workspaces/naviera/apply-changes.sh")
        printf "\033]52;c;%s\a" "\$b64_payload"
        echo -e "\n\033[0;32m✅ Replication script has been AUTOMATICALLY copied to your clipboard! (via OSC 52)\033[0m"
        echo -e "\033[0;32m   Go to the target machine and run 'import-changes' (then press Cmd+V and Ctrl+D).\033[0m\n"
        rm "/workspaces/naviera/apply-changes.sh"
    fi
}

import-changes() {
    echo -e "\033[0;33m🔄 Syncing dev branch with remote origin/master first...\033[0m"
    git checkout master && git pull && git checkout dev && git reset --hard master
    echo -e "\n\033[0;32m📋 Please paste the replication script content below and press Ctrl+D when finished:\033[0m\n"
    command cat | bash
}

refresh-workspace() {
    echo -e "\033[0;33m🧹 Wiping all local modifications and untracked files...\033[0m"
    git reset --hard HEAD
    git clean -fd
    echo -e "\n🔄 Pulling latest master and resetting dev..."
    git checkout master && git pull && git checkout dev && git reset --hard master
    echo -e "\n\033[0;32m✅ Workspace refreshed! Clean slate on branch dev.\033[0m"
}
EOF
fi

echo "✅ Setup complete! Open a new terminal to see changes."