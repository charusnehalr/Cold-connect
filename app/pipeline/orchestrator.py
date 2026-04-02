import asyncio
import logging
import time

from app.config import settings
from app.models.schemas import Company, PipelineResult
from app.pipeline.company_research import CompanyResearch
from app.pipeline.input_parser import CompanyNotFoundError, InputParser, ParsedInput
from app.pipeline.message_generator import MessageGenerator
from app.pipeline.people_finder import PeopleFinder
from app.services.linkedin_mcp import LinkedInMCPClient, MCPServerUnavailableError
from app.tracker.manager import TrackerManager

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(
        self,
        input_parser: InputParser,
        company_research: CompanyResearch,
        people_finder: PeopleFinder,
        message_generator: MessageGenerator,
        linkedin: LinkedInMCPClient,
        tracker: TrackerManager,
    ):
        self._parser = input_parser
        self._research = company_research
        self._finder = people_finder
        self._generator = message_generator
        self._linkedin = linkedin
        self._tracker = tracker

    async def run(self, raw_input: str, user_bio: str) -> list[PipelineResult]:
        """
        Full pipeline for one raw user input (may contain multiple companies).
        Returns a list of PipelineResults (one per company).
        """
        # Step 1: Parse input into company/URL pairs
        try:
            parsed_list = await self._parser.parse(raw_input)
        except CompanyNotFoundError as e:
            return [PipelineResult(
                company=Company(name=raw_input, linkedin_url=""),
                errors=[str(e)],
            )]

        results = []
        for parsed in parsed_list:
            result = await self._run_one(parsed, user_bio)
            results.append(result)

        return results

    async def _run_one(self, parsed: ParsedInput, user_bio: str) -> PipelineResult:
        t_start = time.monotonic()
        errors: list[str] = []

        logger.info("Pipeline start: %s (%s)", parsed.company_name, parsed.linkedin_url)

        try:
            result = await asyncio.wait_for(
                self._pipeline(parsed, user_bio, errors),
                timeout=settings.pipeline_timeout_seconds,
            )
        except asyncio.TimeoutError:
            errors.append(f"Pipeline timed out after {settings.pipeline_timeout_seconds}s")
            result = PipelineResult(
                company=Company(name=parsed.company_name, linkedin_url=parsed.linkedin_url),
                errors=errors,
                duration_seconds=time.monotonic() - t_start,
            )
        except MCPServerUnavailableError as e:
            errors.append(str(e))
            result = PipelineResult(
                company=Company(name=parsed.company_name, linkedin_url=parsed.linkedin_url),
                errors=errors,
                duration_seconds=time.monotonic() - t_start,
            )

        result.duration_seconds = time.monotonic() - t_start
        logger.info("Pipeline done: %s in %.1fs — %d people, %d errors",
                    parsed.company_name, result.duration_seconds,
                    len(result.people), len(result.errors))

        # Save to tracker regardless of partial failures
        if result.people or not errors:
            try:
                await self._tracker.save_pipeline_result(result)
            except Exception as e:
                logger.error("Tracker save failed: %s", e)

        return result

    async def _pipeline(
        self, parsed: ParsedInput, user_bio: str, errors: list[str]
    ) -> PipelineResult:
        company = Company(name=parsed.company_name, linkedin_url=parsed.linkedin_url)

        async with self._linkedin.session() as session:
            # Step 2: Company research
            t0 = time.monotonic()
            try:
                company = await self._research.research(parsed.linkedin_url, session)
            except Exception as e:
                errors.append(f"Company research failed: {e}")
                logger.warning("Company research failed, continuing with partial data: %s", e)
            logger.info("Step: company_research %.1fs", time.monotonic() - t0)

            # Step 3: Find people
            t0 = time.monotonic()
            people = []
            try:
                people = await self._finder.find_people_with_session(
                    company.name, _default_roles(), session,
                )
            except Exception as e:
                errors.append(f"People finder failed: {e}")
                logger.warning("People finder failed: %s", e)
            logger.info("Step: people_finder %.1fs (%d people)", time.monotonic() - t0, len(people))

            if not people:
                errors.append("No people found at this company.")
                return PipelineResult(company=company, errors=errors)

        # Step 4: Generate messages (no MCP session needed)
        t0 = time.monotonic()
        person_results = []
        try:
            person_results = await self._generator.generate_all(company, people, user_bio)
        except Exception as e:
            errors.append(f"Message generation failed: {e}")
            logger.warning("Message generation failed: %s", e)
        logger.info("Step: message_generator %.1fs", time.monotonic() - t0)

        return PipelineResult(company=company, people=person_results, errors=errors)


def _default_roles() -> list[str]:
    return [
        "founder OR co-founder OR CEO",
        "CTO OR VP engineering OR head of engineering",
        "recruiter OR talent acquisition OR hiring manager",
        "senior engineer OR staff engineer OR principal engineer",
        "tech lead OR engineering manager",
    ]
