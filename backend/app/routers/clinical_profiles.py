"""
Ghaf App — Clinical Profiles CRUD.

Clinical profiles capture per-patient demographic, payer, and clinical
context (allergies, chronic conditions, medications, primary clinician,
etc.) used across the platform — e.g. to pre-populate DHA claim
submissions and to drive the Analytics tab's patient-mix views.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ClinicalProfile, User
from ..schemas import ClinicalProfileCreate, ClinicalProfileOut, ClinicalProfileUpdate
from ..security import get_current_user, require_roles

router = APIRouter(prefix="/api/clinical-profiles", tags=["clinical-profiles"])


@router.get("", response_model=List[ClinicalProfileOut])
def list_clinical_profiles(
    facility_id: Optional[int] = None,
    search: Optional[str] = Query(default=None, description="Search by name, member ID, or Emirates ID"),
    is_active: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(ClinicalProfile)

    facility_scope = facility_id or current_user.facility_id
    if facility_scope is not None:
        query = query.filter(ClinicalProfile.facility_id == facility_scope)

    if is_active is not None:
        query = query.filter(ClinicalProfile.is_active == is_active)

    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                ClinicalProfile.full_name.ilike(like),
                ClinicalProfile.member_id.ilike(like),
                ClinicalProfile.emirates_id.ilike(like),
            )
        )

    return (
        query.order_by(ClinicalProfile.full_name.asc())
        .offset(offset)
        .limit(min(limit, 500))
        .all()
    )


@router.get("/{profile_id}", response_model=ClinicalProfileOut)
def get_clinical_profile(
    profile_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    profile = db.get(ClinicalProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clinical profile not found")
    return profile


@router.post("", response_model=ClinicalProfileOut, status_code=status.HTTP_201_CREATED)
def create_clinical_profile(
    payload: ClinicalProfileCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "billing_manager", "clinician", "staff")),
):
    existing = (
        db.query(ClinicalProfile)
        .filter(
            ClinicalProfile.facility_id == payload.facility_id,
            ClinicalProfile.member_id == payload.member_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A clinical profile with this member ID already exists for this facility",
        )

    profile = ClinicalProfile(**payload.model_dump())
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@router.put("/{profile_id}", response_model=ClinicalProfileOut)
def update_clinical_profile(
    profile_id: int,
    payload: ClinicalProfileUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "billing_manager", "clinician", "staff")),
):
    profile = db.get(ClinicalProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clinical profile not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)

    db.commit()
    db.refresh(profile)
    return profile


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_clinical_profile(
    profile_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
):
    profile = db.get(ClinicalProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clinical profile not found")

    db.delete(profile)
    db.commit()
    return None
