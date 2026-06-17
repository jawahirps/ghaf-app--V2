"""
Ghaf App — demo/sample data generator for local development.

Populates a second demo facility plus ~2 years of realistic-looking claims,
claim activities, and remittances (with denials and resubmissions) so the
Analytics & Financial Insights dashboards have something to render.

Run with:

    python -m app.seed_demo_data

Safe to re-run: if a facility already has claims, that facility is skipped.
"""
import logging
import random
from datetime import date, timedelta
from decimal import Decimal

from .database import SessionLocal
from .models import Claim, ClaimActivity, Facility, Remittance

log = logging.getLogger(__name__)

random.seed(42)

# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------
RECEIVERS = [
    ("RV001", "Neuron"),
    ("RV002", "NAS Administration Services"),
    ("RV003", "Nextcare"),
    ("RV004", "ProVantage Health"),
]

PAYERS = [
    ("INS001", "Daman - Thiqa"),
    ("INS002", "Daman - Enhanced"),
    ("INS003", "AXA Gulf"),
    ("INS004", "Oman Insurance (Sukoon)"),
    ("INS005", "Cigna"),
    ("INS006", "MetLife"),
    ("INS007", "Self-Pay"),
]

CLINICIANS = [
    ("DR-1001", "Roofina Thazhathe Peedika", "FAMILY/GENERAL PRACTICE"),
    ("DR-1002", "Murtuza Abbas", "INTERNAL MEDICINE"),
    ("DR-1003", "Ekramulla Mohamed Ali", "FAMILY/GENERAL PRACTICE"),
    ("DR-1004", "Shakir Mohammad", "INTERNAL MEDICINE"),
    ("DR-1005", "Preetha Madhu", "PEDIATRICS"),
    ("DR-1006", "Noureen Nagiub Ghanem Metwalli Ahmed", "OBSTETRICS & GYNECOLOGY"),
    ("DR-1007", "Abish Brinda Lessly", "DERMATOLOGY"),
    ("DR-1008", "Abdul Gafoor Parakkal", "DENTAL"),
    ("DR-1009", "Fathima Amrin", "PEDIATRICS"),
    ("DR-1010", "Suji Shajahan", "FAMILY/GENERAL PRACTICE"),
]

ENCOUNTER_TYPES = ["Outpatient", "Inpatient", "Emergency", "Day Case"]

SERVICE_CODES = [
    ("9", "Consultation GP", "CPT"),
    ("10", "Consultation Specialist", "CPT"),
    ("82.09", "Home Nursing Visit", "HCPCS"),
    ("12", "Generic Code Follow-up", "CPT"),
    ("80061", "Lipid Panel", "CPT"),
    ("96374", "Therapeutic/Prophylactic Injection", "CPT"),
    ("85025", "Complete Blood Count", "CPT"),
    ("80047", "Metabolic Panel", "CPT"),
]

DENIAL_CODES = [
    ("DN01", "Not a covered benefit"),
    ("DN02", "Prior authorization required"),
    ("DN03", "Duplicate claim"),
    ("DN04", "Service not matching diagnosis"),
    ("DN05", "Patient not eligible on date of service"),
    ("DN06", "Documentation insufficient"),
]

DEMO_FACILITIES = [
    dict(
        facility_code="GHAF-001",
        facility_name="Ghaf App Demo Clinic",
        license_id="DHA-LIC-0001",
        eclaimlink_username="demo_user",
        credential_key="demo_credential",
        dhpo_provider_id="PR0001",
    ),
    dict(
        facility_code="GHAF-002",
        facility_name="Ghaf App Demo Hospital",
        license_id="DHA-LIC-0002",
        eclaimlink_username="demo_user_2",
        credential_key="demo_credential_2",
        dhpo_provider_id="PR0002",
    ),
]

START_MONTH = date(2023, 1, 1)
END_MONTH = date(2024, 12, 1)  # inclusive


def month_range(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)


def random_day_in_month(month_start: date) -> date:
    if month_start.month == 12:
        next_month = date(month_start.year + 1, 1, 1)
    else:
        next_month = date(month_start.year, month_start.month + 1, 1)
    days_in_month = (next_month - month_start).days
    return month_start + timedelta(days=random.randint(0, days_in_month - 1))


