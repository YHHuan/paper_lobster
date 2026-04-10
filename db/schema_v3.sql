-- Lobster v3.0 Schema Migration
-- Run AFTER schema_v2.5.sql in Supabase SQL Editor.
-- Adds the curiosity-loop tables on top of existing v2.5 tables.

-- ============================================================
-- v3 NEW TABLES
-- ============================================================

-- 龍蝦的腦：knowledge clusters (one row = one topic the lobster has a model of)
create table if not exists knowledge_clusters (
  id text primary key,                       -- e.g. 'hrv_firefighter'
  current_understanding text not null,        -- 自然語言摘要
  confidence real default 0.5,
  key_sources jsonb default '[]'::jsonb,     -- extract IDs
  open_gaps jsonb default '[]'::jsonb,       -- 未解答的問題
  related_clusters jsonb default '[]'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- Structured extracts (one row per article processed by digester/extract)
create table if not exists extracts (
  id text primary key,                       -- e.g. 'ext_20260410_012'
  source_type text not null,                 -- pubmed | arxiv | biorxiv | blog | twitter
  source_id text,                            -- PMID, arXiv ID, URL, etc.
  url text,
  title text,
  structured_data jsonb not null,            -- PICO or other schema output
  one_liner text,                            -- Salmon-style summary
  created_at timestamptz default now()
);

-- Connection results (one row per extract × cluster comparison from digester/connect)
create table if not exists connections (
  id text primary key,
  extract_id text references extracts(id) on delete cascade,
  connection_type text not null,             -- confirms | contradicts | extends | novel | irrelevant
  connected_clusters jsonb default '[]'::jsonb,
  insight text,
  confidence real,
  questions_spawned jsonb default '[]'::jsonb,
  created_at timestamptz default now()
);

-- Insights (publishable or not — produced by digester/synthesize)
create table if not exists insights (
  id text primary key,
  type text not null,                        -- trend | gap | connection | research_lead | tool_discovery
  title text not null,
  body text not null,
  soul_relevance jsonb default '[]'::jsonb,  -- active project names
  publishable boolean default false,
  hook_score integer,
  source_extracts jsonb default '[]'::jsonb, -- extract IDs
  published boolean default false,
  human_rating integer,                      -- 1-5, nullable
  human_comment text,
  created_at timestamptz default now()
);

-- Open questions queue (foraged from when status='pending')
create table if not exists open_questions (
  id serial primary key,
  question text not null,
  soul_anchor text,
  expected_source_types jsonb default '[]'::jsonb,
  priority real default 0.5,
  reasoning text,
  parent_insight_id text,                    -- which insight spawned this
  status text default 'pending',             -- pending | foraging | resolved | stale
  created_at timestamptz default now(),
  resolved_at timestamptz
);

-- Source quality tracking (read by Forage to weight choices, written by Evolve)
create table if not exists source_weights (
  source text primary key,
  weight real default 0.5,
  connect_rate_7d real,
  connect_rate_30d real,
  total_extracts integer default 0,
  total_connects integer default 0,
  updated_at timestamptz default now()
);

-- Curiosity loop run log (one row per loop iteration)
create table if not exists loop_runs (
  id serial primary key,
  started_at timestamptz default now(),
  finished_at timestamptz,
  questions_input integer,
  extracts_produced integer,
  connections_made integer,
  insights_generated integer,
  local_tokens_used integer default 0,
  remote_tokens_used integer default 0,
  status text default 'running',             -- running | completed | stalled | budget_exceeded | failed
  notes text
);

-- Evolution proposals (Telegram → user approve/reject)
create table if not exists evolution_proposals (
  id serial primary key,
  type text not null,                        -- source_quality | frontier | deprecation
  proposal jsonb not null,
  status text default 'pending',             -- pending | approved | rejected
  created_at timestamptz default now(),
  resolved_at timestamptz
);

-- Reflection memos (one row per Reflect run, used as input for Hypothesize)
create table if not exists reflections (
  id serial primary key,
  memo text not null,
  trigger text,                              -- 'morning_seed' | 'evening_seed' | 'manual' | ...
  created_at timestamptz default now()
);

-- ============================================================
-- INDEXES
-- ============================================================

create index if not exists idx_open_questions_status on open_questions(status);
create index if not exists idx_open_questions_priority on open_questions(priority desc) where status = 'pending';
create index if not exists idx_extracts_source on extracts(source_type);
create index if not exists idx_extracts_created on extracts(created_at desc);
create index if not exists idx_connections_type on connections(connection_type);
create index if not exists idx_connections_extract on connections(extract_id);
create index if not exists idx_insights_publishable on insights(publishable) where publishable = true;
create index if not exists idx_insights_created on insights(created_at desc);
create index if not exists idx_loop_runs_date on loop_runs(started_at desc);
create index if not exists idx_evolution_status on evolution_proposals(status);
create index if not exists idx_reflections_created on reflections(created_at desc);

-- ============================================================
-- SEED source_weights (initial values from soul.md)
-- ============================================================

insert into source_weights (source, weight) values
  ('pubmed',  0.90),
  ('biorxiv', 0.75),
  ('arxiv',   0.80),
  ('tavily',  0.50),
  ('jina',    0.45)
on conflict (source) do nothing;

-- ============================================================
-- Identity_state seeds (extend v2.5)
-- ============================================================

insert into identity_state (key, content) values
  ('curiosity_loop_paused', 'false'),
  ('last_seed_date', '')
on conflict (key) do nothing;
