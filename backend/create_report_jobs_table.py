"""
Run this once to create the report_jobs table in the ghaf_app database.

Usage (from the backend directory):
    python create_report_jobs_table.py
"""
import sys
import os

# Make sure 'app' package is on the path
sys.path.insert(0, os.path.dirname(__file__))

from app.database import engine
from app.models import Base, ReportJob  # noqa: F401 — ensures ReportJob is registered

print("Creating report_jobs table (if not exists)…")
ReportJob.__table__.create(bind=engine, checkfirst=True)
print("Done. Table 'report_jobs' is ready.")
