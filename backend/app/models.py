"""
Ghaf App — RCM Platform — SQLAlchemy ORM Models

Base claims/remittance/recon models adapted from the existing DHPO ingestion
pipeline, extended with:
  - User accounts + LoginLog (login tracking)
  - ClinicalProfile (per-patient clinical profile setup)
"""
from __future__ import annotations
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List

from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime, ForeignKey,
    Integer, LargeBinary, Numeric, SmallInteger, String, Text, UniqueConstraint,
    CheckConstraint, Index, text
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

# SQLAlchemy's postgresql dialect doesn't export a TIMESTAMPTZ name directly;
# this is just TIMESTAMP WITH TIME ZONE.
TIMESTAMPTZ = TIMESTAMP(timezone=True)
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Facility
# ---------------------------------------------------------------------------
class Facility(Base):
    __tablename__ = "facilities"

    id               : Mapped[int]           = mapped_column(Integer, primary_key=True)
    facility_code    : Mapped[str]           = mapped_column(String(20), nullable=False, unique=True)
    facility_name    : Mapped[str]           = mapped_column(String(200), nullable=False)
    license_id       : Mapped[str]           = mapped_column(String(50), nullable=False)
    eclaimlink_username: Mapped[str]         = mapped_column(String(100), nullable=False)
    credential_key   : Mapped[str]           = mapped_column(String(100), nullable=False)
    dhpo_provider_id : Mapped[Optional[str]] = mapped_column(String(50))
    is_active        : Mapped[bool]          = mapped_column(Boolean, nullable=False, default=True)
    created_at       : Mapped[datetime]      = mapped_column(TIMESTAMPTZ, server_default=func.now())
    updated_at       : Mapped[datetime]      = mapped_column(TIMESTAMPTZ, server_default=func.now(), onupdate=func.now())

    claims           : Mapped[List["Claim"]]          = relationship(back_populates="facility")
    remittances      : Mapped[List["Remittance"]]     = relationship(back_populates="facility")
    recon_results    : Mapped[List["ReconResult"]]    = relationship(back_populates="facility")
    fetch_logs       : Mapped[List["FetchLog"]]       = relationship(back_populates="facility")
    raw_xml_store    : Mapped[List["RawXmlStore"]]    = relationship(back_populates="facility")
    users            : Mapped[List["User"]]           = relationship(back_populates="facility")
    clinical_profiles: Mapped[List["ClinicalProfile"]] = relationship(back_populates="facility")

    def __repr__(self) -> str:
        return f"<Facility {self.facility_code} — {self.facility_name}>"


# ---------------------------------------------------------------------------
# User (auth + login tracking)
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id               : Mapped[int]           = mapped_column(Integer, primary_key=True)
    facility_id      : Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("facilities.id"))
    email            : Mapped[str]           = mapped_column(String(255), nullable=False, unique=True)
    full_name        : Mapped[str]           = mapped_column(String(200), nullable=False)
    hashed_password  : Mapped[str]           = mapped_column(String(255), nullable=False)
    role             : Mapped[str]           = mapped_column(String(30), nullable=False, default="staff")
    is_active        : Mapped[bool]          = mapped_column(Boolean, nullable=False, default=True)
    last_login_at    : Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ)
    created_at       : Mapped[datetime]      = mapped_column(TIMESTAMPTZ, server_default=func.now())
    updated_at       : Mapped[datetime]      = mapped_column(TIMESTAMPTZ, server_default=func.now(), onupdate=func.now())

    facility         : Mapped[Optional["Facility"]] = relationship(back_populates="users")
    login_logs       : Mapped[List["LoginLog"]]     = relationship(back_populates="user")

    __table_args__ = (
        CheckConstraint(
            "role IN ('admin','billing_manager','clinician','staff')",
            name="ck_user_role",
        ),
    )

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.role})>"


