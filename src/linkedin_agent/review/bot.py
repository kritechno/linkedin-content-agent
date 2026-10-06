"""Telegram approval bot — the human-in-the-loop gate (plan §5).

One owner chat controls everything. Each pending draft is sent with an inline
keyboard; taps drive approve/edit/regenerate/angle/image/skip. Blocking work
(LLM, LinkedIn) runs in a thread so the event loop stays responsive.

PTB JobQueue handles the schedule (Phase 6): a posting-cadence cycle plus a
daily token-expiry check.
"""

from __future__ import annotations

import asyncio
import datetime as dt

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from linkedin_agent.config import Settings, get_settings
from linkedin_agent.linkedin import tokens
from linkedin_agent import feedback, pipeline, store

# PTB v22: days 0-6 == Sunday-Saturday.
_DAY_TO_INT = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}


def keyboard(draft_id: int, *, has_image: bool = False) -> InlineKeyboardMarkup:
    def b(label: str, action: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(label, callback_data=f"{action}:{draft_id}")

    image_label = "🖼 Regenerate image" if has_image else "🖼 Create image"
    return InlineKeyboardMarkup([
        [b("✅ Approve & post", "approve"), b("✏️ Edit", "edit")],
        [b("🔄 Regenerate", "regen"), b("🎭 Other angle", "angle")],
        [b(image_label, "image"), b("📝 Change image text", "image_text")],
        [b("❌ Skip", "skip")],
    ])


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.application.bot_data["settings"]


async def send_draft_for_review(app: Application, settings: Settings, draft_id: int) -> None:
    record = store.get_draft(settings, draft_id)
    if record is None:
        return
    chat_id = int(settings.telegram_chat_id)
    if record.image_path:
        with open(record.image_path, "rb") as fh:
            await app.bot.send_photo(chat_id, photo=fh, caption=f"🖼 {record.topic_title}")
    msg = await app.bot.send_message(
        chat_id,
        pipeline.render_review_text(record),
        reply_markup=keyboard(draft_id, has_image=bool(record.image_path)),
        disable_web_page_preview=True,
    )
    store.set_message_id(settings, draft_id, msg.message_id)
    store.set_status(settings, draft_id, "pending")


# ── commands ──────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "LinkedIn content agent is live.\n"
        "/run – research + draft now\n"
        "/posts – recent posts + their performance\n"
        "/perf – record how a post performed (feeds back into drafts)\n"
        "/status – token + weekly post count"
    )


async def cmd_run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    await update.message.reply_text("Researching + drafting… (this takes a moment)")
    result = await asyncio.to_thread(pipeline.run_cycle, settings=settings)
    if not result.draft_ids:
        await update.message.reply_text(
            f"No new topics to draft (considered {result.considered}, "
            f"{result.skipped_seen} already seen)."
        )
        return
    for draft_id in result.draft_ids:
        await send_draft_for_review(context.application, settings, draft_id)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    token = tokens.load_token(settings)
    posted = store.posts_in_last_days(settings, 7)
    learned = feedback.stats(settings)
    recent = store.list_recent_posts(settings, limit=20)
    with_metrics = sum(1 for p in recent if p.has_metrics)
    lines = [f"Posts in last 7 days: {posted}/{settings.max_posts_per_week}"]
    if token:
        lines.append(f"LinkedIn token: {token.access_seconds_left // 3600}h of access left")
    else:
        lines.append("LinkedIn token: not authenticated (run `linkedin-agent auth`)")
    lines.append(
        f"Voice corpus: {learned['total']} learned post(s), {learned['edited']} edited "
        "— drafts adapt to your voice as this grows."
    )
    if recent:
        lines.append(
            f"Performance: recorded on {with_metrics}/{len(recent)} recent posts "
            "— winners steer future drafts (/perf to add more)."
        )
    await update.message.reply_text("\n".join(lines))


def _snippet(text: str, n: int = 80) -> str:
    one = " ".join((text or "").split())
    return one if len(one) <= n else one[:n].rstrip() + "…"


def _parse_metrics(parts: list[str]) -> dict | None:
    """Parse 'impressions reactions comments [reposts]' into record_metrics kwargs."""
    try:
        nums = [int(p.replace(",", "")) for p in parts]
    except ValueError:
        return None
    if len(nums) == 3:
        nums.append(0)  # reposts optional
    if len(nums) != 4:
        return None
    impressions, reactions, comments, reposts = nums
    return {
        "impressions": impressions, "reactions": reactions,
        "comments": comments, "reposts": reposts,
    }


