# LinkedIn Content Agent

[![CI](https://github.com/kritechno/linkedin-content-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/kritechno/linkedin-content-agent/actions/workflows/ci.yml)

An LLM agent that researches current AI topics, drafts LinkedIn posts in the author's own voice, fact-checks them against the source, and publishes only after a human approves each one in Telegram. It runs on a schedule and learns from every post that is approved or edited, and from how published posts perform.

I built it for my own LinkedIn account. The design notes are in [`linkedin-agent-architecture.md`](linkedin-agent-architecture.md).

To run it you need three credentials of your own: a LinkedIn app for OAuth, an OpenAI or Anthropic API key, and a Telegram bot token.

```
research → draft (voice + 3 angles + fact-check) → Telegram review
        → approve card text → create image card → post to LinkedIn
```

## Setup

```bash
uv sync --extra dev          # venv + deps
cp .env.example .env         # fill in secrets (see below)
uv run pytest                # 66 tests, offline
```

Run via `uv run linkedin-agent <command>` (or `python -m linkedin_agent`).

| Command | Phase | What it does |
|---|---|---|
| `research [--top N] [--all]` | 1 | Live HN pull → rank → top topics (on-topic by default) |
| `draft [--top N] [--mock]` | 2 | Generate 3 voice-matched angles for the top topic(s) |
| `cycle [--mock] [--enrich]` | 1–3,5 | Full run: research → draft → queue drafts with an image-card text proposal |
| `bot` | 3,4,6 | Run the Telegram review bot (+ schedule) |
| `card "<text>"` | 5 | Render a text-card image (test) |
| `post-draft <id> [--yes]` | 4 | Publish a queued draft to LinkedIn |
| `posts [--show N]` | — | List recent published posts + their recorded performance |
| `perf <id> --reactions … --comments …` | — | Record how a post performed (feeds the writer) |
| `learned [--show N]` | — | Inspect the learned voice corpus (published posts + edits) |
| `auth` / `token-status` / `post-hello` | 0 | LinkedIn OAuth / token info / hello-world post |

## Secrets (.env)

- **LinkedIn (Phase 0):** `LINKEDIN_CLIENT_ID/SECRET`, redirect `http://localhost:8000/callback`
  registered in the app's Auth tab, products *Share on LinkedIn* + *Sign In with
  LinkedIn (OpenID Connect)*. Run `auth` once. Access tokens last 60 days; if no
  refresh token is granted you'll re-run `auth` (the bot warns you ~7 days out).
  Bump `LINKEDIN_API_VERSION` (YYYYMM) if a post returns a version error.
- **LLM (Phase 2):** `LLM_PROVIDER=openai` + `OPENAI_API_KEY` (default model
  `gpt-5.5`), or `anthropic` + `ANTHROPIC_API_KEY`. Override with `LLM_MODEL`.
- **Telegram (Phase 3):** create a bot with [@BotFather](https://t.me/BotFather)
  → `TELEGRAM_BOT_TOKEN`; get your numeric id from
  [@userinfobot](https://t.me/userinfobot) → `TELEGRAM_CHAT_ID` (only this chat
  is obeyed).

## Voice & persona (the quality lever)

Drop your own writing into `voice_examples/` (`.txt`/`.md`/`.rtf`) — these are
fed as few-shot examples so drafts match your rhythm and vocabulary. More
samples = better voice. The persona (AI student + Central Asia tour founder) is
in `PERSONA` / `config.DEFAULT_PERSONA`. **This is where most of the quality
lives — add samples and reject-and-regenerate freely while tuning.**

### It learns from every post you approve

The agent improves itself as you use it. When you publish a post:
- the **final text** is stored as a gold voice example (your real published
  writing is the strongest possible signal), and
- if you **edited** it, the *AI-draft → your-final* diff is kept as a correction
  the model studies.

Both are injected into future draft prompts (`feedback.py` → `learned_voice`
table): recent published posts are weighted most heavily, and recent edits are
shown as "here's what this author changes, pre-apply it." So the more you
approve and edit, the more drafts sound like you. Inspect the corpus anytime
with `linkedin-agent learned`; the bot's `/status` shows the running count.

### It learns what actually performs

Sounding like you isn't the same as landing with your audience, so the agent
also closes a **performance feedback loop**. A few days after a post goes live,
the bot nudges you to record its numbers (impressions / reactions / comments /
reposts) — tap **/perf** in Telegram (guided), or `/perf <#> <impr> <rx> <cm>
<rp>` in one line; `linkedin-agent perf` does the same from the terminal.
**/posts** lists recent posts with their scores. Your **highest-engagement**
posts are then fed back into the draft prompt as "reuse what worked here," so
the writer drifts toward the hooks, structure, and topics your network actually
engages with — not just your voice. Engagement is scored
`reactions + 2·comments + 3·reposts` (a repost is the strongest endorsement).

## Going live

```bash
uv run linkedin-agent cycle            # preview drafts in the terminal first
uv run linkedin-agent bot              # then run the bot; /run to draft on demand
```

In Telegram each draft shows the proposed text that would be burned into the
image card. Use **Create image** only after that text is final; use
**Change image text** to edit only the card headline without changing the
LinkedIn post. Buttons: **Approve & post · Edit · Regenerate · Other angle ·
Create/Regenerate image · Change image text · Skip**. Approve posts it to LinkedIn.
The bot also runs itself on `POST_DAYS` at `POST_HOUR` and caps at
`MAX_POSTS_PER_WEEK`; seen topics don't resurface for `TOPIC_MEMORY_DAYS`.

## Layout

```
src/linkedin_agent/
  config.py / db.py / store.py / voice.py / pipeline.py
  research/   hackernews · ranker · engine          (Phase 1)
  draft/      models · prompts · llm · writer        (Phase 2)
  enrich/     images (text cards + charts)           (Phase 5)
  linkedin/   oauth · tokens · client (text+image)   (Phase 0/4)
  review/     bot (Telegram + JobQueue schedule)     (Phase 3/6)
  cli.py
```
