from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from time import perf_counter
from typing import Iterable
from hunt_board.core.observability import metrics


logger = logging.getLogger("hunt_board")


JOB_FAMILIES: tuple[tuple[str, str], ...] = (
    ("software-engineering", "Software and engineering"),
    ("data-analytics", "Data and analytics"),
    ("product-management", "Product management"),
    ("design-user-experience", "Design and user experience"),
    ("finance-accounting", "Finance and accounting"),
    ("consulting-strategy", "Consulting and strategy"),
    ("marketing-communications", "Marketing and communications"),
    ("sales-business-development", "Sales and business development"),
    ("operations-supply-chain", "Operations and supply chain"),
    ("human-resources-recruiting", "Human resources and recruiting"),
    ("legal-compliance", "Legal and compliance"),
    ("research", "Research"),
    ("other", "Other"),
)
JOB_FAMILY_SLUGS = frozenset(slug for slug, _ in JOB_FAMILIES)


# One central rule table is used for source labels, titles, and descriptions.
# Phrase ordering is immaterial; scoring and taxonomy order break ties.
FAMILY_RULES: dict[str, dict[str, tuple[str, ...]]] = {
    "software-engineering": {
        "source": ("engineering", "software engineering", "technology", "information technology"),
        "title": ("software engineer", "software developer", "frontend", "front end", "backend", "back end", "full stack", "platform engineer", "devops", "site reliability", "mobile engineer", "security engineer", "qa engineer"),
        "description": ("software development", "distributed systems", "production code", "web application"),
    },
    "data-analytics": {
        "source": ("data", "analytics", "business intelligence", "data science"),
        "title": ("data analyst", "data scientist", "data engineer", "analytics", "business intelligence", "machine learning engineer", "quantitative analyst"),
        "description": ("data analysis", "statistical modeling", "business intelligence", "machine learning models"),
    },
    "product-management": {
        "source": ("product", "product management"),
        "title": ("product manager", "product owner", "product lead", "product operations"),
        "description": ("product roadmap", "product strategy", "user stories", "product requirements"),
    },
    "design-user-experience": {
        "source": ("design", "user experience", "creative"),
        "title": ("product designer", "ux designer", "ui designer", "user researcher", "visual designer", "content designer", "design systems"),
        "description": ("user experience", "interaction design", "design system", "user research"),
    },
    "finance-accounting": {
        "source": ("finance", "accounting", "tax", "treasury", "audit"),
        "title": ("financial analyst", "accountant", "controller", "auditor", "tax", "treasury", "finance manager", "bookkeeper", "investment analyst"),
        "description": ("financial reporting", "general ledger", "financial planning", "accounts payable", "accounts receivable"),
    },
    "consulting-strategy": {
        "source": ("consulting", "strategy", "corporate strategy"),
        "title": ("consultant", "strategy analyst", "strategy manager", "management consulting", "business strategist"),
        "description": ("client engagements", "strategic recommendations", "management consulting", "market entry"),
    },
    "marketing-communications": {
        "source": ("marketing", "communications", "brand", "public relations"),
        "title": ("marketing manager", "growth marketing", "content marketing", "communications", "brand manager", "public relations", "seo", "copywriter"),
        "description": ("marketing campaigns", "brand awareness", "content strategy", "media relations"),
    },
    "sales-business-development": {
        "source": ("sales", "business development", "revenue"),
        "title": ("account executive", "sales representative", "sales manager", "business development", "customer success", "partnerships manager", "sales development"),
        "description": ("sales pipeline", "revenue growth", "prospective customers", "quota attainment"),
    },
    "operations-supply-chain": {
        "source": ("operations", "supply chain", "procurement", "logistics", "manufacturing"),
        "title": ("operations manager", "operations analyst", "supply chain", "procurement", "logistics", "inventory", "program manager", "facilities manager"),
        "description": ("operational efficiency", "supply planning", "vendor management", "logistics operations"),
    },
    "human-resources-recruiting": {
        "source": ("people", "human resources", "recruiting", "talent"),
        "title": ("human resources", "hr business partner", "recruiter", "talent acquisition", "people operations", "compensation analyst"),
        "description": ("employee relations", "talent acquisition", "people programs", "human resources"),
    },
    "legal-compliance": {
        "source": ("legal", "compliance", "privacy", "risk"),
        "title": ("legal counsel", "attorney", "paralegal", "compliance", "privacy counsel", "contracts manager", "risk analyst"),
        "description": ("legal advice", "regulatory compliance", "contract negotiation", "privacy law"),
    },
    "research": {
        "source": ("research", "laboratory", "science"),
        "title": ("research scientist", "research associate", "researcher", "scientist", "economist", "lab technician", "postdoctoral"),
        "description": ("research studies", "scientific research", "experimental design", "peer reviewed"),
    },
}


