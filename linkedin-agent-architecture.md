# LinkedIn AI-Content Agent — Architecture & Build Plan

**Goal:** A scheduled agent that researches hot/controversial topics in AI, vibecoding, AI engineering, and new tools; drafts a post in *your* voice with your opinion; attaches an image if useful; sends it to a Telegram bot for your approval; and auto-posts to your LinkedIn profile once you approve.

**Owner:** Amir | **Stack fit:** Python/FastAPI, Telegram bots, Apps Script automation — all things you already run for SilkOffRoad.

---

## 1. System overview

```
┌─────────────┐
│  Scheduler  │  (cron / APScheduler — e.g. Mon/Wed/Fri 08:00)
└──────┬──────┘
       │
┌──────▼───────────────┐
│  1. RESEARCH         │  Pull live signals → rank → pick top 3–5 topics
│  (sources + ranker)  │
└──────┬───────────────┘
       │  topic + source links + summary
┌──────▼───────────────┐
│  2. DRAFT            │  LLM writes 2–3 angles in your voice, you-grounded
│  (voice + opinion)   │
└──────┬───────────────┘
       │  draft text + suggested angle
┌──────▼───────────────┐
│  3. ENRICH           │  Generate or fetch an image (optional)
│  (image gen/search)  │
└──────┬───────────────┘
       │  draft + image
┌──────▼───────────────┐
│  4. REVIEW           │  Telegram message: Approve / Edit / Regenerate / Reject
│  (Telegram approval) │
└──────┬───────────────┘
       │  approved
┌──────▼───────────────┐
│  5. POST             │  LinkedIn Posts API (w_member_social)
└──────────────────────┘
```

**Key principle:** keep yourself in the loop at stage 4. Fully autonomous posting in your name is the single biggest risk to presence-building — one hallucinated "fact" or tone-deaf hot take can undo months of work. The Telegram gate costs you 30 seconds per post and removes that risk entirely.

---

## 2. Stage 1 — Research engine

### Sources (start free, expand later)

| Source | How | Cost | Signal it gives |
|--------|-----|------|-----------------|
| Hacker News | Algolia API | Free | Best single source; points + comments |
| Reddit | PRAW (r/LocalLLaMA, r/MachineLearning, r/singularity) | Free | Practitioner debate, upvotes |
| Substack/RSS | feedparser (Raschka, Nathan Lambert, Latent Space, Simon Willison) | Free | Expert framing, deeper takes |
| News aggregators | RSS / scrape llm-stats.com, dentro.de/ai | Free | Release timeline |
| X / Twitter | API (paid) or list-scraping (ToS risk) | $$ | Real-time, but optional/skip at first |

**Start with Hacker News only.** The Algolia endpoint is free, no auth, and covers ~80% of what trends in AI:
```
https://hn.algolia.com/api/v1/search_by_date?tags=story&query=LLM
```
Run a few queries (LLM, "AI agent", "vibe coding", Claude, GPT, "AI engineering") and merge results.

### Ranking / topic selection

Score each candidate story, then dedupe near-identical ones (cosine similarity on titles, or just an LLM dedupe pass):

```
score = w1 * recency_decay(age_hours)
      + w2 * normalized(points)
      + w3 * normalized(num_comments)
      + w4 * controversy_signal           # high comment:point ratio = debate
      + w5 * topic_match(your_focus_areas) # AI eng / vibecoding / tools
```

- **Controversy** is what you specifically asked for: a high comment-to-upvote ratio usually means people are arguing. Weight `w4` highly.
- **Topic match:** keep a small keyword/embedding filter so you don't get pulled into adjacent noise (crypto, generic tech).
- Output: top 3–5 ranked topics, each with title, links, a 3-sentence summary, and *why it's hot* (the debate angle).

### Optional enrichment
Before drafting, have the LLM (with web search enabled) read 1–2 source links per topic so the draft is grounded in the actual story, not the model's stale priors. This matters — AI news goes stale in days.

