"""
Ghaf App — passkey (WebAuthn / FIDO2) registration and sign-in.

Flow (both ceremonies are two steps):
  1. POST .../options  -> server creates a single-use challenge, returns
     WebAuthn options JSON + a challenge_id.
  2. Browser runs navigator.credentials.create()/get() with those options.
  3. POST .../verify   -> client sends challenge_id + the credential JSON;
     server verifies the signature against the stored challenge.

Registration requires an existing session (the user is signed in with their
password). Sign-in is usernameless: the browser offers the user's discoverable
passkeys for this site and the credential ID identifies the account.
"""
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, parse_authentication_credential_json
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidRegistrationResponse
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from ..config import get_settings
from ..database import get_db
from ..models import LoginLog, PasskeyCredential, User, WebAuthnChallenge
from ..schemas import (
    PasskeyLoginVerify,
    PasskeyOptionsOut,
    PasskeyOut,
    PasskeyRegisterVerify,
    PasskeyRename,
    Token,
    UserOut,
)
from ..security import create_access_token, get_current_user

settings = get_settings()
router = APIRouter(prefix="/api/auth/passkeys", tags=["passkeys"])

MAX_PASSKEYS_PER_USER = 10


# ---------------------------------------------------------------------------
# Challenge helpers
# ---------------------------------------------------------------------------
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    # SQLite returns naive datetimes; treat them as UTC.
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _store_challenge(db: Session, challenge: bytes, purpose: str, user_id: Optional[int]) -> str:
    now = _utcnow()
    # Opportunistic cleanup so the table never grows unbounded.
    db.query(WebAuthnChallenge).filter(WebAuthnChallenge.expires_at < now).delete(synchronize_session=False)
    challenge_id = secrets.token_urlsafe(32)
    db.add(
        WebAuthnChallenge(
            id=challenge_id,
            challenge=challenge,
            purpose=purpose,
            user_id=user_id,
            expires_at=now + timedelta(seconds=settings.WEBAUTHN_CHALLENGE_TTL_SECONDS),
        )
    )
    db.commit()
    return challenge_id


def _consume_challenge(db: Session, challenge_id: str, purpose: str, user_id: Optional[int]) -> bytes:
    """Fetch and delete a challenge (single use). Raises 400 if missing/expired/mismatched.

    Atomic under concurrency: only the request whose DELETE actually removes the
    row may use it. A concurrent request with the same challenge_id blocks on the
    row lock (Postgres) or the write lock (SQLite), then deletes 0 rows and is
    rejected.
    """
    row = db.get(WebAuthnChallenge, challenge_id)
    deleted = 0
    if row is not None:
        challenge, row_purpose, row_user_id, expires_at = row.challenge, row.purpose, row.user_id, row.expires_at
        deleted = (
            db.query(WebAuthnChallenge)
            .filter(WebAuthnChallenge.id == challenge_id)
            .delete(synchronize_session=False)
        )
        db.commit()
    if (
        deleted != 1
        or row_purpose != purpose
        or row_user_id != user_id
        or _as_utc(expires_at) < _utcnow()
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Passkey request expired. Please try again.")
    return challenge


def _transports(raw: Optional[list]) -> Optional[List[AuthenticatorTransport]]:
    if not raw:
        return None
    out = []
    for t in raw:
        try:
            out.append(AuthenticatorTransport(t))
        except ValueError:
            continue
    return out or None


# ---------------------------------------------------------------------------
# Registration (signed-in user adds a passkey)
# ---------------------------------------------------------------------------
@router.post("/register/options", response_model=PasskeyOptionsOut)
def registration_options(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if len(user.passkeys) >= MAX_PASSKEYS_PER_USER:
        raise HTTPException(status_code=400, detail=f"You can register at most {MAX_PASSKEYS_PER_USER} passkeys.")

    options = generate_registration_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        rp_name=settings.WEBAUTHN_RP_NAME,
        user_id=str(user.id).encode(),
        user_name=user.email,
        user_display_name=user.full_name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        # Stop the same authenticator being registered twice.
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=pk.credential_id, transports=_transports(pk.transports))
            for pk in user.passkeys
        ],
    )
    challenge_id = _store_challenge(db, options.challenge, "register", user.id)
    return PasskeyOptionsOut(challenge_id=challenge_id, options=options_to_json(options))


