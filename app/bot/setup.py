from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from app.bot.callbacks import handle_callback
from app.bot.handlers import (
    cmd_accepted,
    cmd_cancel,
    cmd_followup,
    cmd_help,
    cmd_ignored,
    cmd_list,
    cmd_mybio,
    cmd_sent,
    cmd_setbio,
    cmd_start,
    cmd_status,
    handle_message,
)
from app.config import settings


def build_application(orchestrator, tracker) -> Application:
    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )

    # Store shared services so handlers can access them via context.bot_data
    app.bot_data["orchestrator"] = orchestrator
    app.bot_data["tracker"] = tracker

    # Register handlers — ORDER MATTERS (commands before general text)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("setbio", cmd_setbio))
    app.add_handler(CommandHandler("mybio", cmd_mybio))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("sent", cmd_sent))
    app.add_handler(CommandHandler("accepted", cmd_accepted))
    app.add_handler(CommandHandler("ignored", cmd_ignored))
    app.add_handler(CommandHandler("followup", cmd_followup))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app
