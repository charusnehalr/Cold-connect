import asyncio
import logging
import logging.handlers
import sys

from app.config import settings


def setup_logging() -> None:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)

    file_handler = logging.handlers.RotatingFileHandler(
        settings.log_dir / "cold_connect.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    root.addHandler(console)
    root.addHandler(file_handler)


async def _init() -> tuple:
    """Initialize all services and return (application, tracker)."""
    logger = logging.getLogger(__name__)

    from app.services.groq_client import GroqClient
    from app.services.linkedin_mcp import LinkedInMCPClient
    from app.services.web_search import WebSearch

    groq = GroqClient()
    linkedin = LinkedInMCPClient()
    search = WebSearch()

    logger.info("Checking LinkedIn MCP server at %s ...", settings.mcp_server_url)
    healthy = await linkedin.health_check()
    if not healthy:
        logger.error(
            "LinkedIn MCP server is not reachable at %s\n"
            "Start it with: uvx linkedin-scraper-mcp --transport streamable-http --port 8080",
            settings.mcp_server_url,
        )
        sys.exit(1)
    logger.info("LinkedIn MCP server OK")

    from app.tracker.manager import TrackerManager
    tracker = TrackerManager()
    await tracker.load()
    logger.info("Tracker loaded")

    from app.pipeline.input_parser import InputParser
    from app.pipeline.company_research import CompanyResearch
    from app.pipeline.people_finder import PeopleFinder
    from app.pipeline.message_generator import MessageGenerator
    from app.pipeline.orchestrator import Orchestrator

    orchestrator = Orchestrator(
        input_parser=InputParser(groq=groq, search=search),
        company_research=CompanyResearch(linkedin=linkedin, groq=groq),
        people_finder=PeopleFinder(linkedin=linkedin),
        message_generator=MessageGenerator(groq=groq),
        linkedin=linkedin,
        tracker=tracker,
    )

    from app.bot.setup import build_application
    application = build_application(orchestrator=orchestrator, tracker=tracker)

    return application, tracker


def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Cold Connect starting...")

    # Run async init synchronously to get the application object
    loop = asyncio.new_event_loop()
    try:
        application, tracker = loop.run_until_complete(_init())
    finally:
        loop.close()

    logger.info("Cold Connect started. Polling for messages...")
    # run_polling is synchronous and manages its own event loop
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
