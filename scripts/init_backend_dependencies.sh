# Go to your monorepo root
cd ../

# Create backend folder
mkdir -p backend && cd backend

# Initialize Poetry project
poetry init --no-interaction --name naviera-backend --description "Naviera backend (FastAPI API service)" --dependency fastapi --dependency "uvicorn[standard]" --dependency sqlmodel --dependency asyncpg --dependency alembic --dependency python-dotenv --dependency python-jose --dependency "passlib[bcrypt]" --dependency httpx

# Add dev dependencies
poetry add --group dev pytest pytest-asyncio black ruff isort pre-commit

# Create basic folder structure
mkdir -p app/api app/core app/models app/db

# Create .env example
cat > .env.example << 'EOF'
# Example environment variables
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/naviera
SECRET_KEY=supersecretkey
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
EOF

# Copy to actual .env for local use (do NOT commit)
cp .env.example .env

# Create .gitignore
cat > .gitignore << 'EOF'
# Python
__pycache__/
*.pyc
*.pyo
*.pyd
*.db
*.sqlite3

# Env
.env
.venv
venv/
env/

# Poetry
poetry.lock

# IDE
.vscode/
.idea/

# Misc
.DS_Store
EOF

# Create README
cat > README.md << 'EOF'
# Naviera Backend

FastAPI-based backend for the Naviera logistics platform.

## Run locally

```bash
poetry install
poetry run uvicorn app.main:app --reload
App will be available at http://127.0.0.1:8000

EOF

# Create main FastAPI entrypoint

cat > app/main.py << 'EOF'
from fastapi import FastAPI

app = FastAPI(title="Naviera API")

@app.get("/")
async def root():
return {"message": "Hello, Naviera!"}
EOF

Initialize git if not already

if [ ! -d .git ]; then
git init
git add .
git commit -m "Initial backend setup with FastAPI and dependencies"
fi

echo "✅ Naviera backend initialized successfully!"
echo "Next: Run the server using -> poetry run uvicorn app.main:app --reload"
