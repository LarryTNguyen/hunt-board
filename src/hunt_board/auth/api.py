from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from hunt_board.auth.dependencies import require_admin, require_identity, require_user
from hunt_board.auth.security import SupabaseIdentity, normalize_email
from hunt_board.core.config import get_settings
from hunt_board.db.models import AuditEvent, Invitation, SavedSearch, User
from hunt_board.db.session import get_db
from hunt_board.matching.service import ensure_user_preference


router = APIRouter(prefix="/auth", tags=["auth"])
admin_router = APIRouter(prefix="/admin", tags=["admin"])


class PublicAuthConfig(BaseModel):
    enabled: bool
    supabase_url: str
    supabase_anon_key: str
    redirect_path: str = "/app/sign-in.html"


class ProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    auth_user_id: UUID
    display_name: str | None
    first_name: str | None
    last_name: str | None
    role: Literal["admin", "user"]
    account_status: str
    is_active: bool
    onboarding_completed_at: datetime | None
    onboarding_skipped_at: datetime | None


class InvitationCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class InvitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    normalized_email: str
    status: str
    inviter_user_id: int
    accepted_auth_user_id: UUID | None
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _audit(
    db: Session,
    request: Request,
    event_name: str,
    *,
    actor: User | None,
    target_type: str,
    target_id: str,
) -> None:
    db.add(
        AuditEvent(
            event_name=event_name,
            actor_user_id=actor.id if actor else None,
            target_type=target_type,
            target_id=target_id,
            request_id=_request_id(request),
            details_json={"trace_id": getattr(request.state, "trace_id", None)},
        )
    )


@router.get("/config", response_model=PublicAuthConfig)
def auth_config() -> dict:
    settings = get_settings()
    return {
        "enabled": bool(settings.supabase_url and settings.supabase_anon_key),
        "supabase_url": settings.supabase_url,
        "supabase_anon_key": settings.supabase_anon_key,
    }


def _ensure_default_profile(db: Session, profile: User) -> None:
    ensure_user_preference(db, profile)
    default = db.scalar(
        select(SavedSearch).where(SavedSearch.user_id == profile.id, SavedSearch.is_default.is_(True))
    )
    if default is None:
        db.add(
            SavedSearch(
                user_id=profile.id,
                name="All Jobs",
                description="Broad default route; add optional preferences to improve relevance.",
                filters_json={
                    "active": True,
                    "discarded": False,
                    "application_state": "none",
                    "include_duplicates": False,
                },
                sort_by="ranking_score",
                sort_order="desc",
                is_default=True,
                is_active=True,
            )
        )


