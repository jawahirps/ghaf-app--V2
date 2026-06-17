"""
Ghaf App — Import real claims data from CLAIMSUMMARY Excel exports.

Supports TWO formats automatically detected from the header row:

FORMAT A — Al Noor (header row 2, data from row 3, 34 columns):
    Facility, TransactionRef, Receiver, Receiver Name, Payer, Payer Name,
    Patient ID, Member Id, Treatment Date, Date Of Admission,
    Submission Date, Encounter Type, Clinician, Service Year, Service Month,
    Submission Level, Net Amt - Initial Sub, RA Received Amt,
    Net Amt - Resubmission, Approved Amt, Initial Sub Rejected Amt,
    Rejected Amt - Resubmission, Unsettied Amt, Payment Status,
    Denial Code, Denial Description, Payment Ref, Settlement Date,
    ID Payer, Submission File, RA File, RA Date, TAT, Diagnosis

FORMAT B — Analytika Reports (header row 1, data from row 2, 39 columns):
    Facility Id, Facility Name, Claim Number, Receiver Id, Receiver Name,
    Payer ID, Payer Name, Patient Id, Member Id, Treatment Date,
    Date Of Admission, Submission Date, Encounter Type, Clinician Name,
    Service Year, Service Month, Submission Level, Net Amt - Initial Sub,
    RA Received Amt, Net Amt - Resubmission, Approved Amt,
    Initial Sub Rejected Amt, Rejected Amt - Resubmission, Unsettied Amt,
    Payment Status, Denial Code, Denial Description, Payment Ref,
    Settlement Date, ID Payer, Submission File Id, RA File, RA Date, TAT,
    Diagnosis, Last Remittance File Id, Last Remittance Date,
    All Remittance File, All Remittance File Id

USAGE (from backend/ directory with venv active):

    python -m app.import_claim_summary "/path/CLAIMSUMMARY_H1 2024.xlsx" ...

Add --limit N to test with only the first N rows of each file.
Add --clear to delete all EXCEL_HISTORICAL claims first (fresh re-import).
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

import openpyxl
from psycopg2.extras import execute_values

from .database import SessionLocal, engine
from .models import Facility

BATCH_SIZE = 500

# ---------------------------------------------------------------------------
# Column name aliases — maps canonical field names to every known header
# variant across Al Noor and Analytika formats (case-insensitive strip match)
# ---------------------------------------------------------------------------
COL_ALIASES: dict[str, list[str]] = {
    "facility_name":       ["Facility Name", "Facility"],
    "claim_id":            ["Claim Number", "TransactionRef"],
    "receiver_id":         ["Receiver Id", "Receiver"],
    "receiver_name":       ["Receiver Name"],
    "payer_id":            ["Payer ID", "Payer"],
    "payer_name":          ["Payer Name"],
    "patient_id":          ["Patient Id", "Patient ID"],
    "member_id":           ["Member Id", "Member ID"],
    "treatment_date":      ["Treatment Date", "Date Of Service"],
    "date_of_admission":   ["Date Of Admission"],
    "submission_date":     ["Submission Date"],
    "encounter_type":      ["Encounter Type"],
    "clinician_name":      ["Clinician Name", "Clinician"],
    "service_year":        ["Service Year"],
    "service_month":       ["Service Month"],
    "submission_level":    ["Submission Level", "Submission Type"],
    "net_initial":         ["Net Amt - Initial Sub", "Net Amount Initial Sub", "Net Amount - Initial Sub"],
    "ra_received":         ["RA Received Amt", "RA Received Amount"],
    "net_resub":           ["Net Amt - Resubmission", "Net Amount - Resubmission", "Net Amount Resubmission"],
    "approved_amt":        ["Approved Amt", "Approved Amount"],
    "initial_rejected":    ["Initial Sub Rejected Amt", "Initial Sub Rejected Amount"],
    "resub_rejected":      ["Rejected Amt - Resubmission", "Rejected Amount - Resubmission"],
    "unsettled":           ["Unsettied Amt", "Unsettled Amt", "Unsettled Amount"],
    "payment_status":      ["Payment Status"],
    "denial_code":         ["Denial Code"],
    "denial_description":  ["Denial Description"],
    "payment_ref":         ["Payment Ref", "Payment Reference"],
    "settlement_date":     ["Settlement Date"],
    "id_payer":            ["ID Payer", "Payer Claim Id"],
    "submission_file":     ["Submission File", "Submission File Id"],
    "ra_file":             ["RA File", "RA File Id"],
    "ra_date":             ["RA Date", "RA Received Date"],
    "tat":                 ["TAT"],
    "diagnosis":           ["Diagnosis"],
}

# Build reverse lookup: lowercase header text → canonical field name
_HEADER_LOOKUP: dict[str, str] = {}
for _field, _aliases in COL_ALIASES.items():
    for _alias in _aliases:
        _HEADER_LOOKUP[_alias.lower().strip()] = _field


# ---------------------------------------------------------------------------
# Raw SQL — bypasses SQLAlchemy compilation to avoid insertmanyvalues issues
# ---------------------------------------------------------------------------
CLAIM_SQL = """
INSERT INTO claims (
    facility_id, source_channel, claim_id, claim_id_payer, encounter_id,
    encounter_type, encounter_start, member_id, payer_id, payer_name,
    clinician_id, clinician_name, receiver_id, receiver_name,
    gross_amount, net_amount, patient_share_total,
    submission_date, claim_status, resubmission_count
) VALUES %s
ON CONFLICT (facility_id, claim_id) DO UPDATE SET
    claim_id_payer     = EXCLUDED.claim_id_payer,
    encounter_type     = EXCLUDED.encounter_type,
    encounter_start    = EXCLUDED.encounter_start,
    member_id          = EXCLUDED.member_id,
    payer_id           = EXCLUDED.payer_id,
    payer_name         = EXCLUDED.payer_name,
    clinician_id       = EXCLUDED.clinician_id,
    clinician_name     = EXCLUDED.clinician_name,
    receiver_id        = EXCLUDED.receiver_id,
    receiver_name      = EXCLUDED.receiver_name,
    gross_amount       = claims.gross_amount + EXCLUDED.gross_amount,
    net_amount         = claims.net_amount + EXCLUDED.net_amount,
    submission_date    = EXCLUDED.submission_date,
    claim_status       = EXCLUDED.claim_status,
    resubmission_count = claims.resubmission_count + EXCLUDED.resubmission_count,
    updated_at         = NOW()
