"""
Backfill resubmission_type on claims by extracting <Resubmission><Type>
from the stored raw claim XML.

Values written:
  NULL              → initial submission (no <Resubmission> tag in XML)
  'Correction'      → standard resubmission (1 Resubmission)
  'InternalComplaint' → standard resubmission (1 Resubmission)
  'Reconciliation'  → reconciliation resubmission

Processes in batches of 200 rows to avoid OOM on 8 GB machines.

Run once (after add_resubmission_type_column.py):
    cd ~/my_project/ghaf-app/backend
    .venv/bin/python3 scripts/backfill_resubmission_type.py
"""
import re
from sqlalchemy import create_engine, text

DATABASE_URL = "postgresql+psycopg2://ghaf@/ghaf_app?host=/tmp"
engine      = create_engine(DATABASE_URL, pool_pre_ping=True)

RESUB_RE = re.compile(
    r"<Resubmission[^>]*>.*?<Type[^>]*>\s*([^<]+)\s*</Type>",
    re.IGNORECASE | re.DOTALL,
)
BATCH_SIZE = 200

with engine.connect() as conn:
    total = conn.execute(text("""
        SELECT COUNT(*)
        FROM claims c
        JOIN raw_xml_store x ON x.id = c.raw_xml_id
        WHERE c.raw_xml_id IS NOT NULL
          AND c.resubmission_type IS NULL
    """)).scalar()
    print(f"Claims to inspect: {total}")

updated   = 0
processed = 0
offset    = 0

while True:
    with engine.begin() as txn:
        rows = txn.execute(text("""
            SELECT c.id, x.xml_content
            FROM claims c
            JOIN raw_xml_store x ON x.id = c.raw_xml_id
            WHERE c.raw_xml_id IS NOT NULL
              AND c.resubmission_type IS NULL
            ORDER BY c.id
            LIMIT :limit OFFSET :offset
        """), {"limit": BATCH_SIZE, "offset": offset}).fetchall()

        if not rows:
            break

        for claim_pk, xml_content in rows:
            if xml_content:
                xml_str = (
                    xml_content if isinstance(xml_content, str)
                    else xml_content.tobytes().decode("utf-8", errors="replace")
                )
                m = RESUB_RE.search(xml_str)
                if m:
                    resub_type = m.group(1).strip()
                    txn.execute(text(
                        "UPDATE claims SET resubmission_type = :rt WHERE id = :id"
                    ), {"rt": resub_type, "id": claim_pk})
                    updated += 1
            processed += 1

    offset += BATCH_SIZE
    print(f"  Processed {processed}/{total} — resubmissions found so far: {updated}")

print(f"\nDone. {updated} claims marked as resubmissions (out of {total} inspected).")
print("Claims with no <Resubmission> tag remain NULL = Initial Submission.")
