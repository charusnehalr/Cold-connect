import asyncio
import logging

from app.config import settings
from app.models.schemas import Company, GeneratedMessage, Person, PersonResult
from app.services.groq_client import GroqClient

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You write personalized LinkedIn connection request messages.

Rules:
- The message MUST be under 300 characters. This is a hard LinkedIn limit.
- Reference specific details: their work, recent posts, interests, or company.
- Never use generic phrases like "I came across your profile" or "I'd love to connect."
- Match their communication style: casual for startup founders, formal for enterprise execs.
- Return valid JSON with exactly two fields: "message" (string) and "why_connect" (string, 1 sentence).
"""


class MessageGenerator:
    def __init__(self, groq: GroqClient):
        self._groq = groq

    async def generate_all(
        self, company: Company, people: list[Person], user_bio: str
    ) -> list[PersonResult]:
        results = []
        for person in people:
            try:
                result = await self.generate_one(company, person, user_bio)
                results.append(result)
            except Exception as e:
                logger.warning("Message generation failed for %s: %s", person.name, e)
                results.append(PersonResult(
                    person=person,
                    message=GeneratedMessage(text="", angle="generation_failed"),
                    why_connect="",
                ))
            await asyncio.sleep(1)  # Respect Groq 30 RPM limit
        return results

    async def generate_one(
        self, company: Company, person: Person, user_bio: str
    ) -> PersonResult:
        prompt = _build_prompt(company, person, user_bio)

        data = await self._groq.complete_json(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            model=settings.groq_model_heavy,
        )

        message_text = str(data.get("message", "")).strip()
        why_connect = str(data.get("why_connect", "")).strip()
        angle = str(data.get("angle", "")).strip()

        # Enforce 300-character limit
        if len(message_text) > settings.linkedin_message_char_limit:
            logger.info("Message too long (%d chars) — shortening", len(message_text))
            message_text = await self._shorten(message_text)

        return PersonResult(
            person=person,
            message=GeneratedMessage(text=message_text, angle=angle),
            why_connect=why_connect,
        )

    async def _shorten(self, message: str) -> str:
        resp = await self._groq.complete_light([
            {"role": "system", "content": "You shorten LinkedIn connection messages. Keep personalization. Return ONLY the shortened message text, no quotes."},
            {"role": "user", "content": f"Shorten this to under 300 characters:\n\n{message}"},
        ])
        shortened = resp.strip().strip('"').strip("'")
        if len(shortened) > settings.linkedin_message_char_limit:
            shortened = shortened[:settings.linkedin_message_char_limit - 3] + "..."
        return shortened


def _build_prompt(company: Company, person: Person, user_bio: str) -> str:
    parts = [
        f"MY BIO: {user_bio}",
        "",
        f"COMPANY: {company.name}",
    ]
    if company.industry:
        parts.append(f"Industry: {company.industry}")
    if company.description:
        parts.append(f"About: {company.description}")
    if company.recent_posts:
        parts.append(f"Recent post: {company.recent_posts[0]}")

    parts += [
        "",
        f"PERSON: {person.name}",
        f"Title: {person.title}",
    ]
    if person.location:
        parts.append(f"Location: {person.location}")
    if person.about:
        about = person.about[:500]
        parts.append(f"About: {about}")
    if person.experience_summary:
        parts.append(f"Experience: {person.experience_summary}")
    if person.recent_posts:
        parts.append(f"Recent post: {person.recent_posts[0]}")
    if person.interests:
        parts.append(f"Interests: {', '.join(person.interests[:3])}")

    return "\n".join(parts)
