-- 一次性：将 harvest 恢复的初稿任务标记为成功（MySQL aiword 库）
-- 执行前确认 ZIP 已存在：outputs/draft_zips/70c8a5cb-1575-4288-924c-50970af1a4b8.zip

UPDATE draft_generation_jobs
SET
  status = 'succeeded',
  progress = 1.0,
  message = '已从 harvest 恢复（applied=50, skipped=10，未再调 Cursor API）',
  error_summary = NULL,
  upstream_job_id = 'f643e142d4954a72',
  local_zip_path = 'outputs/draft_zips/70c8a5cb-1575-4288-924c-50970af1a4b8.zip',
  updated_at = NOW()
WHERE id = '70c8a5cb-1575-4288-924c-50970af1a4b8';
