import asyncio
from sqlalchemy.ext.asyncio import create_async_engine

async def main():
    engine = create_async_engine("postgresql+asyncpg://sylendrar:Iceg7%23XfM1t86Ut5JYg@34.23.138.181:5432/ticketing_genie")
    async with engine.connect() as conn:
        from sqlalchemy import text
        stmt = text("""
            SELECT
                t.ticket_id,
                t.ticket_number,
                t.title,
                te.solution_text,
                1 - (te.embedding <=> (SELECT embedding FROM ticket_embeddings LIMIT 1)) AS similarity
            FROM ticket_embeddings te
            JOIN tickets t ON t.ticket_id = te.ticket_id
            WHERE t.status IN ('RESOLVED', 'CLOSED')
              AND te.embedding IS NOT NULL
            ORDER BY te.embedding <=> (SELECT embedding FROM ticket_embeddings LIMIT 1)
            LIMIT 3;
        """)
        result = await conn.execute(stmt)
        rows = result.fetchall()
        for row in rows:
            print(f"Ticket ID: {row[0]}, Number: {row[1]}, Title: {row[2]}, Sim: {row[4]:.3f}")

asyncio.run(main())