@dataclass(frozen=True)
class ClassificationResult:
    family_slug: str
    confidence: float
    method: str
    reason: str


def _normalized(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def _matches(value: str, phrases: Iterable[str]) -> list[str]:
    padded = f" {value} "
    return sorted(
        {phrase for phrase in phrases if f" {_normalized(phrase)} " in padded},
        key=lambda phrase: (-len(phrase), phrase),
    )


def _best(value: str | None, layer: str) -> tuple[str, list[str]] | None:
    normalized = _normalized(value)
    if not normalized:
        return None
    candidates: list[tuple[int, int, str, list[str]]] = []
    order = {slug: index for index, (slug, _) in enumerate(JOB_FAMILIES)}
    for slug, rules in FAMILY_RULES.items():
        hits = _matches(normalized, rules[layer])
        if hits:
            candidates.append((sum(len(hit.split()) for hit in hits), -order[slug], slug, hits))
    if not candidates:
        return None
    _, _, slug, hits = max(candidates)
    return slug, hits


def classify_job(
    *,
    department: str | None,
    title: str,
    description: str | None = None,
) -> ClassificationResult:
    started = perf_counter()
    result: ClassificationResult
    source_match = _best(department, "source")
    if source_match:
        slug, hits = source_match
        result = ClassificationResult(slug, 0.96, "source_category", f"Source category matched: {', '.join(hits[:3])}")
    else:
        title_match = _best(title, "title")
        if title_match:
            slug, hits = title_match
            confidence = min(0.92, 0.72 + 0.04 * sum(len(hit.split()) for hit in hits))
            result = ClassificationResult(slug, confidence, "title_keyword", f"Title matched: {', '.join(hits[:3])}")
        else:
            description_match = _best(description, "description")
            if description_match:
                slug, hits = description_match
                result = ClassificationResult(slug, 0.62, "description_keyword", f"Description matched: {', '.join(hits[:3])}")
            else:
                result = ClassificationResult("other", 0.0, "fallback", "Insufficient classification evidence")
    logger.info(
        "classification.completed" if result.family_slug != "other" else "classification.fallback",
        extra={
            "event_name": "classification.completed" if result.family_slug != "other" else "classification.fallback",
            "event_data": {
                "family": result.family_slug,
                "method": result.method,
                "confidence_bucket": confidence_bucket(result.confidence),
                "duration_ms": round((perf_counter() - started) * 1000, 3),
            },
        },
    )
    metrics.observe_classification(result.family_slug, result.method, confidence_bucket(result.confidence))
    return result


def confidence_bucket(value: float) -> str:
    if value >= 0.9:
        return "high"
    if value >= 0.6:
        return "medium"
    return "low"


def apply_classification(job: object, result: ClassificationResult) -> bool:
    """Apply a result unless an administrator override is present."""
    if getattr(job, "classification_overridden_at", None) is not None:
        logger.info(
            "classification.override",
            extra={
                "event_name": "classification.override",
                "event_data": {"job_id": getattr(job, "id", None), "family": getattr(job, "job_family_slug", "other")},
            },
        )
        return False
    job.job_family_slug = result.family_slug
    job.classification_confidence = result.confidence
    job.classification_method = result.method
    job.classification_reason = result.reason
    return True
