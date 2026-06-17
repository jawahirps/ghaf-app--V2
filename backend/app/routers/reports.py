"""
Ghaf App — Advanced Excel Report Exports.

Six report types available at GET /api/reports/... (direct download)
and POST /api/reports/generate/{type} (staged to report_jobs queue).

  1. claim-summary       → one row per claim with financials & RA
  2. claim-activity      → service-line (CPT) detail per claim
  3. denial-analysis     → denial breakdown grouped by payer + code
  4. resubmission-aging  → AR aging with bucket classification
  5. remittance-activity → activity-level remittance detail
  6. denial-query        → denied claims with CPT code and RA info

All endpoints accept:
  facility_id, payer_id, encounter_type, date_from, date_to,
  date_field ("treatment_date" | "remittance_date")

date_field controls whether date_from/date_to filter on:
  - encounter_start  (treatment date, the default)
  - remittance_date  (RA transaction date)
"""
from __future__ import annotations

import io
import json as json_mod
from datetime import date, datetime, timezone as _tz
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy import and_, func, cast, Date
from sqlalchemy.orm import Session, aliased

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from ..database import get_db
from ..models import (
    Claim, ClaimActivity, Facility, Remittance,
    RemittanceActivityDetail, ReportJob,
)
from ..security import get_current_user

router = APIRouter(prefix="/api/reports", tags=["reports"])

# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------
HEADER_FONT = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
HEADER_FILL = PatternFill("solid", fgColor="1E3A5F")
ALT_FILL    = PatternFill("solid", fgColor="EEF2F7")
NORMAL_FONT = Font(name="Calibri", size=10)
THIN        = Side(style="thin", color="CCCCCC")
CELL_BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

REPORT_LABELS = {
    "claim-summary":      "Claim Summary Report",
    "claim-activity":     "Claim Activity Report",
    "denial-analysis":    "Denial Analysis Report",
    "resubmission-aging": "Resubmission & Aging Report",
    "remittance-activity":"Remittance Activity Report",
    "denial-query":       "Denial Query Report",
}


def _excel_response(wb: openpyxl.Workbook, filename: str) -> StreamingResponse:
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        },
    )


def _wb_to_bytes(wb: openpyxl.Workbook) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _write_headers(ws, cols: list[str]) -> None:
    for i, name in enumerate(cols, 1):
        cell = ws.cell(row=1, column=i, value=name)
        cell.font      = HEADER_FONT
        cell.fill      = HEADER_FILL
        cell.border    = CELL_BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 28


def _write_row(ws, row_idx: int, values: list, alt: bool = False) -> None:
    fill = ALT_FILL if alt else None
    for i, val in enumerate(values, 1):
        cell = ws.cell(row=row_idx, column=i, value=val)
        cell.font   = NORMAL_FONT
        cell.border = CELL_BORDER
        if fill:
            cell.fill = fill
        if isinstance(val, (int, float)):
            cell.alignment = Alignment(horizontal="right")


def _auto_width(ws, cols: list[str]) -> None:
    for i, name in enumerate(cols, 1):
        ws.column_dimensions[get_column_letter(i)].width = min(len(name) + 4, 32)


def _fmt_date(d) -> str:
    if d is None:
        return ""
    return d.strftime("%d/%m/%Y") if hasattr(d, "strftime") else str(d)


def _f(v) -> float | str:
    if v is None:
        return ""
    try:
        return float(v)
    except Exception:
        return str(v)


