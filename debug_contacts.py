#!/usr/bin/env python3
"""
Debug script to diagnose contacts page 500 error.
Run this on your server to identify the issue.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from workspace_secretary.config import load_config


def check_contacts_tables():
    print("=== Contacts Page Diagnostic ===\n")

    config = load_config("config/config.yaml")
    db_config = config.database.postgres

    if not db_config:
        print("✗ PostgreSQL config not found in config.yaml")
        return

    print(
        f"Database config: {db_config.database} @ {db_config.host}:{db_config.port}\n"
    )

    import psycopg_pool

    pool = psycopg_pool.ConnectionPool(
        conninfo=f"host={db_config.host} "
        f"port={db_config.port} "
        f"dbname={db_config.database} "
        f"user={db_config.user} "
        f"password={db_config.password}",
        min_size=1,
        max_size=5,
    )

    import psycopg_pool

    pool = psycopg_pool.ConnectionPool(
        conninfo=f"host={config.database.postgres.host} "
        f"port={config.database.postgres.port} "
        f"dbname={config.database.postgres.database} "
        f"user={config.database.postgres.user} "
        f"password={config.database.postgres.password}",
        min_size=1,
        max_size=5,
    )

    print("✓ Database connection successful\n")

    with pool.connection() as conn:
        with conn.cursor() as cur:
            print("Checking tables existence...")
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name IN ('contacts', 'contact_interactions', 'contact_notes', 'contact_tags')
                ORDER BY table_name
            """)
            tables = [row[0] for row in cur.fetchall()]

            expected = [
                "contacts",
                "contact_interactions",
                "contact_notes",
                "contact_tags",
            ]
            for table in expected:
                if table in tables:
                    print(f"  ✓ {table} exists")
                else:
                    print(f"  ✗ {table} MISSING")

            print("\nChecking contacts table columns...")
            cur.execute("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'contacts' 
                ORDER BY ordinal_position
            """)
            columns = cur.fetchall()
            if columns:
                for col_name, col_type in columns:
                    print(f"  - {col_name}: {col_type}")
            else:
                print("  ✗ Table doesn't exist or has no columns")

            print("\nTesting get_all_contacts() query...")
            try:
                cur.execute("""
                    SELECT 
                        email, 
                        display_name, 
                        first_name, 
                        last_name, 
                        organization, 
                        email_count, 
                        last_email_date, 
                        is_vip 
                    FROM contacts 
                    ORDER BY email_count DESC NULLS LAST
                    LIMIT 10
                """)
                contacts = cur.fetchall()
                print(f"  ✓ Query successful, found {len(contacts)} contacts")

                if contacts:
                    print(f"\n  Sample contact: {contacts[0]}")
                else:
                    print("\n  (No contacts in database yet)")

            except Exception as e:
                print(f"  ✗ Query failed: {e}")

            print("\nTesting get_frequent_contacts() query...")
            try:
                cur.execute("""
                    SELECT email, display_name, email_count 
                    FROM contacts 
                    WHERE email_count > 0 
                    ORDER BY email_count DESC 
                    LIMIT 10
                """)
                frequent = cur.fetchall()
                print(f"  ✓ Query successful, found {len(frequent)} frequent contacts")
            except Exception as e:
                print(f"  ✗ Query failed: {e}")

            print("\nTesting get_recent_contacts() query...")
            try:
                cur.execute("""
                    SELECT email, display_name, last_email_date 
                    FROM contacts 
                    WHERE last_email_date IS NOT NULL 
                    ORDER BY last_email_date DESC 
                    LIMIT 10
                """)
                recent = cur.fetchall()
                print(f"  ✓ Query successful, found {len(recent)} recent contacts")
            except Exception as e:
                print(f"  ✗ Query failed: {e}")


if __name__ == "__main__":
    try:
        check_contacts_tables()
        print("\n=== Diagnostic Complete ===")
    except Exception as e:
        print(f"\n✗ FATAL ERROR: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
