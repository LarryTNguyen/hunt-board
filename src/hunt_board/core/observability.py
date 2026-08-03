from __future__ import annotations

import json
import logging
import re
import threading
from collections import Counter, defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Iterator
from uuid import uuid4


SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "email",
    "first_name",
    "last_name",
    "display_name",
    "password",
    "access_token",
    "refresh_token",
    "service_role_key",
    "notes",
    "body",
    "magic_link",
    "q",
    "query",
    "search",
    "keyword",
    "keywords",
    "include_keywords",
    "exclude_keywords",
    "location",
    "locations",
    "company",
    "company_name",
    "job_title",
    "title",
    "link",
    "link_url",
    "description",
    "description_text",
}
SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
request_id_context: ContextVar[str | None] = ContextVar("hunt_board_request_id", default=None)
trace_id_context: ContextVar[str | None] = ContextVar("hunt_board_trace_id", default=None)


def sanitized(value: Any, *, key: str | None = None) -> Any:
    if key and key.casefold() in SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): sanitized(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitized(item) for item in value]
    if isinstance(value, str) and len(value) > 500:
        return value[:500]
    return value


class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "service": "hunt-board",
            "event_name": getattr(record, "event_name", record.getMessage()),
        }
        event.update(sanitized(getattr(record, "event_data", {})))
        if "request_id" not in event and request_id_context.get() is not None:
            event["request_id"] = request_id_context.get()
        if "trace_id" not in event and trace_id_context.get() is not None:
            event["trace_id"] = trace_id_context.get()
        return json.dumps(event, separators=(",", ":"), default=str)