def _apply_filters(q, facility_id, payer_id, encounter_type,
                   date_from, date_to,
                   date_field: str = "treatment_date",
                   rem_model=None):
    """Apply standard filters. date_field controls which date column is used.

    rem_model — pass the aliased/base Remittance if already joined and
    date_field == 'remittance_date' should use it.
    """
    if facility_id:
        q = q.filter(Claim.facility_id == facility_id)
    if payer_id:
        q = q.filter(Claim.payer_id == payer_id)
    if encounter_type:
        q = q.filter(Claim.encounter_type == encounter_type)

    if date_field == "remittance_date" and rem_model is not None:
        if date_from:
            q = q.filter(rem_model.remittance_date >= date_from)
        if date_to:
            q = q.filter(rem_model.remittance_date <= date_to)
    else:
        # Default: filter on treatment date (encounter_start)
        if date_from:
            q = q.filter(cast(Claim.encounter_start, Date) >= date_from)
        if date_to:
            q = q.filter(cast(Claim.encounter_start, Date) <= date_to)
    return q


# ---------------------------------------------------------------------------
# 1. CLAIM SUMMARY
# ---------------------------------------------------------------------------
CLAIM_SUMMARY_COLS = [
    "Facility Name", "Claim Number", "Receiver Id", "Receiver Name",
    "Payer ID", "Payer Name", "Member Id",
    "Treatment Date", "Submission Date", "Encounter Type",
    "Clinician Name", "Submission Level",
    "Net Amt - Initial Sub", "Approved Amt",
    "Rejected Amt", "Unsettled Amt",
    "Payment Status", "Denial Code", "Denial Description",
    "RA Date", "TAT (Days)",
]


def _build_claim_summary(db, facility_id, payer_id, encounter_type,
                         date_from, date_to, date_field):
    fac_map = {f.id: f.facility_name for f in db.query(Facility).all()}

    latest_rem_sq = (
        db.query(
            Remittance.facility_id,
            Remittance.claim_id,
            func.max(Remittance.id).label("max_id"),
        )
        .group_by(Remittance.facility_id, Remittance.claim_id)
        .subquery()
    )
    latest_rem = aliased(Remittance)

    q = (
        db.query(Claim, latest_rem)
        .outerjoin(latest_rem_sq, and_(
            Claim.facility_id == latest_rem_sq.c.facility_id,
            Claim.claim_id    == latest_rem_sq.c.claim_id,
        ))
        .outerjoin(latest_rem, latest_rem.id == latest_rem_sq.c.max_id)
    )
    q = _apply_filters(q, facility_id, payer_id, encounter_type,
                       date_from, date_to, date_field, rem_model=latest_rem)
    rows = q.order_by(Claim.submission_date.desc()).all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Claim Summary"
    ws.freeze_panes = "A2"
    _write_headers(ws, CLAIM_SUMMARY_COLS)

    for row_idx, (claim, rem) in enumerate(rows, start=2):
        sub_level = "Resubmission" if claim.resubmission_count > 0 else "Initial Submission"
        approved  = _f(rem.paid_amount)   if rem else ""
        rejected  = _f(rem.denial_amount) if rem else ""
        net       = _f(claim.net_amount)
        unsettled = ""
        if rem and claim.net_amount is not None and rem.paid_amount is not None:
            try:
                unsettled = round(float(claim.net_amount) - float(rem.paid_amount), 2)
            except Exception:
                pass
        pay_status = rem.claim_status_ra or ""   if rem else ""
        den_code   = rem.denial_code or ""        if rem else ""
        den_desc   = rem.denial_description or "" if rem else ""
        ra_date    = _fmt_date(rem.remittance_date) if rem else ""
        tat        = ""
        if rem and rem.remittance_date and claim.submission_date:
            try:
                tat = (rem.remittance_date - claim.submission_date).days
            except Exception:
                pass

        _write_row(ws, row_idx, [
            fac_map.get(claim.facility_id, ""),
            claim.claim_id,
            claim.receiver_id or "",
            claim.receiver_name or "",
            claim.payer_id,
            claim.payer_name or "",
            claim.member_id,
            _fmt_date(claim.encounter_start),
            _fmt_date(claim.submission_date),
            claim.encounter_type or "",
            claim.clinician_name or "",
            sub_level,
            net, approved, rejected, unsettled,
            pay_status, den_code, den_desc, ra_date, tat,
        ], alt=(row_idx % 2 == 0))

    _auto_width(ws, CLAIM_SUMMARY_COLS)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    return wb, f"ClaimSummary_{ts}.xlsx", len(rows)


