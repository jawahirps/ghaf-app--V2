"""
Re-parse ALL RemittanceAdvice records so the activity-level aggregation fix
(NAS / TPA004 format) is applied to every existing RA file in the database.

Before this fix, RA files where denial codes and payment amounts were nested
inside <Activity> elements (instead of at the <Claim> level) were parsed with
NULL denial_code, zero paid_amount, and zero denial_amount.

This script is safe to run multiple times — it deletes existing remittance rows
by (raw_xml_id, claim_id) before re-inserting, so there are no duplicates.

Run:
    cd ~/my_project/ghaf-app/backend
    .venv/bin/python3 scripts/reparse_nas_ra.py [--dry-run]

Options:
    --dry-run   Show what would be done without making any changes.
    --null-only Re-parse only records where denial_code IS NULL (faster if
                most files are already correct; skips DHA-standard RA files
                that parsed fine).
"""
from __future__ import annotations

import sys

DATABASE_URL = "postgresql+psycopg2://ghaf@/ghaf_app?host=/tmp"


def run(dry_run: bool = False, null_only: bool = False) -> None:
    from sqlalchemy import create_engine, text
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

    with engine.begin() as conn:
        # Find RA records to re-parse
        if null_only:
            # Only re-parse files that have at least one remittance with NULL
            # denial_code — these are the ones definitely affected by the bug.
            rows = conn.execute(text(
                "SELECT DISTINCT r.id, r.source_filename, r.facility_id, r.parse_status "
                "FROM raw_xml_store r "
                "JOIN remittances rem ON rem.raw_xml_id = r.id "
                "WHERE r.xml_type = 'RemittanceAdvice' "
                "  AND rem.denial_code IS NULL "
                "ORDER BY r.id"
            )).fetchall()
            print(f"Mode: NULL denial_code only")
        else:
            rows = conn.execute(text(
                "SELECT id, source_filename, facility_id, parse_status "
                "FROM raw_xml_store "
                "WHERE xml_type = 'RemittanceAdvice' "
                "ORDER BY id"
            )).fetchall()
            print(f"Mode: ALL RemittanceAdvice records")

        print(f"Found {len(rows)} RemittanceAdvice file(s) to re-parse.\n")
        if not rows:
            print("Nothing to do.")
            return

        raw_ids = [r[0] for r in rows]

        # Summary by filename pattern
        nas_count = sum(1 for r in rows if (r[1] or "").upper().startswith("RA_NOTAPPLICABLE"))
        dha_count = len(rows) - nas_count
        print(f"  NAS pattern (RA_NOTAPPLICABLE_*) : {nas_count}")
        print(f"  Other patterns                   : {dha_count}")

        # Count existing remittance rows that will be replaced
        cnt = conn.execute(text(
            "SELECT COUNT(*) FROM remittances WHERE raw_xml_id = ANY(:ids)"
        ), {"ids": raw_ids}).scalar()
        print(f"  Remittance rows to replace       : {cnt}")

        if dry_run:
            print(f"\n[DRY RUN] No changes made.")
            print("Re-run without --dry-run to apply.")
            return

        # Delete existing remittance rows for these files
        conn.execute(text(
            "DELETE FROM remittances WHERE raw_xml_id = ANY(:ids)"
        ), {"ids": raw_ids})
        print(f"\nDeleted {cnt} existing remittance row(s).")

        # Reset to pending so the parser will pick them up
        conn.execute(text(
            "UPDATE raw_xml_store "
            "SET parse_status = 'pending', parse_error = NULL "
            "WHERE id = ANY(:ids)"
        ), {"ids": raw_ids})
        print(f"Reset {len(raw_ids)} raw_xml_store record(s) to 'pending'.")

    # Re-parse outside the transaction (parser commits per record)
    print("\nRunning parser on pending records …")
    import os, sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from sqlalchemy.orm import sessionmaker
    engine2 = create_engine(DATABASE_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine2)
    db = Session()
    try:
        from app.services.dhpo_parser import DHPOXmlParser
        parser = DHPOXmlParser(db)
        summary = parser.run_pending()
        print(f"\nDone.")
        print(f"  Files re-parsed : {summary.parsed_records}")
        print(f"  Records created : {summary.records_parsed_total}")
        print(f"  Quarantined     : {summary.quarantined_records}")
    finally:
        db.close()


if __name__ == "__main__":
    dry_run  = "--dry-run" in sys.argv or "-n" in sys.argv
    null_only = "--null-only" in sys.argv

    if dry_run:
        print("=== DRY RUN — no changes will be made ===\n")
    run(dry_run=dry_run, null_only=null_only)
