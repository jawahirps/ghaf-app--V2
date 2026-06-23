"""
Diagnose why a specific claim has no activities in claim_activities.
Usage: .venv/bin/python3 scripts/diagnose_claim.py CLAIM_ID
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text

DATABASE_URL = "postgresql+psycopg2://ghaf@/ghaf_app?host=/tmp"
claim_id = sys.argv[1] if len(sys.argv) > 1 else "ALNRASHID_030126_2040899.146496"

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
with engine.connect() as conn:
    # 1. Claim record
    claim = conn.execute(text(
        "SELECT id, facility_id, raw_xml_id, claim_id, encounter_type, submission_date, claim_status "
        "FROM claims WHERE claim_id = :cid"
    ), {"cid": claim_id}).fetchone()

    if not claim:
        print(f"Claim '{claim_id}' NOT FOUND in claims table.")
        sys.exit(0)

    print(f"=== Claim record ===")
    print(f"  id={claim[0]}  facility_id={claim[1]}  raw_xml_id={claim[2]}")
    print(f"  claim_id={claim[3]}  encounter_type={claim[4]}")
    print(f"  submission_date={claim[5]}  status={claim[6]}")

    # 2. Activities
    acts = conn.execute(text(
        "SELECT id, activity_code, activity_type, activity_start, gross, net "
        "FROM claim_activities WHERE claim_id_fk = :pk"
    ), {"pk": claim[0]}).fetchall()
    print(f"\n=== claim_activities rows: {len(acts)} ===")
    for a in acts:
        print(f"  {a}")

    # 3. Raw XML store record
    if claim[2]:
        raw = conn.execute(text(
            "SELECT id, source_filename, xml_type, submission_date, parse_status, records_parsed "
            "FROM raw_xml_store WHERE id = :id"
        ), {"id": claim[2]}).fetchone()
        print(f"\n=== raw_xml_store ===")
        print(f"  id={raw[0]}  type={raw[2]}  status={raw[4]}  records={raw[5]}")
        print(f"  filename={raw[1]}")
        print(f"  submission_date={raw[3]}")

        # 4. Snippet of the raw XML around this claim_id
        xml_snippet = conn.execute(text(
            "SELECT substring(xml_content FROM position(:cid IN xml_content) - 50 FOR 600) "
            "FROM raw_xml_store WHERE id = :id"
        ), {"cid": claim_id, "id": claim[2]}).scalar()
        print(f"\n=== XML snippet around claim ===")
        print(xml_snippet or "(claim_id not found in raw XML)")
    else:
        print("\nraw_xml_id is NULL — claim was not loaded from raw_xml_store.")

    # 5. Any remittance for this claim
    remits = conn.execute(text(
        "SELECT id, remittance_date, paid_amount, denial_code, denial_description "
        "FROM remittances WHERE claim_id = :cid"
    ), {"cid": claim_id}).fetchall()
    print(f"\n=== Remittances: {len(remits)} ===")
    for r in remits:
        print(f"  id={r[0]} date={r[1]} paid={r[2]} denial_code={r[3]}")
        print(f"  denial_desc={r[4]}")