@router.post("/activate", response_model=ProfileRead)
def activate_profile(
    request: Request,
    identity: Annotated[SupabaseIdentity, Depends(require_identity)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if not identity.email_verified:
        raise HTTPException(status_code=403, detail="Verify your email before activating Hunt Board")

    existing = db.scalar(select(User).where(User.auth_user_id == identity.auth_user_id))
    if existing is not None:
        if existing.normalized_email != identity.email:
            raise HTTPException(status_code=403, detail="Authenticated email does not match the profile")
        if not existing.is_active or existing.account_status != "active":
            raise HTTPException(status_code=403, detail="This profile is not active")
        _ensure_default_profile(db, existing)
        db.commit()
        return existing

    profile = db.scalar(select(User).where(User.normalized_email == identity.email))
    local_seed_id = uuid5(
        NAMESPACE_URL,
        f"hunt-board:local-seed:{identity.email}",
    )
    can_rebind_local_seed = bool(
        profile
        and get_settings().environment in {"development", "dev", "local", "test"}
        and profile.auth_user_id == local_seed_id
    )
    invitation_status = Invitation.status == "pending"
    if can_rebind_local_seed:
        invitation_status = or_(
            invitation_status,
            and_(
                Invitation.status == "accepted",
                Invitation.accepted_auth_user_id == local_seed_id,
            ),
        )
    invitation = db.scalar(
        select(Invitation)
        .where(
            Invitation.normalized_email == identity.email,
            Invitation.revoked_at.is_(None),
            invitation_status,
        )
        .order_by(Invitation.created_at, Invitation.id)
    )
    if invitation is None:
        raise HTTPException(status_code=403, detail="An active invitation is required")

    metadata = identity.claims.get("user_metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    first_name = metadata.get("first_name") or metadata.get("given_name")
    last_name = metadata.get("last_name") or metadata.get("family_name")
    display_name = metadata.get("display_name") or metadata.get("full_name") or metadata.get("name")
    if profile is not None:
        if profile.auth_user_id is not None and not can_rebind_local_seed:
            raise HTTPException(
                status_code=409,
                detail="This email is already linked to another Supabase identity",
            )
        profile.auth_user_id = identity.auth_user_id
        profile.email = identity.email
        profile.first_name = str(first_name)[:120] if first_name else profile.first_name
        profile.last_name = str(last_name)[:120] if last_name else profile.last_name
        profile.display_name = str(display_name)[:255] if display_name else profile.display_name
        profile.is_active = True
        profile.account_status = "active"
    else:
        profile = User(
            auth_user_id=identity.auth_user_id,
            email=identity.email,
            normalized_email=identity.email,
            first_name=str(first_name)[:120] if first_name else None,
            last_name=str(last_name)[:120] if last_name else None,
            display_name=str(display_name)[:255] if display_name else None,
            role="user",
            is_admin=False,
            is_active=True,
            account_status="active",
            preferences_json={},
        )
        db.add(profile)
        db.flush()

    invitation.status = "accepted"
    invitation.accepted_auth_user_id = identity.auth_user_id
    invitation.accepted_at = datetime.now(timezone.utc)
    _audit(
        db,
        request,
        "invitation.accepted",
        actor=profile,
        target_type="invitation",
        target_id=str(invitation.id),
    )
    _ensure_default_profile(db, profile)
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/me", response_model=ProfileRead)
def current_profile(user: Annotated[User, Depends(require_user)]) -> User:
    return user


@admin_router.get("/invitations", response_model=list[InvitationRead])
def list_invitations(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> list[Invitation]:
    return list(db.scalars(select(Invitation).order_by(Invitation.created_at.desc())).all())


@admin_router.post("/invitations", response_model=InvitationRead, status_code=201)
def create_invitation(
    payload: InvitationCreate,
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> Invitation:
    email = normalize_email(payload.email)
    if "@" not in email:
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    existing = db.scalar(
        select(Invitation).where(
            Invitation.normalized_email == email,
            Invitation.status == "pending",
            Invitation.revoked_at.is_(None),
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="An active invitation already exists")
    invitation = Invitation(
        normalized_email=email,
        inviter_user_id=admin.id,
        status="pending",
    )
    db.add(invitation)
    db.flush()
    _audit(
        db,
        request,
        "invitation.created",
        actor=admin,
        target_type="invitation",
        target_id=str(invitation.id),
    )
    db.commit()
    db.refresh(invitation)
    return invitation


@admin_router.post("/invitations/{invitation_id}/revoke", response_model=InvitationRead)
def revoke_invitation(
    invitation_id: int,
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> Invitation:
    invitation = db.get(Invitation, invitation_id)
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invitation.status == "accepted":
        raise HTTPException(status_code=409, detail="Accepted invitations cannot be revoked")
    if invitation.status != "revoked":
        invitation.status = "revoked"
        invitation.revoked_at = datetime.now(timezone.utc)
        _audit(
            db,
            request,
            "invitation.revoked",
            actor=admin,
            target_type="invitation",
            target_id=str(invitation.id),
        )
        db.commit()
        db.refresh(invitation)
    return invitation


@admin_router.post("/profiles/{profile_id}/deactivate", response_model=ProfileRead)
def deactivate_profile(
    profile_id: int,
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    profile = db.get(User, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    if profile.id == admin.id:
        raise HTTPException(status_code=409, detail="Administrators cannot deactivate themselves")
    profile.is_active = False
    profile.account_status = "deactivated"
    profile.deactivated_at = datetime.now(timezone.utc)
    _audit(db, request, "profile.deactivated", actor=admin, target_type="profile", target_id=str(profile.id))
    db.commit()
    db.refresh(profile)
    return profile


@admin_router.post("/profiles/{profile_id}/reactivate", response_model=ProfileRead)
def reactivate_profile(
    profile_id: int,
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    profile = db.get(User, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    profile.is_active = True
    profile.account_status = "active"
    profile.deactivated_at = None
    _audit(db, request, "profile.reactivated", actor=admin, target_type="profile", target_id=str(profile.id))
    db.commit()
    db.refresh(profile)
    return profile
