import os
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


class Settings(BaseModel):
    sec_user_agent: str = Field(default=os.getenv("SEC_USER_AGENT", ""))
    database_url: str = Field(default=os.getenv("DATABASE_URL", "sqlite:///sec_analyzer.db"))
    raw_filings_dir: str = Field(default=os.getenv("RAW_FILINGS_DIR", "data/raw_filings"))
    processed_data_dir: str = Field(default=os.getenv("PROCESSED_DATA_DIR", "data/processed"))
    request_timeout: int = Field(default=int(os.getenv("REQUEST_TIMEOUT", "30")))
    max_requests_per_second: int = Field(default=int(os.getenv("MAX_REQUESTS_PER_SECOND", "5")))
    news_api_key: str = Field(default=os.getenv("NEWS_API_KEY", ""))
    news_api_base_url: str = Field(default=os.getenv("NEWS_API_BASE_URL", "https://newsapi.org/v2"))


settings = Settings()   