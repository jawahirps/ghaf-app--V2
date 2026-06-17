"""
Ghaf App — Seed/update facilities table from eClaimLink facilities list.

Reads the Excel file exported from eClaimLink (cols: A=DHA-F-ID, B=Facility Name)
and does an UPSERT into the facilities table:
  • Existing record whose facility_name fuzzy-matches → update license_id
  • No match → INSERT new record with proper license_id

Then optionally applies a hard-coded rename map so that facility names in the DB
match exactly what appears in CLAIMACTIVITY / CLAIMSUMMARY files.

USAGE (from backend/ directory with venv active):
    python -m app.import_facilities eClaimLink_Facilities_List.xlsx
    python -m app.import_facilities eClaimLink_Facilities_List.xlsx --rename
    python -m app.import_facilities eClaimLink_Facilities_List.xlsx --list
"""
from __future__ import annotations

import argparse
import re
import zipfile
import xml.etree.ElementTree as ET

from .database import engine

# ---------------------------------------------------------------------------
# Rename map: DB facility_name (as stored after CLAIMSUMMARY import)
#             → canonical name used in CLAIMACTIVITY files
# Add entries here whenever a mismatch is discovered.
# ---------------------------------------------------------------------------
RENAME_MAP: dict[str, str] = {
    # CLAIMSUMMARY stores "Apollo Clinics" but CLAIMACTIVITY says "Apollo Clinics"
    # (if they actually differ, adjust the key to the exact DB value)
    "APOLLO CLINIC L.L.C":      "Apollo Clinics",
    "WE CARE MEDICAL CENTER LLC":"We Care Medical Center",
    "AL RASHIDIYAH ALNOOR POLYCLINIC": "Alnoor Rashidiya",
    "AL NOOR POLYCLINIC - BR OF GULF HEALTHCARE INTERNATIONAL L.L.C (DEIRA)": "Alnoor Deira",
}

# Facilities to always ensure exist (DHA-F-ID → display name used in reports)
KNOWN_FACILITIES: dict[str, str] = {
    "DHA-F-0047100": "Alnoor Rashidiya",
    "DHA-F-0253862": "Apollo Clinics",
    "DHA-F-0001604": "We Care Medical Center",
    "DHA-F-0045579": "Alnoor Deira",
}


