"""
Backfill clinician_id on claims where it is NULL or 'UNKNOWN',
using the first activity's clinician_id from claim_activities.

Run once:
    cd ~/my_project/ghaf-app/backend
    .venv/bin/python3 scripts/backfill_clinician.py
"""
from sqlalchemy import create_engine, text

DATABASE_URL = "postgresql+psycopg2://ghaf@/ghaf_app?host=/tmp"
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

with engine.begin() as conn:
    result = conn.execute(text("""
        UPDATE claims c
        SET clinician_id = sub.clinician_id
        FROM (
            SELECT DISTINCT ON (claim_id_fk)
                claim_id_fk,
                clinician_id
            FROM claim_activities
            WHERE clinician_id IS NOT NULL
              AND clinician_id != ''
            ORDER BY claim_id_fk, sequence_no
        ) sub
        WHERE c.id = sub.claim_id_fk
          AND (c.clinician_id IS NULL OR c.clinician_id = 'UNKNOWN')
    """))
    print(f"Updated {result.rowcount} claims with clinician_id from activities.")
