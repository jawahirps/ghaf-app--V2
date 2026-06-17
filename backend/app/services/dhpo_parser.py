"""
Ghaf App — DHA/DHPO XML Parser Engine
Handles: Memory-optimized streaming parse of ClaimSubmission and
RemittanceAdvice XML payloads (DHA Shafafiya / eClaimLink format) that have
been staged into `raw_xml_store` by the upload endpoint or an external
eClaimLink fetch job.

This is invoked by the "Trigger DHA XML Sync" action in the React app
(POST /api/dha-sync/trigger), which calls `run_pending(...)` below.
"""
from __future__ import annotations

import logging
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Optional

from lxml import etree
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..models import RawXmlStore, Claim, ClaimDiagnosis, ClaimActivity, ClaimObservation, Remittance, FetchLog

log = logging.getLogger(__name__)


class SyncRunSummary:
    def __init__(self) -> None:
        self.pending_records = 0
        self.parsed_records = 0
        self.quarantined_records = 0
        self.records_parsed_total = 0  # individual claims/remits across all files


class DHPOXmlParser:
    """Parses staged raw XML payloads into normalized claim/remittance rows."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Entry point used by the DHA Sync trigger endpoint
    # ------------------------------------------------------------------
    def run_pending(self, facility_id: Optional[int] = None) -> SyncRunSummary:
        summary = SyncRunSummary()

        stmt = select(RawXmlStore).where(RawXmlStore.parse_status == "pending")
        if facility_id is not None:
            stmt = stmt.where(RawXmlStore.facility_id == facility_id)
        stmt = stmt.order_by(RawXmlStore.id.asc())

        records = self.db.scalars(stmt).all()
        summary.pending_records = len(records)

        if not records:
            log.info("No pending XML records found in raw store.")
            return summary

        log.info("Found %d pending XML records to parse.", len(records))

        for record in records:
            try:
                record.parsed_at = datetime.utcnow()

                if record.xml_type == "ClaimSubmission":
                    parsed_count = self._process_claims_submission(record)
                elif record.xml_type == "RemittanceAdvice":
                    parsed_count = self._process_remittance_advice(record)
                else:
                    raise ValueError(f"Unknown XML type: {record.xml_type}")

                record.parse_status = "parsed"
                record.records_parsed = parsed_count
                self.db.commit()

                summary.parsed_records += 1
                summary.records_parsed_total += parsed_count
                log.info(
                    "Successfully processed raw_xml_id=%s (%s). Records: %d",
                    record.id, record.xml_type, parsed_count,
                )

            except Exception as e:
                self.db.rollback()
                log.error("Failed parsing raw_xml_id=%s. Sent to quarantine. Error: %s", record.id, e, exc_info=True)
                record.parse_status = "quarantined"
                record.parse_error = str(e)
                self.db.commit()
                summary.quarantined_records += 1

        return summary

    # ------------------------------------------------------------------
    # ClaimSubmission
    # ------------------------------------------------------------------
    def _process_claims_submission(self, record: RawXmlStore) -> int:
        """Parses ClaimSubmission hierarchical trees without memory explosions."""
        context = etree.iterparse(BytesIO(record.xml_content.encode("utf-8")), events=("end",), tag="Claim")
        claim_count = 0

        for _event, elem in context:
            claim_id = elem.findtext("ID")
            encounter_id = elem.findtext("Encounter/ID")

            if not claim_id or not encounter_id:
                elem.clear()
                continue

            db_claim = Claim(
                facility_id=record.facility_id,
                raw_xml_id=record.id,
                source_channel="API",
                claim_id=claim_id,
                encounter_id=encounter_id,
                encounter_type=elem.findtext("Encounter/Type"),
                encounter_start=self._parse_dt(elem.findtext("Encounter/Start")),
                encounter_end=self._parse_optional_dt(elem.findtext("Encounter/End")),
                member_id=elem.findtext("Patient/MemberID") or elem.findtext("MemberID") or "UNKNOWN",
                emirates_id=elem.findtext("Patient/EmiratesID") or elem.findtext("EmiratesIDNumber"),
                payer_id=elem.findtext("PayerID") or "UNKNOWN",
                clinician_id=elem.findtext("ClinicianID") or "UNKNOWN",
                gross_amount=self._parse_decimal(elem.findtext("Gross")),
                net_amount=self._parse_decimal(elem.findtext("Net")),
                patient_share_total=self._parse_decimal(elem.findtext("PatientShare")),
                submission_date=record.submission_date or datetime.utcnow().date(),
                claim_status="submitted",
            )

            # 1. Nested Diagnoses
            for seq, diag in enumerate(elem.findall("Diagnosis"), start=1):
                db_claim.diagnoses.append(
                    ClaimDiagnosis(
                        facility_id=record.facility_id,
                        diagnosis_type=diag.findtext("Type") or "Primary",
                        diagnosis_code=diag.findtext("Code") or "UNKNOWN",
                        diagnosis_description=diag.findtext("Description"),
                        sequence_no=seq,
                    )
                )

            # 2. Nested Activities (+ sub-nested Observations)
            for seq, act in enumerate(elem.findall("Activity"), start=1):
                db_act = ClaimActivity(
                    facility_id=record.facility_id,
                    activity_id=act.findtext("ID"),
                    activity_type=act.findtext("Type") or "Service",
                    activity_code=act.findtext("Code") or "UNKNOWN",
                    activity_description=act.findtext("Description"),
                    non_std_code=act.findtext("NonStandardCode"),
                    quantity=self._parse_decimal(act.findtext("Quantity"), default="1.0"),
                    gross=self._parse_decimal(act.findtext("Gross")),
                    net=self._parse_decimal(act.findtext("Net")),
                    patient_share=self._parse_decimal(act.findtext("PatientShare")),
                    activity_start=self._parse_dt(act.findtext("Start")).date(),
                    authorization_id=act.findtext("PriorAuthorizationID"),
                    clinician_id=act.findtext("Clinician"),
                    sequence_no=seq,
                )

                for obs in act.findall("Observation"):
                    db_act.observations.append(
                        ClaimObservation(
                            observation_type=obs.findtext("Type") or "Other",
                            observation_code=obs.findtext("Code"),
                            observation_value=obs.findtext("Value"),
                            value_type=obs.findtext("ValueType"),
                        )
                    )
                db_claim.activities.append(db_act)

            # Upsert: avoid duplicates if the same XML is re-synced
            existing = self.db.scalar(
                select(Claim).where(
                    Claim.facility_id == record.facility_id,
                    Claim.claim_id == claim_id,
                )
            )
            if existing:
                self.db.delete(existing)
                self.db.flush()

            self.db.add(db_claim)
            claim_count += 1

            elem.clear()
            while elem.getprevious() is not None:
                del elem.getparent()[0]

        self.db.flush()
        return claim_count

    # ------------------------------------------------------------------
    # RemittanceAdvice
    # ------------------------------------------------------------------
    def _process_remittance_advice(self, record: RawXmlStore) -> int:
        """Parses RemittanceAdvice payment elements and links them to baseline claims."""
        context = etree.iterparse(BytesIO(record.xml_content.encode("utf-8")), events=("end",), tag="Claim")
        remit_count = 0

        for _event, elem in context:
            claim_id = elem.findtext("ID")
            if not claim_id:
                elem.clear()
                continue

            remittance_date = record.submission_date or datetime.utcnow().date()

            db_remit = Remittance(
                facility_id=record.facility_id,
                raw_xml_id=record.id,
                source_channel="API",
                claim_id=claim_id,
                payer_id=elem.findtext("PayerID") or "UNKNOWN",
                remittance_date=remittance_date,
                ra_file_id=elem.findtext("IDPayer"),
                gross_amount=self._parse_decimal(elem.findtext("Gross"), allow_none=True),
                net_amount=self._parse_decimal(elem.findtext("Net"), allow_none=True),
                paid_amount=self._parse_decimal(elem.findtext("PaymentAmount") or elem.findtext("Payment/Amount")),
                patient_share_total=self._parse_decimal(elem.findtext("PatientShare")),
                discount_amount=self._parse_decimal(elem.findtext("Discount")),
                denial_amount=self._parse_decimal(elem.findtext("DenialAmount") or elem.findtext("Denial/Amount")),
                denial_code=elem.findtext("DenialCode") or elem.findtext("Denial/Code"),
                denial_description=elem.findtext("DenialDescription") or elem.findtext("Denial/Description"),
                claim_status_ra=elem.findtext("Status") or elem.findtext("ResubmissionType"),
            )

            existing = self.db.scalar(
                select(Remittance).where(
                    Remittance.facility_id == record.facility_id,
                    Remittance.claim_id == claim_id,
                    Remittance.remittance_date == remittance_date,
                )
            )
            if existing:
                self.db.delete(existing)
                self.db.flush()

            self.db.add(db_remit)
            remit_count += 1

            elem.clear()
            while elem.getprevious() is not None:
                del elem.getparent()[0]

        self.db.flush()
        return remit_count

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_dt(dt_str: Optional[str]) -> datetime:
        if not dt_str:
            return datetime.utcnow()
        for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y"):
            try:
                return datetime.strptime(dt_str, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(dt_str)
        except ValueError:
            return datetime.utcnow()

    @classmethod
    def _parse_optional_dt(cls, dt_str: Optional[str]) -> Optional[datetime]:
        if not dt_str:
            return None
        return cls._parse_dt(dt_str)

    @staticmethod
    def _parse_decimal(value: Optional[str], default: str = "0.00", allow_none: bool = False) -> Optional[Decimal]:
        if value is None or value == "":
            return None if allow_none else Decimal(default)
        try:
            return Decimal(value)
        except InvalidOperation:
            return None if allow_none else Decimal(default)