# ---------------------------------------------------------------------------
# Read eClaimLink Excel file
# ---------------------------------------------------------------------------
def read_eclaimlink_file(path: str) -> list[tuple[str, str]]:
    """Returns list of (license_id, facility_name) from the eClaimLink Excel."""
    with zipfile.ZipFile(path) as zf:
        # Shared strings
        ss: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            with zf.open("xl/sharedStrings.xml") as f:
                tree = ET.parse(f)
                ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                ss = [
                    si.text or "".join(
                        t.text or ""
                        for t in si.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
                    )
                    for si in tree.findall(".//x:si", ns)
                ]

        sheets = [n for n in zf.namelist()
                  if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")]
        with zf.open(sheets[0]) as f:
            tree = ET.parse(f)

    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    results: list[tuple[str, str]] = []

    for row in tree.findall(".//x:row", ns):
        cells: dict[str, str] = {}
        for c in row.findall("x:c", ns):
            col = "".join(ch for ch in c.get("r", "") if ch.isalpha())
            t = c.get("t", "")
            v_el = c.find("x:v", ns)
            is_el = c.find(".//x:t", ns)
            if t == "s" and v_el is not None:
                idx = int(v_el.text)
                cells[col] = ss[idx] if idx < len(ss) else ""
            elif t == "inlineStr" and is_el is not None:
                cells[col] = is_el.text or ""
            elif v_el is not None:
                cells[col] = v_el.text or ""

        a = cells.get("A", "").strip()
        b = cells.get("B", "").strip()
        if a.startswith("DHA-F-") and b:
            results.append((a, b))

    return results


# ---------------------------------------------------------------------------
# Normalise for fuzzy matching
# ---------------------------------------------------------------------------
def normalise(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed/update facilities table from eClaimLink Facilities Excel."
    )
    parser.add_argument("eclaim_file", help="eClaimLink_Facilities_List_*.xlsx path")
    parser.add_argument(
        "--rename",
        action="store_true",
        help="Also apply RENAME_MAP: update facility_name in DB to match report files",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Just print current DB facilities and exit",
    )
    args = parser.parse_args()

    raw_conn = engine.raw_connection()
    cur = raw_conn.cursor()

    # --list mode
    if args.list:
        cur.execute("SELECT id, facility_name, license_id FROM facilities ORDER BY id")
        rows = cur.fetchall()
        print(f"{'ID':>4}  {'license_id':<25}  facility_name")
        print("-" * 70)
        for fid, name, lic in rows:
            print(f"{fid:>4}  {(lic or ''):25}  {name}")
        cur.close()
        raw_conn.close()
        return

    # Load eClaimLink data
    print(f"Reading {args.eclaim_file} ...")
    eclaim_rows = read_eclaimlink_file(args.eclaim_file)
    print(f"  Loaded {len(eclaim_rows):,} facilities from eClaimLink file.")

    # Build lookup: normalised_name → (license_id, canonical_name)
    eclaim_by_norm: dict[str, tuple[str, str]] = {}
    eclaim_by_lic:  dict[str, tuple[str, str]] = {}
    for lic, name in eclaim_rows:
        eclaim_by_norm[normalise(name)] = (lic, name)
        eclaim_by_lic[lic.upper()] = (lic, name)

    # Load current DB facilities
    cur.execute("SELECT id, facility_name, license_id FROM facilities")
    db_facilities = cur.fetchall()  # [(id, name, license_id), ...]
    print(f"  Found {len(db_facilities)} facilities in DB:")
    for fid, name, lic in db_facilities:
        print(f"    [{fid}] {name!r:40s}  license_id={lic!r}")

    updated = 0
    inserted = 0

    # 1. Update existing DB facilities: set real license_id if missing/fake
    for fid, db_name, db_lic in db_facilities:
        # Skip if already has a real DHA-F-ID
        if db_lic and db_lic.startswith("DHA-F-"):
            print(f"  [{fid}] {db_name!r} already has license_id={db_lic}, skipping.")
            continue

        # Try to find in eClaimLink by normalised name
        match = eclaim_by_norm.get(normalise(db_name))
        if match:
            new_lic, ecl_name = match
            cur.execute(
                "UPDATE facilities SET license_id = %s, updated_at = NOW() WHERE id = %s",
                (new_lic, fid),
            )
            print(f"  [{fid}] Updated {db_name!r} → license_id={new_lic}  (eClaimLink: {ecl_name!r})")
            updated += 1
        else:
            print(f"  [{fid}] {db_name!r} — no eClaimLink match found (manual mapping needed)")

    # 2. Ensure KNOWN_FACILITIES exist in DB
    cur.execute("SELECT license_id FROM facilities WHERE license_id LIKE 'DHA-F-%'")
    existing_lics = {r[0] for r in cur.fetchall()}

    # Also reload after updates
    cur.execute("SELECT license_id FROM facilities WHERE license_id LIKE 'DHA-F-%'")
    existing_lics = {r[0] for r in cur.fetchall()}

    for lic, display_name in KNOWN_FACILITIES.items():
        if lic in existing_lics:
            continue
        # Look up in eClaimLink for official name
        ecl = eclaim_by_lic.get(lic.upper())
        ecl_name = ecl[1] if ecl else display_name
        # Generate a facility_code
        code = re.sub(r"[^A-Z0-9]+", "-", display_name.upper()).strip("-")[:20]
        cur.execute(
            """
            INSERT INTO facilities
                (facility_code, facility_name, license_id,
                 eclaimlink_username, credential_key, is_active)
            VALUES (%s, %s, %s, %s, %s, TRUE)
            ON CONFLICT (license_id) DO UPDATE
                SET facility_name = EXCLUDED.facility_name,
                    updated_at = NOW()
            """,
            (code, display_name, lic,
             f"user-{code.lower()[:20]}", f"cred-{code.lower()[:20]}"),
        )
        print(f"  Ensured facility: {display_name!r} ({lic})")
        inserted += 1

    # 3. Optional rename pass
    if args.rename:
        print("\nApplying RENAME_MAP ...")
        for old_name, new_name in RENAME_MAP.items():
            cur.execute(
                "UPDATE facilities SET facility_name = %s, updated_at = NOW() "
                "WHERE facility_name = %s",
                (new_name, old_name),
            )
            if cur.rowcount:
                print(f"  Renamed {old_name!r} → {new_name!r}")

    raw_conn.commit()
    cur.close()
    raw_conn.close()
    print(f"\nDone. {updated} license_ids updated, {inserted} facilities ensured.")


if __name__ == "__main__":
    main()
