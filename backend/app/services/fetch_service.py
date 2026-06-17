"""
Ghaf App — eClaimLink (DHPO) live fetch service.

`DHASyncService.run_sync_pipeline(facility_id, date_from, date_to)` is the
orchestration entry point used by:
  - POST /api/dha-sync/fetch (live trigger from the React app)
  - scripts/run_dha_sync.py (standalone/cron worker, e.g. nightly job)

It performs three steps:
  1. Looks up the facility's eClaimLink credentials
     (`Facility.eclaimlink_username` / `Facility.credential_key` /
     `Facility.dhpo_provider_id`).
  2. Calls `_fetch_transactions(...)` for each of ClaimSubmission and
     RemittanceAdvice, staging any returned XML payloads into
     `raw_xml_store` (parse_status="pending").
  3. Runs `DHPOXmlParser.run_pending(...)` to normalize newly staged (and
     any previously pending) records, then finalizes a `FetchLog` row with
     fetch/parse/error counts.

NOTE — `_fetch_transactions` is a scaffold. The DHPO/eClaimLink portal
(https://eclaimlink.ae) exposes a SOAP web service whose WSDL, operation
names, and auth scheme are issued per-payer/per-facility. Implement the
actual SOAP/REST call here using `facility.eclaimlink_username` and
`facility.credential_key` (e.g. with `zeep` for SOAP). Until implemented,
this returns an empty list per xml_type — `run_sync_pipeline` still runs
the parser over anything already staged via manual upload, so the
"Trigger DHA XML Sync" action remains useful out of the box.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..models import Facility, FetchLog, RawXmlStore
from .dhpo_parser import DHPOXmlParser

log = logging.getLogger(__name__)

XML_TYPES = ("ClaimSubmission", "RemittanceAdvice")


class DHASyncService:
    """
    Can be used either:
      - bound to an existing request-scoped Session: `DHASyncService(session=db)`
      - standalone (CLI/cron): `DHASyncService(db_url=..., eclaimlink_api_base=...)`
    """

    def __init__(
        self,
        db_url: Optional[str] = None,
        eclaimlink_api_base: str = "https://eclaimlink.ae/api/v1",
        session: Optional[Session] = None,
    ):
        if session is not None:
            self.db = session
            self._owns_session = False
        else:
            if not db_url:
                raise ValueError("db_url is required when no session is provided")
            engine = create_engine(db_url, pool_pre_ping=True)
            self._SessionLocal = sessionmaker(bind=engine)
            self.db = self._SessionLocal()
            self._owns_session = True

        self.eclaimlink_api_base = eclaimlink_api_base

    def close(self) -> None:
        if self._owns_session:
            self.db.close()

    def __enter__(self) -> "DHASyncService":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------
    def run_sync_pipeline(self, facility_id: int, date_from: date, date_to: date) -> FetchLog:
        facility = self.db.get(Facility, facility_id)
        if facility is None:
            raise ValueError(f"Unknown facility_id={facility_id}")

        fetch_log = FetchLog(
            facility_id=facility_id,
            fetch_type="Backfill",
            date_from=date_from,
            date_to=date_to,
            status="running",
        )
        self.db.add(fetch_log)
        self.db.commit()
        self.db.refresh(fetch_log)

        records_fetched = 0
        http_errors = 0
        error_detail: Dict[str, Any] = {}

        try:
            for xml_type in XML_TYPES:
                try:
                    payloads = self._fetch_transactions(facility, xml_type, date_from, date_to)
                except Exception as e:
                    log.error("eClaimLink fetch failed for %s/%s: %s", facility.facility_code, xml_type, e, exc_info=True)
                    http_errors += 1
                    error_detail[xml_type] = str(e)
                    continue

                for payload in payloads:
                    raw = RawXmlStore(
                        facility_id=facility_id,
                        xml_type=xml_type,
                        source_filename=payload.get("filename"),
                        submission_date=payload.get("submission_date") or date_to,
                        file_size_bytes=len(payload["xml"].encode("utf-8")),
                        xml_content=payload["xml"],
                        parse_status="pending",
                    )
                    self.db.add(raw)
                    records_fetched += 1

            self.db.commit()

            # Parse everything pending (newly fetched + any manual uploads)
            parser = DHPOXmlParser(self.db)
            summary = parser.run_pending(facility_id=facility_id)

            fetch_log.completed_at = datetime.utcnow()
            fetch_log.records_fetched = records_fetched
            fetch_log.records_parsed = summary.records_parsed_total
            fetch_log.records_failed = summary.quarantined_records
            fetch_log.http_errors = http_errors
            if error_detail:
                fetch_log.error_detail = error_detail

            if http_errors and summary.parsed_records == 0 and records_fetched == 0:
                fetch_log.status = "failed"
            elif http_errors or summary.quarantined_records:
                fetch_log.status = "partial"
            else:
                fetch_log.status = "success"

            self.db.commit()
            return fetch_log

        except Exception as e:
            self.db.rollback()
            fetch_log.completed_at = datetime.utcnow()
            fetch_log.status = "failed"
            fetch_log.error_detail = {"error": str(e)}
            self.db.commit()
            raise

    # ------------------------------------------------------------------
    # eClaimLink (DHPO) transport — implement against your WSDL
    # ------------------------------------------------------------------
    def _fetch_transactions(
        self, facility: Facility, xml_type: str, date_from: date, date_to: date
    ) -> List[Dict[str, Any]]:
        """
        Returns a list of {"xml": str, "filename": str, "submission_date": date}.

        TODO: Replace with a real call to the DHPO SOAP service, e.g.:

            from zeep import Client
            client = Client(f"{self.eclaimlink_api_base}/ValidateTransactions.asmx?WSDL")
            result = client.service.SearchTransactions(
                login=facility.eclaimlink_username,
                pwd=facility.credential_key,
                fromDate=date_from.strftime("%d/%m/%Y"),
                toDate=date_to.strftime("%d/%m/%Y"),
                transactionType="ClaimSubmission" if xml_type == "ClaimSubmission" else "RemittanceAdvice",
                facilityID=facility.dhpo_provider_id,
            )
            # ... then DownloadTransaction for each file ID, returning raw XML bytes.

        Until implemented, no live records are fetched — the pipeline still
        parses anything already staged (e.g. via manual upload).
        """
        log.info(
            "eClaimLink live fetch not configured for facility=%s xml_type=%s (%s..%s); skipping.",
            facility.facility_code, xml_type, date_from, date_to,
        )
        return []
