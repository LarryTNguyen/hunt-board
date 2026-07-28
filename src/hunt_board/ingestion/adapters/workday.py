from __future__ import annotations

import asyncio
import ipaddress
import math
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

import httpx

from hunt_board.ingestion.adapters.base import AdapterError, HttpATSAdapter, NormalizedJob, normalize_country


SUPPORTED_HOST_SUFFIXES = (".myworkdayjobs.com", ".myworkdaysite.com")
HOST_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
SEGMENT_RE = re.compile(r"^[A-Za-z0-9._~-]+$")
LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z]{2})?$")
RELATIVE_DATE_RE = re.compile(r"^Posted\s+(\d+)\s+Days?\s+Ago$", re.IGNORECASE)
LOCATION_COUNT_RE = re.compile(r"^\s*\d+\+?\s+Locations?\s*$", re.IGNORECASE)


class ListingIntegrityError(AdapterError):
    pass


class DetailWithdrawn(AdapterError):
    pass


@dataclass(frozen=True)
class WorkdaySettings:
    host: str
    tenant: str
    site: str
    careers_url: str
    locale: str = "en-US"
    page_size: int = 20
    detail_concurrency: int = 3
    request_interval_ms: int = 200
    max_jobs: int = 5000


def validate_workday_source(careers_url: str | None, config: dict[str, Any]) -> WorkdaySettings:
    host = str(config.get("host") or "").strip().lower()
    tenant = str(config.get("tenant") or "").strip()
    site = str(config.get("site") or "").strip()
    locale = str(config.get("locale") or "en-US").strip()

    for key, value in (("host", host), ("tenant", tenant), ("site", site)):
        if not value:
            raise ValueError(f"Workday requires config.{key}")
    if any(token in host for token in ("://", "/", "\\", "@", "?", "#", ":")):
        raise ValueError("Workday config.host must be a bare hostname without scheme, port, or path")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("Workday config.host cannot be an IP address")
    if not HOST_RE.fullmatch(host) or not host.endswith(SUPPORTED_HOST_SUFFIXES):
        raise ValueError(
            "Workday config.host must be a public subdomain of myworkdayjobs.com or myworkdaysite.com"
        )
    for key, value in (("tenant", tenant), ("site", site)):
        if (
            not SEGMENT_RE.fullmatch(value)
            or ".." in value
            or any(token in value for token in ("/", "\\", "://", "?", "#"))
        ):
            raise ValueError(f"Workday config.{key} must be one safe nonempty path segment")
    if not LOCALE_RE.fullmatch(locale):
        raise ValueError("Workday config.locale must use a language-region value such as en-US")
    if not careers_url:
        raise ValueError("Workday requires an HTTPS careers_url")
    parsed_careers = urlsplit(careers_url)
    if (
        parsed_careers.scheme != "https"
        or parsed_careers.username
        or parsed_careers.password
        or parsed_careers.port is not None
        or (parsed_careers.hostname or "").lower() != host
    ):
        raise ValueError("Workday careers_url must use HTTPS on the configured host without credentials or port")

    def bounded_int(key: str, default: int, minimum: int, maximum: int) -> int:
        raw = config.get(key, default)
        if isinstance(raw, bool):
            raise ValueError(f"Workday config.{key} must be an integer from {minimum} to {maximum}")
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Workday config.{key} must be an integer from {minimum} to {maximum}"
            ) from exc
        if value < minimum or value > maximum:
            raise ValueError(f"Workday config.{key} must be between {minimum} and {maximum}")
        return value

    return WorkdaySettings(
        host=host,
        tenant=tenant,
        site=site,
        careers_url=careers_url,
        locale=locale,
        page_size=bounded_int("page_size", 20, 1, 100),
        detail_concurrency=bounded_int("detail_concurrency", 3, 1, 8),
        request_interval_ms=bounded_int("request_interval_ms", 200, 0, 10_000),
        max_jobs=bounded_int("max_jobs", 5000, 1, 10_000),
    )


