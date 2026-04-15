# Lobster v4

Lobster's curiosity brain running on Hermes Agent plumbing.

v4 is a merge of:
- **Lobster v3** — the research agent (curiosity loop, digester, evolve, Telegram bot).
- **Hermes Agent** (Nous Research) — general agent framework for gateway + memory + routing.

The Lobster brain is preserved as-is under `lobster/`. Hermes lives read-only
under `vendor/hermes-agent-main/`. Integration happens via thin shims in
`lobster/bridge/`.

## Run locally

```bash
pip install -e .
pip install -e vendor/hermes-agent-main   # optional; only if you set LOBSTER_USE_HERMES=1

# minimum env
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...
export ALLOWED_USER_ID=...            # same as TELEGRAM_CHAT_ID for solo use
# optional email channel
export SMTP_HOST=smtp.gmail.com SMTP_PORT=587 SMTP_USER=... SMTP_PASS=... SMTP_FROM=...
# optional hermes routing (off by default)
export LOBSTER_USE_HERMES=1

lobster gateway   # Telegram + Email inbound/outbound
lobster loop      # background curiosity scheduler
```

## Processes (Railway)

See `Procfile`:

```
web: lobster gateway
worker: lobster loop
```

## `LOBSTER_USE_HERMES`

- **unset / `0`** — pure v3 behaviour. Telegram bot + heartbeats exactly as before.
- **`1`** — bridge modules try to route through Hermes (gateway, smart model routing,
  memory manager). Anywhere the Hermes API isn't yet wired they fall back to v3.
  Always safe to toggle on/off.

## Layout

```
lobster/
  bridge/           # v3 ↔ hermes adapters (gateway, llm, memory, skills_loader)
  commands/         # thin /command wrappers
  bot/              # v3 Telegram bot (still authoritative in phase 1)
  brain/            # curiosity loop, reflect, hypothesize, knowledge state
  digester/         # extract / connect / synthesize
  agent_logic/      # mirror, evolve, lobster persona
  identity/         # soul.md, memory.md, style.md, curiosity.md
  skills/           # prompt-fragment skill files (agentskills.io-style frontmatter)
  scheduler/        # heartbeat.py — legacy setup_heartbeats + new run_forever
  config/lobster.yaml
vendor/hermes-agent-main/   # read-only
```

## Config

`lobster/config/lobster.yaml` — default local model, remote connect model,
gateway platforms, loop hours, memory mode, cost budget. Override via env where
documented inline.

## Status

See `MIGRATION_TODO.md` for what's still stubbed.