# ---------------------------------------------------------------------------
# LoginLog (login tracking / audit trail)
# ---------------------------------------------------------------------------
class LoginLog(Base):
    __tablename__ = "login_logs"

    id               : Mapped[int]           = mapped_column(BigInteger, primary_key=True)
    user_id          : Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"))
    email_attempted  : Mapped[str]           = mapped_column(String(255), nullable=False)
    success          : Mapped[bool]          = mapped_column(Boolean, nullable=False)
    failure_reason   : Mapped[Optional[str]] = mapped_column(String(200))
    ip_address       : Mapped[Optional[str]] = mapped_column(String(64))
    user_agent       : Mapped[Optional[str]] = mapped_column(String(500))
    created_at       : Mapped[datetime]      = mapped_column(TIMESTAMPTZ, server_default=func.now())

    user             : Mapped[Optional["User"]] = relationship(back_populates="login_logs")

    __table_args__ = (
        Index("idx_login_logs_user", "user_id"),
        Index("idx_login_logs_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<LoginLog {self.email_attempted} success={self.success} @ {self.created_at}>"


# ---------------------------------------------------------------------------
# ClinicalProfile (clinical profile setup per patient)
# ---------------------------------------------------------------------------
class ClinicalProfile(Base):
    __tablename__ = "clinical_profiles"

    id                   : Mapped[int]           = mapped_column(Integer, primary_key=True)
    facility_id          : Mapped[int]           = mapped_column(Integer, ForeignKey("facilities.id"), nullable=False)

    member_id            : Mapped[str]           = mapped_column(String(100), nullable=False)
    emirates_id          : Mapped[Optional[str]] = mapped_column(String(50))
    full_name            : Mapped[str]           = mapped_column(String(200), nullable=False)
    date_of_birth        : Mapped[Optional[date]]= mapped_column(Date)
    gender               : Mapped[Optional[str]] = mapped_column(String(10))
    nationality          : Mapped[Optional[str]] = mapped_column(String(60))

    payer_id             : Mapped[Optional[str]] = mapped_column(String(50))
    policy_number        : Mapped[Optional[str]] = mapped_column(String(100))
    plan_type            : Mapped[Optional[str]] = mapped_column(String(50))

    primary_clinician_id : Mapped[Optional[str]] = mapped_column(String(50))
    blood_type           : Mapped[Optional[str]] = mapped_column(String(5))
    height_cm            : Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 1))
    weight_kg            : Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 1))
    allergies            : Mapped[Optional[str]] = mapped_column(Text)
    chronic_conditions   : Mapped[Optional[str]] = mapped_column(Text)
    current_medications  : Mapped[Optional[str]] = mapped_column(Text)
    notes                : Mapped[Optional[str]] = mapped_column(Text)

    is_active            : Mapped[bool]          = mapped_column(Boolean, nullable=False, default=True)
    created_at           : Mapped[datetime]      = mapped_column(TIMESTAMPTZ, server_default=func.now())
    updated_at           : Mapped[datetime]      = mapped_column(TIMESTAMPTZ, server_default=func.now(), onupdate=func.now())

    facility             : Mapped["Facility"]    = relationship(back_populates="clinical_profiles")

    __table_args__ = (
        UniqueConstraint("facility_id", "member_id", name="uq_clinical_profile_facility_member"),
        CheckConstraint("gender IN ('Male','Female','Other') OR gender IS NULL", name="ck_clinical_profile_gender"),
        Index("idx_clinical_profiles_member", "member_id"),
        Index("idx_clinical_profiles_emirates_id", "emirates_id"),
    )

    def __repr__(self) -> str:
        return f"<ClinicalProfile {self.member_id} — {self.full_name}>"


