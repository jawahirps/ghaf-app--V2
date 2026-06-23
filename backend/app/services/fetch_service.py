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
  2. Calls `_fetch_transactions(...)` for ClaimSubmission and RemittanceAdvice
     via the DHPO SOAP web service (ValidateTransactions.asmx), staging any
     returned XML payloads into `raw_xml_store` (parse_status="pending").
  3. Runs `DHPOXmlParser.run_pending(...)` to normalize newly staged (and any
     previously pending) records, then finalises a `FetchLog` row with
     fetch/parse/error counts.

DHPO SOAP web service (spec V3, effective July 6 2017):
  Live:    https://dhpo.eclaimlink.ae/ValidateTransactions.asmx
  Archive: https://dhpo.eclaimlink.ae/ClaimsAndAuthorizationsArchive.asmx
  (Archive uses identical signatures but different URL; serves data older
  than the live retention window — Claims >24 months, PA/Rx/Referral >6 months.)

PAREQ and PA AUTH endpoints are intentionally excluded.

Requires:  pip install zeep
"""
from __future__ import annotations

import io
import logging
import zipfile
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..models import Facility, FetchLog, RawXmlStore
from .dhpo_parser import DHPOXmlParser

log = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# DHPO SOAP service URLs (spec V3, July 2017)
# ----------------------------------------------------------------------------
DHPO_LIVE_WSDL    = "https://dhpo.eclaimlink.ae/ValidateTransactions.asmx?wsdl"
DHPO_ARCHIVE_WSDL = "https://dhpo.eclaimlink.ae/ClaimsAndAuthorizationsArchive.asmx?wsdl"

# TransactionID bitmask values per spec
TX_CLAIM_SUBMISSION  = 2   # Claim.Submission
TX_REMITTANCE_ADVICE = 8   # Remittance.Advice
# 16 = Prior.Request  )  excluded per requirements — PAREQ & PA AUTH NOT NEEDED
# 32 = Prior.Authorization )

# direction: 1 = sent only, 2 = received only
DIRECTION_SENT     = 1
DIRECTION_RECEIVED = 2

# Successful return codes (0 = success, 1 = success with warnings, 2/3 = no new data)
DHPO_OK_CODES = {0, 1, 2, 3}

# DHPO hard cap on SearchTransactions results per call.
# When exactly this many results are returned the range must be split.
DHPO_SEARCH_CAP = 500

# XML types handled
XML_TYPES = ("ClaimSubmission", "RemittanceAdvice")


# ----------------------------------------------------------------------------
# DHPO SOAP client wrapper
# ----------------------------------------------------------------------------
class DHPOSoapClient:
    """
    Thin wrapper around the DHPO SOAP web service (zeep-based).

    All calls normalise DHPO return codes and raise RuntimeError on failure.
    """

    def __init__(self, wsdl_url: str, timeout: int = 60):
        try:
            from zeep import Client
            from zeep.transports import Transport
            import requests as _requests
        except ImportError as exc:
            raise ImportError(
                "zeep is required for DHPO SOAP calls. "
                "Run: pip install zeep  (inside the backend venv)"
            ) from exc

        session = _requests.Session()
        session.verify = True  # enforce TLS verification
        transport = Transport(session=session, timeout=timeout, operation_timeout=timeout)
        self._client = Client(wsdl_url, transport=transport)
        self._wsdl_url = wsdl_url

    # ------------------------------------------------------------------
    # GetNewTransactions — returns list of undownloaded transactions
    # ------------------------------------------------------------------
    def get_new_transactions(self, login: str, pwd: str) -> List[Dict]:
        """
        Calls GetNewTransactions and returns a list of file descriptor dicts.
        Each dict: {file_id, file_name, sender_id, receiver_id,
                    transaction_date, record_count, is_downloaded}
        """
        result = self._client.service.GetNewTransactions(
            login=login,
            pwd=pwd,
        )
        return_code   = result.getNewTransactionsResult
        xml_str       = result.xmlTransactions or ""
        error_msg     = result.errorMessage or ""

        if return_code not in DHPO_OK_CODES:
            raise RuntimeError(
                f"GetNewTransactions failed (code {return_code}): {error_msg}"
            )
        if error_msg:
            log.warning("GetNewTransactions warning: %s", error_msg)

        return _parse_files_xml(xml_str)

    # ------------------------------------------------------------------
    # SearchTransactions — date-range search
    # ------------------------------------------------------------------
    def search_transactions(
        self,
        login: str,
        pwd: str,
        direction: int,
        caller_license: Optional[str],
        transaction_id: int,
        date_from: date,
        date_to: date,
        transaction_status: int = 1,    # 1 = new (undownloaded) only; 2 = downloaded only
    ) -> List[Dict]:
        """
        Returns list of file descriptor dicts matching search criteria.
        Max 500 records per call per spec.
        """
        from_str = date_from.strftime("%d/%m/%Y 00:00:00")
        to_str   = date_to.strftime("%d/%m/%Y 23:59:59")

        result = self._client.service.SearchTransactions(
            login=login,
            pwd=pwd,
            direction=direction,
            callerLicense=caller_license,
            ePartner=None,
            transactionID=transaction_id,
            TransactionStatus=transaction_status,
            transactionFileName=None,
            transactionFromDate=from_str,
            transactionToDate=to_str,
            minRecordCount=-1,
            maxRecordCount=-1,
        )
        return_code   = (result.searchTransactionsResult
                         if hasattr(result, "searchTransactionsResult")
                         else result.SearchTransactionsResult)
        xml_str       = getattr(result, "foundTransactions",
                         getattr(result, "FoundTransactions", "")) or ""
        error_msg     = getattr(result, "errorMessage",
                         getattr(result, "ErrorMessage", "")) or ""

        if return_code not in DHPO_OK_CODES:
            raise RuntimeError(
                f"SearchTransactions failed (code {return_code}): {error_msg}"
            )
        if error_msg:
            log.warning("SearchTransactions warning: %s", error_msg)

        return _parse_files_xml(xml_str)

    # ------------------------------------------------------------------
    # DownloadTransactionFile — fetch actual file bytes
    # ------------------------------------------------------------------
    def download_transaction_file(self, login: str, pwd: str, file_id: str) -> bytes:
        """
        Downloads the file content for *file_id*.
        Returns raw bytes (may be XML or ZIP containing XML).
        """
        result = self._client.service.DownloadTransactionFile(
            login=login,
            pwd=pwd,
            fileId=file_id,
        )
        return_code = (result.downloadTransactionFileResult
                       if hasattr(result, "downloadTransactionFileResult")
                       else getattr(result, "DownloadTransactionFileResult", 0))
        error_msg   = getattr(result, "errorMessage",
                       getattr(result, "ErrorMessage", "")) or ""
        file_bytes  = getattr(result, "file",
                       getattr(result, "File",
                        getattr(result, "fileContent",
                         getattr(result, "FileContent", None))))

        if return_code not in DHPO_OK_CODES:
            raise RuntimeError(
                f"DownloadTransactionFile({file_id}) failed (code {return_code}): {error_msg}"
            )
        if error_msg:
            log.warning("DownloadTransactionFile warning: %s", error_msg)

        if file_bytes is None:
            raise RuntimeError(f"DownloadTransactionFile({file_id}) returned no data")

        return bytes(file_bytes)

    # ------------------------------------------------------------------
    # SetTransactionDownloaded — mark file as downloaded
    # ------------------------------------------------------------------
    def set_transaction_downloaded(self, login: str, pwd: str, file_id: str) -> None:
        """
        Marks *file_id* as downloaded so GetNewTransactions won't return it again.
        Logs a warning on failure but does not raise (non-critical).
        """
        try:
            result = self._client.service.SetTransactionDownloaded(
                login=login,
                pwd=pwd,
                fieldId=file_id,
            )
            return_code = result.setTransactionDownloadedResult
            error_msg   = result.errorMessage or ""
            if return_code not in DHPO_OK_CODES:
                log.warning(
                    "SetTransactionDownloaded(%s) returned code %d: %s",
                    file_id, return_code, error_msg,
                )
        except Exception as exc:
            log.warning("SetTransactionDownloaded(%s) failed (non-critical): %s", file_id, exc)


# ----------------------------------------------------------------------------
# XML helpers
# ----------------------------------------------------------------------------
def _parse_files_xml(xml_str: str) -> List[Dict]:
    """Parse the <Files><File .../></Files> XML returned by GetNewTransactions /
    SearchTransactions into a list of plain dicts."""
    if not xml_str or not xml_str.strip():
        return []

    from lxml import etree
    try:
        root = etree.fromstring(xml_str.encode("utf-8"))
    except etree.XMLSyntaxError as exc:
        log.warning("Could not parse DHPO files XML: %s — raw: %.200s", exc, xml_str)
        return []

    files = []
    for file_el in root.findall("File"):
        files.append({
            "file_id":          file_el.get("FileID", ""),
            "file_name":        file_el.get("FileName", ""),
            "sender_id":        file_el.get("SenderID", ""),
            "receiver_id":      file_el.get("ReceiverID", ""),
            "transaction_date": file_el.get("TransactionDate", ""),
            "record_count":     file_el.get("RecordCount", "0"),
            "is_downloaded":    file_el.get("IsDownloaded", "False").lower() == "true",
        })
    return files


def _extract_xml_from_bytes(raw: bytes, filename: str) -> List[Dict[str, Any]]:
    """
    Extract XML content(s) from raw bytes.
    *raw* may be:
      - A single XML file → returns [{xml: str, filename: str}]
      - A ZIP archive containing one or more XML files → one entry per member
    """
    # ZIP detection
    if raw[:4] == b"PK\x03\x04":
        results = []
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                for member in zf.namelist():
                    member_bytes = zf.read(member)
                    try:
                        xml_str = member_bytes.decode("utf-8", errors="replace")
                        results.append({"xml": xml_str, "filename": member})
                    except Exception as exc:
                        log.warning("Could not decode zip member %s: %s", member, exc)
        except zipfile.BadZipFile as exc:
            log.warning("File %s looked like ZIP but isn't: %s", filename, exc)
        return results

    # Plain text / XML
    try:
        xml_str = raw.decode("utf-8", errors="replace")
    except Exception as exc:
        log.warning("Could not decode %s as UTF-8: %s", filename, exc)
        return []
    return [{"xml": xml_str, "filename": filename}]


def _parse_tx_date(date_str: str) -> Optional[date]:
    """Parse eClaimLink TransactionDate in any common format → date, or return None."""
    if not date_str:
        return None
    date_str = date_str.strip()
    for fmt in (
        "%d/%m/%Y %H:%M:%S",    # 15/05/2026 08:25:56   ← primary DHPO format
        "%d/%m/%Y %I:%M:%S %p", # 15/05/2026 08:25:56 AM  (AM/PM variant)
        "%d/%m/%Y %H:%M",       # 15/05/2026 08:25
        "%d/%m/%Y",             # 15/05/2026
        "%Y-%m-%dT%H:%M:%S",    # 2026-05-15T08:25:56  (ISO)
        "%Y-%m-%d",             # 2026-05-15
        "%m/%d/%Y %H:%M:%S",    # 05/15/2026 08:25:56  (US format)
        "%m/%d/%Y",             # 05/15/2026
    ):
        try:
            return datetime.strptime(date_str, fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def _parse_date_from_filename(filename: str) -> Optional[date]:
    """Extract submission date embedded in DHA eClaimLink filenames.

    Common patterns:
      TPA029-DHA-F-0047100-MAY-2026-SUB-15052026082556AM.xml  → 2026-05-15
      OP-AC-CR-TPA029-0047100-15052026123045PM.xml             → 2026-05-15

    The date is encoded as DDMMYYYY followed by optional HHMMSS + AM/PM.
    Year is anchored to 20xx to avoid false matches on other 8-digit sequences.
    """
    import re
    m = re.search(r'(\d{2})(\d{2})(20\d{2})\d{6}(?:AM|PM)', filename, re.IGNORECASE)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(year, month, day)
        except ValueError:
            pass
    return None


# ----------------------------------------------------------------------------
# Window-splitting search
# ----------------------------------------------------------------------------
def _search_with_splitting(
    client: DHPOSoapClient,
    login: str,
    pwd: str,
    direction: int,
    caller_license: Optional[str],
    tx_id: int,
    date_from: date,
    date_to: date,
    tx_status: int,
    seen_ids: Set[str],
    depth: int = 0,
) -> List[Dict]:
    """
    Calls SearchTransactions for [date_from, date_to].  If the result count
    equals DHPO_SEARCH_CAP the server has capped the response and there may be
    more files.  The date range is then bisected and each half is fetched
    recursively until every sub-window returns fewer than DHPO_SEARCH_CAP files.

    ``seen_ids`` is shared across all recursive calls so duplicates that appear
    in overlapping sub-windows are silently dropped.

    Max recursion depth: 12 (covers a 4096-day / ~11-year range down to
    single days without any stack risk in practice).
    """
    if depth > 12:
        log.warning(
            "Window-split max depth reached for %s → %s (status=%d); "
            "returning partial results.",
            date_from, date_to, tx_status,
        )

    batch = client.search_transactions(
        login=login,
        pwd=pwd,
        direction=direction,
        caller_license=caller_license,
        transaction_id=tx_id,
        date_from=date_from,
        date_to=date_to,
        transaction_status=tx_status,
    )

    if len(batch) < DHPO_SEARCH_CAP or depth > 12:
        # Under the cap (or recursion limit hit) — accept what we have
        new_files = [d for d in batch if d["file_id"] not in seen_ids]
        for d in new_files:
            seen_ids.add(d["file_id"])
        log.info(
            "  window [%s → %s] status=%d depth=%d: %d file(s) returned, %d new",
            date_from, date_to, tx_status, depth, len(batch), len(new_files),
        )
        return new_files

    # Exactly DHPO_SEARCH_CAP (or more) — cap was hit
    days = (date_to - date_from).days
    if days == 0:
        # Single-day window already at cap — nothing more we can do
        log.warning(
            "Single-day window %s still hits DHPO cap (%d files, status=%d). "
            "Some files may be missing for this day.",
            date_from, len(batch), tx_status,
        )
        new_files = [d for d in batch if d["file_id"] not in seen_ids]
        for d in new_files:
            seen_ids.add(d["file_id"])
        return new_files

    # Bisect: left half [date_from … mid], right half [mid+1 … date_to]
    mid = date_from + timedelta(days=days // 2)
    log.info(
        "SearchTransactions hit cap (%d) for [%s → %s] status=%d — "
        "splitting at %s (depth=%d)",
        len(batch), date_from, date_to, tx_status, mid, depth,
    )

    left = _search_with_splitting(
        client, login, pwd, direction, caller_license, tx_id,
        date_from, mid, tx_status, seen_ids, depth + 1,
    )
    right = _search_with_splitting(
        client, login, pwd, direction, caller_license, tx_id,
        mid + timedelta(days=1), date_to, tx_status, seen_ids, depth + 1,
    )
    return left + right


# ----------------------------------------------------------------------------
# Main service
# ----------------------------------------------------------------------------
class DHASyncService:
    """
    Can be used either:
      - bound to an existing request-scoped Session: `DHASyncService(session=db)`
      - standalone (CLI/cron): `DHASyncService(db_url=...)`
    """

    def __init__(
        self,
        db_url: Optional[str] = None,
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

    def close(self) -> None:
        if self._owns_session:
            self.db.close()

    def __enter__(self) -> "DHASyncService":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Public orchestration entry point
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
                except Exception as exc:
                    log.error(
                        "eClaimLink fetch failed for %s / %s: %s",
                        facility.facility_code, xml_type, exc,
                        exc_info=True,
                    )
                    http_errors += 1
                    error_detail[xml_type] = str(exc)
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

            # Parse everything pending (newly fetched + any manually uploaded)
            parser = DHPOXmlParser(self.db)
            summary = parser.run_pending(facility_id=facility_id)

            fetch_log.completed_at = datetime.now(timezone.utc)
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

        except Exception as exc:
            self.db.rollback()
            fetch_log.completed_at = datetime.now(timezone.utc)
            fetch_log.status = "failed"
            fetch_log.error_detail = {"error": str(exc)}
            self.db.commit()
            raise

    # ------------------------------------------------------------------
    # Per xml_type fetch via DHPO SOAP
    # ------------------------------------------------------------------
    def _fetch_transactions(
        self,
        facility: Facility,
        xml_type: str,
        date_from: date,
        date_to: date,
    ) -> List[Dict[str, Any]]:
        """
        Uses SearchTransactions + DownloadTransactionFile + SetTransactionDownloaded
        per the DHPO WebService Specification V3 (July 2017).

        Returns a list of {"xml": str, "filename": str, "submission_date": date}.
        """
        login = facility.eclaimlink_username
        pwd   = facility.credential_key
        caller_license = facility.dhpo_provider_id  # may be None

        if not login or not pwd:
            log.warning(
                "Facility %s has no eClaimLink credentials — skipping %s fetch.",
                facility.facility_code, xml_type,
            )
            return []

        # Map xml_type → DHPO transactionID + direction
        if xml_type == "ClaimSubmission":
            tx_id     = TX_CLAIM_SUBMISSION
            direction = DIRECTION_SENT       # provider sent claims to payer
        elif xml_type == "RemittanceAdvice":
            tx_id     = TX_REMITTANCE_ADVICE
            direction = DIRECTION_RECEIVED   # provider received remittance from payer
        else:
            log.warning("Unknown xml_type %s — skipping.", xml_type)
            return []

        # Choose WSDL: use archive if date_from is older than 24 months
        months_ago = (date.today().year - date_from.year) * 12 + (
            date.today().month - date_from.month
        )
        if xml_type == "ClaimSubmission" and months_ago >= 24:
            wsdl = DHPO_ARCHIVE_WSDL
            log.info("Using ARCHIVE endpoint for %s (%.0f months ago)", xml_type, months_ago)
        else:
            wsdl = DHPO_LIVE_WSDL

        client = DHPOSoapClient(wsdl)

        log.info(
            "SearchTransactions: facility=%s xml_type=%s from=%s to=%s direction=%d tx_id=%d",
            facility.facility_code, xml_type, date_from, date_to, direction, tx_id,
        )

        # Fetch both new (status=1) and already-downloaded (status=2) files.
        # status=2 captures files previously downloaded via the eClaimLink portal
        # that were never pulled through this API.
        #
        # _search_with_splitting automatically bisects the date window whenever
        # DHPO returns exactly 500 results (its hard cap), recursing until every
        # sub-window returns < 500 — so no files are silently missed.
        file_descriptors: List[Dict] = []
        seen_ids: Set[str] = set()
        for tx_status in (1, 2):
            try:
                batch = _search_with_splitting(
                    client=client,
                    login=login,
                    pwd=pwd,
                    direction=direction,
                    caller_license=caller_license,
                    tx_id=tx_id,
                    date_from=date_from,
                    date_to=date_to,
                    tx_status=tx_status,
                    seen_ids=seen_ids,
                )
                file_descriptors.extend(batch)
                log.info(
                    "SearchTransactions status=%d: %d unique file(s) for %s / %s",
                    tx_status, len(batch), facility.facility_code, xml_type,
                )
            except Exception as exc:
                log.warning("SearchTransactions status=%d failed: %s", tx_status, exc)

        log.info(
            "SearchTransactions total %d unique file(s) for %s / %s",
            len(file_descriptors), facility.facility_code, xml_type,
        )

        payloads: List[Dict[str, Any]] = []

        for desc in file_descriptors:
            file_id   = desc["file_id"]
            file_name = desc["file_name"] or f"file_{file_id}.xml"
            tx_date   = _parse_tx_date(desc.get("transaction_date", ""))
            if tx_date is None:
                tx_date = _parse_date_from_filename(file_name)
                if tx_date:
                    log.info("tx_date extracted from filename %s → %s", file_name, tx_date)
                else:
                    log.warning(
                        "Could not parse TransactionDate '%s' from file '%s'; "
                        "falling back to date_to=%s",
                        desc.get("transaction_date", ""), file_name, date_to,
                    )

            log.info(
                "Downloading FileID=%s FileName=%s RecordCount=%s tx_date=%s",
                file_id, file_name, desc.get("record_count"), tx_date,
            )

            try:
                raw_bytes = client.download_transaction_file(login, pwd, file_id)
            except Exception as exc:
                log.error("DownloadTransactionFile(%s) failed: %s", file_id, exc)
                continue

            # Decompress ZIP or decode plain XML
            extracted = _extract_xml_from_bytes(raw_bytes, file_name)
            if not extracted:
                log.warning("No XML extracted from FileID=%s FileName=%s", file_id, file_name)
                continue

            for item in extracted:
                payloads.append({
                    "xml":             item["xml"],
                    "filename":        item["filename"],
                    "submission_date": tx_date or date_to,
                })

            # SetTransactionDownloaded intentionally skipped — we want files
            # to remain available on DHPO's side for re-fetching if needed.
            # client.set_transaction_downloaded(login, pwd, file_id)

        return payloads
