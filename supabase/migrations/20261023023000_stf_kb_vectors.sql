-- The copilot's dense-retrieval index in the same Postgres as everything else
-- (services/api/vectors.py, STF_VECTOR_BACKEND=pgvector): one row per knowledge-base passage
-- with its embedding, an HNSW index for approximate nearest-neighbour search, and the small
-- meta table the store uses to know whether the index still matches the knowledge base
-- (rebuilt when docs change, the same contract the SQLite store keeps locally).
--
-- Why a real vector column and not more JSON: at 920 passages brute-force cosine is fine, but
-- this table is the seam for continuous ingestion (alarm logs, shift reports) where the row
-- count grows past brute force - the HNSW index is already there, and metadata filtering
-- (file, doc, path) comes free with Postgres.
create extension if not exists vector;

create table if not exists public.kb_vectors (
  id    integer      not null primary key,  -- the passage's id in web/public/copilot/kb.json
  file  text         not null,               -- repository-relative source file
  line  integer      not null default 0,     -- the passage's line there (deep links)
  doc   text         not null default '',    -- document title
  path  text[]       not null default '{}',  -- section headers leading to the passage
  meta  jsonb        not null default '{}'::jsonb,  -- future filters (doc type, part, standard)
  emb   vector(384)  not null                -- the embedder's width (MiniLM, hash); a different
                                             -- STF_EMBED_MODEL keeps its own dims check in
                                             -- PgVectorStore.available() and falls back to SQLite
);

-- approximate cosine search; created after bulk inserts (vectors.py rebuilds in one transaction)
create index if not exists kb_vectors_emb_idx on public.kb_vectors using hnsw (emb vector_cosine_ops);

-- the cache key: 'passages' -> blake2b(embedder, dim, passage ids), same key the SQLite store
-- writes into its meta table - a kb or embedder change is detected before any search runs
create table if not exists public.kb_meta (
  k text primary key,
  v text not null
);

alter table public.kb_vectors enable row level security;
alter table public.kb_meta enable row level security;

-- the API uses the service key; nobody else may read or write the index
-- (the embeddings encode the whole knowledge base)
-- one rebuild: truncate + remember the new cache key (PostgREST cannot DELETE without a filter)
create or replace function public.stf_kb_reset(p_key text)
returns void
language sql
security invoker
set search_path = public
as $$
  truncate public.kb_vectors;
  insert into public.kb_meta as m (k, v) values ('passages', p_key)
  on conflict (k) do update set v = excluded.v;
$$;

-- bulk insert of one rebuild batch, as a JSONB array of rows - the casts are explicit, so no
-- reliance on a text->vector assignment cast the driver may or may not issue
create or replace function public.stf_kb_insert(p_rows jsonb)
returns void
language sql
security invoker
set search_path = public
as $$
  insert into public.kb_vectors (id, file, line, doc, path, meta, emb)
  select
    (r->>'id')::integer,
    coalesce(r->>'file', ''),
    coalesce((r->>'line')::integer, 0),
    coalesce(r->>'doc', ''),
    coalesce((select array(select jsonb_array_elements_text(coalesce(r->'path', '[]'::jsonb)))), '{}'),
    coalesce(r->'meta', '{}'::jsonb),
    (r->>'emb')::vector
  from jsonb_array_elements(p_rows) as r;
$$;

-- ANN top-k by cosine similarity; takes the embedding as its text form ('[0.12,…]') so the
-- API can call it over PostgREST with a plain JSON body
create or replace function public.stf_match_kb(p_emb text, p_k integer)
returns table (id integer, score double precision)
language sql
security invoker
set search_path = public
as $$
  select v.id, 1.0 - (v.emb <=> p_emb::vector) as score
  from public.kb_vectors as v
  order by v.emb <=> p_emb::vector
  limit greatest(p_k, 1);
$$;

revoke execute on function public.stf_kb_reset(text) from public, anon, authenticated;
grant execute on function public.stf_kb_reset(text) to service_role;
revoke execute on function public.stf_kb_insert(jsonb) from public, anon, authenticated;
grant execute on function public.stf_kb_insert(jsonb) to service_role;
revoke execute on function public.stf_match_kb(text, integer) from public, anon, authenticated;
grant execute on function public.stf_match_kb(text, integer) to service_role;
