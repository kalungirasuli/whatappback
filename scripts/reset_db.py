import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect("postgresql://postgres:postgres@localhost:5433/postgres")
    await conn.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = 'whatappseller' AND pid != pg_backend_pid()"
    )
    await conn.execute("DROP DATABASE IF EXISTS whatappseller")
    await conn.execute("CREATE DATABASE whatappseller")
    await conn.close()
    print("DB dropped and recreated")

asyncio.run(main())
