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
    RemittanceActivityDetail, ReportJob, RawXmlStore,
)
from ..security import get_current_user

router = APIRouter(prefix="/api/reports", tags=["reports"])

# ---------------------------------------------------------------------------
# DHA Denial Code lookup  (Code → description / category / type)
# Source: "Denial Codes 29Oct2024.xlsx"
# category = code family prefix (AUTH, CLAI, MNEC, …)
# type     = Technical | Medical
# ---------------------------------------------------------------------------
DENIAL_CODE_MAP: dict[str, dict] = {
    "AUTH-001": {"description": "Prior approval is required and was not obtained", "category": "AUTH", "type": "Technical"},
    "AUTH-002": {"description": "Services performed are inconsistent with authorized or approved services", "category": "AUTH", "type": "Technical"},
    "AUTH-003": {"description": "PriorAuthorizationNumber is invalid", "category": "AUTH", "type": "Technical"},
    "AUTH-004": {"description": "Service(s) is (are) performed outside authorization validity date", "category": "AUTH", "type": "Technical"},
    "AUTH-005": {"description": "Claim information is inconsistent with pre-certified/authorized services", "category": "AUTH", "type": "Technical"},
    "AUTH-006": {"description": "Alert drug - drug interaction or drug is contra-indicated", "category": "AUTH", "type": "Technical"},
    "AUTH-007": {"description": "Drug duplicate therapy", "category": "AUTH", "type": "Technical"},
    "AUTH-008": {"description": "Inappropriate drug dose", "category": "AUTH", "type": "Technical"},
    "AUTH-009": {"description": "Prescription out of date", "category": "AUTH", "type": "Technical"},
    "AUTH-010": {"description": "Authorization request overlaps or is within the period of another paid claim or approved authorization", "category": "AUTH", "type": "Technical"},
    "AUTH-011": {"description": "Waiting period on pre-existing / specific conditions", "category": "AUTH", "type": "Technical"},
    "AUTH-012": {"description": "Request for information", "category": "AUTH", "type": "Technical"},
    "AUTH-013": {"description": "Missing eRx Reference number", "category": "AUTH", "type": "Technical"},
    "AUTH-014": {"description": "Medication has been added to a prior request that is not in line with Pharmacist Edit Restrictions", "category": "AUTH", "type": "Technical"},
    "BENX-001": {"description": "Service / Medication is above AED threshold", "category": "BENX", "type": "Technical"},
    "BENX-002": {"description": "Benefit maximum for this time period or occurrence has been reached", "category": "BENX", "type": "Technical"},
    "BENX-005": {"description": "Annual limit/sublimit amount exceeded", "category": "BENX", "type": "Technical"},
    "BSMA-001": {"description": "Member not covered under Basmah", "category": "BSMA", "type": "Technical"},
    "BSMA-002": {"description": "Claims is not eligible under Basmah Fund", "category": "BSMA", "type": "Technical"},
    "BSMA-003": {"description": "Prior approval is required but not taken (Basmah)", "category": "BSMA", "type": "Technical"},
    "CLAI-007": {"description": "Claim is a work-related injury/illness and thus the liability of the employer", "category": "CLAI", "type": "Technical"},
    "CLAI-008": {"description": "Claim overlaps inpatient stay. Resubmit only those services rendered outside the inpatient stay", "category": "CLAI", "type": "Technical"},
    "CLAI-009": {"description": "Date of birth follows the date of service", "category": "CLAI", "type": "Technical"},
    "CLAI-010": {"description": "Date of death precedes the date of service", "category": "CLAI", "type": "Technical"},
    "CLAI-011": {"description": "Inpatient admission spans multiple rate periods. Resubmit separate claims", "category": "CLAI", "type": "Technical"},
    "CLAI-012": {"description": "Submission not compliant with contractual agreement between provider & payer", "category": "CLAI", "type": "Technical"},
    "CLAI-013": {"description": "Missing an Observation (Dental Tooth #)", "category": "CLAI", "type": "Technical"},
    "CLAI-014": {"description": "Claim not compliant with Resubmission type (used only for resubmissions)", "category": "CLAI", "type": "Technical"},
    "CLAI-017": {"description": "Services not available on direct billing", "category": "CLAI", "type": "Technical"},
    "CLAI-018": {"description": "Claims Recalled By Provider", "category": "CLAI", "type": "Technical"},
    "CLAI-019": {"description": "Incorrect IR-DRG code", "category": "CLAI", "type": "Technical"},
    "CLAI-020": {"description": "Missing IR-DRG code", "category": "CLAI", "type": "Technical"},
    "CLAI-021": {"description": "Incorrect DRG payment parameter", "category": "CLAI", "type": "Technical"},
    "CLAI-022": {"description": "Missing DRG payment parameter", "category": "CLAI", "type": "Technical"},
    "CLAI-023": {"description": "Submission not compliant with contractual agreement between non-network physician & payer", "category": "CLAI", "type": "Technical"},
    "CODE-001": {"description": "Missing, incomplete or invalid principal diagnosis", "category": "CODE", "type": "Technical"},
    "CODE-002": {"description": "Missing, incomplete or invalid service code", "category": "CODE", "type": "Technical"},
    "CODE-006": {"description": "Diagnosis is inconsistent with the procedure", "category": "CODE", "type": "Medical"},
    "CODE-010": {"description": "Activity/diagnosis inconsistent with clinician specialty", "category": "CODE", "type": "Technical"},
    "CODE-012": {"description": "Encounter type inconsistent with service(s) / diagnosis", "category": "CODE", "type": "Medical"},
    "CODE-013": {"description": "Invalid principal diagnosis", "category": "CODE", "type": "Medical"},
    "CODE-014": {"description": "Activity/diagnosis is inconsistent with the patient's age/gender", "category": "CODE", "type": "Medical"},
    "CODE-015": {"description": "Activity/diagnosis is inconsistent with the provider type", "category": "CODE", "type": "Technical"},
    "CODE-016": {"description": "Activity/diagnosis inconsistent with Service", "category": "CODE", "type": "Medical"},
    "COPY-001": {"description": "Deductible/co-pay not collected from member", "category": "COPY", "type": "Technical"},
    "COPY-002": {"description": "Incorrect Patient Share", "category": "COPY", "type": "Technical"},
    "COPY-003": {"description": "Missing Patient Share", "category": "COPY", "type": "Technical"},
    "DRG-001": {"description": "Incorrect DRG code", "category": "DRG", "type": "Technical"},
    "DRG-002": {"description": "Missing DRG code", "category": "DRG", "type": "Technical"},
    "DRG-003": {"description": "Incorrect Billing Regime", "category": "DRG", "type": "Technical"},
    "DRG-004": {"description": "Missing Activities", "category": "DRG", "type": "Technical"},
    "DRG-005": {"description": "Missing Observation (ActivityCost and/or File Attachment)", "category": "DRG", "type": "Technical"},
    "DUPL-001": {"description": "Claim is a duplicate based on service codes and dates", "category": "DUPL", "type": "Technical"},
    "DUPL-002": {"description": "Payment already made for same/similar service within set time frame", "category": "DUPL", "type": "Technical"},
    "ELIG-001": {"description": "Patient is not a covered member", "category": "ELIG", "type": "Technical"},
    "ELIG-005": {"description": "Services performed after the last date of coverage", "category": "ELIG", "type": "Technical"},
    "ELIG-006": {"description": "Services performed prior to the effective date of coverage", "category": "ELIG", "type": "Technical"},
    "ELIG-007": {"description": "Services performed by a non-network provider", "category": "ELIG", "type": "Technical"},
    "ELIG-008": {"description": "Services performed by a non-network physician", "category": "ELIG", "type": "Technical"},
    "MNEC-003": {"description": "Service is not clinically indicated based on good clinical practice", "category": "MNEC", "type": "Medical"},
    "MNEC-004": {"description": "Service is not clinically indicated based on good clinical practice, without additional supporting diagnoses/activities", "category": "MNEC", "type": "Medical"},
    "MNEC-005": {"description": "Service/supply may be appropriate, but too frequent", "category": "MNEC", "type": "Medical"},
    "MNEC-006": {"description": "Alternative service should have been utilized", "category": "MNEC", "type": "Medical"},
    "MNEC-007": {"description": "Service is not clinically indicated based on good clinical practice, without additional supporting documentation", "category": "MNEC", "type": "Medical"},
    "NCOV-001": {"description": "Diagnosis(es) is (are) not covered", "category": "NCOV", "type": "Medical"},
    "NCOV-002": {"description": "Pre-existing conditions are not covered", "category": "NCOV", "type": "Technical"},
    "NCOV-003": {"description": "Service(s) is (are) not covered", "category": "NCOV", "type": "Medical"},
    "NCOV-009": {"description": "Dental treatments are not covered", "category": "NCOV", "type": "Medical"},
    "NCOV-010": {"description": "Elective procedure is not covered", "category": "NCOV", "type": "Medical"},
    "NCOV-012": {"description": "Eye exams and treatments are not covered", "category": "NCOV", "type": "Medical"},
    "NCOV-014": {"description": "Hearing services are not covered", "category": "NCOV", "type": "Medical"},
    "NCOV-018": {"description": "Immunizations are not covered", "category": "NCOV", "type": "Technical"},
    "NCOV-019": {"description": "Preventative care is not covered", "category": "NCOV", "type": "Technical"},
    "NCOV-020": {"description": "Services resulting from attempted suicide or self-infliction are not covered", "category": "NCOV", "type": "Technical"},
    "NCOV-021": {"description": "Vaccinations are not covered", "category": "NCOV", "type": "Medical"},
    "NCOV-024": {"description": "Chronic Condition Service(s) is (are) not covered", "category": "NCOV", "type": "Medical"},
    "NCOV-025": {"description": "Service(s) is (are) not performed (used after audit)", "category": "NCOV", "type": "Technical"},
    "NCOV-027": {"description": "Non Coverage of certain medication as per policy", "category": "NCOV", "type": "Technical"},
    "PRCE-001": {"description": "Calculation discrepancy", "category": "PRCE", "type": "Technical"},
    "PRCE-002": {"description": "Payment is included in the allowance for another service", "category": "PRCE", "type": "Technical"},
    "PRCE-003": {"description": "Recovery of Payment", "category": "PRCE", "type": "Technical"},
    "PRCE-006": {"description": "Consultation within free follow up period", "category": "PRCE", "type": "Technical"},
    "PRCE-007": {"description": "Service has no contract price", "category": "PRCE", "type": "Technical"},
    "PRCE-008": {"description": "Multiple procedure payment rules incorrectly applied", "category": "PRCE", "type": "Technical"},
    "PRCE-009": {"description": "Charges inconsistent with clinician specialty", "category": "PRCE", "type": "Technical"},
    "PRCE-010": {"description": "Use bundled code", "category": "PRCE", "type": "Technical"},
    "PRCE-011": {"description": "Discount discrepancy", "category": "PRCE", "type": "Technical"},
    "PRCE-012": {"description": "Recovery of Payment – DHIC Authorized", "category": "PRCE", "type": "Technical"},
    "SURC-001": {"description": "Severe drug - drug interaction", "category": "SURC", "type": "Medical"},
    "SURC-002": {"description": "Severe drug - age contraindication", "category": "SURC", "type": "Medical"},
    "SURC-003": {"description": "Severe drug - gender contraindication", "category": "SURC", "type": "Medical"},
    "SURC-004": {"description": "Severe drug - diaganosis contraindication", "category": "SURC", "type": "Medical"},
    "SURC-005": {"description": "Severe procedure/service - diagnosis contraindication", "category": "SURC", "type": "Medical"},
    "SURC-006": {"description": "Severe procedure/service - drug contraindication", "category": "SURC", "type": "Medical"},
    "SURC-007": {"description": "Severe procedure/service - procedure contraindication", "category": "SURC", "type": "Medical"},
    "SURC-008": {"description": "Serious safety issue with drug dose", "category": "SURC", "type": "Medical"},
    "TIME-001": {"description": "Time limit for submission has expired", "category": "TIME", "type": "Technical"},
    "TIME-002": {"description": "Requested additional information was not received or was not received within time limit", "category": "TIME", "type": "Technical"},
    "TIME-003": {"description": "Appeal procedures not followed or time limits not met", "category": "TIME", "type": "Technical"},
    "WRNG-001": {"description": "Wrong submission, receiver is not responsible for the payer within this transaction submission.", "category": "WRNG", "type": "Technical"},
}


