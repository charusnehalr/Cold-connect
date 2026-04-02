import asyncio
import logging
import uuid
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from app.bot.formatter import (
    format_company_card,
    format_error,
    format_list,
    format_person_card,
    format_stats,
)
from app.models.schemas import PersonStatus, UserConfig
from app.pipeline.orchestrator import Orchestrator
from app.tracker.manager import TrackerManager

logger = logging.getLogger(__name__)

_WELCOME = """\
👋 <b>Welcome to Cold Connect!</b>

I find key people at any company and write personalized LinkedIn connection messages for you.

<b>To get started:</b>
1. Set your bio: <code>/setbio I'm an AI engineer at ...</code>
2. Send any company name: <code>Anthropic</code>

<b>Commands:</b>
/setbio — Set your bio for personalized messages
/mybio — View your current bio
/list — Companies you've researched
/status — Your outreach stats
/sent &lt;name&gt; — Mark someone as sent
/accepted &lt;name&gt; — Mark someone as accepted
/ignored &lt;name&gt; — Mark someone as ignored
/followup — See who needs a follow-up
/help — Show this message
"""


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(_WELCOME, parse_mode="HTML")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(_WELCOME, parse_mode="HTML")


async def cmd_setbio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bio = " ".join(context.args or []).strip()
    if not bio:
        await update.message.reply_text(
            "Please include your bio after the command.\n"
            "Example: <code>/setbio I'm an AI engineer building developer tools at a Series A startup.</code>",
            parse_mode="HTML",
        )
        return

    config = _get_config(context)
    config.bio = bio
    config.updated_at = datetime.utcnow()
    _save_config(context, config)
    await update.message.reply_text(f"✅ Bio saved ({len(bio)} chars).")


async def cmd_mybio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = _get_config(context)
    if not config.bio:
        await update.message.reply_text("No bio set yet. Use /setbio to set one.")
        return
    await update.message.reply_text(f"Your bio:\n\n{config.bio}")


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tracker: TrackerManager = context.bot_data.get("tracker")
    if not tracker:
        await update.message.reply_text("Tracker not available.")
        return
    companies = tracker.get_all_companies()
    await update.message.reply_text(format_list(companies), parse_mode="HTML")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tracker: TrackerManager = context.bot_data.get("tracker")
    if not tracker:
        await update.message.reply_text("Tracker not available.")
        return
    stats = tracker.get_stats()
    await update.message.reply_text(format_stats(stats), parse_mode="HTML")


async def cmd_sent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _update_person_status(update, context, PersonStatus.SENT, "sent")