def configure_logging() -> None:
    logger = logging.getLogger("hunt_board")
    if any(getattr(handler, "_hunt_board_structured", False) for handler in logger.handlers):
        return
    handler = logging.StreamHandler()
    handler._hunt_board_structured = True  # type: ignore[attr-defined]
    handler.setFormatter(StructuredFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def safe_correlation_id(value: str | None) -> str:
    if value and SAFE_ID.fullmatch(value):
        return value
    return uuid4().hex


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests: Counter[tuple[str, str, str]] = Counter()
        self.request_duration: defaultdict[tuple[str, str, str], float] = defaultdict(float)
        self.auth: Counter[tuple[str, str]] = Counter()
        self.authorization_denials: Counter[str] = Counter()
        self.database_errors = 0
        self.searches: Counter[str] = Counter()
        self.relaxations: Counter[str] = Counter()
        self.saved_search_actions: Counter[str] = Counter()
        self.application_actions: Counter[str] = Counter()
        self.classifications: Counter[tuple[str, str, str]] = Counter()
        self.query_duration: defaultdict[str, float] = defaultdict(float)
        self.query_results: Counter[str] = Counter()

    def observe_request(self, method: str, route: str, status_code: int, duration: float) -> None:
        status_class = f"{status_code // 100}xx"
        key = (method, route, status_class)
        with self._lock:
            self.requests[key] += 1
            self.request_duration[key] += duration

    def observe_auth(self, method: str, category: str) -> None:
        with self._lock:
            self.auth[(method, category)] += 1

    def deny(self, category: str) -> None:
        with self._lock:
            self.authorization_denials[category] += 1

    def database_error(self) -> None:
        with self._lock:
            self.database_errors += 1

    def observe_search(self, kind: str, duration: float, result_count: int) -> None:
        bucket = "0" if result_count == 0 else "1-9" if result_count < 10 else "10-49" if result_count < 50 else "50+"
        with self._lock:
            self.searches[kind] += 1
            self.query_duration[kind] += duration
            self.query_results[bucket] += 1

    def observe_relaxation(self, step: str) -> None:
        with self._lock:
            self.relaxations[step] += 1

    def observe_saved_search(self, action: str) -> None:
        with self._lock:
            self.saved_search_actions[action] += 1

    def observe_application(self, action: str) -> None:
        with self._lock:
            self.application_actions[action] += 1

    def observe_classification(self, family: str, method: str, confidence_bucket: str) -> None:
        with self._lock:
            self.classifications[(family, method, confidence_bucket)] += 1

    def render(
        self,
        *,
        active_profiles: int,
        deactivated_profiles: int,
        invitations: dict[str, int],
        classification_inventory: list[tuple[str, str, str, int]] | None = None,
        classification_overrides: int = 0,
        other_rate: float = 0.0,
    ) -> str:
        lines = [
            "# HELP hunt_board_requests_total HTTP requests by bounded route and status class.",
            "# TYPE hunt_board_requests_total counter",
        ]
        with self._lock:
            for (method, route, status_class), count in sorted(self.requests.items()):
                labels = f'method="{method}",route="{route}",status_class="{status_class}"'
                lines.append(f"hunt_board_requests_total{{{labels}}} {count}")
            lines.extend(
                [
                    "# HELP hunt_board_request_duration_seconds_total Cumulative request duration.",
                    "# TYPE hunt_board_request_duration_seconds_total counter",
                ]
            )
            for (method, route, status_class), duration in sorted(self.request_duration.items()):
                labels = f'method="{method}",route="{route}",status_class="{status_class}"'
                lines.append(f"hunt_board_request_duration_seconds_total{{{labels}}} {duration:.6f}")
            lines.extend(
                [
                    "# HELP hunt_board_auth_total Authentication decisions.",
                    "# TYPE hunt_board_auth_total counter",
                ]
            )
            for (method, category), count in sorted(self.auth.items()):
                lines.append(
                    f'hunt_board_auth_total{{method="{method}",category="{category}"}} {count}'
                )
            for category, count in sorted(self.authorization_denials.items()):
                lines.append(
                    f'hunt_board_authorization_denials_total{{category="{category}"}} {count}'
                )
            lines.append(f"hunt_board_database_errors_total {self.database_errors}")
            for kind, count in sorted(self.searches.items()):
                lines.append(f'hunt_board_searches_total{{kind="{kind}"}} {count}')
            for step, count in sorted(self.relaxations.items()):
                lines.append(f'hunt_board_relaxation_steps_total{{step="{step}"}} {count}')
            for action, count in sorted(self.saved_search_actions.items()):
                lines.append(f'hunt_board_saved_search_actions_total{{action="{action}"}} {count}')
            for action, count in sorted(self.application_actions.items()):
                lines.append(f'hunt_board_application_actions_total{{action="{action}"}} {count}')
            for (family, method, confidence), count in sorted(self.classifications.items()):
                labels = f'family="{family}",method="{method}",confidence="{confidence}"'
                lines.append(f"hunt_board_classifications_total{{{labels}}} {count}")
            for kind, duration in sorted(self.query_duration.items()):
                lines.append(f'hunt_board_query_duration_seconds_total{{kind="{kind}"}} {duration:.6f}')
            for bucket, count in sorted(self.query_results.items()):
                lines.append(f'hunt_board_query_results_total{{bucket="{bucket}"}} {count}')
        lines.extend(
            [
                f'hunt_board_profiles{{status="active"}} {active_profiles}',
                f'hunt_board_profiles{{status="deactivated"}} {deactivated_profiles}',
            ]
        )
        for status in ("created", "accepted", "revoked"):
            lines.append(
                f'hunt_board_invitations_total{{status="{status}"}} {invitations.get(status, 0)}'
            )
        for family, method, confidence, count in classification_inventory or []:
            labels = f'family="{family}",method="{method}",confidence="{confidence}"'
            lines.append(f"hunt_board_jobs{{{labels}}} {count}")
        lines.append(f"hunt_board_classification_overrides {classification_overrides}")
        lines.append(f"hunt_board_other_rate_percent {other_rate:.2f}")
        return "\n".join(lines) + "\n"


metrics = MetricsRegistry()


@contextmanager
def trace_span(logger: logging.Logger, event_name: str, **fields: Any) -> Iterator[None]:
    started = perf_counter()
    try:
        yield
    finally:
        logger.info(
            event_name,
            extra={
                "event_name": event_name,
                "event_data": {**fields, "duration_ms": round((perf_counter() - started) * 1000, 3)},
            },
        )