---

## 3. Stage 2 — Draft writer (your voice + your opinion)

The hard part. Generic LLM output reads like generic LLM output, which kills credibility on LinkedIn fast. Three levers:

### a) Voice priming
Feed 5–10 of your own past posts (or any writing samples) into the system prompt as few-shot examples. If you don't have LinkedIn posts yet, use messages/notes you've written in the same register. The model mimics rhythm, sentence length, and vocabulary far better from examples than from instructions.

### b) Persona grounding
Your differentiator is the **AI/ML student + Central Asia tour founder** angle. Bake it in:
> "You write as Amir: a BSc AI student at JKU Linz who also runs a real adventure-tour business. You prefer concrete, practical takes grounded in actually shipping software for a small business over abstract hype. You're skeptical of benchmarks-as-marketing. You sometimes connect AI topics to running operations on the ground."

This is the thing nobody else can copy. Lean on it.

### c) Multiple angles, you choose
For each topic, generate 2–3 *distinct* angles, not three tones of the same take:
- **Contrarian** — "everyone's celebrating X, here's why it's overhyped"
- **Practical** — "here's how I'd actually use this in a real workflow"
- **What everyone's missing** — the under-discussed second-order effect

You pick the angle in Telegram (or let it suggest one and you swap).

### Draft spec
- Length: LinkedIn sweet spot is ~150–250 words, hook in the first line (before the "...see more" fold).
- No hashtag soup; 3–5 relevant tags max.
- Always include the source link or context so it doesn't look like you're claiming the news as your own discovery.
- A **fact-check pass:** have the model flag any specific claim (numbers, quotes, dates) it isn't certain about, so you can verify before posting. Hallucinated stats are the #1 credibility killer.

---

## 4. Stage 3 — Image enrichment (optional per post)

Decide per-post whether an image helps. Options:

- **Generated image** — API image generation for conceptual/abstract visuals. Good for "concept" posts.
- **Recreated chart** — if the topic is a benchmark/number, generate a simple clean chart yourself (matplotlib). These often *outperform* AI images on LinkedIn and look credible.
- **Text-on-color card** — a bold pull-quote on a solid background. Cheap, high-contrast in the feed, very on-brand for "thought" posts.
- **Searched image** — only with care. Charts/diagrams from papers are usually fine with attribution; **product marketing images, logos, and people's photos are a copyright/ToS risk — avoid.**

**Recommendation:** default to recreated charts or text cards. They look more credible than generic AI art and sidestep copyright entirely.

---

## 5. Stage 4 — Telegram review (your approval gate)

Reuse the pattern from your expense bot. For each generated post, send:

```
🔥 Topic: <title>
   Why it's hot: <1-line debate angle>
   Sources: <links>

📝 Draft (angle: Practical):
   <full post text>

🖼 Image: <attached / "none">

[✅ Approve & post]  [✏️ Edit]  [🔄 Regenerate]
[🎭 Other angle]     [🖼 New image]  [❌ Skip]
```

- **Approve** → queue for posting (immediately, or at an optimal time slot).
- **Edit** → you reply with edited text; bot posts your version.
- **Regenerate / Other angle** → re-run stage 2 with a different angle.
- **Skip** → discard, optionally surface the next-ranked topic.

Inline keyboard buttons (callback queries) make this one-tap on mobile.

---

## 6. Stage 5 — Posting to LinkedIn

### What's actually allowed (verified June 2026)
Good news: posting to your **own personal profile** is one of the few things the LinkedIn API permits without partner approval.

- **Auth:** OAuth 2.0, 3-legged (you grant consent once).
- **Scopes:** `w_member_social` (post) + `profile`/`openid` (identity).
- **App setup:** register an app in the LinkedIn Developer Portal, enable the **"Share on LinkedIn"** product, get Client ID/Secret.
- **Endpoint:** the **Posts API** (`/rest/posts`) — the older UGC endpoint is legacy.
- **Required headers:** `LinkedIn-Version` (YYYYMM format) and `X-Restli-Protocol-Version: 2.0.0`.
- **Rate limit:** ~100 calls/day/member — a non-issue for a few posts a week.

