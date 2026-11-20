-- Phase 3: version-aware hybrid search (vector + full-text, fused with RRF)
-- mode: 'current' | 'as_of' (needs as_of date) | 'all' (history)
create or replace function search_chunks(
  q_emb vector(384),
  q_text text,
  mode text default 'current',
  as_of date default null,
  k int default 8
)
returns table (
  chunk_id bigint, version_id bigint, doc_id bigint, title text,
  version_label text, effective_date date, expiry_date date, status text,
  section text, content text, score double precision
)
language sql stable as $$
with eligible as (
  select c.chunk_id, c.version_id, c.section, c.content, c.embedding, c.tsv,
         v.doc_id, v.version_label, v.effective_date, v.expiry_date, v.status
  from chunks c
  join doc_versions v on v.version_id = c.version_id
  where case mode
    when 'current' then v.status = 'current'
    when 'as_of' then v.effective_date <= as_of
                      and (v.expiry_date is null or v.expiry_date > as_of)
    else true
  end
),
vec as (
  select chunk_id, row_number() over (order by embedding <=> q_emb) as r
  from eligible order by embedding <=> q_emb limit 50
),
fts as (
  select e.chunk_id, row_number() over (order by ts_rank(e.tsv, tq) desc) as r
  from eligible e, to_tsquery('english', q_text) tq
  where e.tsv @@ tq
  order by ts_rank(e.tsv, tq) desc limit 50
),
fused as (
  select coalesce(vec.chunk_id, fts.chunk_id) as chunk_id,
         coalesce(1.0 / (60 + vec.r), 0) + coalesce(1.0 / (60 + fts.r), 0) as s
  from vec full join fts on vec.chunk_id = fts.chunk_id
)
select e.chunk_id, e.version_id, e.doc_id, d.title, e.version_label,
       e.effective_date, e.expiry_date, e.status, e.section, e.content,
       f.s::double precision
from fused f
join eligible e on e.chunk_id = f.chunk_id
join documents d on d.doc_id = e.doc_id
order by f.s desc
limit k;
$$;