async def cmd_posts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    posts = store.list_recent_posts(settings, limit=10)
    if not posts:
        await update.message.reply_text("No posts published yet.")
        return
    lines = ["📋 Recent posts (newest first):"]
    for p in posts:
        when = dt.datetime.fromtimestamp(p.posted_at).strftime("%b %d")
        if p.has_metrics:
            perf = (f"{p.impressions or 0} impr · {p.reactions or 0} rx · "
                    f"{p.comments or 0} cm · {p.reposts or 0} rp (score {p.engagement_score})")
        else:
            perf = "no metrics yet"
        lines.append(f"\n#{p.draft_id} · {when}\n  {_snippet(p.text)}\n  {perf}")
    lines.append("\nRecord performance with  /perf  (or  /perf <#> <impr> <rx> <cm> [rp]).")
    await update.message.reply_text("\n".join(lines), disable_web_page_preview=True)


async def cmd_perf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    args = context.args or []
    usage = "Usage: /perf <post#> <impressions> <reactions> <comments> [reposts]\n" \
            "or just /perf to be walked through the latest post."

    if args:  # direct one-liner
        try:
            draft_id = int(args[0])
        except ValueError:
            await update.message.reply_text(usage)
            return
        metrics = _parse_metrics(args[1:])
        if metrics is None:
            await update.message.reply_text(usage)
            return
        ok = store.record_metrics(settings, draft_id, **metrics)
        await update.message.reply_text(
            f"📊 Saved performance for post #{draft_id}. It now steers future drafts."
            if ok else f"No published post found for #{draft_id}. Use /posts to see ids."
        )
        return

    # guided: pick the most recent post that still lacks metrics
    pending = [
        p for p in store.list_recent_posts(settings, limit=20)
        if not p.has_metrics and p.draft_id is not None
    ]
    if not pending:
        await update.message.reply_text("All recent posts already have performance recorded. 🎉")
        return
    target = pending[0]
    context.user_data.pop("awaiting_edit", None)
    context.user_data.pop("awaiting_image_text", None)
    context.user_data["awaiting_metrics"] = target.draft_id
    await update.message.reply_text(
        f"📊 Post #{target.draft_id}:\n\n{_snippet(target.text, 140)}\n\n"
        "Reply with four numbers — impressions reactions comments reposts — e.g. 1200 34 8 2"
    )


# ── callback buttons ──────────────────────────────────────────────────────
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    action, _, raw_id = query.data.partition(":")
    settings = _settings(context)
    draft_id = int(raw_id)
    record = store.get_draft(settings, draft_id)
    if record is None:
        await query.edit_message_text("This draft is no longer available.")
        return

    if action == "approve":
        await query.edit_message_text(query.message.text + "\n\n⏳ Posting…")
        try:
            outcome = await asyncio.to_thread(pipeline.publish_draft, settings, draft_id)
        except Exception as exc:  # surface the real LinkedIn error to the owner
            await query.edit_message_text(query.message.text + f"\n\n❌ Post failed: {exc}")
            return
        note = " (⚠️ over weekly cap)" if outcome.over_cap else ""
        await query.edit_message_text(
            query.message.text + f"\n\n✅ Posted{note}\n{outcome.post_urn}"
        )

    elif action == "edit":
        context.user_data.pop("awaiting_image_text", None)
        context.user_data["awaiting_edit"] = draft_id
        await query.message.reply_text("✏️ Send the edited post text as a reply.")

    elif action == "regen":
        await query.edit_message_text(query.message.text + "\n\n🔄 Regenerating…")
        await asyncio.to_thread(pipeline.regenerate_current_angle, settings, record)
        fresh = store.get_draft(settings, draft_id)
        await query.edit_message_text(
            pipeline.render_review_text(fresh),
            reply_markup=keyboard(draft_id, has_image=bool(fresh.image_path)),
        )

    elif action == "angle":
        pipeline.cycle_angle(settings, record)
        fresh = store.get_draft(settings, draft_id)
        await query.edit_message_text(
            pipeline.render_review_text(fresh),
            reply_markup=keyboard(draft_id, has_image=bool(fresh.image_path)),
        )

    elif action == "image":
        path = await asyncio.to_thread(pipeline.regenerate_image, settings, record)
        fresh = store.get_draft(settings, draft_id)
        await query.edit_message_text(
            pipeline.render_review_text(fresh),
            reply_markup=keyboard(draft_id, has_image=True),
            disable_web_page_preview=True,
        )
        with open(path, "rb") as fh:
            await query.message.reply_photo(photo=fh, caption="🖼 Image generated")

    elif action == "image_text":
        context.user_data.pop("awaiting_edit", None)
        context.user_data["awaiting_image_text"] = draft_id
        await query.message.reply_text(
            "Current image card text:\n\n"
            f"{pipeline.image_card_text(record)}\n\n"
            "Send the exact replacement text for the image card. "
            "This changes only the image, not the LinkedIn post."
        )

    elif action == "skip":
        store.set_status(settings, draft_id, "skipped")
        await query.edit_message_text(query.message.text + "\n\n❌ Skipped.")


