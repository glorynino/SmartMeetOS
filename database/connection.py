import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "Missing DATABASE_URL. Set it to your Supabase Postgres connection string (include sslmode=require if needed)."
    )


engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()





def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()