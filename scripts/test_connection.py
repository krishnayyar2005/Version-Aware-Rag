"""Test database connection to Supabase."""

import os
import sys

from dotenv import load_dotenv
import psycopg

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("ERROR: DATABASE_URL is not set. Please fill it in your .env file.")
    sys.exit(1)

try:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM documents;")
            count = cur.fetchone()[0]
            print(f"Connection successful! documents table has {count} row(s).")
except psycopg.OperationalError as e:
    print(f"ERROR: Could not connect to the database.\n{e}")
    sys.exit(1)
except psycopg.errors.UndefinedTable:
    print("ERROR: The 'documents' table does not exist yet.")
    sys.exit(1)
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)