def build_claim_and_children(facility: Facility, seq: int, month_start: date):
    clinician_id, clinician_name, department = random.choice(CLINICIANS)
    payer_id, payer_name = random.choice(PAYERS)
    receiver_id, receiver_name = random.choice(RECEIVERS)
    encounter_type = random.choice(ENCOUNTER_TYPES)

    encounter_start = random_day_in_month(month_start)
    submission_date = encounter_start + timedelta(days=random.randint(1, 5))

    gross_amount = Decimal(random.randint(150, 3000))
    patient_share = (gross_amount * Decimal(random.choice(["0.00", "0.05", "0.10", "0.20"]))).quantize(Decimal("0.01"))
    net_amount = (gross_amount - patient_share).quantize(Decimal("0.01"))

    claim_id = f"{facility.facility_code}-{month_start.year}{month_start.month:02d}-{seq:05d}"
    encounter_id = f"ENC-{claim_id}"

    outcome_roll = random.random()
    resubmission_count = 0

    claim = Claim(
        facility_id=facility.id,
        source_channel="EXCEL_HISTORICAL",
        claim_id=claim_id,
        claim_id_payer=claim_id,
        encounter_id=encounter_id,
        encounter_type=encounter_type,
        encounter_start=encounter_start,
        member_id=f"MBR{facility.id}{seq:06d}",
        emirates_id=f"784-{1980 + (seq % 30)}-{seq:07d}-{seq % 10}",
        payer_id=payer_id,
        payer_name=payer_name,
        clinician_id=clinician_id,
        clinician_name=clinician_name,
        department=department,
        receiver_id=receiver_id,
        receiver_name=receiver_name,
        gross_amount=gross_amount,
        net_amount=net_amount,
        patient_share_total=patient_share,
        submission_date=submission_date,
        claim_status="submitted",
        resubmission_count=0,
    )

    activity_code, activity_desc, activity_type = random.choice(SERVICE_CODES)
    activity = ClaimActivity(
        facility_id=facility.id,
        activity_id=f"ACT-{claim_id}",
        activity_type=activity_type,
        activity_code=activity_code,
        activity_description=activity_desc,
        quantity=Decimal("1"),
        gross=gross_amount,
        net=net_amount,
        patient_share=patient_share,
        activity_start=encounter_start,
        clinician_id=clinician_id,
        sequence_no=1,
    )

    remittance = None
    if outcome_roll < 0.15:
        # Not yet remitted
        claim.claim_status = "submitted"
    else:
        remittance_date = submission_date + timedelta(days=random.randint(15, 45))
        if outcome_roll < 0.27:
            # Fully denied
            claim.claim_status = "denied"
            denial_code, denial_desc = random.choice(DENIAL_CODES)
            if random.random() < 0.35:
                resubmission_count = random.choice([1, 2])
            remittance = Remittance(
                facility_id=facility.id,
                source_channel="EXCEL_HISTORICAL",
                claim_id=claim_id,
                claim_id_payer=claim_id,
                payer_id=payer_id,
                remittance_date=remittance_date,
                gross_amount=gross_amount,
                net_amount=net_amount,
                paid_amount=Decimal("0.00"),
                patient_share_total=patient_share,
                discount_amount=Decimal("0.00"),
                denial_amount=net_amount,
                claim_status_ra="DENIED",
                denial_code=denial_code,
                denial_description=denial_desc,
            )
        elif outcome_roll < 0.45:
            # Partially denied
            claim.claim_status = "remitted_partial"
            paid_pct = Decimal(str(round(random.uniform(0.55, 0.9), 2)))
            paid_amount = (net_amount * paid_pct).quantize(Decimal("0.01"))
            denial_amount = (net_amount - paid_amount).quantize(Decimal("0.01"))
            denial_code, denial_desc = random.choice(DENIAL_CODES)
            if random.random() < 0.25:
                resubmission_count = 1
            remittance = Remittance(
                facility_id=facility.id,
                source_channel="EXCEL_HISTORICAL",
                claim_id=claim_id,
                claim_id_payer=claim_id,
                payer_id=payer_id,
                remittance_date=remittance_date,
                gross_amount=gross_amount,
                net_amount=net_amount,
                paid_amount=paid_amount,
                patient_share_total=patient_share,
                discount_amount=Decimal("0.00"),
                denial_amount=denial_amount,
                claim_status_ra="PARTIAL",
                denial_code=denial_code,
                denial_description=denial_desc,
            )
        else:
            # Fully paid
            claim.claim_status = "remitted_full"
            discount = (net_amount * Decimal("0.02")).quantize(Decimal("0.01")) if random.random() < 0.2 else Decimal("0.00")
            paid_amount = (net_amount - discount).quantize(Decimal("0.01"))
            remittance = Remittance(
                facility_id=facility.id,
                source_channel="EXCEL_HISTORICAL",
                claim_id=claim_id,
                claim_id_payer=claim_id,
                payer_id=payer_id,
                remittance_date=remittance_date,
                gross_amount=gross_amount,
                net_amount=net_amount,
                paid_amount=paid_amount,
                patient_share_total=patient_share,
                discount_amount=discount,
                denial_amount=Decimal("0.00"),
                claim_status_ra="FULL",
            )

    claim.resubmission_count = resubmission_count
    return claim, activity, remittance


def run_seed_demo() -> None:
    db = SessionLocal()
    try:
        for fdata in DEMO_FACILITIES:
            facility = db.query(Facility).filter(Facility.facility_code == fdata["facility_code"]).first()
            if facility is None:
                facility = Facility(is_active=True, **fdata)
                db.add(facility)
                db.commit()
                db.refresh(facility)
                log.info("Created demo facility %s", facility.facility_code)

            existing_claims = db.query(Claim).filter(Claim.facility_id == facility.id).count()
            if existing_claims > 0:
                log.info("Facility %s already has %d claims — skipping.", facility.facility_code, existing_claims)
                continue

            seq = 1
            batch = []
            for month_start in month_range(START_MONTH, END_MONTH):
                claims_this_month = random.randint(20, 45)
                for _ in range(claims_this_month):
                    claim, activity, remittance = build_claim_and_children(facility, seq, month_start)
                    seq += 1
                    batch.append((claim, activity, remittance))

            log.info("Generating %d demo claims for %s ...", len(batch), facility.facility_code)
            for claim, activity, remittance in batch:
                db.add(claim)
            db.flush()

            for claim, activity, remittance in batch:
                activity.claim_id_fk = claim.id
                db.add(activity)
                if remittance is not None:
                    db.add(remittance)

            db.commit()
            log.info("Seeded %d demo claims for %s.", len(batch), facility.facility_code)
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_seed_demo()
