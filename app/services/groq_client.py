import json
import logging
import time
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqAuthError(Exception):
    pass


class GroqJSONParseError(Exception):
    def __init__(self, message: str, raw: str):
        super().__init__(message)
        self.raw = raw


class GroqClient:
    def __init__(self):
        self._headers = {
            "Authorization": f"Bearer {settings.groq_api_key}",
            "Content-Type": "application/json",
        }

    async def complete(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        async with httpx.AsyncClient(timeout=60) as client:
            for attempt in range(settings.max_retries + 1):
                import asyncio
                t0 = time.monotonic()
                resp = await client.post(_GROQ_API_URL, headers=self._headers, json=payload)
                latency = time.monotonic() - t0

                if resp.status_code == 200:
                    data = resp.json()
                    usage = data.get("usage", {})
                    logger.debug(
                        "Groq call | model=%s | in=%s out=%s tokens | %.2fs",
                        model,
                        usage.get("prompt_tokens", "?"),
                        usage.get("completion_tokens", "?"),
                        latency,
                    )
                    return data["choices"][0]["message"]["content"]

                if resp.status_code == 401:
                    raise GroqAuthError("Invalid Groq API key")

                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("retry-after", 5))
                    logger.warning("Groq rate limit — waiting %.1fs", retry_after)
                    await asyncio.sleep(retry_after)
                    continue

                if resp.status_code in (500, 502, 503) and attempt < settings.max_retries:
                    logger.warning("Groq %s — retrying (attempt %d)", resp.status_code, attempt + 1)
                    await asyncio.sleep(2)
                    continue

                resp.raise_for_status()

        raise RuntimeError("Groq request failed after retries")

    async def complete_light(self, messages: list[dict], max_tokens: int = 512) -> str:
        """Use for fast, simple tasks: parsing, summarization, shortening."""
        return await self.complete(
            messages,
            model=settings.groq_model_light,
            temperature=0.3,
            max_tokens=max_tokens,
        )

    async def complete_heavy(self, messages: list[dict], max_tokens: int = 1024) -> str:
        """Use for quality tasks: personalized message generation."""
        return await self.complete(
            messages,
            model=settings.groq_model_heavy,
            temperature=0.7,
            max_tokens=max_tokens,
        )

    async def complete_json(self, messages: list[dict], model: str | None = None) -> Any:
        """Call Groq and parse the response as JSON. Retries once on parse failure."""
        model = model or settings.groq_model_light
        patched = list(messages)
        if patched and patched[0]["role"] == "system":
            patched[0] = {
                "role": "system",
                "content": patched[0]["content"]
                + "\n\nRespond ONLY with valid JSON. No markdown, no code fences, no explanation.",
            }

        raw = ""
        for attempt in range(2):
            raw = await self.complete(patched, model=model, temperature=0.1, max_tokens=1024)
            cleaned = _strip_code_fences(raw)
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                logger.warning("JSON parse failed (attempt %d). Raw: %.200s", attempt + 1, cleaned)
                if attempt == 0:
                    patched.append({"role": "user", "content": "Please respond with valid JSON only."})

        raise GroqJSONParseError("Could not parse Groq response as JSON", raw)

    @staticmethod
    def truncate_to_tokens(text: str, max_tokens: int) -> str:
        """Rough truncation to stay within TPM limits (1 token ≈ 4 chars)."""
        max_chars = max_tokens * 4
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "..."


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner = lines[1:]
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        text = "\n".join(inner).strip()
    return text
