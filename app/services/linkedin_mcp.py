import asyncio
import json
import logging
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from app.config import settings

logger = logging.getLogger(__name__)


class MCPServerUnavailableError(Exception):
    pass


class MCPTimeoutError(Exception):
    pass


class LinkedInAuthError(Exception):
    pass


class LinkedInRateLimitError(Exception):
    pass


class LinkedInMCPClient:
    """
    Wraps the LinkedIn MCP server over streamable HTTP.

    Usage — one session per pipeline run:
        async with client.session() as s:
            result = await client.search_people(s, "founder at Anthropic")
            profile = await client.get_person_profile(s, result[0]["url"])
    """

    def __init__(self, url: str | None = None):
        self.url = url or settings.mcp_server_url

    # ------------------------------------------------------------------
    # Session context manager
    # ------------------------------------------------------------------

    class _Session:
        def __init__(self, url: str):
            self._url = url
            self._transport_cm = None
            self._session_cm = None
            self.session: ClientSession | None = None

        async def __aenter__(self):
            try:
                self._transport_cm = streamablehttp_client(self._url)
                read, write, _ = await self._transport_cm.__aenter__()
                self.session = ClientSession(read, write)
                await self.session.__aenter__()
                await self.session.initialize()
                return self
            except ConnectionRefusedError as e:
                raise MCPServerUnavailableError(
                    "LinkedIn MCP server is not running. Start it with: "
                    "uvx linkedin-scraper-mcp --transport streamable-http --port 8080"
                ) from e

        async def __aexit__(self, *args):
            if self.session:
                await self.session.__aexit__(*args)
            if self._transport_cm:
                await self._transport_cm.__aexit__(*args)

    def session(self) -> "_Session":
        """Open a session for one pipeline run. Use as: async with client.session() as s."""
        return self._Session(self.url)

    # ------------------------------------------------------------------
    # Tool calls (all require an active session)
    # ------------------------------------------------------------------

    async def get_company_profile(
        self, s: "_Session", url: str, sections: list[str] | None = None
    ) -> dict:
        return await self._call(s, "get_company_profile", {
            "url": url,
            "sections": sections or ["posts", "jobs"],
        })

    async def get_company_posts(self, s: "_Session", url: str) -> dict:
        return await self._call(s, "get_company_posts", {"url": url})

    async def search_people(self, s: "_Session", keywords: str, limit: int = 5) -> list[dict]:
        result = await self._call(s, "search_people", {"keywords": keywords, "limit": limit})
        if isinstance(result, list):
            return result
        return result.get("results", [])

    async def get_person_profile(
        self, s: "_Session", url: str, sections: list[str] | None = None
    ) -> dict:
        return await self._call(s, "get_person_profile", {
            "url": url,
            "sections": sections or ["experience", "education", "posts", "interests"],
        })

    async def search_jobs(self, s: "_Session", keywords: str, location: str = "") -> list[dict]:
        result = await self._call(s, "search_jobs", {"keywords": keywords, "location": location})
        if isinstance(result, list):
            return result
        return result.get("results", [])

    async def health_check(self) -> bool:
        try:
            async with self.session() as s:
                await self._call(s, "get_company_profile", {
                    "url": "https://www.linkedin.com/company/linkedin/",
                    "sections": [],
                })
            return True
        except MCPServerUnavailableError:
            return False
        except Exception as e:
            logger.warning("Health check failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # Internal call helper
    # ------------------------------------------------------------------

    async def _call(self, s: "_Session", tool: str, args: dict) -> Any:
        try:
            result = await asyncio.wait_for(
                s.session.call_tool(tool, args),
                timeout=settings.mcp_call_timeout_seconds,
            )
        except asyncio.TimeoutError:
            raise MCPTimeoutError(
                f"MCP tool '{tool}' timed out after {settings.mcp_call_timeout_seconds}s"
            )

        if not result.content:
            return {}

        raw = result.content[0].text
        logger.debug("MCP %s → %.300s", tool, raw)

        # Detect LinkedIn auth/rate-limit errors in the response text
        if isinstance(raw, str):
            lower = raw.lower()
            if "authwall" in lower or "sign in" in lower:
                raise LinkedInAuthError(
                    "LinkedIn session expired. Run: uvx linkedin-scraper-mcp --login"
                )
            if "rate limit" in lower or "too many requests" in lower:
                raise LinkedInRateLimitError("LinkedIn rate limit hit. Wait before retrying.")

        # Parse JSON string responses
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"raw": raw}

        return raw