# ---------------------------------------------------------------------------
# RawXmlStore (Production Optimized)
# ---------------------------------------------------------------------------
class RawXmlStore(Base):
    __tablename__ = "raw_xml_store"

    id               : Mapped[int]           = mapped_column(BigInteger, primary_key=True)
    facility_id      : Mapped[int]           = mapped_column(Integer, ForeignKey("facilities.id"), nullable=False)
    xml_type         : Mapped[str]           = mapped_column(String(20), nullable=False)
    source_filename  : Mapped[Optional[str]] = mapped_column(String(500))
    submission_date  : Mapped[Optional[date]]= mapped_column(Date)
    fetched_at       : Mapped[datetime]      = mapped_column(TIMESTAMPTZ, server_default=func.now())
    file_size_bytes  : Mapped[Optional[int]] = mapped_column(Integer)
    xml_content      : Mapped[str]           = mapped_column(Text, nullable=False) # Handled by PG TOAST out-of-line
    parse_status     : Mapped[str]           = mapped_column(String(20), nullable=False, default="pending")
    parse_error      : Mapped[Optional[str]] = mapped_column(Text)
    records_parsed   : Mapped[Optional[int]] = mapped_column(Integer)
    parsed_at        : Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ)

    facility         : Mapped["Facility"]    = relationship(back_populates="raw_xml_store")

    __table_args__ = (
        CheckConstraint("xml_type IN ('ClaimSubmission', 'RemittanceAdvice')", name="ck_raw_xml_type"),
        CheckConstraint("parse_status IN ('pending','parsed','failed','quarantined')", name="ck_parse_status"),
        Index("idx_raw_xml_facility_type", "facility_id", "xml_type"),
        Index("idx_raw_xml_parse_status", "parse_status"),
    )


# ---------------------------------------------------------------------------
# Claim (Adjusted for Hybrid Ingestion Channels)
# ---------------------------------------------------------------------------
class Claim(Base):
    __tablename__ = "claims"

    id               : Mapped[int]           = mapped_column(BigInteger, primary_key=True)
    facility_id      : Mapped[int]           = mapped_column(Integer, ForeignKey("facilities.id"), nullable=False)

    # Made nullable to allow historical imports from Excel without breaking constraints
    raw_xml_id       : Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("raw_xml_store.id"), nullable=True)

    # Lineage origin tracker to segment analytical reporting
    source_channel   : Mapped[str]           = mapped_column(String(20), nullable=False, default="API")

    # DHPO XML identifiers
    claim_id         : Mapped[str]           = mapped_column(String(100), nullable=False)
    claim_id_payer   : Mapped[Optional[str]] = mapped_column(String(100))

    # Encounter header
    encounter_id     : Mapped[str]           = mapped_column(String(100), nullable=False)
    encounter_type   : Mapped[Optional[str]] = mapped_column(String(50))
    encounter_start  : Mapped[datetime]      = mapped_column(TIMESTAMPTZ, nullable=False)
    encounter_end    : Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ)
    start_type       : Mapped[Optional[str]] = mapped_column(String(50))
    end_type         : Mapped[Optional[str]] = mapped_column(String(50))
    transfer_source  : Mapped[Optional[str]] = mapped_column(String(50))

    # Patient identifiers
    member_id        : Mapped[str]           = mapped_column(String(100), nullable=False)
    emirates_id      : Mapped[Optional[str]] = mapped_column(String(50))
    emirates_id_type : Mapped[Optional[str]] = mapped_column(String(20))

    # Payer & clinician
    payer_id         : Mapped[str]           = mapped_column(String(50), nullable=False)
    payer_name       : Mapped[Optional[str]] = mapped_column(String(150))
    clinician_id     : Mapped[str]           = mapped_column(String(50), nullable=False)
    clinician_name   : Mapped[Optional[str]] = mapped_column(String(150))
    department       : Mapped[Optional[str]] = mapped_column(String(100))

    # eClaimLink / DHPO receiver (TPA that received the submission)
    receiver_id      : Mapped[Optional[str]] = mapped_column(String(50))
    receiver_name    : Mapped[Optional[str]] = mapped_column(String(150))

    # Financial totals
    gross_amount     : Mapped[Decimal]       = mapped_column(Numeric(12, 2), nullable=False, default=0)
    net_amount       : Mapped[Decimal]       = mapped_column(Numeric(12, 2), nullable=False, default=0)
    patient_share_total: Mapped[Decimal]     = mapped_column(Numeric(12, 2), nullable=False, default=0)

    # Submission metadata
    submission_date  : Mapped[date]          = mapped_column(Date, nullable=False)
    claim_status     : Mapped[str]           = mapped_column(String(30), nullable=False, default="submitted")
    resubmission_count: Mapped[int]          = mapped_column(SmallInteger, nullable=False, default=0)

    # Internal
    created_at       : Mapped[datetime]      = mapped_column(TIMESTAMPTZ, server_default=func.now())
    updated_at       : Mapped[datetime]      = mapped_column(TIMESTAMPTZ, server_default=func.now(), onupdate=func.now())

    facility         : Mapped["Facility"]            = relationship(back_populates="claims")
    diagnoses        : Mapped[List["ClaimDiagnosis"]] = relationship(back_populates="claim", cascade="all, delete-orphan")
    activities       : Mapped[List["ClaimActivity"]]  = relationship(back_populates="claim", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("facility_id", "claim_id", name="uq_claims_facility_claim_id"),
        CheckConstraint("source_channel IN ('API', 'EXCEL_HISTORICAL')", name="ck_claim_source_channel"),
        Index("idx_claims_encounter_start", "encounter_start"),
        Index("idx_claims_payer", "payer_id"),
        Index("idx_claims_member", "member_id"),
        Index("idx_claims_channel", "source_channel"),
        Index("idx_claims_receiver", "receiver_id"),
        Index("idx_claims_clinician", "clinician_id"),
        Index("idx_claims_department", "department"),
        Index("idx_claims_status", "claim_status"),
    )

    def __repr__(self) -> str:
        return f"<Claim {self.claim_id} | Channel={self.source_channel} @ {self.facility_id}>"


