import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

DATABASE_URL = "postgresql+asyncpg://postgres:raja807@localhost:5432/ticketing_genie"

engine = create_async_engine(DATABASE_URL)

async def main():
    async with engine.begin() as conn:
        with open("src/data/migrations/agent_skills_migration.sql", "r") as f:
            sql = f.read()
        await conn.execute(text(sql))
        print("Migration and seed script executed successfully.")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
