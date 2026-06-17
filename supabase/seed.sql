insert into ai_skills (
  skill_id,
  name,
  description,
  category,
  system_prompt,
  version,
  enabled
) values
  (
    'general_chat',
    '一般對話',
    '一般閒聊與安全 fallback。',
    'general',
    '保持簡潔、誠實、可讀。',
    '0.1.0',
    true
  )
on conflict (skill_id) do update
set
  name = excluded.name,
  description = excluded.description,
  category = excluded.category,
  system_prompt = excluded.system_prompt,
  version = excluded.version,
  enabled = excluded.enabled;