# ---------------------------------------------------------------------------
# ClaimDiagnosis
# ---------------------------------------------------------------------------
class ClaimDiagnosis(Base):
    __tablename__ = "claim_diagnoses"

    id                 : Mapped[int]           = mapped_column(BigInteger, primary_key=True)
    claim_id_fk        : Mapped[int]           = mapped_column(BigInteger, ForeignKey("claims.id", ondelete="CASCADE"), nullable=False)
    facility_id        : Mapped[int]           = mapped_column(Integer, ForeignKey("facilities.id"), nullable=False)
    diagnosis_type     : Mapped[str]           = mapped_column(String(20), nullable=False)
    diagnosis_code     : Mapped[str]           = mapped_column(String(20), nullable=False)
    diagnosis_description: Mapped[Optional[str]] = mapped_column(String(300))
    sequence_no        : Mapped[int]           = mapped_column(SmallInteger, nullable=False, default=1)
    created_at         : Mapped[datetime]      = mapped_column(TIMESTAMPTZ, server_default=func.now())

    claim              : Mapped["Claim"]       = relationship(back_populates="diagnoses")

    __table_args__ = (
        CheckConstraint("diagnosis_type IN ('Primary','Admitting','Secondary')", name="ck_diag_type"),
        Index("idx_diagnoses_claim", "claim_id_fk"),
        Index("idx_diagnoses_code", "diagnosis_code"),
    )


