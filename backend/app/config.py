"""Central configuration for the whole app.

Everything that the app needs to know about *its environment* lives here:
where the database is, where to cache downloaded filings, what user-agent to
send to the SEC, and which API keys are available. The rest of the codebase
imports the single `settings` instance at the bottom of this file and never
touches `os.environ` directly — that keeps configuration in one place.

Key ideas demonstrated here:
- `python-dotenv` loads a local `.env` file into environment variables so
  secrets stay out of source control (see `.gitignore`).
- `pydantic.BaseModel` is used as a lightweight, typed settings container.
- Paths are resolved *relative to the repo* (not the current working
  directory) so the app behaves the same whether you launch it from the repo
  root, the backend folder, or uvicorn.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# `__file__` is .../backend/app/config.py, so parents[1] is the backend dir
# and its parent is the repo root. Resolving these once lets us build absolute
# paths that don't depend on where the process was started.
BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent


def _load_env_files(*candidate_paths: Path) -> list[Path]:
    """Load each existing `.env` (in order) into os.environ without overriding
    values already set in the real environment. Returns the paths actually loaded.

    We load by *explicit absolute path* rather than a bare `load_dotenv()`: the
    bare call searches upward from the current working directory, so a process
    launched from outside the repo tree (a service, an installed entry point, a
    different cwd) finds no `.env` — the Groq key silently stays unset and
    `llm_analysis` quietly degrades to rule-only output. Explicit paths make
    configuration loading independent of the launch directory.
    """
    loaded: list[Path] = []
    for path in candidate_paths:
        if path.is_file():
            load_dotenv(path)  # override=False by default: real env wins
            loaded.append(path)
    return loaded


# The repo-root `.env` is the documented location (see `.env.example`);
# `backend/app/.env` is a legacy fallback for older setups. Loaded once at import
# so every os.getenv() below sees the values regardless of the launch directory.
_loaded_env_files = _load_env_files(REPO_ROOT / ".env", BACKEND_DIR / "app" / ".env")


def resolve_storage_path(path_value: str) -> Path:
    """Turn a possibly-relative path string into a concrete absolute Path.

    Absolute paths are returned untouched. Relative paths are tried first
    against the backend dir, then the repo root, returning the first that
    actually exists; if neither exists we still return the backend-dir version
    (so callers can create it). This is why the same DB/cache resolves
    correctly no matter the launch directory.
    """
    path = Path(path_value)
    if path.is_absolute():
        return path

    # Prefer an existing file under the backend dir, then the repo root.
    candidates = [
        BACKEND_DIR / path,
        REPO_ROOT / path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()

    # Nothing exists yet (e.g. first run, DB not created) — default to backend.
    return (BACKEND_DIR / path).resolve()


def resolve_database_url(database_url: str) -> str:
    """Rewrite a relative SQLite URL into an absolute one.

    SQLAlchemy URLs look like `sqlite:///relative/path.db` (3 slashes =
    relative) or `sqlite:////abs/path.db` (4 slashes = absolute). Only the
    relative form needs fixing; everything else (already-absolute SQLite, or a
    Postgres/MySQL URL) is passed straight through.
    """
    sqlite_prefix = "sqlite:///"
    sqlite_absolute_prefix = "sqlite:////"

    # Not a relative-SQLite URL -> leave it alone.
    if not database_url.startswith(sqlite_prefix) or database_url.startswith(sqlite_absolute_prefix):
        return database_url

    # Strip the prefix, resolve the path to absolute, then re-attach the prefix.
    raw_path = database_url[len(sqlite_prefix):]
    resolved_path = resolve_storage_path(raw_path)
    return f"{sqlite_prefix}{resolved_path}"


class Settings(BaseModel):
    """Typed bag of settings, each defaulting from an env var (or a fallback).

    Using pydantic here gives free type coercion (e.g. the timeout strings
    become ints) and a clean attribute API: `settings.sec_user_agent`, etc.
    """

    # The SEC *requires* a descriptive User-Agent (name + email) on every
    # request or it returns 403. Set this in .env as SEC_USER_AGENT.
    sec_user_agent: str = Field(default=os.getenv("SEC_USER_AGENT", ""))
    # SQLAlchemy connection URL; defaults to a local SQLite file.
    database_url: str = Field(default=resolve_database_url(os.getenv("DATABASE_URL", "sqlite:///sec_analyzer.db")))
    # Where downloaded raw filing HTML is cached on disk before parsing.
    raw_filings_dir: str = Field(default=str(resolve_storage_path(os.getenv("RAW_FILINGS_DIR", "data/raw_filings"))))
    request_timeout: int = Field(default=int(os.getenv("REQUEST_TIMEOUT", "30")))
    # Client-side rate limit for SEC requests (see sec_client._throttle), kept
    # under the SEC's fair-access policy so the ingest loop doesn't get blocked.
    max_requests_per_second: int = Field(default=int(os.getenv("MAX_REQUESTS_PER_SECOND", "5")))
    # API key for the Groq LLM (Llama 3.3 70B) used in llm_analysis.py.
    groq_api_key: str = Field(default=os.getenv("GROQ_API_KEY", ""))


# The single shared settings instance imported everywhere else in the app.
settings = Settings()
