"""
Bulk eClaimLink fetch — runs one month at a time for a facility.

Splits a date range into calendar months, skips any month that already has a
successful fetch log, and runs DHASyncService.run_sync_pipeline() for each
remaining window.  Safe to re-run: already-covered months are skipped.

Usage:
    cd ~/my_project/ghaf-app/backend

    # Fetch Alnoor Rashidiya from Jun 2024 → Apr 2026 (May+Jun 2026 already done)
    .venv/bin/python3 scripts/bulk_fetch.py --facility 8 --from 2024-06-01 --to 2026-04-30

    # Fetch Alnoor Deira full 2 years
    .venv/bin/python3 scripts/bulk_fetch.py --facility 5 --from 2024-06-01 --to 2026-06-16

    # Dry-run: show which months would be fetched without calling eClaimLink
    .venv/bin/python3 scripts/bulk_fetch.py --facility 8 --from 2024-06-01 --to 2026-04-30 --dry-run

Facility IDs (DHA eClaimLink):
    5  — Alnoor Deira        (DHA-F-0002226)
    6  — Alnoor Muhaisnah    (DHA-F-0002088)
    7  — Alnoor Qusais       (DHA-F-0047641)
    8  — Alnoor Rashidiya    (DHA-F-0047100)
    13 — Apollo Clinics      (DHA-F-0253862)
    14 — We Care Medical Center (DHA-F-0001604)
    15 — New Lotus Medical Center (DHA-F-0046977)
"""
from __future__ import annotations

import argparse
import calendar
import os
import sys
import time
from datetime import date, timedelta

# Make sure app package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATABASE_URL = "postgresql+psycopg2://ghaf@/ghaf_app?host=/tmp"


def _month_windows(date_from: date, date_to: date) -> list[tuple[date, date]]:
    """Return list of (month_start, month_end) tuples covering [date_from, date_to]."""
    windows = []
    cur = date(date_from.year, date_from.month, 1)
    while cur <= date_to:
        last_day = calendar.monthrange(cur.year, cur.month)[1]
        month_end = date(cur.year, cur.month, last_day)
        win_start = max(cur, date_from)
        win_end   = min(month_end, date_to)
        windows.append((win_start, win_end))
        # Advance to first day of next month
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)
    return windows


def _already_covered(conn, facility_id: int, win_start: date, win_end: date) -> bool:
    """Return True if a successful fetch log fully covers [win_start, win_end]."""
    from sqlalchemy import text
    row = conn.execute(text(
        "SELECT id FROM fetch_log "
        "WHERE facility_id = :fid "
        "  AND status = 'success' "
        "  AND date_from <= :ds "
        "  AND date_to   >= :de "
        "LIMIT 1"
    ), {"fid": facility_id, "ds": win_start, "de": win_end}).fetchone()
    return row is not None


def run(facility_id: int, date_from: date, date_to: date, dry_run: bool = False) -> None:
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine)

    # Resolve facility name for display
    with engine.connect() as conn:
        fac = conn.execute(text(
            "SELECT facility_name, facility_code FROM facilities WHERE id = :id"
        ), {"id": facility_id}).fetchone()
    if not fac:
        print(f"ERROR: facility_id={facility_id} not found.")
        sys.exit(1)

    fac_name = fac[0]
    windows = _month_windows(date_from, date_to)

    print("=" * 70)
    print(f"Bulk fetch: {fac_name} (id={facility_id})")
    print(f"Range     : {date_from} → {date_to}  ({len(windows)} month window(s))")
    print(f"Mode      : {'DRY RUN' if dry_run else 'LIVE'}")
    print("=" * 70)

    skipped = 0
    fetched = 0
    failed  = 0

    for i, (win_start, win_end) in enumerate(windows, 1):
        label = f"[{i}/{len(windows)}] {win_start} → {win_end}"

        with engine.connect() as conn:
            covered = _already_covered(conn, facility_id, win_start, win_end)

        if covered:
            print(f"  {label}  ⏭  already covered — skipping")
            skipped += 1
            continue

        if dry_run:
            print(f"  {label}  🔲  would fetch")
            fetched += 1
            continue

        print(f"  {label}  ⏳  fetching …", flush=True)
        t0 = time.time()

        db = SessionLocal()
        try:
            from app.services.fetch_service import DHASyncService
            svc = DHASyncService(session=db)
            log = svc.run_sync_pipeline(facility_id, win_start, win_end)
            elapsed = int(time.time() - t0)

            if log.status == "success":
                print(
                    f"  {label}  ✅  {log.status} — "
                    f"files={log.records_fetched}  records={log.records_parsed}  "
                    f"failed={log.records_failed}  ({elapsed}s)"
                )
                fetched += 1
            else:
                print(
                    f"  {label}  ⚠️  {log.status} — "
                    f"files={log.records_fetched}  records={log.records_parsed}  "
                    f"failed={log.records_failed}  errors={log.http_errors}  ({elapsed}s)"
                )
                if log.status == "failed":
                    failed += 1
                else:
                    fetched += 1  # partial still counts as attempted

        except Exception as exc:
            elapsed = int(time.time() - t0)
            print(f"  {label}  ❌  EXCEPTION after {elapsed}s: {exc}")
            failed += 1
        finally:
            db.close()

        # Brief pause between months to avoid hammering eClaimLink
        time.sleep(2)

    print()
    print("=" * 70)
    print(f"Done.  Fetched={fetched}  Skipped={skipped}  Failed={failed}")
    if dry_run:
        print("(DRY RUN — no actual API calls were made)")
    print("=" * 70)


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date '{s}' — use YYYY-MM-DD")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bulk monthly eClaimLink fetch")
    parser.add_argument("--facility", type=int, required=True, help="Facility DB id")
    parser.add_argument("--from",    dest="date_from", type=_parse_date, required=True)
    parser.add_argument("--to",      dest="date_to",   type=_parse_date, required=True)
    parser.add_argument("--dry-run", action="store_true", help="Show plan without fetching")
    args = parser.parse_args()

    if args.date_from > args.date_to:
        print("ERROR: --from must be before --to")
        sys.exit(1)

    run(
        facility_id=args.facility,
        date_from=args.date_from,
        date_to=args.date_to,
        dry_run=args.dry_run,
    )