"""

REMIT_SQL = """
INSERT INTO remittances (
    facility_id, source_channel, claim_id, claim_id_payer, payer_id,
    remittance_date, ra_file_id, gross_amount, net_amount, paid_amount,
    patient_share_total, discount_amount, denial_amount,
    claim_status_ra, denial_code, denial_description
) VALUES %s
ON CONFLICT (facility_id, claim_id, remittance_date) DO UPDATE SET
    claim_id_payer     = EXCLUDED.claim_id_payer,
    ra_file_id         = EXCLUDED.ra_file_id,
    gross_amount       = remittances.gross_amount + EXCLUDED.gross_amount,
    net_amount         = remittances.net_amount + EXCLUDED.net_amount,
    paid_amount        = remittances.paid_amount + EXCLUDED.paid_amount,
    denial_amount      = remittances.denial_amount + EXCLUDED.denial_amount,
    claim_status_ra    = EXCLUDED.claim_status_ra,
    denial_code        = EXCLUDED.denial_code,
    denial_description = EXCLUDED.denial_description,
    updated_at         = NOW()
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def parse_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_decimal(value) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def slugify_code(name: str, used_codes: set) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "-", name.upper()).strip("-")[:16] or "FAC"
    code = base
    n = 1
    while code in used_codes:
        n += 1
        suffix = f"-{n}"
        code = f"{base[: 20 - len(suffix)]}{suffix}"
    used_codes.add(code)
    return code


def clinician_id_from_name(name) -> str:
    if not name or not str(name).strip():
        return "UNKNOWN"
    digest = abs(hash(str(name).strip().upper())) % (10 ** 8)
    return f"CLN{digest:08d}"


# ---------------------------------------------------------------------------
# Format detection — reads the first two rows to locate the header row
# ---------------------------------------------------------------------------
def detect_format(ws) -> tuple[int, dict[str, int]]:
    """
    Returns (data_start_row, col_map) where col_map maps canonical field
    names to their 0-based column indices.

    Detection logic:
    - If row 1 col 0 matches a known header alias (e.g. "Facility Id" or
      "Facility Name") → Analytika format: header=row1, data from row 2.
    - Otherwise assume Al Noor format: header=row2, data from row 3.
    """
    rows = list(ws.iter_rows(min_row=1, max_row=2, values_only=True))
    if not rows:
        return 3, {}

    row1 = rows[0] if rows else []
    row2 = rows[1] if len(rows) > 1 else []

    def _build_map(header_row):
        col_map: dict[str, int] = {}
        for idx, cell in enumerate(header_row):
            if cell is None:
                continue
            normalized = str(cell).lower().strip()
            field = _HEADER_LOOKUP.get(normalized)
            if field and field not in col_map:
                col_map[field] = idx
        return col_map

    # Check if row 1 looks like a header (has recognizable column names)
    map1 = _build_map(row1)
    if len(map1) >= 3:
        # Row 1 is the header — Analytika format
        return 2, map1

    # Fall back to row 2 as header — Al Noor format
    map2 = _build_map(row2)
    return 3, map2


