import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent


def resolve_storage_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path

    candidates = [
        BACKEND_DIR / path,
        REPO_ROOT / path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()

    return (BACKEND_DIR / path).resolve()


def resolve_database_url(database_url: str) -> str:
    sqlite_prefix = "sqlite:///"
    sqlite_absolute_prefix = "sqlite:////"

    if not database_url.startswith(sqlite_prefix) or database_url.startswith(sqlite_absolute_prefix):
        return database_url

    raw_path = database_url[len(sqlite_prefix):]
    resolved_path = resolve_storage_path(raw_path)
    return f"{sqlite_prefix}{resolved_path}"


class Settings(BaseModel):
    sec_user_agent: str = Field(default=os.getenv("SEC_USER_AGENT", ""))
    database_url: str = Field(default=resolve_database_url(os.getenv("DATABASE_URL", "sqlite:///sec_analyzer.db")))
    raw_filings_dir: str = Field(default=str(resolve_storage_path(os.getenv("RAW_FILINGS_DIR", "data/raw_filings"))))
    processed_data_dir: str = Field(default=str(resolve_storage_path(os.getenv("PROCESSED_DATA_DIR", "data/processed"))))
    request_timeout: int = Field(default=int(os.getenv("REQUEST_TIMEOUT", "30")))
    max_requests_per_second: int = Field(default=int(os.getenv("MAX_REQUESTS_PER_SECOND", "5")))
    news_api_key: str = Field(default=os.getenv("NEWS_API_KEY", ""))
    news_api_base_url: str = Field(default=os.getenv("NEWS_API_BASE_URL", "https://newsapi.org/v2"))


settings = Settings()   
