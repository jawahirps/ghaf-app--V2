"""
Ghaf App — Analytics & Financial Insights endpoints.

Two responsibilities:
  1. /summary — lightweight KPI numbers computed directly from the app DB,
     used for the in-app dashboard cards (fast, no Metabase dependency).
  2. /embed/{dashboard_key} — issues a short-lived signed Metabase
     embedding URL for the heavy reporting (payer breakdowns, collection
     charts, AR aging, denials) rendered inside the React
     "Analytics & Financial Insights" tab via <iframe>.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Claim, ClaimActivity, ClinicalProfile, Facility, LoginLog, RawXmlStore, Remittance, User
from ..schemas import DashboardSummary, MetabaseEmbedResponse
from ..security import get_current_user
from ..services.metabase import build_embed_url, list_dashboard_keys

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


# ---------------------------------------------------------------------------
# Shared filters for the Submissions / Resubmissions / Remittance / Denials /
# Clinicians / Operations / Insurance / Department report tabs.
# ---------------------------------------------------------------------------
@dataclass
class AnalyticsFilters:
    facility_id: Optional[int] = None
    receiver_id: Optional[str] = None
    payer_id: Optional[str] = None
    encounter_type: Optional[str] = None
    department: Optional[str] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None


def get_analytics_filters(
    facility_id: Optional[int] = None,
    receiver_id: Optional[str] = None,
    payer_id: Optional[str] = None,
    encounter_type: Optional[str] = None,
    department: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> AnalyticsFilters:
    return AnalyticsFilters(
        facility_id=facility_id,
        receiver_id=receiver_id,
        payer_id=payer_id,
        encounter_type=encounter_type,
        department=department,
        date_from=date_from,
        date_to=date_to,
    )


def _apply_claim_filters(query, f: AnalyticsFilters):
    if f.facility_id:
        query = query.filter(Claim.facility_id == f.facility_id)
    if f.receiver_id:
        query = query.filter(Claim.receiver_id == f.receiver_id)
    if f.payer_id:
        query = query.filter(Claim.payer_id == f.payer_id)
    if f.encounter_type:
        query = query.filter(Claim.encounter_type == f.encounter_type)
    if f.department:
        query = query.filter(Claim.department == f.department)
    if f.date_from:
        query = query.filter(Claim.submission_date >= f.date_from)
    if f.date_to:
        query = query.filter(Claim.submission_date <= f.date_to)
    return query


def _remits_with_claims(db: Session, f: AnalyticsFilters):
    """Remittance rows joined to their parent Claim, with filters applied."""
    query = db.query(Remittance, Claim).join(
        Claim,
        and_(Claim.facility_id == Remittance.facility_id, Claim.claim_id == Remittance.claim_id),
    )
    if f.facility_id:
        query = query.filter(Remittance.facility_id == f.facility_id)
    if f.receiver_id:
        query = query.filter(Claim.receiver_id == f.receiver_id)
    if f.payer_id:
        query = query.filter(Remittance.payer_id == f.payer_id)
    if f.encounter_type:
        query = query.filter(Claim.encounter_type == f.encounter_type)
    if f.department:
        query = query.filter(Claim.department == f.department)
    if f.date_from:
        query = query.filter(Claim.submission_date >= f.date_from)
    if f.date_to:
        query = query.filter(Claim.submission_date <= f.date_to)
    return query


def _money(value) -> float:
    return float(value or 0)


def _month_label(d) -> str:
    return d.strftime("%Y-%m") if d else "Unknown"


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary(
    facility_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Admins see all facilities unless they explicitly pass facility_id.
    # Non-admin users are always scoped to their own facility.
    if current_user.role == "admin":
        facility_scope = facility_id  # None = no filter = all facilities
    else:
        facility_scope = facility_id or current_user.facility_id

    claims_q = db.query(Claim)
    remits_q = db.query(Remittance)
    raw_q = db.query(RawXmlStore)
    profiles_q = db.query(ClinicalProfile)

    if facility_scope is not None:
        claims_q = claims_q.filter(Claim.facility_id == facility_scope)
        remits_q = remits_q.filter(Remittance.facility_id == facility_scope)
        raw_q = raw_q.filter(RawXmlStore.facility_id == facility_scope)
        profiles_q = profiles_q.filter(ClinicalProfile.facility_id == facility_scope)

    total_claims = claims_q.count()
    total_net = claims_q.with_entities(func.coalesce(func.sum(Claim.net_amount), 0)).scalar() or Decimal("0")
    total_paid = remits_q.with_entities(func.coalesce(func.sum(Remittance.paid_amount), 0)).scalar() or Decimal("0")
    total_denied = remits_q.with_entities(func.coalesce(func.sum(Remittance.denial_amount), 0)).scalar() or Decimal("0")

    pending_raw = raw_q.filter(RawXmlStore.parse_status == "pending").count()
    quarantined_raw = raw_q.filter(RawXmlStore.parse_status == "quarantined").count()
    active_profiles = profiles_q.filter(ClinicalProfile.is_active.is_(True)).count()

    since = datetime.utcnow() - timedelta(hours=24)
    recent_logins = (
        db.query(LoginLog)
        .filter(LoginLog.success.is_(True))
        .filter(LoginLog.created_at >= since)
        .count()
    )

    return DashboardSummary(
        total_claims=total_claims,
        total_net_amount=total_net,
        total_paid_amount=total_paid,
        total_denial_amount=total_denied,
        pending_raw_xml=pending_raw,
        quarantined_raw_xml=quarantined_raw,
        active_clinical_profiles=active_profiles,
        recent_logins_24h=recent_logins,
    )


@router.get("/dashboards", response_model=list[str])
def dashboards(_: User = Depends(get_current_user)):
    """Available Metabase dashboard keys for the Analytics & Financial Insights tab."""
    return list_dashboard_keys()


@router.get("/embed/{dashboard_key}", response_model=MetabaseEmbedResponse)
def embed_url(
    dashboard_key: str,
    facility_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
):
    """
    Returns a signed Metabase iframe URL for the requested dashboard.

    Row-level security: the facility scope (current user's facility, or an
    explicit facility_id for admins) is passed as a Metabase dashboard
    parameter named `facility_id`, which should be wired to a SQL filter
    on the underlying questions.
    """
    facility_scope = facility_id if (facility_id and current_user.role == "admin") else current_user.facility_id

    params = {}
    if facility_scope is not None:
        params["facility_id"] = facility_scope

    try:
        iframe_url, expires_in = build_embed_url(dashboard_key, params=params)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown dashboard: {dashboard_key}")
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))

    return MetabaseEmbedResponse(dashboard_key=dashboard_key, iframe_url=iframe_url, expires_in=expires_in)


# ---------------------------------------------------------------------------
# Filter options (Facility / Receiver / Payer / Encounter type / Department)
# ---------------------------------------------------------------------------
@router.get("/filters")
def analytics_filter_options(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    facilities = [
        {"id": fac.id, "code": fac.facility_code, "name": fac.facility_name}
        for fac in db.query(Facility).filter(Facility.is_active.is_(True)).order_by(Facility.facility_name).all()
    ]

    receivers = (
        db.query(Claim.receiver_id, Claim.receiver_name)
        .filter(Claim.receiver_id.isnot(None))
        .distinct()
        .order_by(Claim.receiver_name)
        .all()
    )
    payers = (
        db.query(Claim.payer_id, Claim.payer_name)
        .filter(Claim.payer_id.isnot(None))
        .distinct()
        .order_by(Claim.payer_name)
        .all()
    )
    encounter_types = [
        row[0]
        for row in db.query(Claim.encounter_type)
        .filter(Claim.encounter_type.isnot(None))
        .distinct()
        .order_by(Claim.encounter_type)
        .all()
    ]
    departments = [
        row[0]
        for row in db.query(Claim.department)
        .filter(Claim.department.isnot(None))
        .distinct()
        .order_by(Claim.department)
        .all()
    ]

    return {
        "facilities": facilities,
        "receivers": [{"id": r, "name": n} for r, n in receivers],
        "payers": [{"id": p, "name": n} for p, n in payers],
        "encounter_types": encounter_types,
        "departments": departments,
    }


# ---------------------------------------------------------------------------
# Submissions
# ---------------------------------------------------------------------------
@router.get("/submissions")
def submissions_report(
    f: AnalyticsFilters = Depends(get_analytics_filters),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    claims_q = _apply_claim_filters(db.query(Claim), f)

    total_submitted_amount = _money(claims_q.with_entities(func.coalesce(func.sum(Claim.net_amount), 0)).scalar())
    total_submitted_claims = claims_q.count()

    remits_q = _remits_with_claims(db, f)
    total_paid_amount = _money(remits_q.with_entities(func.coalesce(func.sum(Remittance.paid_amount), 0)).scalar())
    rejected_amount = _money(remits_q.with_entities(func.coalesce(func.sum(Remittance.denial_amount), 0)).scalar())
    remitted_amount = total_paid_amount + rejected_amount
    not_remitted_amount = max(total_submitted_amount - remitted_amount, 0)

    claimed_rows = (
        claims_q.with_entities(
            func.to_char(Claim.submission_date, "YYYY-MM").label("month"),
            func.coalesce(func.sum(Claim.net_amount), 0).label("claimed"),
            func.count(Claim.id).label("claim_count"),
        )
        .group_by("month")
        .order_by("month")
        .all()
    )
    remit_rows = (
        remits_q.with_entities(
            func.to_char(Claim.submission_date, "YYYY-MM").label("month"),
            func.coalesce(func.sum(Remittance.paid_amount), 0).label("paid"),
            func.coalesce(func.sum(Remittance.denial_amount), 0).label("rejected"),
        )
        .group_by("month")
        .order_by("month")
        .all()
    )
    remit_by_month = {row.month: row for row in remit_rows}
    monthly_trend = []
    for row in claimed_rows:
        remit_row = remit_by_month.get(row.month)
        monthly_trend.append(
            {
                "month": row.month,
                "claimed_amount": _money(row.claimed),
                "claim_count": row.claim_count,
                "paid_amount": _money(remit_row.paid) if remit_row else 0,
                "rejected_amount": _money(remit_row.rejected) if remit_row else 0,
            }
        )

    clinician_rows = (
        claims_q.with_entities(
            Claim.clinician_name,
            Claim.department,
            func.coalesce(func.sum(Claim.net_amount), 0).label("claimed"),
        )
        .group_by(Claim.clinician_name, Claim.department)
        .order_by(func.sum(Claim.net_amount).desc())
        .limit(10)
        .all()
    )
    by_clinician = [
        {
            "clinician": row.clinician_name or "Unknown",
            "department": row.department or "Unknown",
            "claimed_amount": _money(row.claimed),
            "pct_of_total": round(_money(row.claimed) / total_submitted_amount * 100, 2) if total_submitted_amount else 0,
        }
        for row in clinician_rows
    ]

    activity_q = _apply_claim_filters(
        db.query(
            ClaimActivity.activity_code,
            ClaimActivity.activity_description,
            func.coalesce(func.sum(ClaimActivity.net), 0).label("claimed"),
        ).join(Claim, Claim.id == ClaimActivity.claim_id_fk),
        f,
    )
    activity_rows = (
        activity_q.group_by(ClaimActivity.activity_code, ClaimActivity.activity_description)
        .order_by(func.sum(ClaimActivity.net).desc())
        .limit(10)
        .all()
    )
    by_service = [
        {"code": row.activity_code, "description": row.activity_description, "claimed_amount": _money(row.claimed)}
        for row in activity_rows
    ]

    return {
        "kpis": {
            "total_submitted_amount": total_submitted_amount,
            "total_submitted_claims": total_submitted_claims,
            "total_paid_amount": total_paid_amount,
            "rejected_amount": rejected_amount,
            "remitted_amount": remitted_amount,
            "not_remitted_amount": not_remitted_amount,
        },
        "monthly_trend": monthly_trend,
        "by_clinician": by_clinician,
        "by_service": by_service,
    }


# ---------------------------------------------------------------------------
# Resubmissions
# ---------------------------------------------------------------------------
@router.get("/resubmissions")
def resubmissions_report(
    f: AnalyticsFilters = Depends(get_analytics_filters),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    claims_q = _apply_claim_filters(db.query(Claim), f)
    resubmitted_q = claims_q.filter(Claim.resubmission_count > 0)

    total_claims = claims_q.count()
    total_resubmitted_claims = resubmitted_q.count()
    total_resubmissions = resubmitted_q.with_entities(func.coalesce(func.sum(Claim.resubmission_count), 0)).scalar() or 0
    resubmitted_amount = _money(resubmitted_q.with_entities(func.coalesce(func.sum(Claim.net_amount), 0)).scalar())
    resubmission_rate = round(total_resubmitted_claims / total_claims * 100, 2) if total_claims else 0

    monthly_rows = (
        resubmitted_q.with_entities(
            func.to_char(Claim.submission_date, "YYYY-MM").label("month"),
            func.count(Claim.id).label("claim_count"),
            func.coalesce(func.sum(Claim.net_amount), 0).label("amount"),
        )
        .group_by("month")
        .order_by("month")
        .all()
    )
    monthly_trend = [{"month": r.month, "claim_count": r.claim_count, "amount": _money(r.amount)} for r in monthly_rows]

    payer_rows = (
        resubmitted_q.with_entities(
            Claim.payer_name,
            func.count(Claim.id).label("claim_count"),
            func.coalesce(func.sum(Claim.net_amount), 0).label("amount"),
        )
        .group_by(Claim.payer_name)
        .order_by(func.count(Claim.id).desc())
        .limit(10)
        .all()
    )
    by_payer = [{"payer": r.payer_name or "Unknown", "claim_count": r.claim_count, "amount": _money(r.amount)} for r in payer_rows]

    reason_q = _remits_with_claims(db, f).filter(Claim.resubmission_count > 0).filter(Remittance.denial_code.isnot(None))
    reason_rows = (
        reason_q.with_entities(
            Remittance.denial_code,
            Remittance.denial_description,
            func.count(Remittance.id).label("count"),
        )
        .group_by(Remittance.denial_code, Remittance.denial_description)
        .order_by(func.count(Remittance.id).desc())
        .limit(10)
        .all()
    )
    by_reason = [{"code": r.denial_code, "description": r.denial_description, "count": r.count} for r in reason_rows]

    return {
        "kpis": {
            "total_resubmitted_claims": total_resubmitted_claims,
            "total_resubmissions": int(total_resubmissions),
            "resubmitted_amount": resubmitted_amount,
            "resubmission_rate_pct": resubmission_rate,
        },
        "monthly_trend": monthly_trend,
        "by_payer": by_payer,
        "by_reason": by_reason,
    }


# ---------------------------------------------------------------------------
# Remittance
# ---------------------------------------------------------------------------
@router.get("/remittance")
def remittance_report(
    f: AnalyticsFilters = Depends(get_analytics_filters),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    remits_q = _remits_with_claims(db, f)

    total_paid = _money(remits_q.with_entities(func.coalesce(func.sum(Remittance.paid_amount), 0)).scalar())
    total_denied = _money(remits_q.with_entities(func.coalesce(func.sum(Remittance.denial_amount), 0)).scalar())
    total_discount = _money(remits_q.with_entities(func.coalesce(func.sum(Remittance.discount_amount), 0)).scalar())
    remitted_claims = remits_q.count()
    avg_turnaround = remits_q.with_entities(func.avg(Remittance.remittance_date - Claim.submission_date)).scalar()
    avg_turnaround_days = round(float(avg_turnaround), 1) if avg_turnaround is not None else 0

    monthly_rows = (
        remits_q.with_entities(
            func.to_char(Remittance.remittance_date, "YYYY-MM").label("month"),
            func.coalesce(func.sum(Remittance.paid_amount), 0).label("paid"),
            func.coalesce(func.sum(Remittance.denial_amount), 0).label("denied"),
            func.coalesce(func.sum(Remittance.discount_amount), 0).label("discount"),
        )
        .group_by("month")
        .order_by("month")
        .all()
    )
    monthly_trend = [
        {
            "month": r.month,
            "paid_amount": _money(r.paid),
            "denied_amount": _money(r.denied),
            "discount_amount": _money(r.discount),
        }
        for r in monthly_rows
    ]

    turnaround_expr = Remittance.remittance_date - Claim.submission_date
    aging_rows = remits_q.with_entities(turnaround_expr.label("days"), Remittance.paid_amount).all()
    buckets = {"0-15": 0.0, "16-30": 0.0, "31-45": 0.0, "46-60": 0.0, "60+": 0.0}
    for days, paid in aging_rows:
        amt = _money(paid)
        d = days or 0
        if d <= 15:
            buckets["0-15"] += amt
        elif d <= 30:
            buckets["16-30"] += amt
        elif d <= 45:
            buckets["31-45"] += amt
        elif d <= 60:
            buckets["46-60"] += amt
        else:
            buckets["60+"] += amt
    aging_buckets = [{"bucket": k, "amount": round(v, 2)} for k, v in buckets.items()]

    payer_rows = (
        remits_q.with_entities(
            Claim.payer_name,
            func.coalesce(func.sum(Remittance.paid_amount), 0).label("paid"),
            func.coalesce(func.sum(Remittance.denial_amount), 0).label("denied"),
        )
        .group_by(Claim.payer_name)
        .order_by(func.sum(Remittance.paid_amount).desc())
        .limit(10)
        .all()
    )
    by_payer = [{"payer": r.payer_name or "Unknown", "paid_amount": _money(r.paid), "denied_amount": _money(r.denied)} for r in payer_rows]

    return {
        "kpis": {
            "total_paid_amount": total_paid,
            "total_denied_amount": total_denied,
            "total_discount_amount": total_discount,
            "remitted_claims": remitted_claims,
            "avg_turnaround_days": avg_turnaround_days,
        },
        "monthly_trend": monthly_trend,
        "aging_buckets": aging_buckets,
        "by_payer": by_payer,
    }


# ---------------------------------------------------------------------------
# Denials
# ---------------------------------------------------------------------------
@router.get("/denials")
def denials_report(
    f: AnalyticsFilters = Depends(get_analytics_filters),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    remits_q = _remits_with_claims(db, f)
    denied_q = remits_q.filter(Remittance.denial_amount > 0)

    total_denial_amount = _money(denied_q.with_entities(func.coalesce(func.sum(Remittance.denial_amount), 0)).scalar())

    # Denial rate = distinct claims with any denial / total submitted claims
    # (counting remittance rows is wrong — one claim can have multiple remittance rows)
    denied_unique_claims = denied_q.with_entities(
        func.count(func.distinct(Claim.claim_id))
    ).scalar() or 0
    total_submitted_claims = _apply_claim_filters(db.query(Claim), f).count()
    denial_rate = round(denied_unique_claims / total_submitted_claims * 100, 2) if total_submitted_claims else 0

    monthly_rows = (
        denied_q.with_entities(
            func.to_char(Remittance.remittance_date, "YYYY-MM").label("month"),
            func.coalesce(func.sum(Remittance.denial_amount), 0).label("amount"),
            func.count(Remittance.id).label("count"),
        )
        .group_by("month")
        .order_by("month")
        .all()
    )
    monthly_trend = [{"month": r.month, "amount": _money(r.amount), "count": r.count} for r in monthly_rows]

    code_rows = (
        denied_q.with_entities(
            Remittance.denial_code,
            Remittance.denial_description,
            func.coalesce(func.sum(Remittance.denial_amount), 0).label("amount"),
            func.count(Remittance.id).label("count"),
        )
        .group_by(Remittance.denial_code, Remittance.denial_description)
        .order_by(func.sum(Remittance.denial_amount).desc())
        .limit(10)
        .all()
    )
    by_code = [
        {"code": r.denial_code, "description": r.denial_description, "amount": _money(r.amount), "count": r.count}
        for r in code_rows
    ]

    payer_rows = (
        denied_q.with_entities(
            Claim.payer_name,
            func.coalesce(func.sum(Remittance.denial_amount), 0).label("amount"),
        )
        .group_by(Claim.payer_name)
        .order_by(func.sum(Remittance.denial_amount).desc())
        .limit(10)
        .all()
    )
    by_payer = [{"payer": r.payer_name or "Unknown", "amount": _money(r.amount)} for r in payer_rows]

    clinician_rows = (
        denied_q.with_entities(
            Claim.clinician_name,
            func.coalesce(func.sum(Remittance.denial_amount), 0).label("amount"),
        )
        .group_by(Claim.clinician_name)
        .order_by(func.sum(Remittance.denial_amount).desc())
        .limit(10)
        .all()
    )
    by_clinician = [{"clinician": r.clinician_name or "Unknown", "amount": _money(r.amount)} for r in clinician_rows]

    return {
        "kpis": {
            "total_denial_amount": total_denial_amount,
            "denied_claims": denied_unique_claims,
            "denial_rate_pct": denial_rate,
        },
        "monthly_trend": monthly_trend,
        "by_code": by_code,
        "by_payer": by_payer,
        "by_clinician": by_clinician,
    }


# ---------------------------------------------------------------------------
# Clinicians
# ---------------------------------------------------------------------------
@router.get("/clinicians")
def clinicians_report(
    f: AnalyticsFilters = Depends(get_analytics_filters),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    claims_q = _apply_claim_filters(db.query(Claim), f)
    total_claimed = _money(claims_q.with_entities(func.coalesce(func.sum(Claim.net_amount), 0)).scalar())

    claim_rows = (
        claims_q.with_entities(
            Claim.clinician_name,
            Claim.department,
            func.coalesce(func.sum(Claim.net_amount), 0).label("claimed"),
            func.count(Claim.id).label("claim_count"),
        )
        .group_by(Claim.clinician_name, Claim.department)
        .all()
    )

    remits_q = _remits_with_claims(db, f)
    remit_rows = (
        remits_q.with_entities(
            Claim.clinician_name,
            func.coalesce(func.sum(Remittance.paid_amount), 0).label("paid"),
            func.coalesce(func.sum(Remittance.denial_amount), 0).label("denied"),
        )
        .group_by(Claim.clinician_name)
        .all()
    )
    remit_by_clinician = {r.clinician_name: r for r in remit_rows}

    rows = []
    for r in claim_rows:
        remit = remit_by_clinician.get(r.clinician_name)
        claimed = _money(r.claimed)
        rows.append(
            {
                "clinician": r.clinician_name or "Unknown",
                "department": r.department or "Unknown",
                "claimed_amount": claimed,
                "paid_amount": _money(remit.paid) if remit else 0,
                "denied_amount": _money(remit.denied) if remit else 0,
                "claim_count": r.claim_count,
                "pct_of_total": round(claimed / total_claimed * 100, 2) if total_claimed else 0,
            }
        )
    rows.sort(key=lambda x: x["claimed_amount"], reverse=True)

    return {"kpis": {"total_claimed_amount": total_claimed, "clinician_count": len(rows)}, "clinicians": rows[:25]}


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------
@router.get("/operations")
def operations_report(
    f: AnalyticsFilters = Depends(get_analytics_filters),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    claims_q = _apply_claim_filters(db.query(Claim), f)
    total_claims = claims_q.count()

    encounter_rows = (
        claims_q.with_entities(
            Claim.encounter_type,
            func.count(Claim.id).label("claim_count"),
            func.coalesce(func.sum(Claim.net_amount), 0).label("amount"),
        )
        .group_by(Claim.encounter_type)
        .order_by(func.count(Claim.id).desc())
        .all()
    )
    by_encounter_type = [
        {"encounter_type": r.encounter_type or "Unknown", "claim_count": r.claim_count, "amount": _money(r.amount)}
        for r in encounter_rows
    ]

    status_rows = claims_q.with_entities(Claim.claim_status, func.count(Claim.id).label("count")).group_by(Claim.claim_status).all()
    by_status = [{"status": r.claim_status, "count": r.count} for r in status_rows]

    remits_q = _remits_with_claims(db, f)
    avg_turnaround = remits_q.with_entities(func.avg(Remittance.remittance_date - Claim.submission_date)).scalar()
    avg_turnaround_days = round(float(avg_turnaround), 1) if avg_turnaround is not None else 0

    monthly_rows = (
        claims_q.with_entities(
            func.to_char(Claim.submission_date, "YYYY-MM").label("month"),
            func.count(Claim.id).label("claim_count"),
        )
        .group_by("month")
        .order_by("month")
        .all()
    )
    monthly_trend = [{"month": r.month, "claim_count": r.claim_count} for r in monthly_rows]

    return {
        "kpis": {"total_claims": total_claims, "avg_turnaround_days": avg_turnaround_days},
        "by_encounter_type": by_encounter_type,
        "by_status": by_status,
        "monthly_trend": monthly_trend,
    }


# ---------------------------------------------------------------------------
# Insurance (Payer / Receiver breakdown)
# ---------------------------------------------------------------------------
@router.get("/insurance")
def insurance_report(
    f: AnalyticsFilters = Depends(get_analytics_filters),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    claims_q = _apply_claim_filters(db.query(Claim), f)
    total_claimed = _money(claims_q.with_entities(func.coalesce(func.sum(Claim.net_amount), 0)).scalar())

    payer_rows = (
        claims_q.with_entities(
            Claim.payer_name,
            func.coalesce(func.sum(Claim.net_amount), 0).label("claimed"),
            func.count(Claim.id).label("claim_count"),
        )
        .group_by(Claim.payer_name)
        .all()
    )

    remits_q = _remits_with_claims(db, f)
    remit_rows = (
        remits_q.with_entities(
            Claim.payer_name,
            func.coalesce(func.sum(Remittance.paid_amount), 0).label("paid"),
            func.coalesce(func.sum(Remittance.denial_amount), 0).label("denied"),
        )
        .group_by(Claim.payer_name)
        .all()
    )
    remit_by_payer = {r.payer_name: r for r in remit_rows}

    by_payer = []
    for r in payer_rows:
        claimed = _money(r.claimed)
        remit = remit_by_payer.get(r.payer_name)
        by_payer.append(
            {
                "payer": r.payer_name or "Unknown",
                "claimed_amount": claimed,
                "paid_amount": _money(remit.paid) if remit else 0,
                "denied_amount": _money(remit.denied) if remit else 0,
                "claim_count": r.claim_count,
                "pct_of_total": round(claimed / total_claimed * 100, 2) if total_claimed else 0,
            }
        )
    by_payer.sort(key=lambda x: x["claimed_amount"], reverse=True)

    receiver_rows = (
        claims_q.with_entities(
            Claim.receiver_name,
            func.coalesce(func.sum(Claim.net_amount), 0).label("claimed"),
            func.count(Claim.id).label("claim_count"),
        )
        .group_by(Claim.receiver_name)
        .order_by(func.sum(Claim.net_amount).desc())
        .all()
    )
    by_receiver = [
        {"receiver": r.receiver_name or "Unknown", "claimed_amount": _money(r.claimed), "claim_count": r.claim_count}
        for r in receiver_rows
    ]

    return {"kpis": {"total_claimed_amount": total_claimed}, "by_payer": by_payer, "by_receiver": by_receiver}


# ---------------------------------------------------------------------------
# Department
# ---------------------------------------------------------------------------
@router.get("/department")
def department_report(
    f: AnalyticsFilters = Depends(get_analytics_filters),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    claims_q = _apply_claim_filters(db.query(Claim), f)
    total_claimed = _money(claims_q.with_entities(func.coalesce(func.sum(Claim.net_amount), 0)).scalar())

    dept_rows = (
        claims_q.with_entities(
            Claim.department,
            func.coalesce(func.sum(Claim.net_amount), 0).label("claimed"),
            func.count(Claim.id).label("claim_count"),
        )
        .group_by(Claim.department)
        .all()
    )

    remits_q = _remits_with_claims(db, f)
    remit_rows = (
        remits_q.with_entities(
            Claim.department,
            func.coalesce(func.sum(Remittance.paid_amount), 0).label("paid"),
            func.coalesce(func.sum(Remittance.denial_amount), 0).label("denied"),
        )
        .group_by(Claim.department)
        .all()
    )
    remit_by_dept = {r.department: r for r in remit_rows}

    by_department = []
    for r in dept_rows:
        claimed = _money(r.claimed)
        remit = remit_by_dept.get(r.department)
        by_department.append(
            {
                "department": r.department or "Unknown",
                "claimed_amount": claimed,
                "paid_amount": _money(remit.paid) if remit else 0,
                "denied_amount": _money(remit.denied) if remit else 0,
                "claim_count": r.claim_count,
                "pct_of_total": round(claimed / total_claimed * 100, 2) if total_claimed else 0,
            }
        )
    by_department.sort(key=lambda x: x["claimed_amount"], reverse=True)

    monthly_rows = (
        claims_q.with_entities(
            func.to_char(Claim.submission_date, "YYYY-MM").label("month"),
            Claim.department,
            func.coalesce(func.sum(Claim.net_amount), 0).label("claimed"),
        )
        .group_by("month", Claim.department)
        .order_by("month")
        .all()
    )
    monthly_trend = [
        {"month": r.month, "department": r.department or "Unknown", "claimed_amount": _money(r.claimed)} for r in monthly_rows
    ]

    return {"kpis": {"total_claimed_amount": total_claimed}, "by_department": by_department, "monthly_trend": monthly_trend}