@router.get("/claim-summary")
def export_claim_summary(
    facility_id:    Optional[int]  = None,
    payer_id:       Optional[str]  = None,
    encounter_type: Optional[str]  = None,
    date_from:      Optional[date] = None,
    date_to:        Optional[date] = None,
    date_field:     Optional[str]  = "treatment_date",
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    wb, filename, _ = _build_claim_summary(
        db, facility_id, payer_id, encounter_type, date_from, date_to, date_field)
    return _excel_response(wb, filename)


# ---------------------------------------------------------------------------
# 2. CLAIM ACTIVITY
# ---------------------------------------------------------------------------
CLAIM_ACTIVITY_COLS = [
    "Facility Name", "Claim Number", "Receiver Id", "Receiver Name",
    "Payer ID", "Payer Name", "Member Id",
    "Encounter Start", "Transaction Date",
    "Clinician ID", "Clinician Name", "Prior Auth ID",
    "CPT Type", "Claim Activity Number", "CPT Code",
    "Quantity", "Net Amount",
]


def _build_claim_activity(db, facility_id, payer_id, encounter_type,
                          date_from, date_to, date_field):
    fac_map = {f.id: f.facility_name for f in db.query(Facility).all()}

    q = (
        db.query(ClaimActivity, Claim)
        .join(Claim, Claim.id == ClaimActivity.claim_id_fk)
    )
    if facility_id:
        q = q.filter(Claim.facility_id == facility_id)
    if payer_id:
        q = q.filter(Claim.payer_id == payer_id)
    if encounter_type:
        q = q.filter(Claim.encounter_type == encounter_type)
    # Claim activity date filter always uses activity_start (treatment date)
    if date_from:
        q = q.filter(ClaimActivity.activity_start >= date_from)
    if date_to:
        q = q.filter(ClaimActivity.activity_start <= date_to)

    rows = q.order_by(Claim.submission_date.desc(), ClaimActivity.sequence_no).all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Claim Activity"
    ws.freeze_panes = "A2"
    _write_headers(ws, CLAIM_ACTIVITY_COLS)

    for row_idx, (act, claim) in enumerate(rows, start=2):
        _write_row(ws, row_idx, [
            fac_map.get(claim.facility_id, ""),
            claim.claim_id,
            claim.receiver_id or "",
            claim.receiver_name or "",
            claim.payer_id,
            claim.payer_name or "",
            claim.member_id,
            _fmt_date(act.activity_start),
            _fmt_date(act.activity_start),
            act.clinician_id or claim.clinician_id or "",
            claim.clinician_name or "",
            act.authorization_id or "",
            act.activity_type or "",
            act.sequence_no or "",
            act.activity_code or "",
            _f(act.quantity),
            _f(act.net),
        ], alt=(row_idx % 2 == 0))

    _auto_width(ws, CLAIM_ACTIVITY_COLS)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    return wb, f"ClaimActivity_{ts}.xlsx", len(rows)


@router.get("/claim-activity")
def export_claim_activity(
    facility_id:    Optional[int]  = None,
    payer_id:       Optional[str]  = None,
    encounter_type: Optional[str]  = None,
    date_from:      Optional[date] = None,
    date_to:        Optional[date] = None,
    date_field:     Optional[str]  = "treatment_date",
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    wb, filename, _ = _build_claim_activity(
        db, facility_id, payer_id, encounter_type, date_from, date_to, date_field)
    return _excel_response(wb, filename)


# ---------------------------------------------------------------------------
# 3. DENIAL ANALYSIS
# ---------------------------------------------------------------------------
DENIAL_COLS = [
    "Facility Name", "Payer ID", "Payer Name",
    "Denial Code", "Denial Description",
    "Claim Count", "Total Denied (AED)", "% of Total Denied",
]


def _build_denial_analysis(db, facility_id, payer_id, encounter_type,
                           date_from, date_to, date_field):
    fac_map = {f.id: f.facility_name for f in db.query(Facility).all()}

    q = (
        db.query(
            Claim.facility_id,
            Claim.payer_id,
            Claim.payer_name,
            Remittance.denial_code,
            Remittance.denial_description,
            func.count(Claim.id).label("claim_count"),
            func.coalesce(func.sum(Remittance.denial_amount), 0).label("total_denied"),
        )
        .join(Remittance, and_(
            Claim.facility_id == Remittance.facility_id,
            Claim.claim_id    == Remittance.claim_id,
        ))
        .filter(Remittance.denial_code.isnot(None), Remittance.denial_code != "")
    )
    if facility_id:
        q = q.filter(Claim.facility_id == facility_id)
    if payer_id:
        q = q.filter(Claim.payer_id == payer_id)
    if encounter_type:
        q = q.filter(Claim.encounter_type == encounter_type)

    # For denial analysis, date_field controls which date column
    if date_field == "remittance_date":
        if date_from:
            q = q.filter(Remittance.remittance_date >= date_from)
        if date_to:
            q = q.filter(Remittance.remittance_date <= date_to)
    else:
        if date_from:
            q = q.filter(cast(Claim.encounter_start, Date) >= date_from)
        if date_to:
            q = q.filter(cast(Claim.encounter_start, Date) <= date_to)

    q = q.group_by(
        Claim.facility_id, Claim.payer_id, Claim.payer_name,
        Remittance.denial_code, Remittance.denial_description,
    ).order_by(func.sum(Remittance.denial_amount).desc())

    rows = q.all()
    grand_total = sum(float(r.total_denied or 0) for r in rows)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Denial Analysis"
    ws.freeze_panes = "A2"
    _write_headers(ws, DENIAL_COLS)

    for row_idx, r in enumerate(rows, start=2):
        denied = float(r.total_denied or 0)
        pct = round(denied / grand_total * 100, 2) if grand_total else 0
        _write_row(ws, row_idx, [
            fac_map.get(r.facility_id, ""),
            r.payer_id,
            r.payer_name or "",
            r.denial_code or "",
            r.denial_description or "",
            r.claim_count,
            denied, pct,
        ], alt=(row_idx % 2 == 0))

    _auto_width(ws, DENIAL_COLS)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    return wb, f"DenialAnalysis_{ts}.xlsx", len(rows)


@router.get("/denial-analysis")
def export_denial_analysis(
    facility_id:    Optional[int]  = None,
    payer_id:       Optional[str]  = None,
    encounter_type: Optional[str]  = None,
    date_from:      Optional[date] = None,
    date_to:        Optional[date] = None,
    date_field:     Optional[str]  = "treatment_date",
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    wb, filename, _ = _build_denial_analysis(
        db, facility_id, payer_id, encounter_type, date_from, date_to, date_field)
    return _excel_response(wb, filename)


# ---------------------------------------------------------------------------
# 4. RESUBMISSION & AR AGING
# ---------------------------------------------------------------------------
AGING_COLS = [
    "Facility Name", "Claim Number", "Payer ID", "Payer Name",
    "Member Id", "Submission Date", "Encounter Type",
    "Net Amount (AED)", "Approved (AED)", "Unsettled (AED)",
    "Resubmission Count", "Days Outstanding",
    "Aging Bucket", "Payment Status", "Denial Code",
]

BUCKETS = [
    (30, "0-30 days"), (60, "31-60 days"), (90, "61-90 days"),
    (180, "91-180 days"), (365, "181-365 days"), (9999, "365+ days"),
]


def _bucket(days: int) -> str:
    for cutoff, label in BUCKETS:
        if days <= cutoff:
            return label
    return "365+ days"


def _build_resubmission_aging(db, facility_id, payer_id, encounter_type,
                              date_from, date_to, date_field,
                              unsettled_only: bool = True):
    fac_map = {f.id: f.facility_name for f in db.query(Facility).all()}
    today   = date.today()

    q = (
        db.query(Claim, Remittance)
        .outerjoin(Remittance, and_(
            Claim.facility_id == Remittance.facility_id,
            Claim.claim_id    == Remittance.claim_id,
        ))
    )
    q = _apply_filters(q, facility_id, payer_id, encounter_type,
                       date_from, date_to, date_field, rem_model=Remittance)
    rows = q.order_by(Claim.submission_date).all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Resubmission & Aging"
    ws.freeze_panes = "A2"
    _write_headers(ws, AGING_COLS)

    row_idx   = 2
    row_count = 0
    for claim, rem in rows:
        net       = float(claim.net_amount or 0)
        approved  = float(rem.paid_amount or 0) if rem else 0
        unsettled = round(net - approved, 2)

        if unsettled_only and unsettled <= 0:
            continue

        days_out = (today - claim.submission_date).days if claim.submission_date else 0

        _write_row(ws, row_idx, [
            fac_map.get(claim.facility_id, ""),
            claim.claim_id,
            claim.payer_id,
            claim.payer_name or "",
            claim.member_id,
            _fmt_date(claim.submission_date),
            claim.encounter_type or "",
            net, approved, unsettled,
            claim.resubmission_count,
            days_out,
            _bucket(days_out),
            rem.claim_status_ra or "Pending" if rem else "Pending",
            rem.denial_code or "" if rem else "",
        ], alt=(row_idx % 2 == 0))
        row_idx   += 1
        row_count += 1

    _auto_width(ws, AGING_COLS)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    return wb, f"ResubmissionAging_{ts}.xlsx", row_count


@router.get("/resubmission-aging")
def export_resubmission_aging(
    facility_id:    Optional[int]  = None,
    payer_id:       Optional[str]  = None,
    encounter_type: Optional[str]  = None,
    date_from:      Optional[date] = None,
    date_to:        Optional[date] = None,
    date_field:     Optional[str]  = "treatment_date",
    unsettled_only: bool = True,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    wb, filename, _ = _build_resubmission_aging(
        db, facility_id, payer_id, encounter_type, date_from, date_to, date_field,
        unsettled_only)
    return _excel_response(wb, filename)


# ---------------------------------------------------------------------------
# 5. REMITTANCE ACTIVITY
# ---------------------------------------------------------------------------
REMITTANCE_ACTIVITY_COLS = [
    "Facility ID", "Facility Name", "Receiver ID", "Receiver Name",
    "Payer ID", "Payer Name", "Patient ID", "Member Id", "Emirates Id",
    "Encounter Start Date", "Encounter End Date",
    "Encounter Start Year", "Encounter Start Month",
    "Last Submission Date", "First Submission Date", "Transaction Date",
    "Claim Number", "Encounter Type", "Encounter End Type",
    "IDPayer", "Payment Reference", "Date Settlement",
    "Service Date", "Clinician", "Ordering Clinician",
    "Activity Code", "Activity Type", "Activity Type Name",
    "No Of Unit", "Gross Amt", "Net Amt", "Patient Share",
    "Payment Amt", "Denial Code", "Denial Description", "Denial Category",
]


def _build_remittance_activity(db, facility_id, payer_id, encounter_type,
                               date_from, date_to, date_field):
    fac_map = {f.id: (f.facility_name, f.license_id) for f in db.query(Facility).all()}

    q = (
        db.query(RemittanceActivityDetail, Remittance, Claim)
        .join(Remittance, Remittance.id == RemittanceActivityDetail.remittance_id_fk)
        .join(Claim, and_(
            Claim.facility_id == Remittance.facility_id,
            Claim.claim_id    == Remittance.claim_id,
        ))
    )
    if facility_id:
        q = q.filter(Remittance.facility_id == facility_id)
    if payer_id:
        q = q.filter(Remittance.payer_id == payer_id)
    if encounter_type:
        q = q.filter(Claim.encounter_type == encounter_type)

    # Remittance Activity defaults to remittance_date, but respects date_field
    if date_field == "treatment_date":
        if date_from:
            q = q.filter(cast(Claim.encounter_start, Date) >= date_from)
        if date_to:
            q = q.filter(cast(Claim.encounter_start, Date) <= date_to)
    else:
        if date_from:
            q = q.filter(Remittance.remittance_date >= date_from)
        if date_to:
            q = q.filter(Remittance.remittance_date <= date_to)

    rows = q.order_by(Remittance.remittance_date.desc(), Claim.claim_id).all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "RemittanceActivityReportTemplat"
    ws.freeze_panes = "A2"
    _write_headers(ws, REMITTANCE_ACTIVITY_COLS)

    for row_idx, (rad, rem, claim) in enumerate(rows, start=2):
        fac_name  = fac_map.get(rem.facility_id, ("", ""))[0]
        enc_start = claim.encounter_start
        enc_year  = enc_start.year  if enc_start else ""
        enc_month = enc_start.month if enc_start else ""

        _write_row(ws, row_idx, [
            rem.facility_id, fac_name,
            claim.receiver_id or "", claim.receiver_name or "",
            claim.payer_id, claim.payer_name or "",
            claim.member_id, claim.member_id, claim.emirates_id or "",
            _fmt_date(enc_start), _fmt_date(claim.encounter_end),
            enc_year, enc_month,
            _fmt_date(claim.submission_date), _fmt_date(claim.submission_date),
            _fmt_date(rem.remittance_date),
            claim.claim_id, claim.encounter_type or "", claim.end_type or "",
            claim.claim_id_payer or "", rem.ra_file_id or "",
            _fmt_date(rem.remittance_date),
            _fmt_date(enc_start),
            claim.clinician_name or claim.clinician_id or "",
            claim.clinician_name or claim.clinician_id or "",
            rad.activity_code or "", rad.activity_type or "", rad.activity_type or "",
            _f(rad.quantity_approved), _f(rad.gross), _f(rad.net),
            _f(rad.patient_share), _f(rad.paid_amount),
            rad.denial_code or "", rad.denial_description or "", "",
        ], alt=(row_idx % 2 == 0))

    _auto_width(ws, REMITTANCE_ACTIVITY_COLS)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    return wb, f"RemittanceActivity_{ts}.xlsx", len(rows)


@router.get("/remittance-activity")
def export_remittance_activity(
    facility_id:    Optional[int]  = None,
    payer_id:       Optional[str]  = None,
    encounter_type: Optional[str]  = None,
    date_from:      Optional[date] = None,
    date_to:        Optional[date] = None,
    date_field:     Optional[str]  = "remittance_date",
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    wb, filename, _ = _build_remittance_activity(
        db, facility_id, payer_id, encounter_type, date_from, date_to, date_field)
    return _excel_response(wb, filename)


# ---------------------------------------------------------------------------
# 6. DENIAL QUERY
# ---------------------------------------------------------------------------
DENIAL_QUERY_COLS = [
    "RAHistory", "Submission Level", "License No",
    "Facility Name", "Receiver Id", "Receiver Name",
    "Payer ID", "Payer Name", "Member Id", "Emirates Id",
    "Invoice No", "Payment Status", "RAFile Name",
    "Service Date", "CPTCode",
    "Claim Amt", "Paid Amt", "Denied Amt",
    "Remittance Date", "Last Resub Date",
    "Denial Code", "F1comments", "R1Comments",
]


def _build_denial_query(db, facility_id, payer_id, encounter_type,
                        date_from, date_to, date_field):
    fac_map = {f.id: (f.facility_name, f.license_id) for f in db.query(Facility).all()}

    first_cpt_sq = (
        db.query(
            ClaimActivity.claim_id_fk,
            func.min(ClaimActivity.activity_code).label("first_cpt"),
        )
        .filter(ClaimActivity.activity_type == "CPT")
        .group_by(ClaimActivity.claim_id_fk)
        .subquery()
    )

    q = (
        db.query(Claim, Remittance, first_cpt_sq.c.first_cpt)
        .join(Remittance, and_(
            Claim.facility_id == Remittance.facility_id,
            Claim.claim_id    == Remittance.claim_id,
        ))
        .outerjoin(first_cpt_sq, first_cpt_sq.c.claim_id_fk == Claim.id)
        .filter(
            Remittance.denial_code.isnot(None),
            Remittance.denial_code != "",
        )
    )
    if facility_id:
        q = q.filter(Claim.facility_id == facility_id)
    if payer_id:
        q = q.filter(Claim.payer_id == payer_id)
    if encounter_type:
        q = q.filter(Claim.encounter_type == encounter_type)

    # Denial query defaults to remittance date; respects date_field
    if date_field == "treatment_date":
        if date_from:
            q = q.filter(cast(Claim.encounter_start, Date) >= date_from)
        if date_to:
            q = q.filter(cast(Claim.encounter_start, Date) <= date_to)
    else:
        if date_from:
            q = q.filter(Remittance.remittance_date >= date_from)
        if date_to:
            q = q.filter(Remittance.remittance_date <= date_to)

    rows = q.order_by(Remittance.remittance_date.desc(), Claim.claim_id).all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "DenialQueryReport"
    ws.freeze_panes = "A2"
    _write_headers(ws, DENIAL_QUERY_COLS)

    for row_idx, (claim, rem, first_cpt) in enumerate(rows, start=2):
        fac_name, lic_no = fac_map.get(claim.facility_id, ("", ""))
        sub_level  = "Resubmission" if claim.resubmission_count > 0 else "Initial Submission"
        ra_history = claim.resubmission_count

        _write_row(ws, row_idx, [
            ra_history, sub_level, lic_no, fac_name,
            claim.receiver_id or "", claim.receiver_name or "",
            claim.payer_id, claim.payer_name or "",
            claim.member_id, claim.emirates_id or "",
            claim.claim_id,
            rem.claim_status_ra or "", rem.ra_file_id or "",
            _fmt_date(claim.encounter_start),
            first_cpt or "",
            _f(claim.net_amount), _f(rem.paid_amount), _f(rem.denial_amount),
            _fmt_date(rem.remittance_date),
            _fmt_date(claim.submission_date),
            rem.denial_code or "", "", "",
        ], alt=(row_idx % 2 == 0))

    _auto_width(ws, DENIAL_QUERY_COLS)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    return wb, f"DenialQuery_{ts}.xlsx", len(rows)


@router.get("/denial-query")
def export_denial_query(
    facility_id:    Optional[int]  = None,
    payer_id:       Optional[str]  = None,
    encounter_type: Optional[str]  = None,
    date_from:      Optional[date] = None,
    date_to:        Optional[date] = None,
    date_field:     Optional[str]  = "remittance_date",
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    wb, filename, _ = _build_denial_query(
        db, facility_id, payer_id, encounter_type, date_from, date_to, date_field)
    return _excel_response(wb, filename)


# ---------------------------------------------------------------------------
# Report builder dispatch map
# ---------------------------------------------------------------------------
REPORT_BUILDERS = {
    "claim-summary":      _build_claim_summary,
    "claim-activity":     _build_claim_activity,
    "denial-analysis":    _build_denial_analysis,
    "resubmission-aging": _build_resubmission_aging,
    "remittance-activity":_build_remittance_activity,
    "denial-query":       _build_denial_query,
}


# ---------------------------------------------------------------------------
# STAGING QUEUE ENDPOINTS
# ---------------------------------------------------------------------------

@router.post("/generate/{report_type}")
def generate_report_job(
    report_type:    str,
    facility_id:    Optional[int]  = None,
    payer_id:       Optional[str]  = None,
    encounter_type: Optional[str]  = None,
    date_from:      Optional[date] = None,
    date_to:        Optional[date] = None,
    date_field:     Optional[str]  = "treatment_date",
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Generate a report and save it to the report_jobs staging queue."""
    try:
        builder = REPORT_BUILDERS.get(report_type)
        if not builder:
            raise HTTPException(status_code=404, detail=f"Unknown report type: {report_type}")

        # Build the workbook
        try:
            wb, filename, row_count = builder(
                db, facility_id, payer_id, encounter_type, date_from, date_to, date_field)
            file_bytes = _wb_to_bytes(wb)
            status     = "completed"
            error_msg  = None
        except Exception as exc:
            import traceback
            file_bytes = None
            filename   = None
            row_count  = 0
            status     = "error"
            error_msg  = traceback.format_exc()

        # Persist to DB
        filters_dict = {
            "facility_id":    facility_id,
            "payer_id":       payer_id,
            "encounter_type": encounter_type,
            "date_from":      str(date_from) if date_from else None,
            "date_to":        str(date_to)   if date_to   else None,
            "date_field":     date_field,
        }

        # Safely get user_id — handle both ORM objects and Pydantic schemas
        user_id = getattr(current_user, "id", None) or getattr(current_user, "user_id", None)

        now = datetime.now(_tz.utc)
        job = ReportJob(
            user_id       = user_id,
            report_type   = report_type,
            report_label  = REPORT_LABELS.get(report_type, report_type),
            filters_json  = json_mod.dumps(filters_dict),
            status        = status,
            file_data     = file_bytes,
            filename      = filename,
            row_count     = row_count,
            error_message = error_msg,
            completed_at  = now,
        )
        db.add(job)
        db.flush()       # sends INSERT → populates job.id via RETURNING
        job_id = job.id  # capture id before commit expires attributes
        db.commit()
        # Do NOT call db.refresh(job) — it triggers a relationship-load bug

        return {
            "id":          job_id,
            "report_type": report_type,
            "report_label":REPORT_LABELS.get(report_type, report_type),
            "status":      status,
            "filename":    filename,
            "row_count":   row_count,
            "error":       error_msg,
            "created_at":  now.isoformat(),
            "completed_at":now.isoformat(),
            "filters":     filters_dict,
        }

    except HTTPException:
        raise
    except Exception as exc:
        import traceback
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@router.get("/jobs")
def list_report_jobs(
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List all report jobs (most recent first)."""
    try:
        # Select only non-BYTEA columns to avoid loading large file data on list
        from sqlalchemy import text as _text
        rows = db.execute(
            _text(
                "SELECT id, user_id, report_type, report_label, filters_json, "
                "status, filename, row_count, error_message, "
                "created_at, completed_at, "
                "(file_data IS NOT NULL) AS has_file "
                "FROM report_jobs ORDER BY created_at DESC LIMIT :lim"
            ),
            {"lim": limit},
        ).mappings().all()

        return [
            {
                "id":          r["id"],
                "report_type": r["report_type"],
                "report_label":r["report_label"],
                "status":      r["status"],
                "filename":    r["filename"],
                "row_count":   r["row_count"],
                "error":       r["error_message"],
                "has_file":    bool(r["has_file"]),
                "created_at":  r["created_at"].isoformat() if r["created_at"] else None,
                "completed_at":r["completed_at"].isoformat() if r["completed_at"] else None,
                "filters":     json_mod.loads(r["filters_json"]) if r["filters_json"] else {},
            }
            for r in rows
        ]
    except Exception as exc:
        import traceback
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@router.get("/jobs/{job_id}/download")
def download_report_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Download the Excel file for a previously generated report job."""
    job = db.get(ReportJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Report job not found")
    if not job.file_data:
        raise HTTPException(status_code=400,
                            detail="No file available for this job (status: " + job.status + ")")
    return StreamingResponse(
        io.BytesIO(job.file_data),
        headers={
            "Content-Disposition": f'attachment; filename="{job.filename or "report.xlsx"}"',
            "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        },
    )
