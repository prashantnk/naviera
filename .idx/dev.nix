{ pkgs, ... }: {
  channel = "stable-23.11"; # Uses a stable Linux environment

  # System Dependencies & Terminal Tools
  packages = [
    pkgs.nodejs_20
    pkgs.python311
    pkgs.poetry
    pkgs.git-lfs
    pkgs.bat
    pkgs.bash-completion
    pkgs.curl
    pkgs.netcat-openbsd
    pkgs.lsd
    pkgs.stdenv.cc.cc.lib
  ];

  env = { };

  idx = {
    # We will add your VS Code extensions here next!
    extensions = [
      "ms-python.python"
      "ms-python.vscode-pylance"
      "ms-python.black-formatter"
      "ms-python.isort"
      "charliermarsh.ruff"
      # "eamodio.gitlens"
      #"ms-vsliveshare.vsliveshare"
      "esbenp.prettier-vscode"
      #"rangav.vscode-thunder-client"
      #"ckolkman.vscode-postgres"
      "mikestead.dotenv"
      #"Google.geminicodeassist"
      "Codeium.codeium"
      "Google.gemini-cli-vscode-ide-companion"
      #"openai.chatgpt"
      "dbaeumer.vscode-eslint"
      # "bradlc.vscode-tailwindcss"
      "akamud.vscode-theme-onedark"
    ];

    workspace = {
      # Runs once when the workspace is initially created
      onCreate = {
        setup-backend = "cd backend && poetry config virtualenvs.in-project true && poetry install";
        setup-frontend = "cd frontend && npm install";
        setup-bashrc = ''
          if ! grep -q "# --- Shell Enhancements & Aliases ---" ~/.bashrc; then
            cat <<'EOF' >> ~/.bashrc
            
            # --- Shell Enhancements & Aliases ---
            if [ -f /etc/bash_completion ]; then . /etc/bash_completion; fi
            alias reload="source ~/.bashrc && echo 'Bash configuration reloaded!'"
            alias run-backend="unset LD_LIBRARY_PATH && export LD_LIBRARY_PATH=\$(nix-build --no-out-link '<nixpkgs>' -A stdenv.cc.cc.lib)/lib && cd ~/naviera/backend && poetry run uvicorn app.main:app --host 0.0.0.0 --reload"
            alias run-frontend="unset LD_LIBRARY_PATH && cd ~/naviera/frontend && npm run dev" 
            alias ls='lsd -l --icon=auto'
            alias ll='lsd -al --icon=auto'
            alias rebase='unset && git config --global alias.sync-dev "!git checkout master && git pull && git checkout dev && git reset --hard master" && git sync-dev && git push -f origin dev'
            if command -v batcat &> /dev/null; then
                alias cat='batcat'
            elif command -v bat &> /dev/null; then
                alias cat='bat'
            fi

            # --- Naviera Workspace Local Replicator Shortcuts ---
            export-changes() {
                "~/naviera/scripts/bundle-local-changes.sh"
                echo -e "\n\033[0;32m📋 Double-click and copy the entire block below, then paste it on the target machine:\033[0m\n"
                command cat "~/naviera/apply-changes.sh"
                rm "~/naviera/apply-changes.sh"
            }

            import-changes() {
                echo -e "\033[0;32m📋 Please paste the replication script content below and press Ctrl+D when finished:\033[0m\n"
                command cat | bash
            }
            EOF
          fi
        '';
      };

      onStart = { };
    };
  };
}
