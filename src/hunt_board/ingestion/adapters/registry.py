from __future__ import annotations

from collections.abc import Callable

import httpx

from hunt_board.ingestion.adapters.ashby import AshbyAdapter
from hunt_board.ingestion.adapters.base import ATSAdapter
from hunt_board.ingestion.adapters.greenhouse import GreenhouseAdapter
from hunt_board.ingestion.adapters.lever import LeverAdapter
from hunt_board.ingestion.adapters.workday import WorkdayAdapter


AdapterFactory = Callable[..., ATSAdapter]


ADAPTER_REGISTRY: dict[str, AdapterFactory] = {
    "greenhouse": GreenhouseAdapter,
    "lever": LeverAdapter,
    "ashby": AshbyAdapter,
    "workday": WorkdayAdapter,
}


def registered_adapter_keys() -> frozenset[str]:
    return frozenset(ADAPTER_REGISTRY)


def create_adapter(
    ats: str,
    client: httpx.AsyncClient,
    *,
    max_retries: int,
    retry_backoff_seconds: float,
    retry_jitter_seconds: float = 0.25,
) -> ATSAdapter:
    try:
        factory = ADAPTER_REGISTRY[ats]
    except KeyError as exc:
        supported = ", ".join(sorted(ADAPTER_REGISTRY))
        raise ValueError(f"Unsupported ATS adapter '{ats}'. Registered adapters: {supported}") from exc
    return factory(
        client,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
        retry_jitter_seconds=retry_jitter_seconds,
    )
