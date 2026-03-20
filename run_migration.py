import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect(
        user="sylendrar",
        password="Iceg7#XfM1t86Ut5JYg",
        database="ticketing_genie",
        host="/cloudsql/gwx-internship-01:us-east1:gwx-csql-intern-01"
    )
    with open("/app/src/data/migrations/001.__init__.sql", "r") as f:
        sql = f.read()
    await conn.execute(sql)
    await conn.close()
    print("Migration completed successfully!")

asyncio.run(main())
