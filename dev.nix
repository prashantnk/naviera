# dev.nix
{ pkgs, ... }: {
  channel = "unstable"; # Use unstable to ensure Node 22 and Python 3.11+ are available

  # 1. System Dependencies (Replaces your apt-get and devcontainer features)
  packages = [
    pkgs.nodejs_22
    pkgs.python311
    pkgs.poetry
    pkgs.git-lfs
    pkgs.bat
    pkgs.bash-completion
    pkgs.curl
    pkgs.netcat-openbsd
    pkgs.starship
    pkgs.lsd
  ];

  # 2. Environment Variables
  env = {};

  idx = {
    # 3. VS Code Extensions (Directly from your devcontainer.json)
    extensions = [
      "ms-python.python"
      "ms-python.vscode-pylance"
      "ms-python.black-formatter"
      "ms-python.isort"
      "charliermarsh.ruff"
      "eamodio.gitlens"
      "esbenp.prettier-vscode"
      "rangav.vscode-thunder-client"
      "ckolkman.vscode-postgres"
      "mikestead.dotenv"
      "Google.geminicodeassist"
      "Codeium.codeium"
      "dbaeumer.vscode-eslint"
      "bradlc.vscode-tailwindcss"
      "akamud.vscode-theme-onedark"
    ];

    workspace = {
      # 4. First-time Setup (Replaces your post-create.sh)
      onCreate = {
        setup-backend = "poetry config virtualenvs.in-project true && cd backend && poetry install";
        setup-frontend = "if [ -d 'frontend' ]; then cd frontend && npm install; fi";
        setup-bashrc = ''
          if ! grep -q "# --- Shell Enhancements & Aliases ---" ~/.bashrc; then
            cat <<'EOF' >> ~/.bashrc
            
            # --- Shell Enhancements & Aliases ---
            eval "$(starship init bash)"
            if [ -f /etc/bash_completion ]; then . /etc/bash_completion; fi
            alias reload="source ~/.bashrc && echo 'Bash configuration reloaded!'"
            alias run-backend="cd /workspace/naviera/backend && poetry run uvicorn app.main:app --host 0.0.0.0 --reload"
            alias run-frontend="cd /workspace/naviera/frontend && npm run dev" 
            alias ls='lsd -l --icon=auto'
            alias ll='lsd -al --icon=auto'
            alias rebase='git pull; git merge origin/master; git push;'
            alias cat='bat'
            EOF
          fi
        '';
      };
      
      # Runs every time the workspace wakes up
      onStart = {
        # You can add auto-start commands here if you want
      };
    };
  };
}
