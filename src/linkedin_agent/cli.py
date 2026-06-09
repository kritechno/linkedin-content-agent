"""Command-line entry point.

    linkedin-agent research        # Phase 1: live HN pull → rank → top topics
    linkedin-agent auth            # Phase 0: one-time LinkedIn OAuth consent
    linkedin-agent token-status    # Phase 0: inspect stored token / expiry
    linkedin-agent post-hello      # Phase 0: post a hardcoded hello-world

Run with no install via:  python -m linkedin_agent <command>
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from linkedin_agent.config import get_settings
from linkedin_agent.research.engine import get_top_topics
from linkedin_agent.research.models import Story

HELLO_TEXT = (
    "Hello world — this is a test post from my LinkedIn content agent. "
    "If you're seeing this, the posting pipeline works. Normal programming "
    "resumes shortly. 🤖"
)


def _fmt_age(hours: float) -> str:
    if hours < 1:
        return f"{int(hours * 60)}m"
    if hours < 48:
        return f"{hours:.0f}h"
    return f"{hours / 24:.1f}d"


def _print_topics(topics: list[Story]) -> None:
    if not topics:
        print("No topics found. Try widening RESEARCH_QUERIES or RESEARCH_MAX_AGE_HOURS.")
        return
    print(f"\n🔥 Top {len(topics)} topics\n" + "=" * 72)
    for i, s in enumerate(topics, 1):
        kws = ", ".join(s.matched_keywords) or "—"
        print(f"\n{i}. {s.title}")
        print(f"   score {s.score:.3f}  |  {s.points} pts  |  {s.num_comments} comments  "
              f"|  {_fmt_age(s.age_hours)} old  |  ratio {s.comment_point_ratio:.2f}")
        print(f"   why hot: comment/point ratio {s.comment_point_ratio:.2f} "
              f"(higher = more debate)  |  matched: {kws}")
        bd = s.score_breakdown
        print("   breakdown: " + "  ".join(f"{k}={v:.2f}" for k, v in bd.items()))
        print(f"   link:       {s.url}")
        print(f"   discussion: {s.discussion_url}")
    print("\n" + "=" * 72)


def cmd_research(args: argparse.Namespace) -> int:
    settings = get_settings()
    print(f"Querying HN for {settings.research_queries} "
          f"(last {settings.research_max_age_hours:.0f}h)…")
    topics = get_top_topics(
        n=args.top, settings=settings,
        require_topic=not args.all, require_popular=not args.all,
    )
    if not args.all:
        print(f"(on-topic + traction-gated: ≥{settings.min_points} pts or "
              f"≥{settings.min_comments} comments; pass --all to disable both gates)")
    _print_topics(topics)
    return 0


def cmd_auth(args: argparse.Namespace) -> int:
    from linkedin_agent.linkedin.oauth import run_auth_flow

    run_auth_flow(get_settings(), open_browser=not args.no_browser)
    return 0


def cmd_token_status(args: argparse.Namespace) -> int:
    from linkedin_agent.linkedin import tokens

    settings = get_settings()
    token = tokens.load_token(settings)
    if token is None:
        print("No stored token. Run `linkedin-agent auth`.")
        return 1

    def _when(ts: int | None) -> str:
        if ts is None:
            return "n/a"
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    print(f"member_urn:       {token.member_urn}")
    print(f"scope:            {token.scope}")
    print(f"access valid:     {token.access_valid} "
          f"({token.access_seconds_left // 3600}h left, exp {_when(token.access_expires_at)})")
    rl = token.refresh_seconds_left
    print(f"refresh expires:  {_when(token.refresh_expires_at)} "
          f"({rl // 86400 if rl is not None else 'n/a'}d left)")
    if token.refresh_expiring_soon:
        print("⚠️  Refresh token expiring soon — re-run `linkedin-agent auth` to re-consent.")
    return 0


def cmd_post_hello(args: argparse.Namespace) -> int:
    from linkedin_agent.linkedin.client import post_text

    if not args.yes:
        print("This will publish a real post to your LinkedIn profile:\n")
        print(f"  {HELLO_TEXT}\n")
        confirm = input("Type 'post' to publish: ").strip().lower()
        if confirm != "post":
            print("Aborted.")
            return 1
    result = post_text(HELLO_TEXT)
    print(f"✅ Posted. urn={result.post_urn} (HTTP {result.status_code})")
    return 0


def _print_draftset(ds) -> None:
    print(f"\n📰 {ds.topic_title}")
    print(f"   why hot: {ds.why_hot}")
    for a in ds.angles:
        print("\n" + "─" * 72)
        print(f"🎭 {a.angle_type.label}")
        print(f"\n{a.full_text}\n")
        if a.fact_flags:
            print("⚠️  verify:")
            for f in a.fact_flags:
                print(f"   • {f.claim}" + (f" — {f.reason}" if f.reason else ""))
        if a.suggested_image:
            print(f"🖼  suggested image: {a.suggested_image}")
    print("\n" + "═" * 72)


def cmd_draft(args: argparse.Namespace) -> int:
    from linkedin_agent.draft import writer
    from linkedin_agent.draft.llm import get_provider

    settings = get_settings()
    topics = get_top_topics(n=args.top, settings=settings)
    if not topics:
        print("No topics found.")
        return 1
    provider = get_provider(settings, force_mock=args.mock)
    print(f"LLM provider: {provider.name}  (model: {getattr(provider, '_model', 'n/a')})")
    for story in topics[: args.top]:
        ds = writer.draft_from_story(story, settings=settings, provider=provider)
        _print_draftset(ds)
    return 0


def cmd_cycle(args: argparse.Namespace) -> int:
    from linkedin_agent import pipeline, store

    settings = get_settings()
    print("Running cycle (research → draft → queue for review)…")
    result = pipeline.run_cycle(settings=settings, force_mock=args.mock, enrich=args.enrich)
    print(f"Created {len(result.draft_ids)} draft(s); considered {result.considered}, "
          f"skipped {result.skipped_seen} already-seen.")
    for draft_id in result.draft_ids:
        record = store.get_draft(settings, draft_id)
        print("\n" + "═" * 72)
        print(f"[draft #{draft_id}]")
        print(pipeline.render_review_text(record))
        if record.image_path:
            print(f"\n(image saved: {record.image_path})")
    if result.draft_ids:
        print("\nDrafts queued. Start the bot (`linkedin-agent bot`) to review, "
              "or publish one with `linkedin-agent post-draft <id>`.")
    return 0


def cmd_bot(args: argparse.Namespace) -> int:
    from linkedin_agent.review.bot import run

    run(get_settings())
    return 0


def cmd_card(args: argparse.Namespace) -> int:
    from linkedin_agent.enrich.images import text_card

    out = args.out or "generated_images/card.png"
    path = text_card(args.text, out)
    print(f"✅ wrote {path}")
    return 0


def cmd_post_draft(args: argparse.Namespace) -> int:
    from linkedin_agent import pipeline, store

    settings = get_settings()
    record = store.get_draft(settings, args.id)
    if record is None:
        print(f"Draft #{args.id} not found. Run `linkedin-agent cycle` first.")
        return 1
    print("This will publish to your LinkedIn profile:\n")
    print(record.effective_text + "\n")
    if record.image_path:
        print(f"(with image {record.image_path})\n")
    if not args.yes:
        if input("Type 'post' to publish: ").strip().lower() != "post":
            print("Aborted.")
            return 1
    outcome = pipeline.publish_draft(settings, args.id)
    note = " (⚠️ over weekly cap)" if outcome.over_cap else ""
    print(f"✅ Posted{note}. urn={outcome.post_urn}")
    return 0


def cmd_learned(args: argparse.Namespace) -> int:
    from linkedin_agent import feedback

    settings = get_settings()
    st = feedback.stats(settings)
    print(f"Learned voice corpus: {st['total']} published post(s); "
          f"{st['edited']} were edited (correction signal).")
    if st["total"] == 0:
        print("Nothing yet — approve/edit posts in Telegram and they'll accumulate here, "
              "feeding back into future drafts.")
        return 0
    for i, text in enumerate(feedback.recent_finals(settings, limit=args.show), 1):
        print("\n" + "─" * 60)
        print(f"[{i}] {text}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="linkedin-agent", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_research = sub.add_parser("research", help="Phase 1: pull + rank HN topics")
    p_research.add_argument("--top", type=int, default=5, help="how many topics to show")
    p_research.add_argument("--all", action="store_true",
                            help="disable the topic-relevance gate (include off-topic stories)")
    p_research.set_defaults(func=cmd_research)

    p_auth = sub.add_parser("auth", help="Phase 0: one-time LinkedIn OAuth consent")
    p_auth.add_argument("--no-browser", action="store_true", help="don't auto-open the browser")
    p_auth.set_defaults(func=cmd_auth)

    p_status = sub.add_parser("token-status", help="Phase 0: show stored token + expiry")
    p_status.set_defaults(func=cmd_token_status)

    p_hello = sub.add_parser("post-hello", help="Phase 0: post a hardcoded hello-world")
    p_hello.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    p_hello.set_defaults(func=cmd_post_hello)

    p_draft = sub.add_parser("draft", help="Phase 2: draft angles for the top topic(s)")
    p_draft.add_argument("--top", type=int, default=1, help="how many topics to draft")
    p_draft.add_argument("--mock", action="store_true", help="use the offline mock LLM")
    p_draft.set_defaults(func=cmd_draft)

    p_cycle = sub.add_parser("cycle", help="Full cycle: research → draft → queue")
    p_cycle.add_argument("--mock", action="store_true", help="use the offline mock LLM")
    p_cycle.add_argument(
        "--enrich",
        action="store_true",
        help="legacy flag; image cards are created in Telegram after text approval",
    )
    p_cycle.set_defaults(func=cmd_cycle)

    p_bot = sub.add_parser("bot", help="Phase 3/4/6: run the Telegram review bot")
    p_bot.set_defaults(func=cmd_bot)

    p_card = sub.add_parser("card", help="Phase 5: render a text-card image (test)")
    p_card.add_argument("text", help="the pull-quote text")
    p_card.add_argument("--out", help="output path (default generated_images/card.png)")
    p_card.set_defaults(func=cmd_card)

    p_post = sub.add_parser("post-draft", help="Phase 4: publish a queued draft by id")
    p_post.add_argument("id", type=int, help="draft id from `cycle`")
    p_post.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    p_post.set_defaults(func=cmd_post_draft)

    p_learned = sub.add_parser("learned", help="Show the learned voice corpus (posts + edits)")
    p_learned.add_argument("--show", type=int, default=3, help="how many recent posts to print")
    p_learned.set_defaults(func=cmd_learned)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    try:
        return args.func(args)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