def extract(data: dict, field: str, default=None):
    return data.get(field, default)


# ---------------------------------------------------------------------------
# Facility cache
# ---------------------------------------------------------------------------
def load_facility_cache(db):
    cache: dict[str, int] = {}
    used_codes: set[str] = set()
    for fac in db.query(Facility).all():
        cache[fac.facility_name] = fac.id
        used_codes.add(fac.facility_code)
    return cache, used_codes


def get_or_create_facility(db, cache, used_codes, facility_name: str) -> int:
    if facility_name in cache:
        return cache[facility_name]
    code = slugify_code(facility_name, used_codes)
    fac = Facility(
        facility_code=code,
        facility_name=facility_name,
        license_id=f"LIC-{code}",
        eclaimlink_username=f"user-{code.lower()}",
        credential_key=f"cred-{code.lower()}",
        is_active=True,
    )
    db.add(fac)
    db.flush()
    cache[facility_name] = fac.id
    return fac.id


# ---------------------------------------------------------------------------
# Row → tuple builders
# ---------------------------------------------------------------------------
def build_claim_tuple(data: dict, facility_id: int):
    claim_id = (extract(data, "claim_id") or "").strip()
    if not claim_id:
        return None
    submission_date = parse_date(extract(data, "submission_date")) or parse_date(extract(data, "treatment_date"))
    if submission_date is None:
        return None
    encounter_start = parse_date(extract(data, "treatment_date")) or submission_date
    sub_lvl = extract(data, "submission_level")
    is_resub = isinstance(sub_lvl, str) and sub_lvl.strip().lower() == "resubmission"
    net_amount = parse_decimal(extract(data, "net_initial")) + parse_decimal(extract(data, "net_resub"))
    payment_status = str(extract(data, "payment_status") or "submitted").strip()[:30] or "submitted"
    return (
        facility_id,
        "EXCEL_HISTORICAL",
        claim_id,
        extract(data, "id_payer") or None,
        claim_id,                                           # encounter_id
        extract(data, "encounter_type") or None,
        datetime.combine(encounter_start, datetime.min.time()),
        (str(extract(data, "member_id") or claim_id))[:100],
        (str(extract(data, "payer_id") or "UNKNOWN"))[:50],
        extract(data, "payer_name") or None,
        clinician_id_from_name(extract(data, "clinician_name")),
        extract(data, "clinician_name") or None,
        extract(data, "receiver_id") or None,
        extract(data, "receiver_name") or None,
        net_amount,
        net_amount,
        Decimal("0"),                                       # patient_share_total
        submission_date,
        payment_status,
        1 if is_resub else 0,
    )


def build_remit_tuple(data: dict, facility_id: int):
    claim_id = (extract(data, "claim_id") or "").strip()
    if not claim_id:
        return None
    remit_date = parse_date(extract(data, "settlement_date")) or parse_date(extract(data, "ra_date"))
    if remit_date is None:
        return None
    approved = parse_decimal(extract(data, "approved_amt"))
    rejected = parse_decimal(extract(data, "initial_rejected")) + parse_decimal(extract(data, "resub_rejected"))
    if approved == 0 and rejected == 0:
        return None
    net_amount = parse_decimal(extract(data, "net_initial")) + parse_decimal(extract(data, "net_resub"))
    denial_desc = extract(data, "denial_description")
    denial_desc = str(denial_desc)[:500] if denial_desc else None
    _s = lambda v, n: str(v)[:n] if v else None
    return (
        facility_id,
        "EXCEL_HISTORICAL",
        claim_id,
        _s(extract(data, "id_payer"), 100),
        _s(extract(data, "payer_id") or "UNKNOWN", 50),
        remit_date,
        _s(extract(data, "ra_file"), 100),
        net_amount,
        net_amount,
        approved,
        Decimal("0"),   # patient_share_total
        Decimal("0"),   # discount_amount
        rejected,
        _s(extract(data, "payment_status"), 50),
        _s(extract(data, "denial_code"), 50),
        denial_desc,
    )


# ---------------------------------------------------------------------------
# Dedup helpers
# ---------------------------------------------------------------------------
def dedup_claims(tuples: list) -> list:
    seen: dict = {}
    for t in tuples:
        key = (t[0], t[2])
        if key in seen:
            e = seen[key]
            e[14] = e[14] + t[14]
            e[15] = e[15] + t[15]
            e[19] = e[19] + t[19]
            e[3]  = t[3];  e[5]  = t[5];  e[9]  = t[9];  e[10] = t[10]
            e[11] = t[11]; e[12] = t[12]; e[13] = t[13]; e[17] = t[17]; e[18] = t[18]
        else:
            seen[key] = list(t)
    return [tuple(v) for v in seen.values()]