def _lookup_denial(code: Optional[str]) -> tuple[str, str, str]:
    """Return (description, category, type) for a denial code, or ('','','')."""
    if not code:
        return "", "", ""
    entry = DENIAL_CODE_MAP.get(code.strip(), {})
    return entry.get("description", ""), entry.get("category", ""), entry.get("type", "")


# ---------------------------------------------------------------------------
# Clinician lookup  (eClaimLink ID → Professional Name)
# Loaded once at import time from data/clinicians.xlsx (both DHA_HRD + MOH sheets)
# ---------------------------------------------------------------------------
import os as _os
import openpyxl as _openpyxl

def _load_clinician_map() -> dict[str, str]:
    data_path = _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
        "..", "data", "clinicians.xlsx"
    )
    data_path = _os.path.normpath(data_path)
    cmap: dict[str, str] = {}
    if not _os.path.exists(data_path):
        return cmap
    try:
        wb = _openpyxl.load_workbook(data_path, read_only=True, data_only=True)
        for sheet in wb.sheetnames:
            ws = wb[sheet]
            for row in ws.iter_rows(min_row=2, values_only=True):
                if row and row[0] and row[1]:
                    cmap[str(row[0]).strip()] = str(row[1]).strip()
        wb.close()
    except Exception:
        pass
    return cmap

