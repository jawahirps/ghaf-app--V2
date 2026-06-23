"""
Fix existing raw_xml_store records where submission_date was incorrectly set
to the fetch date_to (2026-06-19) because eClaimLink TransactionDate parsing
failed and no filename-based fallback existed.

This script:
  1. Finds raw_xml_store records whose source_filename contains an embedded
     DDMMYYYY date (DHA filename convention).
  2. Extracts the correct date and updates raw_xml_store.submission_date.
  3. Updates claims.submission_date via the raw_xml_id FK.
  4. Updates remittances.remittance_date via the raw_xml_id FK.

Run once after upgrading to the fixed fetch_service.py:
    cd ~/my_project/ghaf-app/backend
    .venv/bin/python3 scripts/fix_submission_dates.py [--dry-run]
"""
from __future__ import annotations

import re
import sys
from datetime import date
from typing import Optional

DATABASE_URL = "postgresql+psycopg2://ghaf@/ghaf_app?host=/tmp"

# ─── date extraction ─────────────────────────────────────────────────────────

def _parse_date_from_filename(filename: str) -> Optional[date]:
    """Extract DDMMYYYY from DHA filename. Year must be 20xx."""
    if not filename:
        return None
    m = re.search(r'(\d{2})(\d{2})(20\d{2})\d{6}(?:AM|PM)', filename, re.IGNORECASE)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(year, month, day)
        except ValueError:
            pass
    return None


# ─── main ────────────────────────────────────────────────────────────────────

def run(dry_run: bool = False) -> None:
    from sqlalchemy import create_engine, text
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

    with engine.begin() as conn:
        # Fetch all raw_xml_store rows that have a source_filename
        rows = conn.execute(text(
            "SELECT id, source_filename, submission_date::text "
            "FROM raw_xml_store "
            "WHERE source_filename IS NOT NULL "
            "ORDER BY id"
        )).fetchall()

        print(f"Checking {len(rows)} raw_xml_store records ...")

        updated_raw = 0
        updated_claims = 0
        updated_remits = 0
        skipped = 0
        no_date = 0

        for raw_id, filename, stored_date in rows:
            extracted = _parse_date_from_filename(filename)
            if extracted is None:
                no_date += 1
                continue

            if str(extracted) == stored_date:
                skipped += 1
                continue  # already correct

            print(
                f"  raw_xml_id={raw_id} | filename={filename!r} "
                f"| stored={stored_date} → extracted={extracted}"
            )

            if not dry_run:
                # 1. Fix raw_xml_store
                conn.execute(text(
                    "UPDATE raw_xml_store SET submission_date = :dt WHERE id = :id"
                ), {"dt": extracted, "id": raw_id})
                updated_raw += 1

                # 2. Fix claims linked to this raw record
                r = conn.execute(text(
                    "UPDATE claims SET submission_date = :dt "
                    "WHERE raw_xml_id = :id "
                    "RETURNING id"
                ), {"dt": extracted, "id": raw_id})
                updated_claims += r.rowcount

                # 3. Fix remittances linked to this raw record
                r2 = conn.execute(text(
                    "UPDATE remittances SET remittance_date = :dt "
                    "WHERE raw_xml_id = :id "
                    "RETURNING id"
                ), {"dt": extracted, "id": raw_id})
                updated_remits += r2.rowcount
            else:
                updated_raw += 1

        mode = "[DRY RUN] Would update" if dry_run else "Updated"
        print()
        print(f"Done.")
        print(f"  {mode} raw_xml_store rows : {updated_raw}")
        if not dry_run:
            print(f"  Updated claims rows      : {updated_claims}")
            print(f"  Updated remittances rows : {updated_remits}")
        print(f"  Already correct          : {skipped}")
        print(f"  No date in filename      : {no_date}")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv or "-n" in sys.argv
    if dry:
        print("=== DRY RUN mode — no changes will be committed ===\n")
    run(dry_run=dry)
