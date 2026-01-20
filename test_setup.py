"""Quick test to verify Redis and Postgres connections."""
import asyncio
import sys
sys.path.insert(0, '.')

async def test_connections():
    print("Testing connections...\n")

    # Test Redis
    print("1. Testing Redis...")
    try:
        import redis.asyncio as redis
        r = redis.from_url("redis://localhost:6379/0")
        await r.ping()
        print("   Redis: OK")
        await r.close()
    except Exception as e:
        print(f"   Redis: FAILED - {e}")
        return False

    # Test Postgres
    print("2. Testing Postgres...")
    try:
        import asyncpg
        conn = await asyncpg.connect("postgresql://postgres:postgres@127.0.0.1:5432/pocketwatcher")
        result = await conn.fetchval("SELECT 1")
        print("   Postgres: OK")
        await conn.close()
    except Exception as e:
        print(f"   Postgres: FAILED - {e}")
        return False

    # Test imports
    print("3. Testing imports...")
    try:
        from config.settings import settings
        from storage.postgres_client import PostgresClient
        from storage.redis_client import RedisClient
        print("   Imports: OK")
    except Exception as e:
        print(f"   Imports: FAILED - {e}")
        return False

    # Test table creation
    print("4. Testing table creation...")
    try:
        from storage.postgres_client import PostgresClient
        pg = PostgresClient("postgresql://postgres:postgres@127.0.0.1:5432/pocketwatcher")
        await pg.connect()
        await pg.close()
        print("   Tables: OK")
    except Exception as e:
        print(f"   Tables: FAILED - {e}")
        return False

    print("\n All tests passed! Ready to run.")
    return True

if __name__ == "__main__":
    success = asyncio.run(test_connections())
    sys.exit(0 if success else 1)
