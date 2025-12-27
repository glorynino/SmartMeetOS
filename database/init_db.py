import sys
import os
from dotenv import load_dotenv

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

load_dotenv(os.path.join(project_root, '.env'))

from database.connection import engine
from database.models import Base

def create_tables():
    print(f"Project root: {project_root}")
    print(f"Connecting to Supabase...")

    if engine is None:
        print("Error: DATABASE_URL is not set (engine not configured).")
        sys.exit(1)

    try:
        print("Creating tables...")
        Base.metadata.create_all(bind=engine)
        print("Success! All tables created in Supabase.")
        print("\nCreated tables:")
        for table in Base.metadata.tables:
            print(f"  • {table}")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    create_tables()