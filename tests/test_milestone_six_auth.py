from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from hunt_board.auth.security import (
    SupabaseIdentity,
    SupabaseJWTVerifier,
    TokenVerificationError,
)
from hunt_board.core.config import get_settings
from hunt_board.core.observability import StructuredFormatter, MetricsRegistry
from hunt_board.db.models import (
    ApplicationStatus,
    Invitation,
    JobMatch,
    JobPosting,
    Notification,
    Source,
    User,
    UserPreference,
)
from hunt_board.db.seed import seed_milestone_one
from hunt_board.db.session import get_db
from hunt_board.ingestion.adapters.base import NormalizedJob
from hunt_board.ingestion.service import IngestionService
from hunt_board.main import create_app


FIXTURES = Path(__file__).parent / "fixtures"


class FakeVerifier:
    def __init__(self, identities: dict[str, SupabaseIdentity]):
        self.identities = identities

    def verify(self, token: str) -> SupabaseIdentity:
        if token not in self.identities:
            raise TokenVerificationError("Access token is invalid")
        return self.identities[token]


def identity(*, auth_user_id=None, email="member@example.com", provider="password", verified=True):
    return SupabaseIdentity(
        auth_user_id=auth_user_id or uuid4(),
        email=email,
        provider=provider,
        email_verified=verified,
        claims={"sub": str(auth_user_id or uuid4()), "email": email, "user_metadata": {}},
    )


@contextmanager
def auth_client(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    identities: dict[str, SupabaseIdentity],
) -> Generator[TestClient, None, None]:
    import hunt_board.auth.dependencies as dependencies

    app = create_app()

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(dependencies, "get_token_verifier", lambda: FakeVerifier(identities))
    with TestClient(app) as client:
        yield client


