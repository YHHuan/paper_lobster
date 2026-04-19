-- Lobster v4.0 Schema Migration — Multi-source feeds + Telegram digest.
-- Run AFTER schema_v3.sql in Supabase SQL Editor.
-- Idempotent: uses IF NOT EXISTS / ON CONFLICT throughout.

-- ============================================================
-- discoveries: extra columns for feed coordinator + digest
-- ============================================================

alter table discoveries add column if not exists fetch_batch_id uuid;
alter table discoveries add column if not exists url_hash text;
alter table discoveries add column if not exists in_digest boolean default false;
alter table discoveries add column if not exists metadata jsonb default '{}'::jsonb;

-- Backfill url_hash for existing rows (md5 of url) so the unique index can apply.
update discoveries
   set url_hash = md5(url)
 where url is not null and url_hash is null;

create unique index if not exists idx_discoveries_url_hash
  on discoveries(url_hash) where url_hash is not null;
create index if not exists idx_discoveries_batch on discoveries(fetch_batch_id);
create index if not exists idx_discoveries_in_digest
  on discoveries(in_digest) where in_digest = false;
create index if not exists idx_discoveries_explored_at_desc
  on discoveries(explored_at desc);

-- ============================================================
-- digest_history: one row per Telegram digest send
-- ============================================================

create table if not exists digest_history (
  id uuid default gen_random_uuid() primary key,
  sent_at timestamptz default now(),
  categories jsonb,
  discovery_ids uuid[],
  telegram_message_ids text[],
  token_cost numeric(8,4)
);

create index if not exists idx_digest_history_sent_at
  on digest_history(sent_at desc);

-- ============================================================
-- dynamic_sources: lobster-proposed feed entries pending owner approval
-- ============================================================

create table if not exists dynamic_sources (
  id uuid default gen_random_uuid() primary key,
  source_type text not null,                   -- rss | google_news | reddit | hackernews
  source_config jsonb not null,                -- a single YAML-equivalent entry
  added_by text default 'lobster',             -- lobster | owner
  status text default 'pending',               -- pending | active | rejected
  discovery_reason text,
  performance_score float,
  added_at timestamptz default now(),
  approved_at timestamptz,
  last_active_at timestamptz
);

create index if not exists idx_dynamic_sources_status
  on dynamic_sources(status);
