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

# ⚠️ This is the URI Chainlit uses (Async)
DB_URI = f"postgresql+asyncpg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@localhost:5442/{POSTGRES_DB}"

async def test_connection():
    print(f"🔌 ATTEMPTING CONNECTION TO:\n   {DB_URI}")
    print("-" * 50)
    
    try:
        # 1. Create Engine
        engine = create_async_engine(DB_URI)
        
        # 2. Try to Connect
        async with engine.connect() as conn:
            print("✅ CONNECTION SUCCESSFUL!")
            
            # 3. Check for Chainlit Tables
            result = await conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public';"))
            tables = [row[0] for row in result.fetchall()]
            print(f"📂 Tables found in DB: {tables}")
            
            if "users" in tables and "threads" in tables:
                print("✅ Chainlit Tables Exist.")
            else:
                print("❌ Chainlit Tables are MISSING. Chainlit cannot save history.")

    except ImportError:
        print("❌ CRITICAL ERROR: 'asyncpg' module is missing.")
        print("   👉 Run: pip install asyncpg")
        
    except Exception as e:
        print(f"❌ CONNECTION FAILED: {type(e).__name__}")
        print(f"   Error Details: {e}")
        
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(test_connection())