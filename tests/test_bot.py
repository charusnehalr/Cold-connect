"""
Minimal bot test — no LinkedIn MCP or Groq required.
Tests all commands and the message handler with a fake pipeline response.
Run from cold-connect/ directory:
    python test_bot.py
"""
import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

from app.config import settings
from app.tracker.manager import TrackerManager
from app.models.schemas import (
    Company, Person, GeneratedMessage, PersonResult, PipelineResult, RoleCategory
)


# --- Fake orchestrator that returns dummy data instantly (no LinkedIn/Groq) ---
class FakeOrchestrator:
    async def run(self, raw_input: str, user_bio: str) -> list[PipelineResult]:
        company = Company(
            name=raw_input.strip().title(),
            linkedin_url=f"https://www.linkedin.com/company/{raw_input.lower().replace(' ', '-')}/",
            industry="Artificial Intelligence",
            size="50-200 employees",
            description=f"{raw_input.title()} is a cutting-edge AI startup building the future.",
            recent_posts=["Just shipped a major model update!", "Hiring senior engineers — apply now."],
        )

        people = [
            PersonResult(
                person=Person(
                    name="Alice Chen",
                    title="Co-founder & CEO",
                    linkedin_url="https://www.linkedin.com/in/alicechen/",
                    location="San Francisco, CA",
                    about="Building AI tools that actually work.",
                    role_category=RoleCategory.FOUNDER,
                ),
                message=GeneratedMessage(
                    text=f"Alice, your work on {raw_input.title()}'s founding story resonates — I'm building similar infra tools. Would love to connect.",
                    angle="shared founder journey",
                ),
                why_connect="Both building AI developer tools from scratch",
            ),
            PersonResult(
                person=Person(
                    name="Bob Sharma",
                    title="VP of Engineering",
                    linkedin_url="https://www.linkedin.com/in/bobsharma/",
                    location="New York, NY",
                    about="Scaling engineering teams at high-growth startups.",
                    role_category=RoleCategory.ENGINEERING_LEADER,
                ),
                message=GeneratedMessage(
                    text=f"Bob, saw your post on distributed systems at {raw_input.title()} — tackling the same scaling challenges. Would love to connect.",
                    angle="shared engineering challenges",
                ),
                why_connect="Both focused on scaling distributed systems",
            ),
            PersonResult(
                person=Person(
                    name="Carol Kim",
                    title="Senior Software Engineer",
                    linkedin_url="https://www.linkedin.com/in/carolkim/",
                    location="Austin, TX",
                    about="ML infra and developer tooling.",
                    role_category=RoleCategory.SENIOR_ENGINEER,
                ),
                message=GeneratedMessage(
                    text="Carol, your ML infra work caught my eye — building similar tooling on my end. Would love to swap notes.",
                    angle="shared ML infrastructure interest",
                ),
                why_connect="Both working on ML infrastructure tooling",
            ),
        ]

        return [PipelineResult(company=company, people=people, errors=[], duration_seconds=1.5)]


async def init():
    tracker = TrackerManager()
    await tracker.load()

    from app.bot.setup import build_application
    application = build_application(
        orchestrator=FakeOrchestrator(),
        tracker=tracker,
    )
    return application


def main():
    logger.info("Starting bot in TEST MODE (no LinkedIn/Groq)")

    loop = asyncio.new_event_loop()
    application = loop.run_until_complete(init())
    loop.close()

    logger.info("Bot started. Open Telegram and message your bot.")
    logger.info("Try: /start  /setbio  /help  or just type a company name like 'Anthropic'")

    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
