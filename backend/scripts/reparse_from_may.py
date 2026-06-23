"""
Targeted re-parse: only RA files with remittance_date >= 2026-05-01.

This populates the new denial_type and denial_description columns
in remittance_activity_details for recent transactions only.

Scope: 1,033 files / ~34,218 activity rows  (vs 30,311 for full reparse)

Run:
    cd ~/my_project/ghaf-app/backend
    .venv/bin/python3 scripts/reparse_from_may.py [--dry-run]
"""
from __future__ import annotations

import sys
import os
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATABASE_URL = "postgresql+psycopg2://ghaf@/ghaf_app?host=/tmp"
SINCE_DATE   = date(2026, 5, 1)


def run(dry_run: bool = False) -> None:
    from sqlalchemy import create_engine, text
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

    with engine.connect() as conn:
        # Distinct RA raw_xml_store IDs whose remittances fall on/after SINCE_DATE
        rows = conn.execute(text("""
            SELECT DISTINCT r.raw_xml_id, x.source_filename, x.facility_id
            FROM remittances r
            JOIN raw_xml_store x ON x.id = r.raw_xml_id
            WHERE r.remittance_date >= :since
              AND r.raw_xml_id IS NOT NULL
            ORDER BY r.raw_xml_id
        """), {"since": SINCE_DATE}).fetchall()

    print(f"Mode      : {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"Since     : {SINCE_DATE}")
    print(f"RA files  : {len(rows)}")
    print()

    if dry_run:
        for raw_xml_id, fname, fac_id in rows[:10]:
            print(f"  Would re-parse raw_xml_id={raw_xml_id}  {fname}")
        if len(rows) > 10:
            print(f"  ... and {len(rows)-10} more")
        return

    # Run DB migration first (idempotent)
    from sqlalchemy import text as t2
    with engine.begin() as conn:
        conn.execute(t2("""
            ALTER TABLE remittance_activity_details
            ADD COLUMN IF NOT EXISTS denial_type VARCHAR(100)
        """))
    print("Migration: denial_type column ensured.\n")

    from sqlalchemy.orm import sessionmaker
    from app.services.dhpo_parser import DHPOXmlParser

    Session = sessionmaker(bind=engine)

    parsed = 0
    failed = 0

    for i, (raw_xml_id, fname, fac_id) in enumerate(rows, 1):
        db = Session()
        try:
            # Delete existing activity_details for this RA file's remittances
            db.execute(text("""
                DELETE FROM remittance_activity_details
                WHERE remittance_id_fk IN (
                    SELECT id FROM remittances WHERE raw_xml_id = :rid
                )
            """), {"rid": raw_xml_id})

            # Delete existing remittances for this RA file
            db.execute(text(
                "DELETE FROM remittances WHERE raw_xml_id = :rid"
            ), {"rid": raw_xml_id})

            # Reset parse_status so parser picks it up
            db.execute(text(
                "UPDATE raw_xml_store SET parse_status = 'pending' WHERE id = :rid"
            ), {"rid": raw_xml_id})

            db.commit()

            # Re-parse
            parser = DHPOXmlParser(db)
            parser.run_pending(facility_id=fac_id)

            parsed += 1
            if i % 50 == 0 or i == len(rows):
                print(f"  [{i}/{len(rows)}] parsed={parsed}  failed={failed}", flush=True)

        except Exception as e:
            db.rollback()
            print(f"  [{i}/{len(rows)}] ERROR raw_xml_id={raw_xml_id}: {e}")
            failed += 1
        finally:
            db.close()

    print()
    print("=" * 60)
    print(f"Done. Parsed={parsed}  Failed={failed}")
    print("=" * 60)


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    run(dry_run=dry_run)
