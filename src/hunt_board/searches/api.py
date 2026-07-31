from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hunt_board.auth.dependencies import require_user
from hunt_board.db.models import JobPosting, SavedSearch, User
from hunt_board.db.session import get_db
from hunt_board.jobs.query import apply_job_sort, count_jobs, feed_facets
from hunt_board.jobs.service import job_read_payload
from hunt_board.searches.schemas import (
    SavedSearchCreate,
    SavedSearchDeleteResponse,
    SavedSearchMatchesRead,
    SavedSearchRead,
    SavedSearchReviewedRead,
    SavedSearchUpdate,
)
from hunt_board.searches.service import (
    match_statement,
    saved_filters,
    saved_search_counts,
    saved_search_payload,
)


router = APIRouter(prefix="/saved-searches", tags=["saved searches"])


def _owned_search(db: Session, saved_search_id: int, user_id: int) -> SavedSearch:
    saved_search = db.scalar(
        select(SavedSearch).where(
            SavedSearch.id == saved_search_id,
            SavedSearch.user_id == user_id,
        )
    )
    if saved_search is None:
        raise HTTPException(status_code=404, detail="Saved search not found")
    return saved_search


def _ensure_unique_name(
    db: Session,
    user_id: int,
    name: str,
    *,
    excluding_id: int | None = None,
) -> None:
    statement = select(SavedSearch.id).where(
        SavedSearch.user_id == user_id,
        func.lower(SavedSearch.name) == name.lower(),
    )
    if excluding_id is not None:
        statement = statement.where(SavedSearch.id != excluding_id)
    if db.scalar(statement) is not None:
        raise HTTPException(status_code=409, detail="A saved search with this name already exists")


def _unset_other_defaults(db: Session, user_id: int, excluding_id: int | None = None) -> None:
    statement = update(SavedSearch).where(
        SavedSearch.user_id == user_id,
        SavedSearch.is_default.is_(True),
    )
    if excluding_id is not None:
        statement = statement.where(SavedSearch.id != excluding_id)
    db.execute(statement.values(is_default=False))


@router.get(
    "",
    response_model=list[SavedSearchRead],
    response_model_exclude_none=True,
)
def list_saved_searches(
    active: bool | None = None,
    include_counts: bool = True,
    include_preview: bool = False,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    statement = select(SavedSearch).where(SavedSearch.user_id == user.id)
    if active is not None:
        statement = statement.where(SavedSearch.is_active.is_(active))
    searches = db.scalars(
        statement.order_by(
            SavedSearch.is_default.desc(),
            SavedSearch.updated_at.desc(),
            SavedSearch.id.desc(),
        )
    ).all()
    return [
        saved_search_payload(
            db,
            item,
            user.id,
            include_counts=include_counts,
            preview_limit=3 if include_preview else 0,
        )
        for item in searches
    ]


@router.post("", response_model=SavedSearchRead)
def create_saved_search(
    payload: SavedSearchCreate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_unique_name(db, user.id, payload.name)
    if payload.is_default:
        _unset_other_defaults(db, user.id)
    saved_search = SavedSearch(
        user_id=user.id,
        name=payload.name,
        description=payload.description,
        filters_json=payload.filters.model_dump(exclude_none=True),
        sort_by=payload.sort_by,
        sort_order=payload.sort_order,
        is_default=payload.is_default,
        is_active=payload.is_active,
        notify_on_new_matches=payload.notify_on_new_matches,
    )
    db.add(saved_search)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A saved search with this name already exists") from exc
    db.refresh(saved_search)
    return saved_search_payload(db, saved_search, user.id)


@router.get("/{saved_search_id}", response_model=SavedSearchRead)
def get_saved_search(
    saved_search_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    return saved_search_payload(
        db,
        _owned_search(db, saved_search_id, user.id),
        user.id,
        preview_limit=5,
    )


@router.patch("/{saved_search_id}", response_model=SavedSearchRead)
def update_saved_search(
    saved_search_id: int,
    payload: SavedSearchUpdate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    saved_search = _owned_search(db, saved_search_id, user.id)
    fields = payload.model_fields_set
    if "name" in fields:
        _ensure_unique_name(db, user.id, payload.name, excluding_id=saved_search.id)
        saved_search.name = payload.name
    if "description" in fields:
        saved_search.description = payload.description
    if "filters" in fields:
        saved_search.filters_json = payload.filters.model_dump(exclude_none=True)
    if "sort_by" in fields:
        saved_search.sort_by = payload.sort_by
    if "sort_order" in fields:
        saved_search.sort_order = payload.sort_order
    if "is_active" in fields:
        saved_search.is_active = payload.is_active
    if "notify_on_new_matches" in fields:
        saved_search.notify_on_new_matches = payload.notify_on_new_matches
    if "is_default" in fields:
        if payload.is_default:
            _unset_other_defaults(db, user.id, saved_search.id)
        saved_search.is_default = payload.is_default
    if payload.reset_reviewed:
        saved_search.last_viewed_at = None
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A saved search with this name already exists") from exc
    db.refresh(saved_search)
    return saved_search_payload(db, saved_search, user.id)


@router.delete("/{saved_search_id}", response_model=SavedSearchDeleteResponse)
def delete_saved_search(
    saved_search_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    saved_search = _owned_search(db, saved_search_id, user.id)
    db.delete(saved_search)
    db.commit()
    return {"saved_search_id": saved_search_id, "removed": True}


@router.get("/{saved_search_id}/matches", response_model=SavedSearchMatchesRead)
def saved_search_matches(
    saved_search_id: int,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    new_only: bool = False,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    saved_search = _owned_search(db, saved_search_id, user.id)
    unfiltered_new_statement, _, filters = match_statement(db, saved_search, user.id)
    total_new = (
        count_jobs(db, unfiltered_new_statement)
        if saved_search.last_viewed_at is None
        else count_jobs(
            db,
            unfiltered_new_statement.where(
                JobPosting.first_seen_at > saved_search.last_viewed_at
            ),
        )
    )
    statement, relevance, _ = match_statement(
        db, saved_search, user.id, new_only=new_only
    )
    total = count_jobs(db, statement)
    rows = db.execute(
        apply_job_sort(
            statement,
            saved_search.sort_by,
            saved_search.sort_order,
            relevance,
        )
        .offset(offset)
        .limit(limit)
    ).all()
    items = [job_read_payload(*row) for row in rows]
    return {
        "saved_search": {
            "id": saved_search.id,
            "name": saved_search.name,
            "last_viewed_at": saved_search.last_viewed_at,
        },
        "items": items,
        "total": total,
        "new_since_review_count": total_new,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
        "generated_at": datetime.now(timezone.utc),
        "facets": feed_facets(db, user.id, filters),
    }


@router.post(
    "/{saved_search_id}/mark-reviewed",
    response_model=SavedSearchReviewedRead,
)
def mark_saved_search_reviewed(
    saved_search_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    saved_search = _owned_search(db, saved_search_id, user.id)
    saved_search.last_viewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(saved_search)
    match_count, new_count = saved_search_counts(db, saved_search, user.id)
    return {
        "saved_search_id": saved_search.id,
        "last_viewed_at": saved_search.last_viewed_at,
        "match_count": match_count,
        "new_since_review_count": new_count,
    }