_CLINICIAN_MAP: dict[str, str] = _load_clinician_map()


def _clinician_name(cid: Optional[str]) -> str:
    if not cid or cid.strip().upper() == "UNKNOWN":
        return ""
    return _CLINICIAN_MAP.get(cid.strip(), cid.strip())


# ---------------------------------------------------------------------------
# Payer / Receiver lookup
# Sources:
#   data/payers.xlsx   — standard eClaimLink codes (INS001-INS137, TPA001-TPA036, DHA…)
#   data/self_paid.xlsx — self-paid employer codes (SF/SP) with their TPA
#
# Logic:
#   Receiver ID = claim.receiver_id if stored; else for SF/SP payers → their TPA;
#                 else payer_id itself (direct-payer case, Receiver == Payer)
#   Payer Name  = lookup payer_id in combined map
#   Receiver Name = lookup derived receiver_id in combined map
# ---------------------------------------------------------------------------
def _load_payer_map() -> tuple[dict[str, str], dict[str, str]]:
    """Returns (payer_name_map, sp_to_tpa_map)."""
    data_dir = _os.path.normpath(_os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
        "..", "data",
    ))
    pmap: dict[str, str] = {}
    sp_tpa: dict[str, str] = {}

    # Standard payers + TPA codes (col 0 = ID, col 1 = Name)
    payers_path = _os.path.join(data_dir, "payers.xlsx")
    if _os.path.exists(payers_path):
        try:
            wb = _openpyxl.load_workbook(payers_path, read_only=True, data_only=True)
            ws = wb.active
            for row in ws.iter_rows(min_row=2, values_only=True):
                if row and row[0] and row[1]:
                    pmap[str(row[0]).strip()] = str(row[1]).strip()
            wb.close()
        except Exception:
            pass

    # Self-paid employer codes (col 0 = SF/SP ID, col 1 = Name, col 2 = TPA)
    sp_path = _os.path.join(data_dir, "self_paid.xlsx")
    if _os.path.exists(sp_path):
        try:
            wb = _openpyxl.load_workbook(sp_path, read_only=True, data_only=True)
            ws = wb.active
            for row in ws.iter_rows(min_row=2, values_only=True):
                if row and row[0]:
                    code = str(row[0]).strip()
                    name = str(row[1]).strip() if row[1] else code
                    tpa  = str(row[2]).strip() if len(row) > 2 and row[2] else ""
                    pmap[code] = name
                    if tpa:
                        sp_tpa[code] = tpa
            wb.close()
        except Exception:
            pass

    return pmap, sp_tpa


