import logging
import re
from dataclasses import dataclass

from app.services.groq_client import GroqClient
from app.services.web_search import WebSearch

logger = logging.getLogger(__name__)

_LINKEDIN_COMPANY_RE = re.compile(r"https?://(?:www\.)?linkedin\.com/company/[^/\s?]+", re.I)
_LINKEDIN_PERSON_RE = re.compile(r"https?://(?:www\.)?linkedin\.com/in/[^/\s?]+", re.I)
_URL_RE = re.compile(r"https?://\S+", re.I)


@dataclass
class ParsedInput:
    company_name: str
    linkedin_url: str


class CompanyNotFoundError(Exception):
    pass


class InputParser:
    def __init__(self, groq: GroqClient, search: WebSearch):
        self._groq = groq
        self._search = search

    async def parse(self, raw: str) -> list[ParsedInput]:
        """
        Parse raw user input into one or more ParsedInput objects.
        Handles: company names, LinkedIn URLs, website URLs, article URLs,
        comma-separated multiple companies.
        """
        raw = raw.strip()

        # Split comma-separated inputs
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if len(parts) > 1:
            results = []
            for part in parts:
                try:
                    parsed = await self._parse_single(part)
                    results.append(parsed)
                except CompanyNotFoundError as e:
                    logger.warning("Skipping '%s': %s", part, e)
            return results

        return [await self._parse_single(raw)]

    async def _parse_single(self, text: str) -> ParsedInput:
        # Case 1: LinkedIn company URL directly
        match = _LINKEDIN_COMPANY_RE.search(text)
        if match:
            url = match.group(0).rstrip("/") + "/"
            name = url.split("/company/")[1].rstrip("/").replace("-", " ").title()
            logger.info("Direct LinkedIn company URL: %s", url)
            return ParsedInput(company_name=name, linkedin_url=url)

        # Case 2: LinkedIn person URL — extract their company from name heuristic
        if _LINKEDIN_PERSON_RE.search(text):
            logger.info("LinkedIn person URL detected — searching for company")
            return await self._resolve_via_search(text)

        # Case 3: Any other URL (website, article)
        if _URL_RE.search(text):
            company_name = await self._extract_company_from_url(text)
            return await self._resolve_via_search(company_name)

        # Case 4: Plain company name
        return await self._resolve_via_search(text)

    async def _extract_company_from_url(self, url: str) -> str:
        """Use Groq 8B to guess the company name from a URL."""
        resp = await self._groq.complete_light([
            {"role": "system", "content": "You extract company names from URLs. Respond with ONLY the company name, nothing else."},
            {"role": "user", "content": f"What company is this URL from? {url}"},
        ])
        name = resp.strip().strip('"').strip("'")
        logger.info("Extracted company name from URL: '%s' → '%s'", url, name)
        return name

    async def _resolve_via_search(self, query: str) -> ParsedInput:
        """Search DuckDuckGo to find the LinkedIn company URL for a given query."""
        linkedin_url = await self._search.find_linkedin_company_url(query)

        if not linkedin_url:
            # Last resort: ask Groq to clarify the company name and try again
            clarified = await self._clarify_company_name(query)
            if clarified and clarified.lower() != query.lower():
                linkedin_url = await self._search.find_linkedin_company_url(clarified)
                query = clarified

        if not linkedin_url:
            raise CompanyNotFoundError(
                f"Could not find a LinkedIn page for '{query}'. "
                "Try sending the LinkedIn company URL directly."
            )

        # Extract a clean company name from the slug
        slug = linkedin_url.split("/company/")[1].rstrip("/")
        name = slug.replace("-", " ").title()

        logger.info("Resolved '%s' → %s", query, linkedin_url)
        return ParsedInput(company_name=name, linkedin_url=linkedin_url)

    async def _clarify_company_name(self, query: str) -> str:
        resp = await self._groq.complete_light([
            {"role": "system", "content": "You are a company name normalizer. Given any text, return ONLY the most likely official company name, nothing else."},
            {"role": "user", "content": query},
        ])
        return resp.strip().strip('"').strip("'")
