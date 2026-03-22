# backfill_embeddings.py
import asyncio
import sys
import os
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
os.chdir(SCRIPT_DIR)
sys.path.insert(0, str(SCRIPT_DIR / "src"))

from sqlalchemy import text
from src.data.clients.postgres_client import AsyncSessionFactory
from src.core.services.ticket_similarity_service import get_similarity_service

async def backfill():
    similarity_service = get_similarity_service()

    async with AsyncSessionFactory() as session:
        result = await session.execute(text("""
            SELECT t.ticket_id, t.title, t.description
            FROM tickets t
            LEFT JOIN ticket_embeddings te ON te.ticket_id = t.ticket_id
            WHERE te.ticket_id IS NULL AND t.status = 'RESOLVED'
        """))
        tickets = result.fetchall()
        print(f"Found {len(tickets)} tickets missing embeddings\n")

        success = 0
        failed = 0
        for ticket_id, title, description in tickets:
            try:
                await session.begin_nested()
                content = f"{title}\n\n{description}"
                await similarity_service.generate_and_store_embedding(
                    ticket_id=ticket_id,
                    content=content,
                    session=session
                )
                await session.commit()
                success += 1
                print(f"✓ [{success}] TKT {ticket_id}: {title[:50]}")
            except Exception as e:
                await session.rollback()
                failed += 1
                print(f"✗ Failed {ticket_id}: {e}")

        await session.commit()
        print(f"\n✅ Done — {success} succeeded, {failed} failed")

if __name__ == "__main__":
    asyncio.run(backfill())