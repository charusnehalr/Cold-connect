import logging
from datetime import datetime, timedelta
from pathlib import Path

from app.config import settings
from app.models.schemas import (
    CompanyStatus,
    PersonResult,
    PersonStatus,
    PipelineResult,
    TrackedCompany,
    TrackedPerson,
)
from app.tracker.store import JSONStore

logger = logging.getLogger(__name__)


class TrackerManager:
    """High-level tracking operations backed by a JSON file."""

    def __init__(self, path: Path | None = None):
        self._store = JSONStore(path or settings.tracker_path)
        self._data: dict = {"version": 1, "companies": []}

    async def load(self) -> None:
        self._data = await self._store.load()

    # ------------------------------------------------------------------
    # Save pipeline results
    # ------------------------------------------------------------------

    async def save_pipeline_result(self, result: PipelineResult) -> TrackedCompany:
        tracked_people = [
            TrackedPerson(
                person=pr.person,
                message=pr.message,
                why_connect=pr.why_connect,
            )
            for pr in result.people
        ]

        tracked = TrackedCompany(
            company=result.company,
            people=tracked_people,
            status=CompanyStatus.RESEARCHED,
        )

        self._data["companies"].append(tracked.model_dump())
        await self._store.save(self._data)
        logger.info("Saved company '%s' with %d people", result.company.name, len(tracked_people))
        return tracked

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_all_companies(self) -> list[TrackedCompany]:
        return [TrackedCompany(**c) for c in self._data.get("companies", [])]

    def get_company_by_name(self, name: str) -> TrackedCompany | None:
        name_lower = name.lower()
        for c in self._data.get("companies", []):
            if name_lower in c["company"]["name"].lower():
                return TrackedCompany(**c)
        return None

    def has_company(self, linkedin_url: str) -> TrackedCompany | None:
        """Return the most recent TrackedCompany for this URL, or None."""
        matches = [
            c for c in self._data.get("companies", [])
            if c["company"]["linkedin_url"].rstrip("/") == linkedin_url.rstrip("/")
        ]
        if not matches:
            return None
        return TrackedCompany(**matches[-1])

    def find_person(self, name: str) -> list[tuple[TrackedCompany, TrackedPerson]]:
        """Fuzzy name search across all companies. Returns (company, person) pairs."""
        name_lower = name.lower()
        results = []
        for c in self._data.get("companies", []):
            company = TrackedCompany(**c)
            for p in company.people:
                if name_lower in p.person.name.lower():
                    results.append((company, p))
        return results

    def get_pending_followups(self, days: int | None = None) -> list[tuple[TrackedCompany, TrackedPerson]]:
        """People marked 'sent' more than `days` days ago."""
        threshold = timedelta(days=days or settings.followup_days_threshold)
        cutoff = datetime.utcnow() - threshold
        results = []
        for c in self._data.get("companies", []):
            company = TrackedCompany(**c)
            for p in company.people:
                if p.status == PersonStatus.SENT and p.sent_at and p.sent_at < cutoff:
                    results.append((company, p))
        return results

    def get_stats(self) -> dict:
        companies = self.get_all_companies()
        all_people = [p for c in companies for p in c.people]
        status_counts = {s.value: 0 for s in PersonStatus}
        for p in all_people:
            status_counts[p.status.value] += 1

        accepted = status_counts.get("accepted", 0)
        sent = status_counts.get("sent", 0)
        acceptance_rate = round(accepted / (sent + accepted) * 100, 1) if (sent + accepted) > 0 else 0.0

        return {
            "total_companies": len(companies),
            "total_people": len(all_people),
            "status_breakdown": status_counts,
            "acceptance_rate_pct": acceptance_rate,
        }

    # ------------------------------------------------------------------
    # Updates
    # ------------------------------------------------------------------

    async def update_person_status(
        self, person_id: str, status: PersonStatus
    ) -> bool:
        for c in self._data.get("companies", []):
            for p in c.get("people", []):
                if p["id"] == person_id:
                    p["status"] = status.value
                    if status == PersonStatus.SENT:
                        p["sent_at"] = datetime.utcnow().isoformat()
                    elif status == PersonStatus.ACCEPTED:
                        p["accepted_at"] = datetime.utcnow().isoformat()
                    await self._store.save(self._data)
                    logger.info("Updated person %s → %s", person_id, status.value)
                    return True
        return False
