"""
Ghaf App — Facility management endpoints.

GET  /api/facilities          — list all facilities (admin only)
GET  /api/facilities/{id}     — get one facility
PUT  /api/facilities/{id}     — update credentials / settings (admin only)
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Facility, User
from ..security import get_current_user

router = APIRouter(prefix="/api/facilities", tags=["facilities"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class FacilityOut(BaseModel):
    id: int
    facility_code: str
    facility_name: str
    license_id: Optional[str] = None
    eclaimlink_username: Optional[str] = None
    dhpo_provider_id: Optional[str] = None
    is_active: bool
    has_credential: bool = False

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_facility(cls, fac) -> "FacilityOut":
        data = {
            "id": fac.id,
            "facility_code": fac.facility_code,
            "facility_name": fac.facility_name,
            "license_id": fac.license_id,
            "eclaimlink_username": fac.eclaimlink_username,
            "dhpo_provider_id": fac.dhpo_provider_id,
            "is_active": fac.is_active,
            "has_credential": bool(fac.credential_key),
        }
        return cls(**data)


class FacilityUpdate(BaseModel):
    facility_name: Optional[str] = None
    license_id: Optional[str] = None
    eclaimlink_username: Optional[str] = None
    credential_key: Optional[str] = None
    dhpo_provider_id: Optional[str] = None
    is_active: Optional[bool] = None


def _require_admin(user: User):
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("", response_model=list[FacilityOut])
def list_facilities(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    facilities = db.query(Facility).order_by(Facility.facility_name).all()
    return [FacilityOut.from_orm_facility(f) for f in facilities]


@router.get("/{facility_id}", response_model=FacilityOut)
def get_facility(
    facility_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    fac = db.get(Facility, facility_id)
    if not fac:
        raise HTTPException(status_code=404, detail="Facility not found.")
    return FacilityOut.from_orm_facility(fac)


@router.put("/{facility_id}", response_model=FacilityOut)
def update_facility(
    facility_id: int,
    payload: FacilityUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    fac = db.get(Facility, facility_id)
    if not fac:
        raise HTTPException(status_code=404, detail="Facility not found.")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(fac, field, value)

    db.commit()
    db.refresh(fac)
    return FacilityOut.from_orm_facility(fac)