async def on_edit_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    metrics_draft_id = context.user_data.pop("awaiting_metrics", None)
    if metrics_draft_id is not None:
        settings = _settings(context)
        parsed = _parse_metrics(update.message.text.split())
        if parsed is None:
            context.user_data["awaiting_metrics"] = metrics_draft_id  # stay in the flow
            await update.message.reply_text(
                "Need 3-4 numbers: impressions reactions comments [reposts]. e.g. 1200 34 8 2"
            )
            return
        store.record_metrics(settings, metrics_draft_id, **parsed)
        await update.message.reply_text(
            f"📊 Saved for post #{metrics_draft_id}. Top performers now steer future drafts."
        )
        return

    image_draft_id = context.user_data.pop("awaiting_image_text", None)
    if image_draft_id is not None:
        settings = _settings(context)
        store.set_image_text(settings, image_draft_id, update.message.text)
        record = store.get_draft(settings, image_draft_id)
        if record is None:
            await update.message.reply_text("This draft is no longer available.")
            return
        await update.message.reply_text(
            "Image text updated. Review it before creating the image:\n\n"
            + pipeline.render_review_text(record),
            reply_markup=keyboard(image_draft_id, has_image=bool(record.image_path)),
            disable_web_page_preview=True,
        )
        return

    draft_id = context.user_data.pop("awaiting_edit", None)
    if draft_id is None:
        return  # not in an edit flow; ignore stray text
    settings = _settings(context)
    store.set_override_text(settings, draft_id, update.message.text)
    record = store.get_draft(settings, draft_id)
    # Learn from the edit immediately — even if it's never posted.
    feedback.record_edit(settings, record)
    await update.message.reply_text(
        "Updated to your version (and saved as a voice example):\n\n"
        + pipeline.render_review_text(record),
        reply_markup=keyboard(draft_id, has_image=bool(record.image_path)),
        disable_web_page_preview=True,
    )


# ── scheduled jobs (Phase 6) ──────────────────────────────────────────────
async def scheduled_cycle(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]
    result = await asyncio.to_thread(pipeline.run_cycle, settings=settings)
    for draft_id in result.draft_ids:
        await send_draft_for_review(context.application, settings, draft_id)


async def metrics_nudge(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Once a post has had a few days to accumulate engagement, ask the owner to
    record its numbers — that's what closes the performance feedback loop."""
    settings = context.application.bot_data["settings"]
    pending = store.posts_needing_metrics(settings)
    if not pending:
        return
    ids = ", ".join(f"#{p.draft_id}" for p in pending)
    await context.bot.send_message(
        int(settings.telegram_chat_id),
        f"📊 How did {ids} do? Send /perf to record impressions/reactions — "
        "it teaches the writer what actually lands.",
    )


async def token_expiry_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]
    token = tokens.load_token(settings)
    if token is None:
        return
    days_left = token.access_seconds_left // 86400
    no_refresh = not token.refresh_token
    if (no_refresh and days_left <= 7) or token.refresh_expiring_soon:
        await context.bot.send_message(
            int(settings.telegram_chat_id),
            f"⚠️ LinkedIn access expires in ~{days_left} days and there's no "
            "refresh token. Run `linkedin-agent auth` to re-consent.",
        )


def build_application(settings: Settings | None = None) -> Application:
    settings = settings or get_settings()
    settings.require_telegram()
    owner = int(settings.telegram_chat_id)
    only_owner = filters.Chat(chat_id=owner)

    app = Application.builder().token(settings.telegram_bot_token).build()
    app.bot_data["settings"] = settings

    app.add_handler(CommandHandler("start", cmd_start, filters=only_owner))
    app.add_handler(CommandHandler("run", cmd_run, filters=only_owner))
    app.add_handler(CommandHandler("status", cmd_status, filters=only_owner))
    app.add_handler(CommandHandler("posts", cmd_posts, filters=only_owner))
    app.add_handler(CommandHandler("perf", cmd_perf, filters=only_owner))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(only_owner & filters.TEXT & ~filters.COMMAND, on_edit_reply))

    # Schedule the posting cadence + daily token check.
    days = tuple(_DAY_TO_INT[d] for d in settings.post_days if d in _DAY_TO_INT)
    if app.job_queue is not None and days:
        app.job_queue.run_daily(
            scheduled_cycle,
            time=dt.time(hour=settings.post_hour, minute=settings.post_minute),
            days=days,
            name="posting-cycle",
        )
        app.job_queue.run_daily(
            token_expiry_check, time=dt.time(hour=9, minute=0), name="token-check"
        )
        app.job_queue.run_daily(
            metrics_nudge, time=dt.time(hour=10, minute=0), name="metrics-nudge"
        )
    return app


def run(settings: Settings | None = None) -> None:
    app = build_application(settings)
    print("Telegram bot running. Press Ctrl+C to stop.")
    # drop_pending_updates: ignore messages sent before the bot started (e.g. the
    # /start used during setup) so we don't reprocess them on launch.
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
