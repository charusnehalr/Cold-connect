import asyncio
import logging

from app.config import settings
from app.models.schemas import Person, RoleCategory
from app.services.linkedin_mcp import LinkedInMCPClient

logger = logging.getLogger(__name__)

_ROLE_CATEGORY_MAP = {
    0: RoleCategory.FOUNDER,
    1: RoleCategory.ENGINEERING_LEADER,
    2: RoleCategory.RECRUITER,
    3: RoleCategory.SENIOR_ENGINEER,
    4: RoleCategory.TECH_LEAD,
}


class PeopleFinder:
    def __init__(self, linkedin: LinkedInMCPClient):
        self._linkedin = linkedin

    async def find_people_with_session(
        self, company_name: str, target_roles: list[str], session
    ) -> list[Person]:
        """
        Search for up to MAX_PEOPLE_PER_COMPANY unique people at the company.
        Runs sequentially with a delay between each MCP call to avoid rate limits.
        """
        found: list[Person] = []
        seen_urls: set[str] = set()

        for idx, role_query in enumerate(target_roles):
            if len(found) >= settings.max_people_per_company:
                break

            keywords = f"{role_query} at {company_name}"
            logger.info("Searching people: '%s'", keywords)

            try:
                results = await self._linkedin.search_people(session, keywords, limit=5)
            except Exception as e:
                logger.warning("search_people failed for '%s': %s", keywords, e)
                await asyncio.sleep(settings.mcp_call_delay_seconds)
                continue

            for result in results:
                if len(found) >= settings.max_people_per_company:
                    break

                profile_url = _extract_url(result)
                if not profile_url or profile_url in seen_urls:
                    continue

                seen_urls.add(profile_url)
                await asyncio.sleep(settings.mcp_call_delay_seconds)

                try:
                    raw = await self._linkedin.get_person_profile(session, profile_url)
                    person = _build_person(raw, profile_url, _ROLE_CATEGORY_MAP.get(idx, RoleCategory.SENIOR_ENGINEER))
                    if person:
                        found.append(person)
                        logger.info("Found: %s — %s", person.name, person.title)
                except Exception as e:
                    logger.warning("get_person_profile failed for %s: %s", profile_url, e)

            await asyncio.sleep(settings.mcp_call_delay_seconds)

        logger.info("PeopleFinder: %d people found for '%s'", len(found), company_name)
        return found


def _extract_url(result: dict) -> str | None:
    return (
        result.get("profile_url")
        or result.get("linkedin_url")
        or result.get("url")
        or result.get("link")
    )


def _build_person(raw: dict, url: str, role_category: RoleCategory) -> Person | None:
    name = raw.get("name", raw.get("full_name", ""))
    title = raw.get("headline", raw.get("title", raw.get("current_position", "")))

    if not name:
        return None

    posts = raw.get("posts", [])
    post_texts = []
    for p in posts[:3]:
        text = p.get("text", p.get("content", "")) if isinstance(p, dict) else str(p)
        if text:
            post_texts.append(text[:200])

    interests = raw.get("interests", [])
    if isinstance(interests, list):
        interests = [str(i) for i in interests[:5]]

    experience = raw.get("experience", [])
    exp_summary = ""
    if experience and isinstance(experience, list):
        parts = []
        for e in experience[:3]:
            if isinstance(e, dict):
                role = e.get("title", "")
                company = e.get("company", e.get("company_name", ""))
                if role or company:
                    parts.append(f"{role} at {company}".strip(" at"))
        exp_summary = " → ".join(parts)

    return Person(
        name=name,
        title=title or "Professional",
        linkedin_url=url,
        location=raw.get("location", raw.get("geo", "")),
        about=raw.get("about", raw.get("summary", "")),
        experience_summary=exp_summary,
        recent_posts=post_texts,
        interests=interests,
        role_category=role_category,
    )
