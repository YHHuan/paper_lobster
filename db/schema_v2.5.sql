-- Lobster v2.5 Schema Migration
-- Run this in Supabase SQL Editor
-- This adds new tables alongside existing v1 tables (taste_db, drafts, etc.)

create extension if not exists vector;

-- ===== 素材庫 =====
create table if not exists discoveries (
  id uuid default gen_random_uuid() primary key,
  source_type text not null,
  source_name text,
  url text,
  title text,
  summary text,
  raw_content text,
  content_type text,
  interest_score integer,
  interest_reason text,
  language text,
  selected_for_post boolean default false,
  embedding vector(1024),
  explored_at timestamp with time zone default now()
);

-- ===== 發布紀錄 =====
create table if not exists posts (
  id uuid default gen_random_uuid() primary key,
  discovery_id uuid references discoveries(id),
  platform text default 'x',
  skill_used text,
  draft_text text,
  posted_text text,
  language text,
  hook_score integer,
  ai_smell_check_passed boolean,
  x_post_id text,
  threads_post_id text,
  twin_post_id uuid,  -- references self, added as FK below
  posted_at timestamp with time zone,
  engagement_3h jsonb default '{}',
  engagement_24h jsonb default '{}',
  engagement_72h jsonb default '{}',
  owner_feedback text,
  owner_rating integer,
  created_at timestamp with time zone default now()
);

-- Self-referencing FK for twin posts (skip if already exists)
do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'fk_twin_post') then
    alter table posts add constraint fk_twin_post
      foreign key (twin_post_id) references posts(id)
      on delete set null;
  end if;
end $$;

-- ===== 互動紀錄 =====
create table if not exists interactions (
  id uuid default gen_random_uuid() primary key,
  type text not null,
  platform text default 'x',
  related_post_id uuid references posts(id),
  thread_id text,
  other_user_handle text,
  other_user_text text,
  my_reply_text text,
  my_reply_x_id text,
  judged_as text,
  responded boolean default false,
  thread_round integer default 1,
  created_at timestamp with time zone default now()
);

-- ===== 龍蝦演化紀錄 =====
create table if not exists evolution_log (
  id uuid default gen_random_uuid() primary key,
  type text not null,
  description text,
  file_changed text,
  diff_content text,
  approved boolean default null,
  created_at timestamp with time zone default now()
);

-- ===== Token 用量 =====
create table if not exists token_usage (
  id uuid default gen_random_uuid() primary key,
  date date not null,
  heartbeat_type text,
  input_tokens integer default 0,
  output_tokens integer default 0,
  cost_usd numeric(8,4) default 0,
  model text,
  created_at timestamp with time zone default now()
);

-- ===== RSS 來源 =====
create table if not exists rss_sources (
  id uuid default gen_random_uuid() primary key,
  name text not null,
  url text not null,
  category text,
  active boolean default true,
  last_fetched_at timestamp with time zone,
  discovered_by text default 'manual',
  created_at timestamp with time zone default now()
);

-- ===== 追蹤的 X 帳號 =====
create table if not exists tracked_handles (
  id uuid default gen_random_uuid() primary key,
  handle text not null unique,
  reason text,
  proactive_engage boolean default false,
  added_at timestamp with time zone default now()
);

-- ===== 向量搜尋函數 =====
create or replace function match_discoveries(
  query_embedding vector(1024),
  match_threshold float default 0.65,
  match_count int default 10
)
returns table (
  id uuid, title text, summary text,
  content_type text, interest_score integer, similarity float
)
language sql stable
as $$
  select id, title, summary, content_type, interest_score,
    1 - (embedding <=> query_embedding) as similarity
  from discoveries
  where embedding is not null
    and 1 - (embedding <=> query_embedding) > match_threshold
  order by similarity desc
  limit match_count;
$$;

-- ===== Identity State（動態記憶，龍蝦自己維護）=====
create table if not exists identity_state (
  key text primary key,
  content text not null,
  updated_at timestamp with time zone default now(),
  updated_by text default 'lobster'
);

insert into identity_state (key, content) values
  ('curiosity', '# 我最近在關注什麼

（龍蝦還沒開始探索）'),
  ('memory', '# 近期記憶

（龍蝦還沒開始運作）')
on conflict (key) do nothing;

-- ===== 索引 =====
create index if not exists idx_discoveries_explored_at on discoveries(explored_at desc);
create index if not exists idx_discoveries_interest on discoveries(interest_score desc);
create index if not exists idx_posts_posted_at on posts(posted_at desc);
create index if not exists idx_posts_x_post_id on posts(x_post_id) where x_post_id is not null;
create index if not exists idx_posts_threads_post_id on posts(threads_post_id) where threads_post_id is not null;
create index if not exists idx_interactions_thread on interactions(thread_id);
create index if not exists idx_interactions_platform on interactions(platform, created_at desc);
create index if not exists idx_token_usage_date on token_usage(date);