### The one gotcha: token expiry
- Access tokens expire in **60 days**; refresh tokens last **365 days**.
- Your agent **must** store and auto-refresh tokens, and alert you (via Telegram) when the 365-day refresh token is near expiry so you can re-consent.
- Build token storage + refresh logic from day one; don't bolt it on later.

### Image posts
Posting an image is a 3-step dance: register an image upload → PUT the bytes → create the post referencing the returned image URN. Plan for it but ship text-only first.

---

## 7. Tech stack (fits what you already run)

| Concern | Choice | Why |
|---------|--------|-----|
| Language | Python | Matches your existing bots/tools |
| Scheduler | APScheduler (or system cron) | Simple; no extra infra |
| LLM | Anthropic / Gemini API | Your call; voice priming works on both |
| Web framework | FastAPI | Only needed for the OAuth callback + maybe a dashboard later |
| Telegram | python-telegram-bot | Same lib pattern as your expense bot |
| Storage | SQLite to start → Postgres/Supabase if it grows | You already use Supabase |
| Hosting | Railway | Same as your CRM plan |
| Secrets | .env / Railway vars | Never commit tokens |

Storage holds: OAuth tokens, seen-topics history (so you don't repeat stories), draft queue, and a post log.

---

## 8. Build order (phased)

**Phase 0 — Plumbing (½ day)**
LinkedIn dev app, OAuth flow, store + refresh tokens, post one hardcoded "hello world" via the API. *De-risk the posting path first* — it's the part most likely to surprise you.

**Phase 1 — Research engine (1 day)**
HN Algolia pull → ranking → top-5 topics printed to console. No LLM yet.

**Phase 2 — Draft writer (1 day)**
Feed a topic + your voice samples → 2–3 angles. Tune the prompt until it sounds like you. This is where most of the quality lives; spend time here.

**Phase 3 — Telegram review (1 day)**
Wire stages 1–2 into the bot with inline approve/edit/regenerate buttons. At this point you have a useful tool even without auto-posting.

**Phase 4 — Auto-post on approve (½ day)**
Connect Approve → LinkedIn Posts API (text only).

**Phase 5 — Images (1 day, optional)**
Add chart/text-card generation, then the LinkedIn image-upload flow.

**Phase 6 — Polish**
Optimal-time scheduling, seen-topics dedupe, weekly digest, token-expiry alerts.

You'd have a genuinely useful tool after Phase 3, and the full thing by Phase 4.

---

## 9. Risks & guardrails

- **Hallucinated facts** → fact-check pass in stage 2 + your human review. Never let a specific stat through unverified.
- **Generic voice** → voice priming with real samples; reject-and-regenerate freely early on while you tune.
- **Repetition / looking like a news bot** → seen-topics history; always add *your* opinion, never just summarize the news.
- **Over-posting** → cap at 3–4/week; quality over volume for presence-building.
- **Token expiry mid-season** → Telegram alert before refresh token lapses.
- **Copyright on images** → prefer self-made charts/cards; avoid scraped marketing images and photos.
- **LinkedIn ToS** → only use the official API for your own profile; never scrape or automate engagement (likes/follows) — that's what gets accounts flagged.

---

## 10. Decisions still open

1. **LLM provider** — Anthropic vs Gemini (or both, A/B the voice).
2. **Posting cadence** — fixed slots (Mon/Wed/Fri) vs on-demand when a hot topic breaks.
3. **Image default** — off by default, or always attempt a chart/card?
4. **Topic memory horizon** — how long before a topic can resurface (e.g. 30 days)?

None of these block Phase 0–1, so you can start building and decide as you go.
