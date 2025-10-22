#!/bin/sh

# Exit immediately if a command exits with a non-zero status.
set -e

# --- 1. Install System Dependencies ---
echo "Updating package list and installing prerequisites..."
sudo apt-get update
# Install tools that are available in the default repository.
sudo apt-get install -y git-lfs bat bash-completion curl netcat-openbsd

# --- 2. Install Tools Manually ---
echo "Installing Starship, and LSD manually..."
# Install Starship using its official script
curl -sS https://starship.rs/install.sh | sh -s -- --yes

# Install LSD by downloading the .deb package directly
curl -Lo lsd.deb https://github.com/lsd-rs/lsd/releases/download/v1.1.2/lsd_1.1.2_amd64.deb
sudo dpkg -i lsd.deb
rm lsd.deb # Clean up the downloaded file

# --- 3. Setup Backend Project ---
echo "Configuring Poetry and installing backend dependencies..."
poetry config virtualenvs.in-project true
cd /workspaces/naviera/backend && poetry install

# --- 4. Customize the Bash Shell ---
echo "Applying shell customizations to .bashrc..."
if ! grep -q "# --- Shell Enhancements & Aliases ---" /home/vscode/.bashrc; then
  cat <<'EOF' >> /home/vscode/.bashrc

# --- Shell Enhancements & Aliases ---
eval "$(starship init bash)"
if [ -f /etc/bash_completion ]; then . /etc/bash_completion; fi
alias reload="source ~/.bashrc && echo 'Bash configuration reloaded!'"
alias run-backend="cd /workspaces/naviera/backend && poetry run uvicorn app.main:app --host 0.0.0.0 --reload"
alias ls='lsd -l --icon=auto'
alias ll='lsd -al --icon=auto'
alias rebase='git pull; git merge origin/master; git push;'
alias cat='batcat'
EOF
fi

# --- 5. Verify VS Code Extension Installation ---
echo "Waiting for 60 seconds for VS Code server to initialize..."
sleep 60

echo "Verifying installed VS Code extensions..."
REQUESTED_EXTENSIONS="ms-python.python ms-python.vscode-pylance ms-python.black-formatter ms-python.isort charliermarsh.ruff eamodio.gitlens ms-vsliveshare.vsliveshare esbenp.prettier-vscode rangav.vscode-thunder-client ckolkman.vscode-postgres mikestead.dotenv Google.geminicodeassist Codeium.codeium Google.gemini-cli-vscode-ide-companion"

INSTALLED_EXTENSIONS=$(code --list-extensions)

for ext in $REQUESTED_EXTENSIONS; do
    case "$INSTALLED_EXTENSIONS" in
        *"$ext"*)
            ;;
        *)
            echo "⚠️  WARNING: Extension '${ext}' failed to install."
            ;;
    esac
done

echo "✅ Setup complete! Your environment is ready. Open a new terminal to see all changes."