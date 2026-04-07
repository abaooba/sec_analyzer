from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import settings
from app.models import Base

engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, future=True)


def init_db():
    Base.metadata.create_all(engine)