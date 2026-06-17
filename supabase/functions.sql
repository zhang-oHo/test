-- spec-27 hybrid retrieval：vector_weight 與 keyword_weight 控制兩條 rank 的相對權重。
-- 預設 (1.0, 0.0) 等同純向量；要啟用混合檢索由 Python 端依 settings.hybrid_enabled 傳入。
-- 行為相容性：function signature 增加新參數但保留 defaults，舊 client 直接呼叫不會壞，
-- 但 *結果排序* 會從原本 RRF(1+1) 改為 weighted-RRF(1+0)；要復原舊行為傳 (1.0, 1.0)。
create or replace function match_private_knowledge(
  query_embedding vector(1536),
  query_text text,
  match_count int default 8,
  category_filter text[] default null,
  vector_weight float default 1.0,
  keyword_weight float default 0.0
)
returns table (
  id uuid,
  title text,
  content text,
  category text,
  metadata jsonb,
  vector_score float,
  keyword_score float,
  combined_score float
)
language sql stable
as $$
  with vector_matches as (
    select
      pk.id,
      1 - (pk.embedding <=> query_embedding) as vector_score,
      row_number() over (order by pk.embedding <=> query_embedding) as vector_rank
    from private_knowledge pk
    where pk.embedding is not null
      and (category_filter is null or pk.category = any(category_filter))
    order by pk.embedding <=> query_embedding
    limit match_count * 3
  ),
  keyword_matches as (
    select
      pk.id,
      ts_rank(pk.search_vector, plainto_tsquery('simple', query_text)) as keyword_score,
      row_number() over (
        order by ts_rank(pk.search_vector, plainto_tsquery('simple', query_text)) desc
      ) as keyword_rank
    from private_knowledge pk
    where pk.search_vector @@ plainto_tsquery('simple', query_text)
      and (category_filter is null or pk.category = any(category_filter))
    limit match_count * 3
  ),
  fused as (
    select
      pk.id,
      pk.title,
      pk.content,
      pk.category,
      pk.metadata,
      coalesce(vm.vector_score, 0) as vector_score,
      coalesce(km.keyword_score, 0) as keyword_score,
      (
        vector_weight  * coalesce(1.0 / (60 + vm.vector_rank), 0) +
        keyword_weight * coalesce(1.0 / (60 + km.keyword_rank), 0)
      ) as combined_score
    from private_knowledge pk
    left join vector_matches vm on pk.id = vm.id
    left join keyword_matches km on pk.id = km.id
    where vm.id is not null or km.id is not null
  )
  select *
  from fused
  order by combined_score desc
  limit match_count;
$$;
