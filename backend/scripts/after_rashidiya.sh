#!/bin/bash
# Runs automatically after Alnoor Rashidiya bulk fetch completes:
#   Step 2a — clean up stuck "running" fetch_log entries
#   Step 2b — re-parse all RA records with fixed parser
#   Step 3  — bulk fetch New Lotus (facility 15) 2024-06-01 to 2026-06-16

cd "$(dirname "$0")/.."

echo "============================================================"
echo "Waiting for Alnoor Rashidiya (facility 8) fetch to finish..."
echo "============================================================"

while .venv/bin/python3 - <<'EOF'
from sqlalchemy import create_engine, text
e = create_engine('postgresql+psycopg2://ghaf@/ghaf_app?host=/tmp')
with e.connect() as c:
    n = c.execute(text("SELECT COUNT(*) FROM fetch_log WHERE facility_id=8 AND status='running'")).scalar()
exit(0 if n > 0 else 1)
EOF
do
    echo "  Still running... checking again in 10 minutes"
    sleep 600
done

echo ""
echo "============================================================"
echo "Step 2a — Cleaning up stuck 'running' entries..."
echo "============================================================"
.venv/bin/python3 - <<'EOF'
from sqlalchemy import create_engine, text
e = create_engine('postgresql+psycopg2://ghaf@/ghaf_app?host=/tmp')
with e.begin() as c:
    r = c.execute(text("UPDATE fetch_log SET status='failed', error_message='Interrupted' WHERE status='running'"))
    print(f"Updated {r.rowcount} stuck entries")
EOF

echo ""
echo "============================================================"
echo "Step 2b — Re-parsing all RA records..."
echo "============================================================"
.venv/bin/python3 scripts/reparse_nas_ra.py

echo ""
echo "============================================================"
echo "Step 3 — Bulk fetch New Lotus (facility 15)..."
echo "============================================================"
caffeinate -i .venv/bin/python3 scripts/bulk_fetch.py \
    --facility 15 \
    --from 2024-06-01 \
    --to 2026-06-16

echo ""
echo "============================================================"
echo "ALL DONE! Check the app for New Lotus fetch results."
echo "============================================================"