_PAYER_MAP: dict[str, str]
_SP_TPA_MAP: dict[str, str]
_PAYER_MAP, _SP_TPA_MAP = _load_payer_map()


def _payer_name(code: Optional[str]) -> str:
    if not code:
        return ""
    return _PAYER_MAP.get(code.strip(), code.strip())


def _submission_level(resubmission_type: Optional[str]) -> str:
    """
    Map the stored resubmission_type value to a human-readable label.
      NULL / empty         → 'Submission'
      Correction           → '1 Resubmission'
      InternalComplaint    → '1 Resubmission'
      Reconciliation       → 'Reconciliation Resubmission'
      anything else        → '1 Resubmission'
    """
    if not resubmission_type:
        return "Submission"
    rt = resubmission_type.strip()
    if rt.lower() == "reconciliation":
        return "Reconciliation Resubmission"
    return "1 Resubmission"


def _derive_receiver_id(raw_receiver_id: Optional[str], payer_id: Optional[str]) -> str:
    """
    Return the correct Receiver ID:
      1. Use stored receiver_id if it's a real eClaimLink code (not a facility DHA-F- license)
      2. For SF/SP self-paid payers, receiver = their TPA code
      3. Otherwise receiver == payer (direct-payer submission)
    """
    rid = (raw_receiver_id or "").strip()
    # Facility DHA license IDs start with DHA-F- — these are NOT valid receivers
    if rid and not rid.upper().startswith("DHA-F-"):
        return rid
    pid = (payer_id or "").strip()
    if pid in _SP_TPA_MAP:
        return _SP_TPA_MAP[pid]
    return pid

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


