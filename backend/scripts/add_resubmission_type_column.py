"""
One-time migration: adds resubmission_type column to claims table.

Run once:
    cd ~/my_project/ghaf-app/backend
    .venv/bin/python3 scripts/add_resubmission_type_column.py
"""
from sqlalchemy import create_engine, text

DATABASE_URL = "postgresql+psycopg2://ghaf@/ghaf_app?host=/tmp"
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

with engine.begin() as conn:
    conn.execute(text("""
        ALTER TABLE claims
        ADD COLUMN IF NOT EXISTS resubmission_type VARCHAR(50)
    """))
    print("Column 'resubmission_type' added (or already exists).")

    total = conn.execute(text(
        "SELECT COUNT(*) FROM claims WHERE raw_xml_id IS NOT NULL"
    )).scalar()
    print(f"Claims with XML to backfill: {total}")