# ---------------------------------------------------------------------------
# ClaimActivity
# ---------------------------------------------------------------------------
class ClaimActivity(Base):
    __tablename__ = "claim_activities"

    id                 : Mapped[int]            = mapped_column(BigInteger, primary_key=True)
    claim_id_fk        : Mapped[int]            = mapped_column(BigInteger, ForeignKey("claims.id", ondelete="CASCADE"), nullable=False)
    facility_id        : Mapped[int]            = mapped_column(Integer, ForeignKey("facilities.id"), nullable=False)
    activity_id        : Mapped[Optional[str]]  = mapped_column(String(100))
    activity_type      : Mapped[str]            = mapped_column(String(20), nullable=False)
    activity_code      : Mapped[str]            = mapped_column(String(50), nullable=False)
    activity_description: Mapped[Optional[str]] = mapped_column(String(300))
    non_std_code       : Mapped[Optional[str]]  = mapped_column(String(50))
    quantity           : Mapped[Decimal]        = mapped_column(Numeric(10, 3), nullable=False, default=1)
    gross              : Mapped[Decimal]        = mapped_column(Numeric(12, 2), nullable=False)
    net                : Mapped[Decimal]        = mapped_column(Numeric(12, 2), nullable=False)
    patient_share      : Mapped[Decimal]        = mapped_column(Numeric(12, 2), nullable=False, default=0)
    activity_start     : Mapped[date]           = mapped_column(Date, nullable=False)
    authorization_id   : Mapped[Optional[str]]  = mapped_column(String(100))
    clinician_id       : Mapped[Optional[str]]  = mapped_column(String(50))
    sequence_no        : Mapped[int]            = mapped_column(SmallInteger, nullable=False, default=1)
    created_at         : Mapped[datetime]       = mapped_column(TIMESTAMPTZ, server_default=func.now())

    claim              : Mapped["Claim"]               = relationship(back_populates="activities")
    observations       : Mapped[List["ClaimObservation"]] = relationship(back_populates="activity", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("activity_type IN ('CPT','Dental','Drug','Service','HCPCS')", name="ck_activity_type"),
        Index("idx_activities_claim", "claim_id_fk"),
        Index("idx_activities_type", "activity_type"),
        Index("idx_activities_code", "activity_code"),
    )


# ---------------------------------------------------------------------------
# ClaimObservation
# ---------------------------------------------------------------------------
class ClaimObservation(Base):
    __tablename__ = "claim_observations"

    id                 : Mapped[int]            = mapped_column(BigInteger, primary_key=True)
    activity_id_fk     : Mapped[int]            = mapped_column(BigInteger, ForeignKey("claim_activities.id", ondelete="CASCADE"), nullable=False)
    claim_id_fk        : Mapped[int]            = mapped_column(BigInteger, ForeignKey("claims.id", ondelete="CASCADE"), nullable=False)
    observation_type   : Mapped[str]            = mapped_column(String(100), nullable=False)
    observation_code   : Mapped[Optional[str]]  = mapped_column(String(100))
    observation_value  : Mapped[Optional[str]]  = mapped_column(String(500))
    value_type         : Mapped[Optional[str]]  = mapped_column(String(50))
    created_at         : Mapped[datetime]       = mapped_column(TIMESTAMPTZ, server_default=func.now())

    activity           : Mapped["ClaimActivity"] = relationship(back_populates="observations")


# ---------------------------------------------------------------------------
# Remittance (Adjusted for Hybrid Ingestion Channels)
# ---------------------------------------------------------------------------
class Remittance(Base):
    __tablename__ = "remittances"

    id                 : Mapped[int]            = mapped_column(BigInteger, primary_key=True)
    facility_id        : Mapped[int]            = mapped_column(Integer, ForeignKey("facilities.id"), nullable=False)

    # Made nullable to accommodate Excel-extracted Adjudication baselines
    raw_xml_id         : Mapped[Optional[int]]  = mapped_column(BigInteger, ForeignKey("raw_xml_store.id"), nullable=True)
    source_channel     : Mapped[str]            = mapped_column(String(20), nullable=False, default="API")

    claim_id           : Mapped[str]            = mapped_column(String(100), nullable=False)
    claim_id_payer     : Mapped[Optional[str]]  = mapped_column(String(100))
    payer_id           : Mapped[str]            = mapped_column(String(50), nullable=False)
    remittance_date    : Mapped[date]           = mapped_column(Date, nullable=False)
    ra_file_id         : Mapped[Optional[str]]  = mapped_column(String(100))
    gross_amount       : Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    net_amount         : Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    paid_amount        : Mapped[Decimal]        = mapped_column(Numeric(12, 2), nullable=False, default=0)
    patient_share_total: Mapped[Decimal]        = mapped_column(Numeric(12, 2), nullable=False, default=0)
    discount_amount    : Mapped[Decimal]        = mapped_column(Numeric(12, 2), nullable=False, default=0)
    denial_amount      : Mapped[Decimal]        = mapped_column(Numeric(12, 2), nullable=False, default=0)
    claim_status_ra    : Mapped[Optional[str]]  = mapped_column(String(50))
    denial_code        : Mapped[Optional[str]]  = mapped_column(String(50))
    denial_description : Mapped[Optional[str]]  = mapped_column(String(500))
    created_at         : Mapped[datetime]       = mapped_column(TIMESTAMPTZ, server_default=func.now())
    updated_at         : Mapped[datetime]       = mapped_column(TIMESTAMPTZ, server_default=func.now(), onupdate=func.now())

    facility           : Mapped["Facility"]     = relationship(back_populates="remittances")
    activity_details   : Mapped[List["RemittanceActivityDetail"]] = relationship(
        back_populates="remittance", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("facility_id", "claim_id", "remittance_date", name="uq_remittance_claim_date"),
        CheckConstraint("source_channel IN ('API', 'EXCEL_HISTORICAL')", name="ck_remittance_source_channel"),
        Index("idx_remittances_claim_id", "claim_id"),
        Index("idx_remittances_remittance_date", "remittance_date"),
        Index("idx_remittances_channel", "source_channel"),
    )


