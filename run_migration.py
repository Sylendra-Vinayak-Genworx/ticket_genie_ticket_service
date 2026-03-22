#!/usr/bin/env python3
"""
Simple Migration Runner - Run Single Migration
==============================================
Runs the solution_text migration directly without the full runner.

Usage:
    python run_embedding_migration.py
"""
import asyncio
import asyncpg
import sys
from pathlib import Path


async def run_migration():
    """Run the solution_text migration."""
    
    # Database connection string
    DATABASE_URL = "postgresql://sylendrar:Iceg7%23XfM1t86Ut5JYg@34.23.138.181/ticketing_genie"
    
    print("=" * 60)
    print("EMBEDDING MIGRATION - Add solution_text column")
    print("=" * 60)
    print()
    
    # Read migration SQL
    migration_file = Path("/home/sylendra/projects/ticketing_genie/backend/ticketing_service/008_add_solution_text.sql")
    
    if not migration_file.exists():
        print(f"❌ ERROR: Migration file not found: {migration_file}")
        sys.exit(1)
    
    sql = migration_file.read_text(encoding="utf-8")
    
    print(f"📄 Migration file: {migration_file.name}")
    print(f"📝 SQL Preview:")
    print("-" * 60)
    print(sql[:300] + "..." if len(sql) > 300 else sql)
    print("-" * 60)
    print()
    
    # Connect to database
    print("🔌 Connecting to database...")
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        print("✅ Connected successfully!")
        print()
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        sys.exit(1)
    
    try:
        # Check if column already exists
        print("🔍 Checking if solution_text column already exists...")
        check_sql = """
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'ticket_embeddings' 
              AND column_name = 'solution_text'
        """
        existing = await conn.fetch(check_sql)
        
        if existing:
            print("⚠️  Column 'solution_text' already exists!")
            print("   Skipping migration (already applied)")
            return
        
        print("✅ Column does not exist - proceeding with migration")
        print()
        
        # Run migration
        print("🚀 Running migration...")
        async with conn.transaction():
            await conn.execute(sql)
        
        print("✅ Migration completed successfully!")
        print()
        
        # Verify
        print("🔍 Verifying migration...")
        verify_sql = """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'ticket_embeddings'
            ORDER BY ordinal_position
        """
        columns = await conn.fetch(verify_sql)
        
        print("📊 Current ticket_embeddings schema:")
        print("-" * 60)
        for col in columns:
            nullable = "NULL" if col['is_nullable'] == 'YES' else "NOT NULL"
            print(f"  - {col['column_name']:<20} {col['data_type']:<15} {nullable}")
        print("-" * 60)
        print()
        
        # Check if solution_text is there
        has_solution_text = any(col['column_name'] == 'solution_text' for col in columns)
        if has_solution_text:
            print("✅ SUCCESS: solution_text column added!")
        else:
            print("❌ ERROR: solution_text column not found after migration!")
            sys.exit(1)
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await conn.close()
        print()
        print("🔌 Database connection closed")
    
    print()
    print("=" * 60)
    print("✅ MIGRATION COMPLETE")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  1. Deploy updated code files")
    print("  2. Restart Celery worker")
    print("  3. Mark a ticket as RESOLVED to test")


if __name__ == "__main__":
    print()
    asyncio.run(run_migration())