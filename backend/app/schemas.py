"""
Ghaf App — Pydantic schemas (request/response models).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List

from pydantic import BaseModel, EmailStr, ConfigDict, Field


# ---------------------------------------------------------------------------
# Auth / Users / Login tracking
# ---------------------------------------------------------------------------
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: str
    facility_id: Optional[int] = None
    is_active: bool
    last_login_at: Optional[datetime] = None


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str = Field(min_length=8)
    role: str = "staff"
    facility_id: Optional[int] = None


class LoginLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: Optional[int] = None
    email_attempted: str
    success: bool
    failure_reason: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Facilities
# ---------------------------------------------------------------------------
class FacilityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    facility_code: str
    facility_name: str
    dhpo_provider_id: Optional[str] = None
    eclaimlink_username: Optional[str] = None
    is_active: bool


# ---------------------------------------------------------------------------
# Clinical Profiles
# ---------------------------------------------------------------------------
class ClinicalProfileBase(BaseModel):
    member_id: str
    emirates_id: Optional[str] = None
    full_name: str
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    nationality: Optional[str] = None

    payer_id: Optional[str] = None
    policy_number: Optional[str] = None
    plan_type: Optional[str] = None

    primary_clinician_id: Optional[str] = None
    blood_type: Optional[str] = None
    height_cm: Optional[Decimal] = None
    weight_kg: Optional[Decimal] = None
    allergies: Optional[str] = None
    chronic_conditions: Optional[str] = None
    current_medications: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool = True


class ClinicalProfileCreate(ClinicalProfileBase):
    facility_id: int


class ClinicalProfileUpdate(BaseModel):
    emirates_id: Optional[str] = None
    full_name: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    nationality: Optional[str] = None
    payer_id: Optional[str] = None
    policy_number: Optional[str] = None
    plan_type: Optional[str] = None
    primary_clinician_id: Optional[str] = None
    blood_type: Optional[str] = None
    height_cm: Optional[Decimal] = None
    weight_kg: Optional[Decimal] = None
    allergies: Optional[str] = None
    chronic_conditions: Optional[str] = None
    current_medications: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class ClinicalProfileOut(ClinicalProfileBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    facility_id: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# DHA XML Sync pipeline
# ---------------------------------------------------------------------------
class RawXmlStoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    facility_id: int
    xml_type: str
    source_filename: Optional[str] = None
    submission_date: Optional[date] = None
    fetched_at: datetime
    file_size_bytes: Optional[int] = None
    parse_status: str
    parse_error: Optional[str] = None
    records_parsed: Optional[int] = None
    parsed_at: Optional[datetime] = None


class FetchLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    facility_id: int
    fetch_type: str
    date_from: date
    date_to: date
    started_at: datetime
    completed_at: Optional[datetime] = None
    status: str
    records_fetched: int
    records_parsed: int
    records_failed: int
    http_errors: int
    validation_errors: int


class DhaSyncTriggerResponse(BaseModel):
    fetch_log_id: int
    status: str
    pending_records: int
    parsed_records: int
    quarantined_records: int
    message: str


class DhaUploadResponse(BaseModel):
    raw_xml_id: int
    xml_type: str
    source_filename: Optional[str] = None
    parse_status: str


class DhaFetchRequest(BaseModel):
    facility_id: Optional[int] = None
    date_from: date
    date_to: date


# ---------------------------------------------------------------------------
# Analytics / Metabase embeds
# ---------------------------------------------------------------------------
class MetabaseEmbedResponse(BaseModel):
    dashboard_key: str
    iframe_url: str
    expires_in: int


class DashboardSummary(BaseModel):
    total_claims: int
    total_net_amount: Decimal
    total_paid_amount: Decimal
    total_denial_amount: Decimal
    pending_raw_xml: int
    quarantined_raw_xml: int
    active_clinical_profiles: int
    recent_logins_24h: int
