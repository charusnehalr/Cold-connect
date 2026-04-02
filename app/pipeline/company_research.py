import logging

from app.models.schemas import Company
from app.services.groq_client import GroqClient
from app.services.linkedin_mcp import LinkedInMCPClient

logger = logging.getLogger(__name__)


class CompanyResearch:
    def __init__(self, linkedin: LinkedInMCPClient, groq: GroqClient):
        self._linkedin = linkedin
        self._groq = groq

    async def research(self, linkedin_url: str, session) -> Company:
        """Fetch company profile + posts and return a structured Company object."""
        profile = {}
        posts_data = {}

        # Fetch profile
        try:
            profile = await self._linkedin.get_company_profile(session, linkedin_url)
            logger.info("Fetched company profile for %s", linkedin_url)
        except Exception as e:
            logger.warning("Company profile fetch failed: %s", e)

        # Fetch posts (separate call)
        try:
            posts_data = await self._linkedin.get_company_posts(session, linkedin_url)
            logger.info("Fetched company posts for %s", linkedin_url)
        except Exception as e:
            logger.warning("Company posts fetch failed: %s", e)

        # Build Company from raw data
        name = _extract(profile, "name", "company_name") or linkedin_url.split("/company/")[1].rstrip("/").replace("-", " ").title()
        industry = _extract(profile, "industry")
        size = _extract(profile, "company_size", "size", "employee_count")
        website = _extract(profile, "website", "url")

        # Summarize description using Groq
        raw_description = _extract(profile, "description", "about", "tagline") or ""
        description = await self._summarize_description(name, raw_description)

        # Extract recent post summaries (max 3)
        recent_posts = _extract_posts(posts_data)

        return Company(
            name=name,
            linkedin_url=linkedin_url,
            website=website,
            industry=industry,
            size=str(size) if size else None,
            description=description,
            recent_posts=recent_posts,
        )

    async def _summarize_description(self, company_name: str, raw: str) -> str | None:
        if not raw:
            return None
        truncated = self._groq.truncate_to_tokens(raw, 1500)
        resp = await self._groq.complete_light([
            {"role": "system", "content": "Summarize company descriptions in 2-3 sentences. Be factual and concise."},
            {"role": "user", "content": f"Company: {company_name}\n\nDescription: {truncated}"},
        ])
        return resp.strip()


def _extract(data: dict, *keys: str):
    """Try multiple keys and return the first non-empty value found."""
    for key in keys:
        val = data.get(key)
        if val:
            return val
    return None


def _extract_posts(posts_data: dict) -> list[str]:
    """Extract up to 3 post summaries from raw posts data."""
    if not posts_data:
        return []

    posts = posts_data if isinstance(posts_data, list) else posts_data.get("posts", posts_data.get("results", []))
    summaries = []
    for post in posts[:3]:
        text = ""
        if isinstance(post, dict):
            text = post.get("text", post.get("content", post.get("commentary", "")))
        elif isinstance(post, str):
            text = post
        if text:
            # Truncate to a 1-line summary
            summary = text.split("\n")[0][:200]
            summaries.append(summary)
    return summaries
