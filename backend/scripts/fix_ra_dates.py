"""
Fix remittances.remittance_date for existing records where the date was
incorrectly set to the fetch date (2026-06-19) because eClaimLink's
TransactionDate attribute could not be parsed at fetch time.

This script:
  1. Finds all RemittanceAdvice records in raw_xml_store.
  2. Parses the TransactionDate attribute from the XML root element.
  3. Updates remittances.remittance_date for all claims in that file.

Run once after upgrading to the fixed dhpo_parser.py:
    cd ~/my_project/ghaf-app/backend
    .venv/bin/python3 scripts/fix_ra_dates.py [--dry-run]
"""
from __future__ import annotations

import re
import sys
from datetime import date
from typing import Optional

DATABASE_URL = "postgresql+psycopg2://ghaf@/ghaf_app?host=/tmp"


def _parse_date_from_filename(filename: str) -> Optional[date]:
    """Extract DDMMYYYY embedded in DHA RA filenames.

    Handles both formats:
      DHA-F-0047100-XXXXXXXX-XXXXXXXX-28052026021527.XML   (no AM/PM)
      RA_NOTAPPLICABLE_28052026202626_Neuron_To_...xml       (no AM/PM)
      TPA029-DHA-F-0047100-...-15052026082556AM.xml          (with AM/PM)
    """
    if not filename:
        return None
    # Try with AM/PM first (ClaimSubmission pattern)
    m = re.search(r'(\d{2})(\d{2})(20\d{2})\d{6}(?:AM|PM)', filename, re.IGNORECASE)
    if not m:
        # RA pattern: DDMMYYYY followed by 6-digit time, no AM/PM
        m = re.search(r'(\d{2})(\d{2})(20\d{2})\d{6}', filename)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(year, month, day)
        except ValueError:
            pass
    return None


def run(dry_run: bool = False) -> None:
    from sqlalchemy import create_engine, text
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT id, source_filename, submission_date::text "
            "FROM raw_xml_store "
            "WHERE xml_type = 'RemittanceAdvice' "
            "ORDER BY id"
        )).fetchall()

        print(f"Found {len(rows)} RemittanceAdvice records to process ...\n")

        updated_remits = 0
        no_date = 0
        skipped = 0

        for raw_id, filename, stored_date in rows:
            extracted = _parse_date_from_filename(filename or "")

            if extracted is None:
                print(f"  raw_xml_id={raw_id} | {filename!r} — no date in filename")
                no_date += 1
                continue

            if str(extracted) == stored_date:
                skipped += 1
                continue  # already correct

            print(
                f"  raw_xml_id={raw_id} | {filename!r} "
                f"| stored={stored_date} → extracted={extracted}"
            )

            if not dry_run:
                r = conn.execute(text(
                    "UPDATE remittances SET remittance_date = :dt "
                    "WHERE raw_xml_id = :id "
                    "RETURNING id"
                ), {"dt": extracted, "id": raw_id})
                updated_remits += r.rowcount
                print(f"    → updated {r.rowcount} remittance row(s)")
            else:
                r = conn.execute(text(
                    "SELECT COUNT(*) FROM remittances WHERE raw_xml_id = :id"
                ), {"id": raw_id})
                count = r.scalar()
                updated_remits += count
                print(f"    [DRY RUN] would update {count} remittance row(s)")

        mode = "[DRY RUN] Would update" if dry_run else "Updated"
        print()
        print("Done.")
        print(f"  {mode} remittances rows : {updated_remits}")
        print(f"  Already correct        : {skipped}")
        print(f"  No date in filename    : {no_date}")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv or "-n" in sys.argv
    if dry:
        print("=== DRY RUN mode — no changes will be committed ===\n")
    run(dry_run=dry)
