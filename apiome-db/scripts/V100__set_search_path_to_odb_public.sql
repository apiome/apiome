SET search_path TO apiome, public;

-- Who created the key; REST uses this as actor/creator_id for writes (#3329).
ALTER TABLE apiome.api_keys
  ADD COLUMN IF NOT EXISTS created_by_user_id UUID REFERENCES apiome.users(id) ON DELETE SET NULL;

COMMENT ON COLUMN apiome.api_keys.created_by_user_id IS
  'User who created this API key; apiome-rest maps this to auth user_id for project/version creator_id when using X-API-Key.';

CREATE INDEX IF NOT EXISTS idx_api_keys_created_by_user_id
  ON apiome.api_keys(created_by_user_id)
  WHERE deleted_at IS NULL;
