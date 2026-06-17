#!/usr/bin/env python3
"""
Ghaf App — standalone DHA XML Sync worker.

Runs the same `DHASyncService.run_sync_pipeline(...)` used by
POST /api/dha-sync/fetch, intended for cron / scheduled execution
(e.g. nightly eClaimLink pull + parse).

Usage:
    python scripts/run_dha_sync.py --facility-id 1 --from 2026-04-16 --to 2026-04-23

Environment:
    Reads DATABASE_URL (and optionally ECLAIMLINK_API_BASE) from the
    backend's settings (.env), same as the FastAPI app.
"""
import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.services.fetch_service import DHASyncService  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("run_dha_sync")


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def main() -> None:
    settings = get_settings()

    parser = argparse.ArgumentParser(description="Run the Ghaf App DHA XML Sync pipeline")
    parser.add_argument("--facility-id", type=int, required=True)
    parser.add_argument("--from", dest="date_from", type=parse_date, required=True, help="YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", type=parse_date, required=True, help="YYYY-MM-DD")
    args = parser.parse_args()

    with DHASyncService(db_url=settings.DATABASE_URL, eclaimlink_api_base="https://eclaimlink.ae/api/v1") as worker:
        fetch_log = worker.run_sync_pipeline(
            facility_id=args.facility_id,
            date_from=args.date_from,
            date_to=args.date_to,
        )
        log.info(
            "Sync run %s finished: status=%s fetched=%d parsed=%d failed=%d http_errors=%d",
            fetch_log.id, fetch_log.status, fetch_log.records_fetched,
            fetch_log.records_parsed, fetch_log.records_failed, fetch_log.http_errors,
        )


if __name__ == "__main__":
    main()
