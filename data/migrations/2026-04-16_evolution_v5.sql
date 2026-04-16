-- Evolution v5 schema migration (2026-04-16)
--
-- Covers all four proposals in EVOLUTION_PLAN.md:
--   P1: outcome-gated prompt overrides (writer/editor/critic/hook) + A/B
--   P2: auto-dream (nightly cluster consolidation — no embedding)
--   P3: feedback → source_weights + cluster interest + skill bias
--   P4: self-tuning critic (reuses prompt_overrides; adds post status tracking)
--
-- Run in Supabase SQL editor. All statements are idempotent (IF NOT EXISTS /
-- ADD COLUMN IF NOT EXISTS), so re-running is safe.

-- =============================================================
-- P1 + P4 : prompt_overrides (outcome-gated, versioned, A/B-ready)
-- =============================================================

create table if not exists prompt_overrides (
  id uuid primary key default gen_random_uuid(),
  version int not null,
  target text not null check (target in ('writer','editor','critic','hook')),
  variant text not null default 'A',             -- A/B label; 'A' = baseline, 'B' = challenger
  content text not null,                         -- delta prompt appended to skill md
  derived_from jsonb not null,                   -- {top_post_ids:[], bottom_post_ids:[], diff_rationale:"..."}
  baseline_engagement numeric,                   -- 7d mean at creation
  validation_engagement numeric,                 -- 7d mean two weeks later
  status text not null default 'active'
    check (status in ('dry_run','active','superseded','rolled_back','validated')),
  created_at timestamptz default now(),
  validated_at timestamptz,
  superseded_at timestamptz,
  notes text
);

create index if not exists prompt_overrides_target_status_idx
  on prompt_overrides (target, status);
create index if not exists prompt_overrides_variant_idx
  on prompt_overrides (target, variant, status);

-- posts: track which override variant was used at write-time, so we can
-- attribute engagement back to the variant later.
alter table posts add column if not exists override_variant text;       -- 'A' | 'B' | null (no override active)
alter table posts add column if not exists override_ids jsonb;          -- {writer: uuid, editor: uuid, critic: uuid, hook: uuid}

-- P4 : critic kill tracking (so we can measure critic's accuracy)
alter table posts add column if not exists status text default 'published'
  check (status in ('draft','killed_by_critic','published','human_override'));
alter table posts add column if not exists killed_at timestamptz;
alter table posts add column if not exists kill_reason jsonb;           -- from Critic: {issues:[], verdict:"kill", overall_quality:n}
alter table posts add column if not exists human_override_at timestamptz;
alter table posts add column if not exists human_override_note text;

-- =============================================================
-- P2 : dream (nightly cluster consolidation — no embedding)
-- =============================================================

alter table knowledge_clusters add column if not exists last_dream_at timestamptz;
alter table knowledge_clusters add column if not exists parent_cluster_id text;    -- subset relation from merge judge
alter table knowledge_clusters add column if not exists split_from_cluster_id text;-- reverse pointer for /revert_split

-- dream log — one row per nightly run, covers all 4 steps
create table if not exists dream_log (
  id uuid primary key default gen_random_uuid(),
  ran_at timestamptz default now(),
  clusters_before int,
  clusters_after int,
  extracts_classified int,
  merges jsonb,                  -- [{from:[id1,id2], into:id1, rationale:"..."}, ...]
  splits jsonb,                  -- [{from:id1, into:[id_new1, id_new2], rationale:"..."}, ...]
  new_candidates jsonb,          -- [{proposed_topic, extract_ids, seen_count}]
  reunderstandings jsonb,        -- [{cluster_id, confidence_before, confidence_after}]
  narrative text,                -- LLM-written Telegram summary
  llm_tokens_used int,
  duration_seconds int,
  status text default 'completed'  -- completed | failed | reverted
);

create index if not exists dream_log_ran_at_idx on dream_log (ran_at desc);

-- pending_clusters — new candidate topics that must survive N nights to promote
create table if not exists pending_clusters (
  id uuid primary key default gen_random_uuid(),
  proposed_topic text not null,
  extract_ids uuid[] not null default array[]::uuid[],
  seen_count int not null default 1,
  first_seen timestamptz default now(),
  last_seen timestamptz default now(),
  promoted_at timestamptz,          -- non-null once promoted to knowledge_clusters
  dropped_at timestamptz,           -- non-null once expired without promotion
  promoted_cluster_id text
);

create index if not exists pending_clusters_active_idx
  on pending_clusters (seen_count desc)
  where promoted_at is null and dropped_at is null;

-- =============================================================
-- P2 + P3 : knowledge_clusters gets interest_score for P3 dials
-- =============================================================

alter table knowledge_clusters add column if not exists interest_score float default 0.5;

-- =============================================================
-- P3 : feedback capture + dials
-- =============================================================

create table if not exists feedback (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz default now(),
  user_text text not null,
  classified_as text,            -- enum: boring | nice | too_short | too_long | wrong_tone | love_it | more_like_this | less_like_this | unclear
  target_type text,              -- discovery | post | cluster | skill
  target_id text,                -- uuid or string (skill name is a string)
  related_source text,           -- denormalized source for faster aggregation
  applied boolean default false,
  applied_at timestamptz,
  weight_delta numeric           -- the actual adjustment applied (for audit)
);

create index if not exists feedback_unapplied_idx
  on feedback (created_at)
  where applied = false;
create index if not exists feedback_target_idx
  on feedback (target_type, target_id);

-- skill usage bias (P3): table may or may not exist depending on v3 state.
create table if not exists skills_usage (
  skill_name text primary key,
  use_count int default 0,
  last_used_at timestamptz,
  human_bias float default 0.0,  -- P3 dial: + → prefer this skill, - → avoid
  updated_at timestamptz default now()
);

-- =============================================================
-- Convenience view for P1 + P4 validation jobs
-- =============================================================

create or replace view posts_with_engagement as
select
  p.id,
  p.platform,
  p.skill_used,
  p.language,
  p.hook_score,
  p.status,
  p.override_variant,
  p.override_ids,
  p.posted_at,
  p.killed_at,
  p.human_override_at,
  -- collapse engagement_72h json to a single scalar for easy ranking
  coalesce(
    (p.engagement_72h::jsonb ->> 'like_count')::numeric, 0
  ) + coalesce(
    (p.engagement_72h::jsonb ->> 'reply_count')::numeric, 0
  ) + coalesce(
    (p.engagement_72h::jsonb ->> 'retweet_count')::numeric, 0
  ) + coalesce(
    (p.engagement_72h::jsonb ->> 'quote_count')::numeric, 0
  ) as eng_72h_total
from posts p;

-- =============================================================
-- Done. Sanity: list the new surface area.
-- =============================================================

-- To verify after running, execute:
--   select table_name from information_schema.tables
--   where table_name in ('prompt_overrides','dream_log','pending_clusters','feedback','skills_usage');
--
--   select column_name from information_schema.columns
--   where table_name='posts'
--     and column_name in ('override_variant','override_ids','status','killed_at',
--                         'kill_reason','human_override_at','human_override_note');
--
--   select column_name from information_schema.columns
--   where table_name='knowledge_clusters'
--     and column_name in ('last_dream_at','parent_cluster_id','split_from_cluster_id','interest_score');
