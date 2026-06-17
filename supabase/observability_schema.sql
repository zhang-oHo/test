-- Observability schema (opt-in). 對應 spec-22 / task-22。
-- 學生若要跨 session 累積分析才套用；本機 .traces/*.json 已足夠教學。
--
-- 套用：psql $SUPABASE_DB_URL -f supabase/observability_schema.sql

create table if not exists graph_traces (
  id uuid primary key default gen_random_uuid(),
  thread_id text not null,
  variant text not null,
  started_at timestamptz not null,
  finished_at timestamptz not null,
  total_duration_ms int not null,
  total_input_tokens int default 0,
  total_output_tokens int default 0,
  total_cost_usd numeric(10, 6) default 0,
  payload jsonb not null,
  created_at timestamptz default now()
);

create index if not exists idx_graph_traces_variant_time on graph_traces (variant, started_at desc);
create index if not exists idx_graph_traces_thread on graph_traces (thread_id);
