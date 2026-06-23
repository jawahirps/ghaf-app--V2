"""
Backfill receiver_id on claims where it is NULL or a facility DHA-F- license,
by extracting <ReceiverID> from the stored raw claim XML.

Processes in small batches to avoid OOM on low-memory machines.

Run once:
    cd ~/my_project/ghaf-app/backend
    .venv/bin/python3 scripts/backfill_receiver.py
"""
import re
from sqlalchemy import create_engine, text

DATABASE_URL = "postgresql+psycopg2://ghaf@/ghaf_app?host=/tmp"
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

RECEIVER_RE = re.compile(r"<ReceiverID>\s*([^<]+)\s*</ReceiverID>", re.IGNORECASE)
BATCH_SIZE  = 200

with engine.connect() as conn:
    # Count total to backfill
    total = conn.execute(text("""
        SELECT COUNT(*)
        FROM claims c
        JOIN raw_xml_store x ON x.id = c.raw_xml_id
        WHERE c.raw_xml_id IS NOT NULL
          AND (
              c.receiver_id IS NULL
              OR c.receiver_id = ''
              OR c.receiver_id ILIKE 'DHA-F-%'
          )
    """)).scalar()
    print(f"Claims to backfill: {total}")

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
                  AND (
                      c.receiver_id IS NULL
                      OR c.receiver_id = ''
                      OR c.receiver_id ILIKE 'DHA-F-%'
                  )
                ORDER BY c.id
                LIMIT :limit OFFSET :offset
            """), {"limit": BATCH_SIZE, "offset": offset}).fetchall()

            if not rows:
                break

            for claim_id, xml_content in rows:
                if not xml_content:
                    processed += 1
                    continue
                xml_str = xml_content if isinstance(xml_content, str) \
                    else xml_content.tobytes().decode("utf-8", errors="replace")
                m = RECEIVER_RE.search(xml_str)
                if m:
                    receiver_id = m.group(1).strip()
                    if not receiver_id.upper().startswith("DHA-F-"):
                        txn.execute(text(
                            "UPDATE claims SET receiver_id = :rid WHERE id = :id"
                        ), {"rid": receiver_id, "id": claim_id})
                        updated += 1
                processed += 1

        offset += BATCH_SIZE
        print(f"  Processed {processed}/{total} — updated so far: {updated}")

    print(f"\nDone. Updated {updated} of {total} claims with receiver_id from XML.")