# ---------------------------------------------------------------------------
# RemittanceActivityDetail
# ---------------------------------------------------------------------------
class RemittanceActivityDetail(Base):
    __tablename__ = "remittance_activity_details"

    id                 : Mapped[int]            = mapped_column(BigInteger, primary_key=True)
    remittance_id_fk   : Mapped[int]            = mapped_column(BigInteger, ForeignKey("remittances.id", ondelete="CASCADE"), nullable=False)
    facility_id        : Mapped[int]            = mapped_column(Integer, ForeignKey("facilities.id"), nullable=False)
    activity_id        : Mapped[Optional[str]]  = mapped_column(String(100))
    activity_code      : Mapped[Optional[str]]  = mapped_column(String(50))
    activity_type      : Mapped[Optional[str]]  = mapped_column(String(20))
    gross              : Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    net                : Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    paid_amount        : Mapped[Decimal]        = mapped_column(Numeric(12, 2), nullable=False, default=0)
    patient_share      : Mapped[Decimal]        = mapped_column(Numeric(12, 2), nullable=False, default=0)
    denial_code        : Mapped[Optional[str]]  = mapped_column(String(50))
    denial_description : Mapped[Optional[str]]  = mapped_column(String(500))
    quantity_approved  : Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3))
    created_at         : Mapped[datetime]       = mapped_column(TIMESTAMPTZ, server_default=func.now())

    remittance         : Mapped["Remittance"]   = relationship(back_populates="activity_details")


# ---------------------------------------------------------------------------
# ReconResult
# ---------------------------------------------------------------------------
class ReconResult(Base):
    __tablename__ = "recon_results"

    id                     : Mapped[int]               = mapped_column(BigInteger, primary_key=True)
    facility_id            : Mapped[int]               = mapped_column(Integer, ForeignKey("facilities.id"), nullable=False)
    claim_id               : Mapped[str]               = mapped_column(String(100), nullable=False)
    claim_pk               : Mapped[Optional[int]]     = mapped_column(BigInteger, ForeignKey("claims.id"))
    remittance_pk          : Mapped[Optional[int]]     = mapped_column(BigInteger, ForeignKey("remittances.id"))
    encounter_start        : Mapped[Optional[datetime]]= mapped_column(TIMESTAMPTZ)
    submission_date        : Mapped[Optional[date]]    = mapped_column(Date)
    remittance_date        : Mapped[Optional[date]]    = mapped_column(Date)
    payer_id               : Mapped[Optional[str]]     = mapped_column(String(50))
    member_id              : Mapped[Optional[str]]     = mapped_column(String(100))
    submitted_gross        : Mapped[Decimal]           = mapped_column(Numeric(12, 2), nullable=False, default=0)
    submitted_net          : Mapped[Decimal]           = mapped_column(Numeric(12, 2), nullable=False, default=0)
    paid_amount            : Mapped[Decimal]           = mapped_column(Numeric(12, 2), nullable=False, default=0)
    patient_share          : Mapped[Decimal]           = mapped_column(Numeric(12, 2), nullable=False, default=0)
    discount_amount        : Mapped[Decimal]           = mapped_column(Numeric(12, 2), nullable=False, default=0)
    denial_amount          : Mapped[Decimal]           = mapped_column(Numeric(12, 2), nullable=False, default=0)
    recon_status           : Mapped[str]               = mapped_column(String(30), nullable=False)
    denial_code            : Mapped[Optional[str]]     = mapped_column(String(50))
    denial_description     : Mapped[Optional[str]]     = mapped_column(String(500))
    last_reconciled_at     : Mapped[datetime]          = mapped_column(TIMESTAMPTZ, server_default=func.now())

    facility               : Mapped["Facility"]        = relationship(back_populates="recon_results")

    __table_args__ = (
        UniqueConstraint("facility_id", "claim_id", name="uq_recon_facility_claim"),
        Index("idx_recon_encounter_start", "encounter_start"),
        Index("idx_recon_status", "recon_status"),
    )


