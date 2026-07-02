-- ============================================================================
-- Build-a-Champion · Wimbledon — Supabase setup (analytics + aggregates)
-- ----------------------------------------------------------------------------
-- Run this once in the Supabase SQL editor. Then put your project URL + anon
-- key into the SUPA = { url, anon } object in build-a-champion-game_2.html.
-- The client only ever INSERTS (gated behind user consent) and reads back
-- pre-aggregated rollups via the RPCs below — never raw rows.
--
-- Privacy: session_id is an anonymous random UUID stored in the browser only.
-- No names, emails, IPs or other personal data are collected. Pair this with a
-- short privacy notice + the in-game consent toggle (already wired up).
-- ============================================================================

-- ---------- events: anonymous, fine-grained gameplay analytics --------------
create table if not exists public.events (
  id              bigint generated always as identity primary key,
  created_at      timestamptz not null default now(),
  session_id      text not null,
  event_type      text not null,        -- 'game_start' | 'spin' | 'pick' | 'result'
  payload         jsonb,                -- e.g. pick = {attr, value, source, offered:{...}}
  game_version    text,
  ratings_version text,
  daily_seed      text,
  mode            text                  -- 'daily' | 'free'
);
create index if not exists events_seed_type_idx on public.events (daily_seed, event_type);

alter table public.events enable row level security;
-- Anonymous browsers may INSERT only. With no SELECT policy, they cannot read
-- any rows back, so the raw event stream is never exposed to the client.
drop policy if exists "anon insert events" on public.events;
create policy "anon insert events"
  on public.events for insert to anon with check (true);

-- ---------- results: one row per completed run ------------------------------
create table if not exists public.results (
  id              bigint generated always as identity primary key,
  created_at      timestamptz not null default now(),
  session_id      text not null,
  daily_seed      text,
  mode            text,
  score           int,
  rounds_reached  text,                 -- 'R1'..'F'
  won             boolean,
  build           jsonb,                -- the six drafted shot values + sources
  archetype       text,                 -- 'The Cannon · Ice' etc.
  clutch          numeric,
  stamina         numeric,
  title_odds      numeric,
  game_version    text,
  ratings_version text
);
create index if not exists results_seed_idx on public.results (daily_seed);

alter table public.results enable row level security;
drop policy if exists "anon insert results" on public.results;
create policy "anon insert results"
  on public.results for insert to anon with check (true);

-- ============================================================================
-- Aggregate RPCs — the ONLY way the client reads data back. SECURITY DEFINER
-- lets them roll up across all rows without granting table-level SELECT.
-- ============================================================================

-- Daily summary: how many played, win rate, score, archetype spread.
create or replace function public.get_daily_aggregates(seed text)
returns json
language sql
security definer
set search_path = public
as $$
  select json_build_object(
    'players',    (select count(*) from results where daily_seed = seed),
    'win_rate',   (select round(avg(case when won then 1 else 0 end)::numeric, 3)
                     from results where daily_seed = seed),
    'avg_score',  (select round(avg(score)::numeric, 1) from results where daily_seed = seed),
    'archetypes', (select coalesce(json_object_agg(archetype, c), '{}'::json)
                     from (select archetype, count(*) c from results
                           where daily_seed = seed group by archetype) a)
  );
$$;
grant execute on function public.get_daily_aggregates(text) to anon;

-- Pick rates: which players got raided, and for which shot (top 20).
-- Compare against 'offered' in the payload later to de-confound popularity.
create or replace function public.get_pick_rates(seed text)
returns json
language sql
security definer
set search_path = public
as $$
  select coalesce(json_object_agg(source, c), '{}'::json)
  from (
    select payload->>'source' as source, count(*) c
    from events
    where daily_seed = seed and event_type = 'pick'
    group by payload->>'source'
    order by c desc
    limit 20
  ) t;
$$;
grant execute on function public.get_pick_rates(text) to anon;

-- ============================================================================
-- Optional hardening / housekeeping (recommended):
--   * Add a daily retention job to delete events older than N days.
--   * Rate-limit inserts via an Edge Function if abuse appears.
--   * For a trustworthy leaderboard, validate each submitted daily result in an
--     Edge Function by recomputing it from (daily_seed + build) — the game is
--     fully deterministic, so the server can reproduce the exact outcome.
-- ============================================================================