def dedup_remits(tuples: list) -> list:
    seen: dict = {}
    for t in tuples:
        key = (t[0], t[2], t[5])
        if key in seen:
            e = seen[key]
            e[7]  = e[7]  + t[7]
            e[8]  = e[8]  + t[8]
            e[9]  = e[9]  + t[9]
            e[12] = e[12] + t[12]
            e[13] = t[13]; e[14] = t[14]; e[15] = t[15]
        else:
            seen[key] = list(t)
    return [tuple(v) for v in seen.values()]


# ---------------------------------------------------------------------------
# Flush
# ---------------------------------------------------------------------------
def flush(db, claim_tuples: list, remit_tuples: list) -> None:
    db.commit()
    if not claim_tuples and not remit_tuples:
        return
    raw_conn = engine.raw_connection()
    try:
        cur = raw_conn.cursor()
        if claim_tuples:
            execute_values(cur, CLAIM_SQL, dedup_claims(claim_tuples))
        if remit_tuples:
            execute_values(cur, REMIT_SQL, dedup_remits(remit_tuples))
        raw_conn.commit()
    except Exception:
        raw_conn.rollback()
        raise
    finally:
        raw_conn.close()
    claim_tuples.clear()
    remit_tuples.clear()


# ---------------------------------------------------------------------------
# Main import loop
# ---------------------------------------------------------------------------
def process_file(db, path: str, cache, used_codes, limit=None):
    print(f"Opening {path} ...", flush=True)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active

    data_start_row, col_map = detect_format(ws)

    if not col_map:
        print(f"  WARNING: Could not detect column headers in {path}, skipping.", flush=True)
        wb.close()
        return 0, 0

    # Show detected format for verification
    fmt_label = "Analytika" if data_start_row == 2 else "Al Noor"
    print(f"  Format detected: {fmt_label} (data from row {data_start_row}, "
          f"{len(col_map)} fields mapped)", flush=True)

    claim_tuples: list = []
    remit_tuples: list = []
    total = 0
    skipped = 0

    for row in ws.iter_rows(min_row=data_start_row, values_only=True):
        if limit is not None and total >= limit:
            break
        if not row or all(v is None for v in row[:5]):
            continue

        # Build data dict using the detected column map
        data = {field: row[idx] if idx < len(row) else None
                for field, idx in col_map.items()}

        facility_name = str(data.get("facility_name") or "").strip()
        if not facility_name:
            skipped += 1
            continue

        facility_id = get_or_create_facility(db, cache, used_codes, facility_name)

        c = build_claim_tuple(data, facility_id)
        if c is None:
            skipped += 1
            continue
        claim_tuples.append(c)

        r = build_remit_tuple(data, facility_id)
        if r is not None:
            remit_tuples.append(r)

        total += 1
        if len(claim_tuples) >= BATCH_SIZE:
            flush(db, claim_tuples, remit_tuples)
            print(f"  ... {total} rows processed", flush=True)

    flush(db, claim_tuples, remit_tuples)
    wb.close()
    print(f"Done {path}: {total} rows imported, {skipped} skipped.", flush=True)
    return total, skipped


def main():
    parser = argparse.ArgumentParser(description="Import CLAIMSUMMARY_*.xlsx into ghaf_app database.")
    parser.add_argument("files", nargs="+", help="Path(s) to CLAIMSUMMARY_*.xlsx files")
    parser.add_argument("--limit", type=int, default=None, help="Only process first N rows per file (testing)")
    parser.add_argument("--clear", action="store_true",
                        help="Delete all EXCEL_HISTORICAL claims + remittances before importing")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.clear:
            print("Clearing existing EXCEL_HISTORICAL data...", flush=True)
            raw_conn = engine.raw_connection()
            try:
                cur = raw_conn.cursor()
                cur.execute("DELETE FROM remittances WHERE source_channel = 'EXCEL_HISTORICAL'")
                cur.execute("DELETE FROM claims WHERE source_channel = 'EXCEL_HISTORICAL'")
                raw_conn.commit()
                print("  Done.", flush=True)
            finally:
                raw_conn.close()

        cache, used_codes = load_facility_cache(db)
        grand_total = 0
        for path in args.files:
            total, _ = process_file(db, path, cache, used_codes, args.limit)
            grand_total += total
        print(f"\nAll done. {grand_total:,} rows imported across {len(args.files)} file(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
