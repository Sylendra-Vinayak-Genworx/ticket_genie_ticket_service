#!/usr/bin/env python3
"""
Debug Script - Check Embedding System Step by Step
"""
import asyncio
import asyncpg
import sys


async def debug_embeddings():
    """Debug the embedding system step by step."""
    
    DATABASE_URL = "postgresql://sylendrar:Iceg7%23XfM1t86Ut5JYg@34.23.138.181/ticketing_genie"
    
    print("=" * 80)
    print("EMBEDDING SYSTEM DEBUG - Step by Step")
    print("=" * 80)
    print()
    
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        print("✅ Connected to database")
        print()
        
        # Step 1: Check if ticket_embeddings table exists
        print("STEP 1: Check if ticket_embeddings table exists")
        print("-" * 80)
        result = await conn.fetch("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'ticket_embeddings'
            )
        """)
        table_exists = result[0]['exists']
        print(f"Table exists: {table_exists}")
        
        if not table_exists:
            print("❌ ERROR: ticket_embeddings table does not exist!")
            print("   Create it first before proceeding.")
            return
        print()
        
        # Step 2: Check table structure
        print("STEP 2: Check table structure")
        print("-" * 80)
        columns = await conn.fetch("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'ticket_embeddings'
            ORDER BY ordinal_position
        """)
        for col in columns:
            nullable = "NULL" if col['is_nullable'] == 'YES' else "NOT NULL"
            print(f"  - {col['column_name']:<20} {col['data_type']:<15} {nullable}")
        
        has_solution_text = any(col['column_name'] == 'solution_text' for col in columns)
        if has_solution_text:
            print("✅ solution_text column exists")
        else:
            print("⚠️  solution_text column missing (old embeddings won't have solutions)")
        print()
        
        # Step 3: Count total embeddings
        print("STEP 3: Count embeddings in database")
        print("-" * 80)
        result = await conn.fetch("""
            SELECT 
                COUNT(*) as total_embeddings,
                COUNT(embedding) as has_embedding,
                COUNT(solution_text) as has_solution
            FROM ticket_embeddings
        """)
        row = result[0]
        print(f"Total rows:           {row['total_embeddings']}")
        print(f"With embeddings:      {row['has_embedding']}")
        print(f"With solution_text:   {row['has_solution']}")
        
        if row['total_embeddings'] == 0:
            print("❌ ERROR: No embeddings in database!")
            print("   Mark some tickets as RESOLVED to generate embeddings.")
            return
        print()
        
        # Step 4: Check RESOLVED/CLOSED tickets
        print("STEP 4: Check RESOLVED/CLOSED tickets with embeddings")
        print("-" * 80)
        result = await conn.fetch("""
            SELECT 
                t.status,
                COUNT(*) as count
            FROM ticket_embeddings te
            JOIN tickets t ON t.ticket_id = te.ticket_id
            WHERE te.embedding IS NOT NULL
            GROUP BY t.status
            ORDER BY count DESC
        """)
        
        if not result:
            print("❌ ERROR: No tickets with embeddings!")
        else:
            for row in result:
                print(f"  {row['status']:<15} {row['count']} tickets")
        
        resolved_or_closed = await conn.fetch("""
            SELECT COUNT(*) as count
            FROM ticket_embeddings te
            JOIN tickets t ON t.ticket_id = te.ticket_id
            WHERE te.embedding IS NOT NULL
              AND t.status IN ('RESOLVED', 'CLOSED')
        """)
        
        searchable_count = resolved_or_closed[0]['count']
        print(f"\n✅ Searchable tickets (RESOLVED/CLOSED): {searchable_count}")
        
        if searchable_count == 0:
            print("❌ ERROR: No RESOLVED or CLOSED tickets with embeddings!")
            print("   Similarity search only works on RESOLVED/CLOSED tickets.")
            return
        print()
        
        # Step 5: Sample some embeddings
        print("STEP 5: Sample embeddings data")
        print("-" * 80)
        samples = await conn.fetch("""
            SELECT 
                t.ticket_id,
                t.ticket_number,
                t.title,
                t.status,
                te.embedding IS NOT NULL as has_embedding,
                LENGTH(te.solution_text) as solution_length
            FROM ticket_embeddings te
            JOIN tickets t ON t.ticket_id = te.ticket_id
            WHERE t.status IN ('RESOLVED', 'CLOSED')
            LIMIT 5
        """)
        
        for row in samples:
            emb = "✓" if row['has_embedding'] else "✗"
            sol_len = row['solution_length'] if row['solution_length'] else 0
            print(f"  [{emb}] {row['ticket_number']} | {row['status']} | "
                  f"solution: {sol_len} chars | {row['title'][:40]}")
        print()
        
        # Step 6: Test embedding similarity search
        print("STEP 6: Test similarity search with sample query")
        print("-" * 80)
        print("Query: 'Login issue'")
        print()
        
        # First, let's check if we can generate an embedding
        print("Generating test embedding...")
        try:
            from langchain_community.embeddings import HuggingFaceEmbeddings
            embeddings = HuggingFaceEmbeddings(
                model_name="sentence-transformers/all-mpnet-base-v2",
                model_kwargs={'device': 'cpu'},
                encode_kwargs={'normalize_embeddings': True}
            )
            test_embedding = embeddings.embed_query("Login issue")
            print(f"✅ Test embedding generated: {len(test_embedding)} dimensions")
            embedding_str = "[" + ",".join(f"{v:.8f}" for v in test_embedding) + "]"
        except Exception as e:
            print(f"❌ Failed to generate test embedding: {e}")
            return
        print()
        
        # Run similarity search
        print("Running similarity search (min_similarity=0.1 for testing)...")
        results = await conn.fetch("""
            SELECT
                t.ticket_id,
                t.ticket_number,
                t.title,
                t.status,
                1 - (te.embedding <=> CAST($1 AS vector)) AS similarity
            FROM ticket_embeddings te
            JOIN tickets t ON t.ticket_id = te.ticket_id
            WHERE t.status IN ('RESOLVED', 'CLOSED')
              AND te.embedding IS NOT NULL
            ORDER BY te.embedding <=> CAST($1 AS vector)
            LIMIT 10
        """, embedding_str)
        
        print(f"\nFound {len(results)} similar tickets:")
        print("-" * 80)
        
        if not results:
            print("❌ No similar tickets found!")
            print("\nPossible issues:")
            print("  1. Embeddings may be corrupted")
            print("  2. Vector extension not properly configured")
            print("  3. Embedding dimensions mismatch")
        else:
            for row in results:
                sim_score = round(float(row['similarity']), 3)
                stars = "★" * int(sim_score * 5)
                print(f"  [{sim_score:.3f}] {stars:<5} {row['ticket_number']} | {row['title'][:50]}")
        print()
        
        # Step 7: Check vector extension
        print("STEP 7: Check pgvector extension")
        print("-" * 80)
        result = await conn.fetch("""
            SELECT * FROM pg_extension WHERE extname = 'vector'
        """)
        
        if result:
            print("✅ pgvector extension is installed")
        else:
            print("❌ ERROR: pgvector extension not found!")
            print("   Install it with: CREATE EXTENSION vector;")
        print()
        
        # Step 8: Summary
        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)
        
        if searchable_count > 0 and len(results) > 0:
            print("✅ Embedding system is working!")
            print(f"   - {searchable_count} searchable tickets")
            print(f"   - Similarity search returned {len(results)} results")
            print()
            print("If API returns 0 results, check:")
            print("  1. min_similarity threshold (try 0.1 instead of 0.3)")
            print("  2. Query text (try exact title from sample above)")
            print("  3. API logs for errors")
        else:
            print("❌ Embedding system has issues!")
            print("   Review errors above and fix them.")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(debug_embeddings())