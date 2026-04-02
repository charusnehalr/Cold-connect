import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


class WebSearch:
    """DuckDuckGo search wrapper. No API key required."""

    def __init__(self):
        self._cache: dict[str, list[SearchResult]] = {}

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        if query in self._cache:
            logger.debug("WebSearch cache hit: %s", query)
            return self._cache[query]

        results = await asyncio.to_thread(self._sync_search, query, max_results)
        self._cache[query] = results
        logger.debug("WebSearch '%s' → %d results", query, len(results))
        return results

    @staticmethod
    def _sync_search(query: str, max_results: int) -> list[SearchResult]:
        try:
            from ddgs import DDGS
            with DDGS() as ddgs:
                hits = ddgs.text(query, max_results=max_results)
                return [
                    SearchResult(
                        title=h.get("title", ""),
                        url=h.get("href", ""),
                        snippet=h.get("body", ""),
                    )
                    for h in (hits or [])
                ]
        except Exception as e:
            logger.warning("Web search failed for '%s': %s", query, e)
            return []

    async def find_linkedin_company_url(self, company_name: str) -> str | None:
        """Search DuckDuckGo to find a company's LinkedIn page URL."""
        for query in [
            f"{company_name} site:linkedin.com/company",
            f"{company_name} LinkedIn company page",
        ]:
            results = await self.search(query, max_results=5)
            for r in results:
                if "linkedin.com/company/" in r.url:
                    logger.info("Found LinkedIn URL for '%s': %s", company_name, r.url)
                    return r.url
        return None
