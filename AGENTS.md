# Repository Guidelines

## Repository Map

SupportLens is a small monorepo:

- `backend/app/`: FastAPI routes, SQLAlchemy models, schemas, services, and judge logic.
- `backend/tests/`: pytest tests.
- `backend/fixtures/`: versioned JSON fixtures.
- `backend/alembic/`: Alembic migrations.
- `frontend/src/`: React/TypeScript app.
- `frontend/src/components/`: reusable components.
- `frontend/src/pages/`: routed pages.
- `frontend/public/`: static assets.

Keep API contracts synchronized between `backend/app/schemas.py` and `frontend/src/api.ts`.
Never commit `.env`, provider keys, credentials, generated build output, or unrelated local files.

## Development Rules

- Keep changes minimal and scoped to the current user request.
- Do not expand the task into follow-up optimization, refactoring, calibration, architecture work, or adjacent features unless explicitly requested.
- Avoid unrelated refactors or formatting changes.
- Apply repository style only to new or directly modified code.
- Preserve existing behavior outside the requested scope.
- If a required specification is missing or ambiguous, stop and report the gap instead of inventing product rules.

## Validation

For backend changes:
- Run targeted pytest tests for the behavior changed.
- Run `uv run ruff check .`.
- Run full `uv run pytest` only when the change has broad backend impact or the user explicitly requests it.

For frontend changes:
- Run the relevant lint/build checks.
- Manually verify affected routes or interactions when needed.

Always inspect:
- `git diff`
- `git diff --check`
- `git status --short`

If validation fails, do not commit.

## Git Workflow

Treat each explicit user development request as one task boundary.

After completing the current task:

1. Validate only the files and behavior changed in this task.
2. If unrelated or ambiguous workspace changes exist, stop and report them.
3. Stage only files belonging to the current task. Never use `git add .`.
4. If validation passes and the diff is cleanly scoped, create exactly one Git commit automatically without asking for a separate commit instruction.
5. Use the repository's existing Conventional Commit style (`feat:`, `fix:`, `test:`, `revert:`).
6. Do not run `git push`, `git pull`, `git reset`, `git rebase`, `git clean`, `git commit --amend`, force operations, or other destructive Git commands unless explicitly requested.
7. After committing, report:
   - commit hash
   - commit message
   - validation result
   - final `git status --short`
8. Stop after the current task. Do not begin another task without a new user instruction.

## Coding Conventions

Python:
- Python 3.12, type hints, Ruff.
- `snake_case` for functions/modules, `PascalCase` for classes.

TypeScript:
- Follow existing ESLint/project conventions.
- `PascalCase` for React components/pages, `camelCase` for functions and variables.
- Keep page-specific CSS beside its page.
