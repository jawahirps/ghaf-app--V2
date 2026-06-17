"""
Ghaf App — first-run seed data.

Creates a default facility and admin user if the database is empty, so the
React app has something to log in with on first run.

  email:    admin@ghafapp.local
  password: ChangeMe123!
"""
import logging

from sqlalchemy.orm import Session

from .models import Facility, User
from .security import hash_password

log = logging.getLogger(__name__)

DEFAULT_ADMIN_EMAIL = "admin@ghafapp.local"
DEFAULT_ADMIN_PASSWORD = "ChangeMe123!"


def run_seed(db: Session) -> None:
    facility = db.query(Facility).first()
    if facility is None:
        facility = Facility(
            facility_code="GHAF-001",
            facility_name="Ghaf App Demo Clinic",
            license_id="DHA-LIC-0001",
            eclaimlink_username="demo_user",
            credential_key="demo_credential",
            dhpo_provider_id="PR0001",
            is_active=True,
        )
        db.add(facility)
        db.commit()
        db.refresh(facility)
        log.info("Seeded default facility %s", facility.facility_code)

    admin = db.query(User).filter(User.email == DEFAULT_ADMIN_EMAIL).first()
    if admin is None:
        admin = User(
            facility_id=facility.id,
            email=DEFAULT_ADMIN_EMAIL,
            full_name="Ghaf App Administrator",
            hashed_password=hash_password(DEFAULT_ADMIN_PASSWORD),
            role="admin",
            is_active=True,
        )
        db.add(admin)
        db.commit()
        log.warning(
            "Seeded default admin user %s with password '%s' — change this immediately.",
            DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD,
        )
