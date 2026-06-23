"""List all facility IDs and credentials."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import create_engine, text

DATABASE_URL = "postgresql+psycopg2://ghaf@/ghaf_app?host=/tmp"
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

with engine.connect() as conn:
    rows = conn.execute(text(
        "SELECT id, facility_name, facility_code, license_id, eclaimlink_username, is_active "
        "FROM facilities ORDER BY id"
    )).fetchall()

    print(f"{'ID':<5} {'Name':<30} {'Code':<25} {'License':<18} {'Username':<20} Active")
    print("-" * 105)
    for r in rows:
        print(f"{str(r[0]):<5} {str(r[1] or ''):<30} {str(r[2] or ''):<25} {str(r[3] or ''):<18} {str(r[4] or ''):<20} {r[5]}")