def accepted_profile(
    db: Session,
    *,
    email: str,
    auth_user_id,
    role: str = "user",
    active: bool = True,
) -> User:
    user = User(
        auth_user_id=auth_user_id,
        email=email,
        normalized_email=email,
        role=role,
        is_admin=role == "admin",
        is_active=active,
        account_status="active" if active else "deactivated",
    )
    db.add(user)
    db.flush()
    db.add(
        Invitation(
            normalized_email=email,
            inviter_user_id=user.id,
            status="accepted",
            accepted_auth_user_id=auth_user_id,
            accepted_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    return user


def catalog_job(db: Session) -> JobPosting:
    source = Source(slug="m6", name="M6", ats="greenhouse", company_name="M6 Co")
    db.add(source)
    db.flush()
    job = JobPosting(
        source_id=source.id,
        source_slug=source.slug,
        company_name=source.company_name,
        external_job_id="m6-1",
        title="Platform Engineer",
        normalized_title="platform engineer",
        location="Remote",
        normalized_location="remote",
        description_text="Build a platform.",
        raw_json={"private": "raw source payload"},
    )
    db.add(job)
    db.flush()
    db.add(ApplicationStatus(name="Applied", slug="applied", sort_order=1))
    db.commit()
    return job


def test_jwt_verification_success_invalid_and_expired() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    settings = replace(
        get_settings(),
        supabase_url="https://project.supabase.co",
        supabase_jwt_issuer="https://project.supabase.co/auth/v1",
        supabase_jwt_audience="authenticated",
    )
    verifier = SupabaseJWTVerifier(settings)
    verifier.jwks = SimpleNamespace(
        get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=public_key)
    )
    now = datetime.now(timezone.utc)
    subject = uuid4()
    claims = {
        "sub": str(subject),
        "email": "Member@Example.com",
        "aud": "authenticated",
        "iss": settings.supabase_jwt_issuer,
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "app_metadata": {"provider": "google"},
    }
    token = jwt.encode(claims, private_key, algorithm="RS256")
    verified = verifier.verify(token)
    assert verified.auth_user_id == subject
    assert verified.email == "member@example.com"
    assert verified.email_verified is True

    expired = jwt.encode(
        {**claims, "iat": now - timedelta(hours=2), "exp": now - timedelta(hours=1)},
        private_key,
        algorithm="RS256",
    )
    with pytest.raises(TokenVerificationError, match="expired"):
        verifier.verify(expired)
    with pytest.raises(TokenVerificationError, match="invalid"):
        verifier.verify("not-a-jwt")


def test_invite_only_activation_and_email_verification(db_session, monkeypatch) -> None:
    admin_id = uuid4()
    admin = accepted_profile(
        db_session,
        email="admin@example.com",
        auth_user_id=admin_id,
        role="admin",
    )
    invited_id = uuid4()
    db_session.add(
        Invitation(
            normalized_email="invited@example.com",
            inviter_user_id=admin.id,
            status="pending",
        )
    )
    db_session.commit()
    identities = {
        "invited": identity(
            auth_user_id=invited_id,
            email="invited@example.com",
            verified=True,
        ),
        "unverified": identity(email="other@example.com", verified=False),
        "uninvited": identity(email="nobody@example.com", verified=True),
    }
    with auth_client(db_session, monkeypatch, identities) as client:
        assert client.post("/auth/activate", headers={"Authorization": "Bearer uninvited"}).status_code == 403
        assert client.post("/auth/activate", headers={"Authorization": "Bearer unverified"}).status_code == 403
        activated = client.post(
            "/auth/activate", headers={"Authorization": "Bearer invited"}
        )
        assert activated.status_code == 200
        assert activated.json()["role"] == "user"
        assert client.get("/auth/me", headers={"Authorization": "Bearer invited"}).status_code == 200

    invitation = db_session.scalar(
        select(Invitation).where(Invitation.normalized_email == "invited@example.com")
    )
    assert invitation.status == "accepted"
    assert invitation.accepted_auth_user_id == invited_id


def test_401_403_admin_and_deactivated_boundaries(db_session, monkeypatch) -> None:
    member_id = uuid4()
    disabled_id = uuid4()
    accepted_profile(db_session, email="member@example.com", auth_user_id=member_id)
    accepted_profile(
        db_session,
        email="disabled@example.com",
        auth_user_id=disabled_id,
        active=False,
    )
    identities = {
        "member": identity(auth_user_id=member_id, email="member@example.com"),
        "disabled": identity(auth_user_id=disabled_id, email="disabled@example.com"),
    }
    with auth_client(db_session, monkeypatch, identities) as client:
        assert client.get("/me/preferences").status_code == 401
        assert client.get(
            "/admin/operations", headers={"Authorization": "Bearer member"}
        ).status_code == 403
        assert client.get(
            "/me/preferences", headers={"Authorization": "Bearer disabled"}
        ).status_code == 403
        assert client.get("/jobs").status_code == 200


def test_two_user_private_domain_isolation(db_session, monkeypatch) -> None:
    a_id, b_id = uuid4(), uuid4()
    user_a = accepted_profile(db_session, email="a@example.com", auth_user_id=a_id)
    user_b = accepted_profile(db_session, email="b@example.com", auth_user_id=b_id)
    job = catalog_job(db_session)
    db_session.add(
        Notification(
            user_id=user_a.id,
            job_posting_id=None,
            kind="new_match",
            dedupe_key="m6-a",
            payload_json={},
        )
    )
    db_session.commit()
    identities = {
        "a": identity(auth_user_id=a_id, email="a@example.com"),
        "b": identity(auth_user_id=b_id, email="b@example.com"),
    }
    a = {"Authorization": "Bearer a"}
    b = {"Authorization": "Bearer b"}
    with auth_client(db_session, monkeypatch, identities) as client:
        assert client.patch("/me/preferences", headers=a, json={"home_location": "Seattle"}).status_code == 200
        assert client.get("/me/preferences", headers=b).json()["home_location"] != "Seattle"

        saved_search = client.post(
            "/saved-searches",
            headers=a,
            json={"name": "A only", "filters": {}},
        )
        assert saved_search.status_code == 200
        assert client.get(
            f"/saved-searches/{saved_search.json()['id']}", headers=b
        ).status_code == 404

        assert client.post(f"/jobs/{job.id}/save", headers=a, json={}).status_code == 200
        assert client.get("/saved-jobs", headers=b).json() == []
        assert client.post(f"/jobs/{job.id}/discard", headers=a, json={}).status_code == 200
        assert client.get("/discarded-jobs", headers=b).json() == []

        application = client.post(
            f"/jobs/{job.id}/applications",
            headers=a,
            json={"status": "applied"},
        )
        assert application.status_code == 200
        application_id = application.json()["id"]
        second_application = client.post(
            f"/jobs/{job.id}/applications",
            headers=a,
            json={"status": "applied", "create_new": True},
        )
        assert second_application.status_code == 200
        assert second_application.json()["id"] != application_id
        assert client.get(f"/applications/{application_id}", headers=b).status_code == 404
        assert client.get(f"/applications/{application_id}/events", headers=b).status_code == 404

        notification = client.get("/notifications", headers=a).json()[0]
        assert client.patch(
            f"/notifications/{notification['id']}/read", headers=b
        ).status_code == 404

        b_profile = db_session.get(User, user_b.id)
        assert b_profile.auth_user_id == b_id


def test_ingestion_ranks_and_notifies_every_active_profile(db_session) -> None:
    a_id, b_id = uuid4(), uuid4()
    user_a = accepted_profile(db_session, email="rank-a@example.com", auth_user_id=a_id)
    user_b = accepted_profile(db_session, email="rank-b@example.com", auth_user_id=b_id)
    db_session.add_all(
        [
            UserPreference(
                user_id=user_a.id,
                include_keywords=["platform engineer"],
                exclude_keywords=[],
                role_groups=[],
                preferred_levels=["mid"],
                preferred_locations=["remote"],
            ),
            UserPreference(
                user_id=user_b.id,
                include_keywords=["product designer"],
                exclude_keywords=[],
                role_groups=[],
                preferred_levels=["mid"],
                preferred_locations=["remote"],
            ),
        ]
    )
    target = catalog_job(db_session)
    normalized = NormalizedJob(
        source_slug=target.source_slug,
        company_name=target.company_name,
        external_job_id=target.external_job_id,
        title=target.title,
        location=target.location,
        department=target.department,
        employment_type=target.employment_type,
        workplace_type="remote",
        apply_url=target.apply_url,
        description_html=None,
        description_text=target.description_text,
        raw_json={},
    )
    IngestionService._record_user_results(
        db_session,
        target,
        normalized,
        1,
        outcome="new",
        reactivated=False,
        changed_version=None,
        scrape_run=None,
    )
    db_session.commit()

    matches = {
        match.user_id: match
        for match in db_session.scalars(
            select(JobMatch).where(JobMatch.job_posting_id == target.id)
        ).all()
    }
    assert matches[user_a.id].matched is True
    assert matches[user_b.id].matched is False
    notified_users = set(db_session.scalars(select(Notification.user_id)).all())
    assert notified_users == {user_a.id}


def test_request_ids_redaction_bounded_metrics_and_frontend_contract(
    db_session, monkeypatch
) -> None:
    with auth_client(db_session, monkeypatch, {}) as client:
        response = client.get("/health", headers={"X-Request-ID": "owner-check-123"})
        assert response.headers["X-Request-ID"] == "owner-check-123"
        assert response.headers["X-Trace-ID"]

    record = logging.LogRecord("hunt_board", logging.INFO, "", 0, "event", (), None)
    record.event_name = "test"
    record.event_data = {
        "email": "person@example.com",
        "authorization": "Bearer secret",
        "route": "/jobs/{job_id}",
    }
    rendered = StructuredFormatter().format(record)
    assert "person@example.com" not in rendered
    assert "Bearer secret" not in rendered

    registry = MetricsRegistry()
    registry.observe_request("GET", "/jobs/{job_id}", 200, 0.1)
    metrics_text = registry.render(
        active_profiles=2,
        deactivated_profiles=1,
        invitations={"created": 2, "accepted": 1, "revoked": 0},
    )
    assert "user_id" not in metrics_text
    assert "email" not in metrics_text
    assert 'route="/jobs/{job_id}"' in metrics_text

    static = Path(__file__).parents[1] / "src" / "hunt_board" / "web" / "static"
    auth_js = (static / "assets" / "auth.js").read_text(encoding="utf-8")
    sign_in = (static / "sign-in.html").read_text(encoding="utf-8")
    assert "Authorization: `Bearer ${session.access_token}`" in auth_js
    assert "refreshSession" in auth_js
    assert "SUPABASE_SERVICE_ROLE" not in auth_js + sign_in
    assert "Continue with Google" in sign_in
    assert "sign-in link" in sign_in


def test_seed_refuses_automatic_production_admin(db_session) -> None:
    with pytest.raises(RuntimeError, match="disabled in production"):
        seed_milestone_one(
            db_session,
            "owner@example.com",
            str(FIXTURES / "sources_acme.yaml"),
            environment="production",
        )