def validate_external_path(value: Any) -> str:
    if not isinstance(value, str):
        raise ListingIntegrityError("Workday listing externalPath must be a string")
    parsed = urlsplit(value)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/job/")
        or "\\" in parsed.path
        or any(segment in {".", ".."} for segment in parsed.path.split("/"))
    ):
        raise ListingIntegrityError(f"Unsafe Workday externalPath: {value!r}")
    return parsed.path


def parse_workday_posted_at(value: Any, scan_time: datetime) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if "+" in text:
        return None
    if text.casefold() == "posted today":
        days = 0
    elif text.casefold() == "posted yesterday":
        days = 1
    else:
        match = RELATIVE_DATE_RE.fullmatch(text)
        if not match:
            return None
        days = int(match.group(1))
    target = scan_time.astimezone(timezone.utc).date() - timedelta(days=days)
    return datetime.combine(target, datetime.min.time(), tzinfo=timezone.utc)


def parse_exact_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return datetime.combine(date.fromisoformat(text), datetime.min.time(), tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def normalize_workplace_type(value: Any) -> str | None:
    if value in (None, ""):
        return None
    normalized = re.sub(r"[\s_-]+", " ", str(value)).strip().casefold()
    if "hybrid" in normalized or "flexible" in normalized:
        return "hybrid"
    if "remote" in normalized or "home" in normalized:
        return "remote"
    if "onsite" in normalized or "on site" in normalized or "office" in normalized:
        return "onsite"
    return None


class WorkdayAdapter(HttpATSAdapter):
    MAX_RETRY_AFTER_SECONDS = 30.0

    def __init__(
        self,
        client: httpx.AsyncClient,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        super().__init__(client, max_retries=max_retries, retry_backoff_seconds=retry_backoff_seconds)
        self.sleep = sleep
        self._pace_lock = asyncio.Lock()
        self._last_request_started = 0.0

    async def fetch_jobs(self, source: Any) -> list[NormalizedJob]:
        try:
            settings = validate_workday_source(source.careers_url, source.config)
        except ValueError as exc:
            raise AdapterError(str(exc)) from exc
        scan_time = datetime.now(timezone.utc)
        listings = await self._complete_listing_scan(settings)
        if not listings:
            return []

        details, withdrawn = await self._fetch_detail_set(settings, listings)
        if withdrawn:
            reconciled = await self._complete_listing_scan(settings)
            current_paths = [item["externalPath"] for item in reconciled]
            current_set = set(current_paths)
            unresolved = withdrawn & current_set
            if unresolved:
                retry_listings = [item for item in reconciled if item["externalPath"] in unresolved]
                retried, still_withdrawn = await self._fetch_detail_set(settings, retry_listings)
                details.update(retried)
                if still_withdrawn:
                    raise AdapterError(
                        "Workday detail remains unavailable for a path still present in the reconciled listing"
                    )
            new_listings = [item for item in reconciled if item["externalPath"] not in details]
            if new_listings:
                new_details, new_withdrawn = await self._fetch_detail_set(settings, new_listings)
                if new_withdrawn:
                    raise AdapterError("Workday board changed again during its single reconciliation cycle")
                details.update(new_details)
            listings = reconciled

        jobs = [
            self._normalize(source, settings, listing, details[listing["externalPath"]], scan_time)
            for listing in listings
        ]
        identities = [job.external_job_id for job in jobs]
        if len(identities) != len(set(identities)):
            raise AdapterError("Workday detail responses contain duplicate stable job identities")
        return jobs

    async def _complete_listing_scan(self, settings: WorkdaySettings) -> list[dict[str, Any]]:
        first_error: ListingIntegrityError | None = None
        for attempt in range(2):
            try:
                return await self._listing_scan(settings)
            except ListingIntegrityError as exc:
                if attempt == 0:
                    first_error = exc
                    continue
                raise AdapterError(
                    f"Workday listing remained incomplete or unstable after a full retry: {exc}"
                ) from exc
        raise AssertionError(first_error)

    async def _listing_scan(self, settings: WorkdaySettings) -> list[dict[str, Any]]:
        url = f"https://{settings.host}/wday/cxs/{settings.tenant}/{settings.site}/jobs"
        headers = self._headers(settings, content_type=True)
        offset = 0
        expected_total: int | None = None
        listings: list[dict[str, Any]] = []
        paths: set[str] = set()
        max_pages = math.ceil(settings.max_jobs / settings.page_size) + 1
        for _page in range(max_pages):
            payload = await self._request_json(
                "POST",
                url,
                settings,
                headers=headers,
                json_body={
                    "appliedFacets": {},
                    "limit": settings.page_size,
                    "offset": offset,
                    "searchText": "",
                },
                listing=True,
            )
            if not isinstance(payload, dict):
                raise ListingIntegrityError("Workday listing response must be a JSON object")
            total = payload.get("total")
            page = payload.get("jobPostings")
            if isinstance(total, bool) or not isinstance(total, int) or total < 0:
                raise ListingIntegrityError("Workday listing total must be a nonnegative integer")
            if not isinstance(page, list):
                raise ListingIntegrityError("Workday listing jobPostings must be a list")
            if expected_total is None:
                expected_total = total
                if total > settings.max_jobs:
                    raise AdapterError(
                        f"Workday board reports {total} jobs, exceeding config.max_jobs={settings.max_jobs}"
                    )
            elif total != expected_total:
                raise ListingIntegrityError(
                    f"Workday listing total changed from {expected_total} to {total}"
                )
            if not page and len(listings) < expected_total:
                raise ListingIntegrityError("Workday listing returned an early empty page")
            for entry in page:
                if not isinstance(entry, dict):
                    raise ListingIntegrityError("Every Workday jobPostings entry must be an object")
                path = validate_external_path(entry.get("externalPath"))
                if path in paths:
                    raise ListingIntegrityError(f"Workday listing repeated externalPath {path}")
                paths.add(path)
                listings.append({**entry, "externalPath": path})
                if len(listings) > expected_total:
                    raise ListingIntegrityError("Workday listing returned more unique jobs than its total")
            if len(listings) == expected_total:
                return listings
            offset += len(page)
        raise ListingIntegrityError("Workday listing exceeded its maximum safe page count")

    async def _fetch_detail_set(
        self,
        settings: WorkdaySettings,
        listings: list[dict[str, Any]],
    ) -> tuple[dict[str, dict[str, Any]], set[str]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        for listing in listings:
            queue.put_nowait(listing)
        details: dict[str, dict[str, Any]] = {}
        withdrawn: set[str] = set()
        fatal_errors: list[BaseException] = []

        async def worker() -> None:
            while not queue.empty():
                listing = await queue.get()
                path = listing["externalPath"]
                try:
                    detail = await self._detail(settings, path)
                    if detail["jobPostingInfo"].get("posted") is False:
                        withdrawn.add(path)
                    else:
                        details[path] = detail
                except DetailWithdrawn:
                    withdrawn.add(path)
                except BaseException as exc:
                    fatal_errors.append(exc)
                finally:
                    queue.task_done()

        workers = [
            asyncio.create_task(worker())
            for _ in range(min(settings.detail_concurrency, len(listings)))
        ]
        await queue.join()
        await asyncio.gather(*workers)
        if fatal_errors:
            error = fatal_errors[0]
            if isinstance(error, AdapterError):
                raise error
            raise AdapterError(f"Workday detail fetch failed: {error}") from error
        return details, withdrawn

    async def _detail(self, settings: WorkdaySettings, external_path: str) -> dict[str, Any]:
        path = validate_external_path(external_path)
        url = f"https://{settings.host}/wday/cxs/{settings.tenant}/{settings.site}{path}"
        payload = await self._request_json(
            "GET",
            url,
            settings,
            headers=self._headers(settings),
            withdrawal_statuses={404, 410},
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("jobPostingInfo"), dict):
            raise AdapterError("Workday detail response must contain an object-valued jobPostingInfo")
        return payload

    async def _pace(self, settings: WorkdaySettings) -> None:
        interval = settings.request_interval_ms / 1000
        if interval <= 0:
            return
        async with self._pace_lock:
            now = time.monotonic()
            wait = max(0.0, interval - (now - self._last_request_started))
            if wait:
                await self.sleep(wait)
            self._last_request_started = time.monotonic()

    async def _request_json(
        self,
        method: str,
        url: str,
        settings: WorkdaySettings,
        *,
        headers: dict[str, str],
        json_body: dict[str, Any] | None = None,
        listing: bool = False,
        withdrawal_statuses: set[int] | None = None,
    ) -> Any:
        withdrawal_statuses = withdrawal_statuses or set()
        for attempt in range(self.max_retries + 1):
            await self._pace(settings)
            try:
                response = await self.client.request(method, url, headers=headers, json=json_body)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt >= self.max_retries:
                    raise AdapterError(
                        f"Workday request failed after {attempt + 1} attempt(s): {exc}"
                    ) from exc
                await self.sleep(self.retry_backoff_seconds * (2**attempt))
                continue
            if response.status_code in withdrawal_statuses:
                raise DetailWithdrawn(f"Workday detail returned {response.status_code}")
            if response.status_code in self.TRANSIENT_STATUS_CODES:
                if attempt < self.max_retries:
                    await self.sleep(self._retry_delay(response, attempt))
                    continue
                if response.status_code == 429:
                    raise AdapterError("Workday board remains rate limited after retries")
                raise AdapterError(
                    f"Workday request exhausted retries with HTTP {response.status_code}"
                )
            if response.status_code in {401, 403}:
                raise AdapterError("Workday public access is unavailable or blocked")
            if listing and response.status_code == 404:
                raise AdapterError("Workday listing endpoint was not found; check host, tenant, and site")
            if listing and response.status_code == 422:
                raise AdapterError("Workday listing request contract or board configuration is unsupported")
            if response.is_error:
                raise AdapterError(f"Workday request failed with HTTP {response.status_code}")
            response_host = (response.url.host or "").lower()
            if response.url.scheme != "https" or response_host != settings.host:
                raise AdapterError("Workday redirected to an unexpected host or non-HTTPS URL")
            content_type = response.headers.get("content-type", "").casefold()
            if "json" not in content_type:
                raise AdapterError("Workday public response contract is unavailable: expected JSON content")
            try:
                return response.json()
            except ValueError as exc:
                raise AdapterError("Workday public response contained malformed JSON") from exc
        raise AssertionError("unreachable")

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        if response.status_code in {429, 503}:
            raw = response.headers.get("retry-after")
            if raw:
                try:
                    value = float(raw)
                except ValueError:
                    try:
                        parsed = parsedate_to_datetime(raw)
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=timezone.utc)
                        value = (parsed - datetime.now(timezone.utc)).total_seconds()
                    except (TypeError, ValueError, OverflowError):
                        value = -1
                if value >= 0:
                    return min(value, self.MAX_RETRY_AFTER_SECONDS)
        return self.retry_backoff_seconds * (2**attempt)

    @staticmethod
    def _headers(settings: WorkdaySettings, *, content_type: bool = False) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Accept-Language": settings.locale,
            "Referer": settings.careers_url,
        }
        if content_type:
            headers["Content-Type"] = "application/json"
        return headers

    @staticmethod
    def _normalize(
        source: Any,
        settings: WorkdaySettings,
        listing: dict[str, Any],
        detail: dict[str, Any],
        scan_time: datetime,
    ) -> NormalizedJob:
        info = detail["jobPostingInfo"]
        external_id = next(
            (str(info[key]).strip() for key in ("id", "jobPostingId", "jobReqId") if info.get(key)),
            "",
        )
        if not external_id:
            raise AdapterError("Workday detail is missing a stable job identity")
        title = str(info.get("title") or listing.get("title") or "").strip()
        if not title:
            raise AdapterError(f"Workday detail {external_id} is missing a title")
        external_path = listing["externalPath"]
        fallback_url = f"{settings.careers_url.rstrip('/')}{external_path}"
        public_url = WorkdayAdapter._safe_public_url(info.get("externalUrl"), settings.host) or fallback_url
        country_obj = (
            (info.get("jobRequisitionLocation") or {}).get("country")
            if isinstance(info.get("jobRequisitionLocation"), dict)
            else None
        )
        if not isinstance(country_obj, dict):
            country_obj = info.get("country") if isinstance(info.get("country"), dict) else {}
        code_value = country_obj.get("alpha2Code")
        descriptor = country_obj.get("descriptor")
        country_code, country_name = normalize_country(code_value, descriptor)
        if code_value and isinstance(code_value, str) and len(code_value.strip()) == 2:
            country_code = code_value.strip().upper()
            country_name = str(descriptor).strip() if descriptor else country_name
        locations = WorkdayAdapter._locations(info, listing, country_code, country_name)
        location = WorkdayAdapter._location_summary(locations)
        posted_at = (
            parse_exact_date(info.get("startDate"))
            or parse_workday_posted_at(info.get("postedOn"), scan_time)
            or parse_workday_posted_at(listing.get("postedOn"), scan_time)
        )
        description_html = info.get("jobDescription")
        return NormalizedJob(
            source_slug=source.slug,
            company_name=source.company_name,
            external_job_id=external_id,
            title=title,
            location=location,
            location_country_code=country_code,
            location_country=country_name,
            locations=locations,
            department=None,
            employment_type=info.get("timeType"),
            workplace_type=normalize_workplace_type(info.get("remoteType")),
            posting_url=public_url,
            apply_url=public_url,
            description_html=description_html,
            description_text=None,
            raw_json={"listing": listing, "detail": detail},
            posted_at=posted_at,
            updated_at=None,
        )

    @staticmethod
    def _safe_public_url(value: Any, expected_host: str) -> str | None:
        if not isinstance(value, str):
            return None
        parsed = urlsplit(value.strip())
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port is not None
            or (parsed.hostname or "").lower() != expected_host
        ):
            return None
        return value.strip()

    @staticmethod
    def _locations(
        info: dict[str, Any],
        listing: dict[str, Any],
        country_code: str | None,
        country_name: str | None,
    ) -> list[dict[str, Any]]:
        candidates: list[Any] = [info.get("location")]
        additional = info.get("additionalLocations")
        if isinstance(additional, list):
            candidates.extend(additional)
        elif additional:
            candidates.append(additional)
        requisition_location = info.get("jobRequisitionLocation")
        if requisition_location:
            candidates.append(requisition_location)
        if listing.get("locationsText"):
            candidates.append(listing["locationsText"])

        locations: list[dict[str, Any]] = []
        seen: set[str] = set()
        for candidate in candidates:
            if isinstance(candidate, dict):
                display = next(
                    (
                        candidate.get(key)
                        for key in ("descriptor", "name", "location")
                        if candidate.get(key)
                    ),
                    None,
                )
            else:
                display = candidate
            if not isinstance(display, str):
                continue
            clean = re.sub(r"\s+", " ", display).strip()
            if not clean or LOCATION_COUNT_RE.fullmatch(clean):
                continue
            key = clean.casefold()
            if key in seen:
                continue
            seen.add(key)
            code, name = normalize_country(None, clean)
            is_primary = not locations
            locations.append(
                {
                    "display": clean,
                    "country_code": country_code if is_primary else code,
                    "country": country_name if is_primary else name,
                    "is_primary": is_primary,
                }
            )
        return locations

    @staticmethod
    def _location_summary(locations: list[dict[str, Any]]) -> str | None:
        if not locations:
            return None
        joined = " · ".join(location["display"] for location in locations)
        if len(joined) <= 500:
            return joined
        return f"{locations[0]['display']} + {len(locations) - 1} more"[:500]