# ---------------------------------------------------------------------------
# FetchLog
# ---------------------------------------------------------------------------
class FetchLog(Base):
    __tablename__ = "fetch_log"

    id                 : Mapped[int]            = mapped_column(BigInteger, primary_key=True)
    facility_id        : Mapped[int]            = mapped_column(Integer, ForeignKey("facilities.id"), nullable=False)
    fetch_type         : Mapped[str]            = mapped_column(String(20), nullable=False)
    date_from          : Mapped[date]           = mapped_column(Date, nullable=False)
    date_to            : Mapped[date]           = mapped_column(Date, nullable=False)
    started_at         : Mapped[datetime]       = mapped_column(TIMESTAMPTZ, server_default=func.now())
    completed_at       : Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ)
    status             : Mapped[str]            = mapped_column(String(20), nullable=False, default="running")
    records_fetched    : Mapped[int]            = mapped_column(Integer, nullable=False, default=0)
    records_parsed     : Mapped[int]            = mapped_column(Integer, nullable=False, default=0)
    records_failed     : Mapped[int]            = mapped_column(Integer, nullable=False, default=0)
    http_errors        : Mapped[int]            = mapped_column(Integer, nullable=False, default=0)
    validation_errors  : Mapped[int]            = mapped_column(Integer, nullable=False, default=0)
    error_detail       : Mapped[Optional[dict]] = mapped_column(JSONB)

    facility           : Mapped["Facility"]     = relationship(back_populates="fetch_logs")

    __table_args__ = (
        CheckConstraint("fetch_type IN ('ClaimSubmission','RemittanceAdvice','Backfill')", name="ck_fetch_type"),
        CheckConstraint("status IN ('running','success','partial','failed')", name="ck_fetch_status"),
        Index("idx_fetch_log_started", "started_at"),
    )


# ---------------------------------------------------------------------------
# ReportJob — staged report queue
# ---------------------------------------------------------------------------
class ReportJob(Base):
    __tablename__ = "report_jobs"

    id            : Mapped[int]             = mapped_column(Integer, primary_key=True)
    user_id       : Mapped[Optional[int]]   = mapped_column(Integer, nullable=True)  # no ORM FK — avoids User model resolution issues
    report_type   : Mapped[str]             = mapped_column(String(50), nullable=False)
    report_label  : Mapped[str]             = mapped_column(String(100), nullable=False)
    filters_json  : Mapped[Optional[str]]   = mapped_column(Text)        # JSON string of applied filters
    status        : Mapped[str]             = mapped_column(String(20), nullable=False, default="completed")
    file_data     : Mapped[Optional[bytes]] = mapped_column(LargeBinary)  # raw xlsx bytes
    filename      : Mapped[Optional[str]]   = mapped_column(String(255))
    row_count     : Mapped[Optional[int]]   = mapped_column(Integer)
    error_message : Mapped[Optional[str]]   = mapped_column(Text)
    created_at    : Mapped[datetime]        = mapped_column(TIMESTAMPTZ, server_default=func.now())
    completed_at  : Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ)

    __table_args__ = (
        Index("idx_report_jobs_created_at", "created_at"),
    )
