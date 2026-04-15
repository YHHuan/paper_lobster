# Lobster v3.0 — Curiosity-Driven Research Explorer

## What it is

A digital lobster that thinks, explores, digests research papers, and evolves.
Not an RSS reader. Not a paper alert. A curious research partner.

Core loop: Reflect → Hypothesize → Forage → Digest → Evolve → (sometimes) Publish

## What it does on its own

| Time | Behavior |
|------|----------|
| 06:00 | Morning Seed — reflect on recent learning, generate today's questions |
| 06:15-17:59 | Curiosity Loop — forage / digest / connect on open questions. No questions = sleep. |
| 09:30 | Morning Engagement — X/Threads mentions and replies |
| 12:00 | Midday Create — post if there's a publishable insight |
| 15:30 | Afternoon Engagement |
| 18:00 | Evening Seed — second reflection, humanities/cross-domain bias |
| 22:00 | Nightly Reflection — update memory.md, Telegram daily summary |
| Sun 23:00 | Weekly Mirror + Evolve proposals |

0-10 loops/day depending on how curious the lobster is. No forced posting.

## What it pushes to you

### Daily (automatic)

- **Insight notifications**: research insights with a one-liner
- **Publish request**: hook score >= 7 → "should I post this?"
- **Daily summary**: loops run, articles read, what it learned, cost

### Weekly (automatic)

- **Evolution proposals**: source reweighting, new frontiers, deprecations
- **Knowledge growth report**: what clusters grew

## What you can do

| Command | Purpose | When |
|---------|---------|------|
| `/menu` | This table | Forgot what's available |
| `/status` | Loop status | Curious about activity |
| `/questions` | Pending questions | See what it's thinking |
| `/inject <q>` | Push a question | Want it to research something |
| `/explore <topic>` | Quick search | Ad-hoc curiosity |
| `/knowledge <topic>` | Cluster understanding | Check what it knows |
| `/digest` | Latest digest | See recent learning |
| `/evolve` | Trigger evolve now | Don't want to wait for Sunday |
| `/stats` | Monthly statistics | Check spending |
| `/pause` | Pause loop | Save tokens |
| `/resume` | Resume | Unpause |
| `/rate <id> <1-5> <note>` | Rate insight | Train the lobster's taste |
| `/track <handle>` | Track X account | Found someone worth following |
| Paste URL | Immediately digest | Found something interesting |
| Type text | Chat with lobster | Random thoughts |

## Cost

| Item | Monthly |
|------|---------|
| Local LLM (gpt-oss-b) | $0 |
| Remote LLM (Sonnet, Connect only) | ~$7.50 |
| APIs (PubMed, bioRxiv, arXiv, Tavily, Jina) | $0 |
| Railway | ~$5 |
| **Total** | **~$12.50/mo** |

## What the lobster will NOT do

- Change soul.md Core Identity or Active Projects without your approval
- Publish without your consent
- Pretend it understands (low-confidence connections are marked as such)
- Run loops for the sake of running (no questions = no loops)
