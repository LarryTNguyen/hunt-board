from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from time import perf_counter

from sqlalchemy import Select
from sqlalchemy.orm import Session

from hunt_board.core.observability import metrics, trace_span
from hunt_board.jobs.query import JobQueryFilters, apply_job_filters, count_jobs, job_row_statement


logger = logging.getLogger("hunt_board")
RELAXATION_ORDER = ("min_salary", "location", "experience_levels", "desired_titles", "job_families")


@dataclass(frozen=True)
class SearchExecution:
    strict_statement: Select
    final_statement: Select
    relevance: object | None
    final_filters: JobQueryFilters
    strict_total: int
    final_total: int
    relaxed_filters: tuple[str, ...]


def execute_with_relaxation(
    db: Session,
    user_id: int | None,
    filters: JobQueryFilters,
    *,
    minimum_results: int = 10,
    kind: str = "feed",
) -> SearchExecution:
    started = perf_counter()
    with trace_span(logger, "job_query.execution", query_kind=kind):
        strict_statement, strict_relevance = apply_job_filters(job_row_statement(user_id), db, filters)
        strict_total = count_jobs(db, strict_statement)
        current = filters
        final_statement = strict_statement
        final_relevance = strict_relevance
        final_total = strict_total
        relaxed: list[str] = []
        if strict_total < minimum_results:
            for step in RELAXATION_ORDER:
                candidate = _relax(current, step)
                if candidate == current:
                    continue
                current = candidate
                final_statement, final_relevance = apply_job_filters(job_row_statement(user_id), db, current)
                final_total = count_jobs(db, final_statement)
                relaxed.append(step)
                metrics.observe_relaxation(step)
                if final_total >= minimum_results:
                    break
    search_kind = "relaxed" if relaxed else "strict"
    metrics.observe_search(search_kind, perf_counter() - started, final_total)
    logger.info(
        "search.executed",
        extra={
            "event_name": "search.executed",
            "event_data": {
                "kind": kind,
                "mode": search_kind,
                "strict_count_bucket": _count_bucket(strict_total),
                "result_count_bucket": _count_bucket(final_total),
                "relaxed_filters": relaxed,
            },
        },
    )
    return SearchExecution(
        strict_statement=strict_statement,
        final_statement=final_statement,
        relevance=final_relevance,
        final_filters=current,
        strict_total=strict_total,
        final_total=final_total,
        relaxed_filters=tuple(relaxed),
    )


def _relax(filters: JobQueryFilters, step: str) -> JobQueryFilters:
    if step == "min_salary" and filters.min_salary is not None:
        return replace(filters, min_salary=None)
    if step == "location" and filters.location:
        return replace(filters, location=None)
    if step == "experience_levels" and filters.experience_levels:
        return replace(filters, experience_levels=())
    if step == "desired_titles" and filters.desired_titles:
        return replace(filters, desired_titles=())
    if step == "job_families" and filters.job_families and filters.related_job_families:
        expanded = tuple(dict.fromkeys((*filters.job_families, *filters.related_job_families)))
        return replace(filters, job_families=expanded)
    return filters


def _count_bucket(value: int) -> str:
    return "0" if value == 0 else "1-9" if value < 10 else "10-49" if value < 50 else "50+"
