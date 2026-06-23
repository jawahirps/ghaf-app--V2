"""Quick check — shows distinct parse errors for quarantined RA records."""
from sqlalchemy import create_engine, text
from collections import Counter

DATABASE_URL = "postgresql+psycopg2://ghaf@/ghaf_app?host=/tmp"
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

with engine.connect() as conn:
    rows = conn.execute(text(
        "SELECT parse_error FROM raw_xml_store "
        "WHERE xml_type = 'RemittanceAdvice' AND parse_status = 'quarantined' "
        "ORDER BY id"
    )).fetchall()

    print(f"Total quarantined RA records: {len(rows)}\n")
    counts = Counter(r[0][:120] if r[0] else "NULL" for r in rows)
    for err, n in counts.most_common(10):
        print(f"  [{n}x] {err}")
