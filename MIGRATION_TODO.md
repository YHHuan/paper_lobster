# Lobster v4 Migration TODO

Tracks what the v4 merge has **not** yet wired. Every item has a working v3
fallback, so none of this blocks `LOBSTER_USE_HERMES=0` operation.

## Stubbed in phase 2 (this pass)

- **Full Hermes gateway integration** — `lobster/bridge/gateway.py` currently
  falls back to `lobster/_legacy_main.py` when `LOBSTER_USE_HERMES=1`. Hermes's
  `gateway.run` has its own YAML config + session model; we need a translator
  and the right startup sequence for platforms + session_context.
  _Effort: M (1–2 days)_

- **Hermes smart_model_routing** — `lobster/bridge/llm.py` imports but does not
  route via `agent.smart_model_routing`. It still defers to v3 `LLMRouter`.
  The hermes router wants a model-metadata context we haven't plumbed.
  _Effort: S (half day)_

- **Hermes MemoryManager integration** — `MemoryBridge` and
  `migrate_identity_to_hermes()` back up identity md files but don't yet write
  them into a hermes `BuiltinMemoryProvider` store. Need to decide on provider
  keys (e.g. `identity.soul`) and whether to use builtin or an external plugin.
  _Effort: M (1 day)_

- **Hermes skill registry** — `lobster/bridge/skills_loader.py` adds
  agentskills.io frontmatter to every `lobster/skills/*.md` but does not call
  hermes's skill registration. `agent/skill_utils.py` is file-tree based so
  this should be straightforward once we point it at `lobster/skills/`.
  _Effort: S (half day)_

## Bigger pieces (phase 3+)

- **Trajectory recording** — wire `agent/trajectory.py` to record every loop
  iteration + publish attempt for RL data. _Effort: M._
- **RL data collection pipeline** — downstream of trajectory; push to whatever
  store Nous uses for post-training. _Effort: L._
- **Honcho dialectic user modelling** — hermes supports a Honcho provider for
  long-term user modelling; plug it in for the Telegram DM channel so Lobster
  starts learning the user's taste. _Effort: M._
- **Skills hub sync** — agentskills.io two-way sync (pull community skills,
  push curated ones). _Effort: M._
- **Hermes session/memory per-chat** — currently Lobster has a single owner;
  hermes sessions allow multi-user. Probably unnecessary unless opened up.
  _Effort: L, optional._

## Maintenance

- Keep `requirements.txt` in sync with `pyproject.toml` (Railway may build from
  either). PyYAML was added for bridge config loading.
- `lobster/_legacy_main.py` is intentionally kept as the escape-hatch entry
  point. Do not delete until the hermes gateway path is proven on Railway.