async def cmd_accepted(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _update_person_status(update, context, PersonStatus.ACCEPTED, "accepted")


async def cmd_ignored(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _update_person_status(update, context, PersonStatus.IGNORED, "ignored")


async def cmd_followup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tracker: TrackerManager = context.bot_data.get("tracker")
    if not tracker:
        await update.message.reply_text("Tracker not available.")
        return

    pending = tracker.get_pending_followups()
    if not pending:
        await update.message.reply_text("No follow-ups needed right now. 🎉")
        return

    await update.message.reply_text(f"<b>📬 {len(pending)} follow-ups due:</b>", parse_mode="HTML")
    for company, person in pending[:10]:
        days = (datetime.utcnow() - person.sent_at).days if person.sent_at else "?"
        await update.message.reply_text(
            f"<b>{person.person.name}</b> — {person.person.title}\n"
            f"@ {company.company.name} · sent {days} days ago\n"
            f"<a href='{person.person.linkedin_url}'>Open profile</a>",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.chat_data["cancel_requested"] = True
    await update.message.reply_text("⏹ Cancel requested. Current search will stop after the current step.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    if not text:
        return

    # Check bio is set
    config = _get_config(context)
    if not config.bio:
        await update.message.reply_text(
            "Please set your bio first so I can personalize messages for you.\n"
            "Example: <code>/setbio I'm an AI engineer at ...</code>",
            parse_mode="HTML",
        )
        return

    # Check if pipeline already running
    if context.chat_data.get("pipeline_running"):
        await update.message.reply_text(
            "⏳ A search is already running. Please wait for it to finish, or use /cancel."
        )
        return

    # Fire pipeline as a background task
    context.application.create_task(
        _run_pipeline(update, context, text, config.bio),
        update=update,
    )


# ------------------------------------------------------------------
# Pipeline runner (background task)
# ------------------------------------------------------------------

async def _run_pipeline(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, user_bio: str
) -> None:
    chat_id = update.effective_chat.id
    context.chat_data["pipeline_running"] = True
    context.chat_data["cancel_requested"] = False

    companies = [c.strip() for c in text.split(",") if c.strip()]
    display = ", ".join(companies) if len(companies) > 1 else text
    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"🔍 Researching <b>{display}</b>...",
        parse_mode="HTML",
    )

    orchestrator: Orchestrator = context.bot_data.get("orchestrator")
    if not orchestrator:
        await context.bot.send_message(chat_id=chat_id, text=format_error("Orchestrator not initialized."), parse_mode="HTML")
        context.chat_data["pipeline_running"] = False
        return

    try:
        results = await orchestrator.run(text, user_bio)
    except Exception as e:
        logger.exception("Pipeline error for '%s': %s", text, e)
        await context.bot.send_message(
            chat_id=chat_id,
            text=format_error("Something went wrong. The error has been logged."),
            parse_mode="HTML",
        )
        context.chat_data["pipeline_running"] = False
        return
    finally:
        try:
            await status_msg.delete()
        except Exception:
            pass

    # Send results for each company
    for result in results:
        if result.errors and not result.people:
            await context.bot.send_message(
                chat_id=chat_id,
                text=format_error(result.errors[0]),
                parse_mode="HTML",
            )
            continue

        # Company card
        await context.bot.send_message(
            chat_id=chat_id,
            text=format_company_card(result),
            parse_mode="HTML",
        )
        await asyncio.sleep(0.1)

        # Generate a short run_id for callback data
        run_id = uuid.uuid4().hex[:6]

        # Store person data in chat_data for callback lookups
        run_store = {}
        for idx, pr in enumerate(result.people):
            run_store[str(idx)] = {
                "name": pr.person.name,
                "message": pr.message.text,
                "person_id": "",  # filled after tracker save
            }
        context.chat_data[run_id] = run_store

        # Person cards
        for idx, pr in enumerate(result.people):
            text_card, keyboard = format_person_card(pr, run_id, idx)
            await context.bot.send_message(
                chat_id=chat_id,
                text=text_card,
                reply_markup=keyboard,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            await asyncio.sleep(0.1)

        if result.errors:
            note = f"⚠️ Note: {result.errors[0]}"
            await context.bot.send_message(chat_id=chat_id, text=note, parse_mode="HTML")

    context.chat_data["pipeline_running"] = False


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

async def _update_person_status(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
    status: PersonStatus, label: str
) -> None:
    name = " ".join(context.args or []).strip()
    if not name:
        await update.message.reply_text(f"Usage: /{label} <person name>")
        return

    tracker: TrackerManager = context.bot_data.get("tracker")
    if not tracker:
        await update.message.reply_text("Tracker not available.")
        return

    matches = tracker.find_person(name)
    if not matches:
        await update.message.reply_text(f"No one found matching '{name}'.")
        return

    if len(matches) == 1:
        company, person = matches[0]
        await tracker.update_person_status(person.id, status)
        await update.message.reply_text(
            f"✅ <b>{person.person.name}</b> marked as {label}.", parse_mode="HTML"
        )
    else:
        lines = [f"Multiple matches for '{name}'. Which one?", ""]
        for i, (company, person) in enumerate(matches[:5], 1):
            lines.append(f"{i}. {person.person.name} — {person.person.title} @ {company.company.name}")
        lines.append(f"\nUse a more specific name (e.g. /{label} {matches[0][1].person.name})")
        await update.message.reply_text("\n".join(lines))


def _get_config(context: ContextTypes.DEFAULT_TYPE) -> UserConfig:
    if "user_config" not in context.chat_data:
        context.chat_data["user_config"] = UserConfig().model_dump()
    return UserConfig(**context.chat_data["user_config"])


def _save_config(context: ContextTypes.DEFAULT_TYPE, config: UserConfig) -> None:
    context.chat_data["user_config"] = config.model_dump()
