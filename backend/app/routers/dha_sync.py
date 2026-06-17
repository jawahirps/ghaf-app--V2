"""
Ghaf App — DHA XML Sync pipeline endpoints.

Workflow:
  1. ClaimSubmission / RemittanceAdvice XML payloads (DHA Shafafiya /
     eClaimLink format) are staged via POST /api/dha-sync/upload, which
     writes a row to `raw_xml_store` with parse_status="pending".
  2. POST /api/dha-sync/trigger runs the DHPOXmlParser over all pending
     records for a facility, normalizing them into claims/remittances and
     recording a FetchLog entry for observability.
  3. GET endpoints expose raw XML and fetch-log history for the
     "DHA XML Sync" view in the React app.
"""
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import FetchLog, RawXmlStore, User
from ..schemas import DhaFetchRequest, DhaSyncTriggerResponse, DhaUploadResponse, FetchLogOut, RawXmlStoreOut
from ..security import get_current_user, require_roles
from ..services.dhpo_parser import DHPOXmlParser
from ..services.fetch_service import DHASyncService

router = APIRouter(prefix="/api/dha-sync", tags=["dha-sync"])

ALLOWED_XML_TYPES = {"ClaimSubmission", "RemittanceAdvice"}


@router.post("/upload", response_model=DhaUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_xml(
    facility_id: int,
    xml_type: str,
    submission_date: Optional[date] = None,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "billing_manager")),
):
    """Stage a DHA ClaimSubmission / RemittanceAdvice XML file for parsing."""
    if xml_type not in ALLOWED_XML_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"xml_type must be one of {sorted(ALLOWED_XML_TYPES)}",
        )

    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")

    record = RawXmlStore(
        facility_id=facility_id,
        xml_type=xml_type,
        source_filename=file.filename,
        submission_date=submission_date or date.today(),
        file_size_bytes=len(raw_bytes),
        xml_content=raw_bytes.decode("utf-8", errors="replace"),
        parse_status="pending",
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return DhaUploadResponse(
        raw_xml_id=record.id,
        xml_type=record.xml_type,
        source_filename=record.source_filename,
        parse_status=record.parse_status,
    )


@router.post("/trigger", response_model=DhaSyncTriggerResponse)
def trigger_sync(
    facility_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "billing_manager")),
):
    """Run the DHA XML Sync pipeline over all pending raw XML records."""
    facility_scope = facility_id or current_user.facility_id

    fetch_log = FetchLog(
        facility_id=facility_scope or 0,
        fetch_type="Backfill",
        date_from=date.today(),
        date_to=date.today(),
        status="running",
    )
    db.add(fetch_log)
    db.commit()
    db.refresh(fetch_log)

    try:
        parser = DHPOXmlParser(db)
        summary = parser.run_pending(facility_id=facility_scope)

        fetch_log.completed_at = datetime.utcnow()
        fetch_log.records_fetched = summary.pending_records
        fetch_log.records_parsed = summary.records_parsed_total
        fetch_log.records_failed = summary.quarantined_records
        fetch_log.status = (
            "success" if summary.quarantined_records == 0 else
            ("failed" if summary.parsed_records == 0 else "partial")
        )
        db.commit()

        return DhaSyncTriggerResponse(
            fetch_log_id=fetch_log.id,
            status=fetch_log.status,
            pending_records=summary.pending_records,
            parsed_records=summary.parsed_records,
            quarantined_records=summary.quarantined_records,
            message=(
                f"Processed {summary.pending_records} staged file(s): "
                f"{summary.parsed_records} parsed, {summary.quarantined_records} quarantined "
                f"({summary.records_parsed_total} claim/remittance records)."
            ),
        )
    except Exception as e:
        fetch_log.completed_at = datetime.utcnow()
        fetch_log.status = "failed"
        fetch_log.error_detail = {"error": str(e)}
        db.commit()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"DHA sync failed: {e}")


@router.post("/fetch", response_model=FetchLogOut)
def fetch_from_eclaimlink(
    payload: DhaFetchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "billing_manager")),
):
    """
    Live eClaimLink (DHPO) fetch for a date range, then parse.

    Pulls ClaimSubmission / RemittanceAdvice transactions for the facility
    and date range via DHASyncService, stages them in raw_xml_store, and
    runs the DHA XML Sync parser over everything pending. See
    app/services/fetch_service.py to wire up the real DHPO SOAP client.
    """
    facility_scope = payload.facility_id or current_user.facility_id
    if facility_scope is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="facility_id is required")

    if payload.date_to < payload.date_from:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="date_to must be on or after date_from")

    try:
        worker = DHASyncService(session=db)
        fetch_log = worker.run_sync_pipeline(
            facility_id=facility_scope,
            date_from=payload.date_from,
            date_to=payload.date_to,
        )
        return fetch_log
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"DHA fetch failed: {e}")


@router.get("/raw-xml", response_model=List[RawXmlStoreOut])
def list_raw_xml(
    facility_id: Optional[int] = None,
    parse_status: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(RawXmlStore)

    facility_scope = facility_id or current_user.facility_id
    if facility_scope is not None:
        query = query.filter(RawXmlStore.facility_id == facility_scope)
    if parse_status:
        query = query.filter(RawXmlStore.parse_status == parse_status)

    return query.order_by(RawXmlStore.fetched_at.desc()).limit(min(limit, 500)).all()


@router.get("/fetch-logs", response_model=List[FetchLogOut])
def list_fetch_logs(
    facility_id: Optional[int] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(FetchLog)

    facility_scope = facility_id or current_user.facility_id
    if facility_scope is not None:
        query = query.filter(FetchLog.facility_id == facility_scope)

    return query.order_by(FetchLog.started_at.desc()).limit(min(limit, 200)).all()
