import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from dotenv import load_dotenv
import os

load_dotenv()

# Get Config from .env
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "password")
POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")
DB_URI = f"postgresql+asyncpg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@localhost:5442/{POSTGRES_DB}?sslmode=disable"

async def check_database():
    print(f"🔌 Connecting to: {DB_URI}")
    try:
        engine = create_async_engine(DB_URI)
        async with engine.connect() as conn:
            print("✅ Connection Successful!")
            
            # 1. Check Tables
            result = await conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public';"))
            tables = [row[0] for row in result.fetchall()]
            print(f"\n📂 Found Tables: {tables}")
            
            if "threads" not in tables:
                print("❌ ERROR: 'threads' table is MISSING. Chainlit did not create the database schema.")
                return

            # 2. Check Users
            result = await conn.execute(text("SELECT * FROM users;"))
            users = result.fetchall()
            print(f"\n👤 Users in DB: {users}")
            
            # 3. Check Threads (Chats)
            result = await conn.execute(text("SELECT * FROM threads;"))
            threads = result.fetchall()
            print(f"\n💬 Threads (Chats) in DB: {threads}")
            
    except Exception as e:
        print(f"\n❌ CRITICAL ERROR: {e}")
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(check_database())