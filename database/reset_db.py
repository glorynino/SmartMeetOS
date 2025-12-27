from sqlalchemy import text
from database.connection import engine
from database.models import Base

def reset_database():
    print("Dropping ALL tables (with CASCADE)...")

    with engine.begin() as conn:
        conn.execute(text("""
            DROP SCHEMA public CASCADE;
            CREATE SCHEMA public;
            GRANT ALL ON SCHEMA public TO postgres;
            GRANT ALL ON SCHEMA public TO public;
        """))
    print("Creating ALL tables with updated schema...")
    Base.metadata.create_all(bind=engine)
    print("All tables recreated successfully!")
    print("\nCreated tables:")
    for table in Base.metadata.tables:
        print(f"  • {table}")

if __name__ == "__main__":
    reset_database()