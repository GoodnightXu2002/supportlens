# SupportLens

Minimum monorepo skeleton for the SupportLens frontend and API.

## Requirements

- Python 3.12.13
- Node.js 20.19+ or 22.12+
- npm
- uv

## Backend

```powershell
cd backend
uv sync --dev
Copy-Item .env.example .env
uv run uvicorn app.main:app --reload
```

The API is available at `http://127.0.0.1:8000`. Check it with:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

Run backend checks:

```powershell
cd backend
uv run pytest
uv run ruff check .
uv run alembic current
```

Create future migrations from `backend/` with `uv run alembic revision --autogenerate -m "description"`. No business models or revisions are included in this skeleton.

## Frontend

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```

The frontend is available at `http://127.0.0.1:5173` and reads the API origin from `VITE_API_BASE_URL`.

Run frontend checks:

```powershell
cd frontend
npm run lint
npm run build
```

