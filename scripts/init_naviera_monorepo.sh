#This script initializes a monorepo structure for a project named "naviera"
#This should be run in an empty directory where you want to set up the monorepo.
#As naviera grows, you will clone the repo and do not need to run this again.

#!/usr/bin/env bash
set -euo pipefail

# -------- CONFIG --------
REPO_NAME="naviera"
GITHUB_USER="prashantnk"   # <-- change this
VISIBILITY="public"                  # or "private"
# ------------------------

# Create project root
mkdir -p $REPO_NAME/{frontend,backend}
cd $REPO_NAME

# --- Top-level README ---
cat > README.md <<'README'
# Naviera Monorepo 🚢

This is the **monorepo** for Naviera — a multi-tenant logistics platform.

### Structure
- `frontend/` → Next.js (to be added later)
- `backend/`  → FastAPI (development starts here)

---

**Setup Steps**
1. Clone the repo
2. Navigate to `backend/` and follow the README inside
3. More services will be added here as Naviera grows
README

# --- .gitignore ---
cat > .gitignore <<'GITIGNORE'
# Node / Frontend
node_modules/
.next/
dist/

# Python / Backend
__pycache__/
*.py[cod]
.venv/
.env
*.egg-info/
poetry.lock
__pypackages__/

# IDE / Editor
.vscode/
.idea/

# OS
.DS_Store
Thumbs.db
GITIGNORE

# --- Optional LICENSE ---
cat > LICENSE <<'LICENSE'
MIT License

Copyright (c) 2025 Naviera

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
LICENSE

# --- Initialize Git ---
git init
git add .
git commit -m "chore: initialize monorepo with frontend and backend folders"

# --- Push to GitHub (optional) ---
if command -v gh &>/dev/null; then
  echo "✅ GitHub CLI found. Creating repo on GitHub..."
  gh repo create "$GITHUB_USER/$REPO_NAME" --$VISIBILITY --source=. --remote=origin --push
else
  echo "⚠️ GitHub CLI not found. Please create the repo manually:"
  echo "git remote add origin git@github.com:$GITHUB_USER/$REPO_NAME.git"
  echo "git push -u origin main"
fi

echo "🎉 Monorepo '$REPO_NAME' created successfully with frontend/ and backend/ folders!"
