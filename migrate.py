#!/usr/bin/env python3
"""
Run SQL migration files against the database.

Usage:
    # Run all migrations in order:
    python migrate.py

    # Run a specific migration file:
    python migrate.py migrations/001_create_inventory.sql
"""

import os
import sys
import mysql.connector
from dotenv import load_dotenv

load_dotenv()


def get_db():
    instance_connection = os.getenv("INSTANCE_CONNECTION_NAME")
    if instance_connection:
        return mysql.connector.connect(
            unix_socket=f"/cloudsql/{instance_connection}",
            user=os.getenv("MYSQL_USER"),
            password=os.getenv("MYSQL_PASSWORD"),
            database=os.getenv("MYSQL_DATABASE"),
        )
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DATABASE"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
    )


def run_migration(filepath: str):
    with open(filepath, "r") as f:
        sql = f.read()

    # Split on semicolons, skip blank statements and comment-only blocks
    statements = [s.strip() for s in sql.split(";") if s.strip()]

    db = get_db()
    try:
        cur = db.cursor()
        for stmt in statements:
            # Skip pure comment blocks
            lines = [l for l in stmt.splitlines() if not l.strip().startswith("--")]
            body = "\n".join(lines).strip()
            if not body:
                continue
            preview = body[:80].replace("\n", " ")
            print(f"  → {preview}...")
            cur.execute(stmt)
        db.commit()
        print(f"✅ Applied: {filepath}")
    except Exception as e:
        db.rollback()
        print(f"❌ Failed:  {filepath}\n   {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    migrations_dir = os.path.join(os.path.dirname(__file__), "migrations")

    if len(sys.argv) > 1:
        run_migration(sys.argv[1])
    else:
        files = sorted(
            f for f in os.listdir(migrations_dir) if f.endswith(".sql")
        )
        if not files:
            print("No migration files found in ./migrations/")
            sys.exit(0)
        for f in files:
            run_migration(os.path.join(migrations_dir, f))
        print("All migrations complete.")