@router.post("/register/verify", response_model=PasskeyOut, status_code=status.HTTP_201_CREATED)
def registration_verify(
    payload: PasskeyRegisterVerify,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    expected_challenge = _consume_challenge(db, payload.challenge_id, "register", user.id)
    try:
        verified = verify_registration_response(
            credential=payload.credential,
            expected_challenge=expected_challenge,
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.webauthn_origins_list,
            require_user_verification=True,
        )
    except InvalidRegistrationResponse as exc:
        raise HTTPException(status_code=400, detail=f"Passkey could not be verified: {exc}")

    if db.query(PasskeyCredential).filter(PasskeyCredential.credential_id == verified.credential_id).first():
        raise HTTPException(status_code=409, detail="This passkey is already registered.")

    transports = (payload.credential.get("response") or {}).get("transports")
    passkey = PasskeyCredential(
        user_id=user.id,
        credential_id=verified.credential_id,
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        name=(payload.name or "").strip()[:100] or "Passkey",
        transports=transports if isinstance(transports, list) else None,
        backed_up=verified.credential_backed_up,
    )
    db.add(passkey)
    db.commit()
    db.refresh(passkey)
    return passkey


# ---------------------------------------------------------------------------
# Management
# ---------------------------------------------------------------------------
@router.get("", response_model=List[PasskeyOut])
def list_passkeys(user: User = Depends(get_current_user)):
    return sorted(user.passkeys, key=lambda p: p.id)


@router.patch("/{passkey_id}", response_model=PasskeyOut)
def rename_passkey(
    passkey_id: int,
    payload: PasskeyRename,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    pk = db.get(PasskeyCredential, passkey_id)
    if pk is None or pk.user_id != user.id:
        raise HTTPException(status_code=404, detail="Passkey not found")
    pk.name = payload.name.strip()[:100] or pk.name
    db.commit()
    db.refresh(pk)
    return pk


@router.delete("/{passkey_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_passkey(
    passkey_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    pk = db.get(PasskeyCredential, passkey_id)
    if pk is None or pk.user_id != user.id:
        raise HTTPException(status_code=404, detail="Passkey not found")
    db.delete(pk)
    db.commit()


# ---------------------------------------------------------------------------
# Sign-in (usernameless)
# ---------------------------------------------------------------------------
@router.post("/login/options", response_model=PasskeyOptionsOut)
def login_options(db: Session = Depends(get_db)):
    options = generate_authentication_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    challenge_id = _store_challenge(db, options.challenge, "login", None)
    return PasskeyOptionsOut(challenge_id=challenge_id, options=options_to_json(options))


@router.post("/login/verify", response_model=Token)
def login_verify(payload: PasskeyLoginVerify, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    def fail(reason: str, user: Optional[User], code: int, detail: str):
        db.add(
            LoginLog(
                user_id=user.id if user else None,
                email_attempted=user.email if user else "(passkey)",
                success=False,
                failure_reason=reason,
                ip_address=ip,
                user_agent=user_agent,
            )
        )
        db.commit()
        raise HTTPException(status_code=code, detail=detail)

    expected_challenge = _consume_challenge(db, payload.challenge_id, "login", None)

    try:
        parsed = parse_authentication_credential_json(payload.credential)
    except Exception:
        fail("passkey_malformed", None, 400, "Invalid passkey response")

    pk = (
        db.query(PasskeyCredential)
        .filter(PasskeyCredential.credential_id == base64url_to_bytes(parsed.id))
        .first()
    )
    if pk is None:
        fail("passkey_unknown", None, 401, "This passkey isn't registered with Ghaf App")

    user = pk.user
    try:
        verified = verify_authentication_response(
            credential=parsed,
            expected_challenge=expected_challenge,
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.webauthn_origins_list,
            credential_public_key=pk.public_key,
            credential_current_sign_count=pk.sign_count,
            require_user_verification=True,
        )
    except InvalidAuthenticationResponse:
        fail("passkey_invalid", user, 401, "Passkey verification failed")

    if not user.is_active:
        fail("inactive_account", user, 403, "Account is inactive")

    now = _utcnow()
    pk.sign_count = verified.new_sign_count
    pk.last_used_at = now
    user.last_login_at = now
    db.add(
        LoginLog(
            user_id=user.id,
            email_attempted=user.email,
            success=True,
            failure_reason=None,
            ip_address=ip,
            user_agent=f"[passkey] {user_agent or ''}"[:500],
        )
    )
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": str(user.id), "role": user.role})
    return Token(access_token=token, user=UserOut.model_validate(user))
