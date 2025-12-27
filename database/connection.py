import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


engine = create_engine(DATABASE_URL) if DATABASE_URL else None
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine) if engine else None
Base = declarative_base()





def get_db():
    if SessionLocal is None:
        raise RuntimeError(
            "DATABASE_URL is not set. Configure it in the environment (or .env) before using the database."
        )
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()