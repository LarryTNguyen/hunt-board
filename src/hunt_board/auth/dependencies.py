from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from hunt_board.auth.security import (
    SupabaseIdentity,
    TokenVerificationError,
    get_token_verifier,
)
from hunt_board.db.models import Invitation, User
from hunt_board.db.session import get_db
from hunt_board.core.observability import metrics, trace_span


bearer_scheme = HTTPBearer(auto_error=False)
logger = logging.getLogger("hunt_board")


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def optional_identity(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> SupabaseIdentity | None:
    if credentials is None:
        return None
    if credentials.scheme.casefold() != "bearer":
        raise _unauthorized("Bearer authentication is required")
    try:
        with trace_span(
            logger,
            "auth.token_verification",
            request_id=getattr(request.state, "request_id", None),
        ):
            identity = get_token_verifier().verify(credentials.credentials)
    except TokenVerificationError as exc:
        metrics.observe_auth("bearer", "failure")
        raise _unauthorized(str(exc)) from exc
    metrics.observe_auth(identity.provider, "success")
    request.state.auth_identity = identity
    return identity


def require_identity(
    identity: Annotated[SupabaseIdentity | None, Depends(optional_identity)],
) -> SupabaseIdentity:
    if identity is None:
        raise _unauthorized("Authentication is required")
    return identity


def _set_rls_identity(db: Session, identity: SupabaseIdentity) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT set_config('request.jwt.claim.sub', :subject, true)"),
            {"subject": str(identity.auth_user_id)},
        )


def optional_user(
    request: Request,
    identity: Annotated[SupabaseIdentity | None, Depends(optional_identity)],
    db: Annotated[Session, Depends(get_db)],
) -> User | None:
    if identity is None:
        return None
    _set_rls_identity(db, identity)
    with trace_span(
        logger,
        "auth.profile_resolution",
        request_id=getattr(request.state, "request_id", None),
    ):
        user = db.scalar(select(User).where(User.auth_user_id == identity.auth_user_id))
    if user is None:
        metrics.deny("uninvited")
        raise HTTPException(status_code=403, detail="This identity has not been invited and activated")
    if user.normalized_email != identity.email:
        metrics.deny("email_mismatch")
        raise HTTPException(status_code=403, detail="Authenticated email does not match the profile")
    if not user.is_active or user.account_status != "active" or user.deleted_at is not None:
        metrics.deny("deactivated")
        raise HTTPException(status_code=403, detail="This profile is not active")
    invitation = db.scalar(
        select(Invitation.id).where(
            Invitation.accepted_auth_user_id == identity.auth_user_id,
            Invitation.normalized_email == identity.email,
            Invitation.status == "accepted",
            Invitation.revoked_at.is_(None),
        )
    )
    if invitation is None:
        metrics.deny("invitation_required")
        raise HTTPException(status_code=403, detail="An accepted invitation is required")
    request.state.current_user = user
    return user


def require_user(
    user: Annotated[User | None, Depends(optional_user)],
) -> User:
    if user is None:
        metrics.observe_auth("bearer", "missing")
        raise _unauthorized("Authentication is required")
    return user


def require_admin(user: Annotated[User, Depends(require_user)]) -> User:
    if user.role != "admin" or not user.is_admin:
        metrics.deny("admin_required")
        raise HTTPException(status_code=403, detail="Administrator access is required")
    return user
