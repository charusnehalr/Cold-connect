import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.models.schemas import PersonStatus
from app.tracker.manager import TrackerManager

logger = logging.getLogger(__name__)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    parts = data.split(":")
    if len(parts) < 2:
        return

    action = parts[0]
    run_id = parts[1]
    idx = int(parts[2]) if len(parts) > 2 else 0

    # Retrieve person data stored when results were sent
    run_data: dict = (context.chat_data or {}).get(run_id, {})
    person_data: dict = run_data.get(str(idx), {})

    tracker: TrackerManager = context.bot_data.get("tracker")

    if action == "cp":
        # Send the raw message text so user can copy it
        message_text = person_data.get("message", "")
        if message_text:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=message_text,
            )
        else:
            await query.answer("No message available.", show_alert=True)

    elif action == "ms":
        person_id = person_data.get("person_id", "")
        if tracker and person_id:
            updated = await tracker.update_person_status(person_id, PersonStatus.SENT)
            if updated:
                await query.answer("✅ Marked as sent!", show_alert=False)
                # Edit the message to remove the "Mark Sent" button
                await _remove_button(query, "ms", run_id, idx)
            else:
                await query.answer("Could not update status.", show_alert=True)
        else:
            await query.answer("Tracker not available.", show_alert=True)

    elif action == "sk":
        person_id = person_data.get("person_id", "")
        if tracker and person_id:
            await tracker.update_person_status(person_id, PersonStatus.SKIPPED)
        await query.answer("⏭ Skipped", show_alert=False)
        await _remove_button(query, "sk", run_id, idx)


async def _remove_button(query, action: str, run_id: str, idx: int) -> None:
    """Edit the inline keyboard to visually reflect the action taken."""
    try:
        original_markup = query.message.reply_markup
        if not original_markup:
            return

        new_rows = []
        for row in original_markup.inline_keyboard:
            new_row = [btn for btn in row if not btn.callback_data or not btn.callback_data.startswith(f"{action}:")]
            if new_row:
                new_rows.append(new_row)

        from telegram import InlineKeyboardMarkup
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup(new_rows) if new_rows else None
        )
    except Exception as e:
        logger.debug("Could not edit keyboard: %s", e)