# DHA XML encounter type codes → human-readable labels
_ENCOUNTER_TYPE_LABELS: dict[str, str] = {
    "1": "OP",   # Outpatient
    "2": "IP",   # Inpatient
    "3": "ER",   # Emergency
    "4": "OT",   # Others
}


def _enc_label(code: Optional[str]) -> str:
    """Map DHA numeric encounter type code to a readable label."""
    if not code:
        return ""
    return _ENCOUNTER_TYPE_LABELS.get(str(code).strip(), str(code).strip())


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
    "Net Amt - Initial Sub", "RA Net",
    "Approved Amt", "Rejected Amt", "Resubmitted Amt", "Unsettled Amt",
    "Payment Status", "Denial Code", "Denial Description",
    "RA Date", "TAT (Days)",
]


def _build_claim_summary(db, facility_id, payer_id, encounter_type,
                         date_from, date_to, date_field):
    # fac_map: id → (facility_name, license_id)  — used for receiver fallback
    fac_map = {f.id: (f.facility_name, f.license_id) for f in db.query(Facility).all()}

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

    # Resubmission subquery: for each original claim, find total net of
    # resubmission claims with same facility + member + encounter date
    resub_sq = (
        db.query(
            Claim.facility_id.label("fid"),
            Claim.member_id.label("mid"),
            cast(Claim.encounter_start, Date).label("enc_date"),
            func.sum(Claim.net_amount).label("resub_amt"),
        )
        .filter(Claim.resubmission_type.isnot(None))
        .group_by(
            Claim.facility_id,
            Claim.member_id,
            cast(Claim.encounter_start, Date),
        )
        .subquery()
    )

    # 2nd-RA subquery: resubmission claims that have ALSO received their own RA.
    # resub_net > resub_paid → still has receivable after 2nd adjudication → "Reconcilable"
    resub_ra_sq = (
        db.query(
            Claim.facility_id.label("fid"),
            Claim.member_id.label("mid"),
            cast(Claim.encounter_start, Date).label("enc_date"),
            func.sum(Claim.net_amount).label("resub_net"),
            func.sum(Remittance.paid_amount).label("resub_paid"),
        )
        .join(Remittance, Remittance.claim_id == Claim.claim_id)
        .filter(Claim.resubmission_type.isnot(None))
        .group_by(
            Claim.facility_id,
            Claim.member_id,
            cast(Claim.encounter_start, Date),
        )
        .subquery()
    )

    q = (
        db.query(Claim, latest_rem, resub_sq.c.resub_amt,
                 resub_ra_sq.c.resub_net, resub_ra_sq.c.resub_paid)
        .outerjoin(latest_rem_sq, and_(
            Claim.facility_id == latest_rem_sq.c.facility_id,
            Claim.claim_id    == latest_rem_sq.c.claim_id,
        ))
        .outerjoin(latest_rem, latest_rem.id == latest_rem_sq.c.max_id)
        .outerjoin(resub_sq, and_(
            Claim.facility_id == resub_sq.c.fid,
            Claim.member_id   == resub_sq.c.mid,
            cast(Claim.encounter_start, Date) == resub_sq.c.enc_date,
            Claim.resubmission_type.is_(None),   # only attach to original claims
        ))
        .outerjoin(resub_ra_sq, and_(
            Claim.facility_id == resub_ra_sq.c.fid,
            Claim.member_id   == resub_ra_sq.c.mid,
            cast(Claim.encounter_start, Date) == resub_ra_sq.c.enc_date,
            Claim.resubmission_type.is_(None),
        ))
    )
    q = _apply_filters(q, facility_id, payer_id, encounter_type,
                       date_from, date_to, date_field, rem_model=latest_rem)
    rows = q.order_by(Claim.submission_date.desc()).all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Claim Summary"
    ws.freeze_panes = "A2"
    _write_headers(ws, CLAIM_SUMMARY_COLS)

    for row_idx, (claim, rem, resub_amt, resub_net, resub_paid) in enumerate(rows, start=2):
        fac_name, fac_license = fac_map.get(claim.facility_id, ("", ""))
        sub_level = _submission_level(claim.resubmission_type)

        # --- Financial calculations ---
        net_sub  = float(claim.net_amount) if claim.net_amount is not None else None
        ra_net   = float(rem.net_amount)   if rem and rem.net_amount   is not None else ""
        paid     = float(rem.paid_amount)  if rem and rem.paid_amount  is not None else None

        approved  = _f(paid) if paid is not None else ""
        unsettled = ""
        rejected  = ""
        pay_status = ""

        if net_sub is not None and paid is not None:
            rejected  = round(max(0.0, net_sub - paid), 2)
            has_resub          = resub_amt  is not None and float(resub_amt)  > 0
            resub_has_ra       = resub_net  is not None   # 2nd RA received
            resub_receivable   = resub_has_ra and float(resub_net or 0) > float(resub_paid or 0)
            if paid >= net_sub:
                pay_status = "Fully Paid"
            elif rejected > 0 and resub_has_ra and resub_receivable:
                pay_status = "Reconcilable"
            elif rejected > 0 and has_resub:
                pay_status = "Resub Awaiting Adjudication"
            elif paid == 0.0 and not has_resub:
                pay_status = "Fully Rejected"
            else:
                pay_status = "Partially Paid"
        elif rem:
            # RA exists but claim net missing
            pay_status = rem.claim_status_ra or ""
        else:
            # No RA received yet
            pay_status = "Unpaid"

        # Unsettled = full claim amount for everything except Fully Paid
        if pay_status != "Fully Paid":
            if net_sub is not None and paid is not None:
                unsettled = round(net_sub - paid, 2)
            elif net_sub is not None:
                # No RA yet (Unpaid) — entire claim is unsettled
                unsettled = net_sub

        den_code  = rem.denial_code        or "" if rem else ""
        den_desc  = rem.denial_description or "" if rem else ""
        ra_date   = _fmt_date(rem.remittance_date) if rem else ""
        tat       = ""
        if rem and rem.remittance_date and claim.submission_date:
            try:
                tat = (rem.remittance_date - claim.submission_date).days
            except Exception:
                pass

        _write_row(ws, row_idx, [
            fac_name,
            claim.claim_id,
            _derive_receiver_id(claim.receiver_id, claim.payer_id),
            _payer_name(_derive_receiver_id(claim.receiver_id, claim.payer_id)),
            claim.payer_id,
            _payer_name(claim.payer_id),
            claim.member_id,
            _fmt_date(claim.encounter_start),
            _fmt_date(claim.submission_date),
            _enc_label(claim.encounter_type),
            claim.clinician_name or claim.clinician_id or "",
            sub_level,
            _f(net_sub) if net_sub is not None else "",
            ra_net,
            approved, rejected,
            _f(resub_amt) if resub_amt is not None else "",
            unsettled,
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
    fac_map = {f.id: (f.facility_name, f.license_id) for f in db.query(Facility).all()}

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
        fac_name, fac_license = fac_map.get(claim.facility_id, ("", ""))
        _write_row(ws, row_idx, [
            fac_name,
            claim.claim_id,
            _derive_receiver_id(claim.receiver_id, claim.payer_id),
            _payer_name(_derive_receiver_id(claim.receiver_id, claim.payer_id)),
            claim.payer_id,
            _payer_name(claim.payer_id),
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
            _enc_label(claim.encounter_type),
            net, approved, unsettled,
            _submission_level(claim.resubmission_type),
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
    "Denial Type",
    "Activity Detail ID",
    "RASubmission File Name",
    "RAFille Id",
    "Claim Submission File Name",
    "Response Comments",
    "RAPament For",
]


def _ra_payment_for(rem_id: int, ra_rank_map: dict, dup_rem_ids: set) -> str:
    """Universal RAPament For computation — facility and filename agnostic.

    Based purely on remittance chronology per claim:
      - Duplicate RA   : same ra_file_id processed >1 time for same claim
      - 1st RA         : earliest remittance for this claim
      - Resubmission RA Claim Level - N : Nth subsequent remittance (N >= 1)
    """
    if rem_id in dup_rem_ids:
        return "Duplicate RA"
    rank = ra_rank_map.get(rem_id, 1)
    if rank == 1:
        return "1st RA"
    return f"Resubmission RA Claim Level - {rank - 1}"


def _build_remittance_activity(db, facility_id, payer_id, encounter_type,
                               date_from, date_to, date_field):
    fac_map = {f.id: (f.facility_name, f.license_id) for f in db.query(Facility).all()}

    # ------------------------------------------------------------------
    # Pre-compute RA rank per claim (ordered by remittance_date, then id)
    # and duplicate remittance IDs (same ra_file_id for same claim > once)
    # ------------------------------------------------------------------
    from sqlalchemy import text as _text
    rank_rows = db.execute(_text("""
        SELECT id,
               ROW_NUMBER() OVER (
                   PARTITION BY facility_id, claim_id
                   ORDER BY remittance_date, id
               ) AS ra_rank
        FROM remittances
    """)).fetchall()
    ra_rank_map = {row[0]: row[1] for row in rank_rows}

    dup_rows = db.execute(_text("""
        SELECT r.id
        FROM remittances r
        JOIN (
            SELECT facility_id, claim_id, ra_file_id
            FROM remittances
            WHERE ra_file_id IS NOT NULL
            GROUP BY facility_id, claim_id, ra_file_id
            HAVING COUNT(*) > 1
        ) dup ON r.facility_id = dup.facility_id
              AND r.claim_id   = dup.claim_id
              AND r.ra_file_id = dup.ra_file_id
    """)).fetchall()
    dup_rem_ids = {row[0] for row in dup_rows}

    ra_xml_store    = aliased(RawXmlStore)
    claim_xml_store = aliased(RawXmlStore)
    act_alias       = aliased(ClaimActivity)

    q = (
        db.query(RemittanceActivityDetail, Remittance, Claim,
                 ra_xml_store, claim_xml_store, act_alias)
        .join(Remittance, Remittance.id == RemittanceActivityDetail.remittance_id_fk)
        .join(Claim, and_(
            Claim.facility_id == Remittance.facility_id,
            Claim.claim_id    == Remittance.claim_id,
        ))
        .outerjoin(ra_xml_store,    ra_xml_store.id    == Remittance.raw_xml_id)
        .outerjoin(claim_xml_store, claim_xml_store.id == Claim.raw_xml_id)
        .outerjoin(act_alias, and_(
            act_alias.claim_id_fk  == Claim.id,
            act_alias.activity_id  == RemittanceActivityDetail.activity_id,
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

    for row_idx, (rad, rem, claim, ra_xml_row, claim_xml_row, act_row) in enumerate(rows, start=2):
        enc_start = claim.encounter_start
        enc_year  = enc_start.year  if enc_start else ""
        enc_month = enc_start.month if enc_start else ""

        fac_name, fac_license = fac_map.get(rem.facility_id, ("", ""))

        # Denial lookups from DHA code set
        den_code = rad.denial_code or ""
        den_desc, den_cat, den_type = _lookup_denial(den_code)

        # Clinician: prefer activity-level ID, fall back to claim-level
        act_clin_id = (act_row.clinician_id if act_row else None) or claim.clinician_id
        ord_clin_id = (
            getattr(act_row, "ordering_clinician_id", None) if act_row else None
        ) or act_clin_id
        clinician     = _clinician_name(act_clin_id)
        ord_clinician = _clinician_name(ord_clin_id)

        _write_row(ws, row_idx, [
            rem.facility_id, fac_name,
            _derive_receiver_id(claim.receiver_id, claim.payer_id),
            _payer_name(_derive_receiver_id(claim.receiver_id, claim.payer_id)),
            claim.payer_id, _payer_name(claim.payer_id),
            claim.member_id, claim.member_id, claim.emirates_id or "",
            _fmt_date(enc_start), _fmt_date(claim.encounter_end),
            enc_year, enc_month,
            _fmt_date(claim.submission_date), _fmt_date(claim.submission_date),
            _fmt_date(rem.remittance_date),
            claim.claim_id, _enc_label(claim.encounter_type), claim.end_type or "",
            claim.claim_id_payer or "", rem.ra_file_id or "",
            _fmt_date(rem.remittance_date),
            _fmt_date(enc_start),
            clinician, ord_clinician,
            rad.activity_code or "", rad.activity_type or "", rad.activity_type or "",
            _f(rad.quantity_approved), _f(rad.gross), _f(rad.net),
            _f(rad.patient_share), _f(rad.paid_amount),
            den_code, den_desc, den_cat,
            den_type,                                                # Denial Type
            rad.activity_id or "",                                   # Activity Detail ID
            ra_xml_row.source_filename    if ra_xml_row    else "",  # RASubmission File Name
            rem.ra_file_id or "",                                    # RAFille Id
            claim_xml_row.source_filename if claim_xml_row else "",  # Claim Submission File Name
            rad.denial_description or rem.denial_description or "",    # Response Comments
            _ra_payment_for(rem.id, ra_rank_map, dup_rem_ids),        # RAPament For
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
        sub_level  = _submission_level(claim.resubmission_type)
        ra_history = 1 if claim.resubmission_type else 0

        _write_row(ws, row_idx, [
            ra_history, sub_level, lic_no, fac_name,
            _derive_receiver_id(claim.receiver_id, claim.payer_id),
            _payer_name(_derive_receiver_id(claim.receiver_id, claim.payer_id)),
            claim.payer_id, _payer_name(claim.payer_id),
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
    import traceback as _tb
    try:
        from sqlalchemy import text as _text
        row = db.execute(
            _text("SELECT file_data, filename, status FROM report_jobs WHERE id = :id"),
            {"id": job_id},
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Report job not found")
        if not row.file_data:
            raise HTTPException(
                status_code=400,
                detail=f"No file available for this job (status: {row.status})",
            )

        raw = row.file_data
        if isinstance(raw, memoryview):
            data = bytes(raw)
        elif isinstance(raw, bytes):
            data = raw
        elif isinstance(raw, str):
            # PostgreSQL hex-bytea format: '\x504b...'
            hex_str = raw[2:] if raw.startswith("\\x") else raw
            data = bytes.fromhex(hex_str)
        else:
            raise ValueError(f"Unexpected file_data type: {type(raw)}")

        return StreamingResponse(
            io.BytesIO(data),
            headers={
                "Content-Disposition": f'attachment; filename="{row.filename or "report.xlsx"}"',
                "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            },
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail=_tb.format_exc())
