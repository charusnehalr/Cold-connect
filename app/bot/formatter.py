import html
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.models.schemas import PipelineResult, PersonResult, TrackedCompany


def format_company_card(result: PipelineResult) -> str:
    c = result.company
    lines = [f"<b>🏢 {html.escape(c.name)}</b>"]

    meta = []
    if c.industry:
        meta.append(html.escape(c.industry))
    if c.size:
        meta.append(html.escape(c.size))
    if meta:
        lines.append(" · ".join(meta))

    if c.description:
        lines.append("")
        lines.append(html.escape(c.description))

    if c.recent_posts:
        lines.append("")
        lines.append(f"📰 <i>{html.escape(c.recent_posts[0][:200])}</i>")

    count = len(result.people)
    if count:
        lines.append("")
        lines.append(f"Found <b>{count}</b> {'person' if count == 1 else 'people'} to connect with ↓")
    else:
        lines.append("")
        lines.append("⚠️ Couldn't find key people at this company.")

    return "\n".join(lines)


def format_person_card(pr: PersonResult, run_id: str, idx: int) -> tuple[str, InlineKeyboardMarkup]:
    p = pr.person
    lines = [
        "━━━━━━━━━━━━━━━━━━",
        f"<b>👤 {html.escape(p.name)}</b>",
        html.escape(p.title),
    ]

    if p.location:
        lines.append(f"📍 {html.escape(p.location)}")

    if pr.why_connect:
        lines.append("")
        lines.append(f"💡 {html.escape(pr.why_connect)}")

    if pr.message.text:
        lines.append("")
        lines.append("✉️ <b>Message:</b>")
        lines.append(f'<i>"{html.escape(pr.message.text)}"</i>')
        char_count = len(pr.message.text)
        lines.append(f"<code>{char_count}/300 chars</code>")

    lines.append("━━━━━━━━━━━━━━━━━━")
    text = "\n".join(lines)

    # Truncate if over Telegram's 4096 char limit
    if len(text) > 4000:
        text = text[:4000] + "\n...</i>"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔗 Open Profile", url=p.linkedin_url),
            InlineKeyboardButton("📋 Copy Message", callback_data=f"cp:{run_id}:{idx}"),
        ],
        [
            InlineKeyboardButton("✅ Mark Sent", callback_data=f"ms:{run_id}:{idx}"),
            InlineKeyboardButton("⏭ Skip", callback_data=f"sk:{run_id}:{idx}"),
        ],
    ])

    return text, keyboard


def format_error(message: str) -> str:
    return f"❌ {html.escape(message)}"


def format_list(companies: list) -> str:
    if not companies:
        return "No companies researched yet. Send a company name to get started."

    lines = ["<b>📋 Researched Companies</b>", ""]
    for i, c in enumerate(companies, 1):
        company = c.company
        people_count = len(c.people)
        statuses = [p.status.value for p in c.people]
        sent = statuses.count("sent")
        accepted = statuses.count("accepted")

        date_str = c.searched_at.strftime("%b %d") if c.searched_at else ""
        lines.append(
            f"{i}. <b>{html.escape(company.name)}</b> — "
            f"{people_count} people · {sent} sent · {accepted} accepted"
            + (f" <i>({date_str})</i>" if date_str else "")
        )

    return "\n".join(lines)


def format_stats(stats: dict) -> str:
    breakdown = stats.get("status_breakdown", {})
    lines = [
        "<b>📊 Your Outreach Stats</b>",
        "",
        f"Companies researched: <b>{stats['total_companies']}</b>",
        f"Total people found: <b>{stats['total_people']}</b>",
        "",
        "<b>Status breakdown:</b>",
        f"  · Researched: {breakdown.get('researched', 0)}",
        f"  · Sent: {breakdown.get('sent', 0)}",
        f"  · Accepted: {breakdown.get('accepted', 0)}",
        f"  · Ignored: {breakdown.get('ignored', 0)}",
        f"  · Skipped: {breakdown.get('skipped', 0)}",
    ]
    rate = stats.get("acceptance_rate_pct", 0)
    if rate:
        lines.append(f"\n🎯 Acceptance rate: <b>{rate}%</b>")
    return "\n".join(lines)
