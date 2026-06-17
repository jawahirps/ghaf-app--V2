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
    license_id: str
    eclaimlink_username: str
    credential_key: str
    dhpo_provider_id: Optional[str] = None
    is_active: bool

    model_config = {"from_attributes": True}


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
    return db.query(Facility).order_by(Facility.facility_name).all()


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
    return fac


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
    return fac
