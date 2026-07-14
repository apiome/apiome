-- Per-key MCP capability grants — MTG-1.3 (#4767).
--
-- Problem: runtime enforcement must bind to the API key used for access.
-- mcp_api_keys.scope_json only limits which tenants/projects' data a key may
-- read — not which tools it may invoke. Tool enable-sets must stay independent
-- of AGX agent keys (api_keys.kind=agent).
--
-- Solution: extend apiome.mcp_api_keys with jsonb capability grants (MVP parity
-- with AGX allowlist patterns; no child table mcp_api_key_tools):
--
--   * capability_mode  — 'inherit' | 'explicit' (default inherit)
--   * enabled_tools    — jsonb array of stable MTG-1.1 tool ids (default [])
--
-- Semantics:
--   * inherit  — enabled_tools must be []; effective enable-set is the tenant
--                default enable-set at resolve time (MTG-1.4). Changing tenant
--                defaults never rewrites rows stored for explicit keys.
--   * explicit — enabled_tools is authoritative for that key; tools absent from
--                the list cannot be called once MTG-1.4 / 2.2 gate.
--
-- Write-time invariant: key enable-set ⊆ tenant ceiling (BEFORE INSERT/UPDATE).
-- Missing tenant_mcp_policies row is treated as full ceiling (default_mode=all)
-- until MTG-1.5 seeds existing tenants. Under default_mode all/inherit_registry,
-- absent tool rows mean allowed; under explicit, every listed tool must have
-- in_ceiling=true. Tools with in_ceiling=false are always rejected.
--
-- Existing keys pick up capability_mode=inherit and enabled_tools=[] via column
-- defaults on ADD COLUMN (additive; no row rewrite). MTG-1.5 still documents the
-- full upgrade / regression path.
--
-- Rollback notes: purely additive. To roll back:
--   DROP TRIGGER IF EXISTS trg_mcp_api_keys_capability_ceiling ON apiome.mcp_api_keys;
--   DROP FUNCTION IF EXISTS apiome.trg_mcp_api_keys_capability_ceiling();
--   ALTER TABLE apiome.mcp_api_keys
--     DROP CONSTRAINT IF EXISTS mcp_api_keys_capability_mode_ck,
--     DROP CONSTRAINT IF EXISTS mcp_api_keys_enabled_tools_valid_ck,
--     DROP CONSTRAINT IF EXISTS mcp_api_keys_inherit_empty_tools_ck;
--   DROP FUNCTION IF EXISTS apiome.mcp_enabled_tools_is_valid(jsonb);
--   ALTER TABLE apiome.mcp_api_keys
--     DROP COLUMN IF EXISTS enabled_tools,
--     DROP COLUMN IF EXISTS capability_mode;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------
-- Shape helper for enabled_tools CHECK (subqueries cannot live in CHECK directly)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION apiome.mcp_enabled_tools_is_valid(p_tools jsonb)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT p_tools IS NOT NULL
    AND jsonb_typeof(p_tools) = 'array'
    AND NOT EXISTS (
      SELECT 1
      FROM jsonb_array_elements_text(p_tools) AS t(tool_id)
      WHERE char_length(trim(tool_id)) = 0
    );
$$;

COMMENT ON FUNCTION apiome.mcp_enabled_tools_is_valid(jsonb) IS
  'True when p_tools is a jsonb array of non-empty trimmed tool id strings (#4767, MTG-1.3).';

-- ---------------------------------------------------------------------------
-- Columns on mcp_api_keys
-- ---------------------------------------------------------------------------
ALTER TABLE mcp_api_keys
  ADD COLUMN IF NOT EXISTS capability_mode TEXT NOT NULL DEFAULT 'inherit',
  ADD COLUMN IF NOT EXISTS enabled_tools JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE mcp_api_keys
  DROP CONSTRAINT IF EXISTS mcp_api_keys_capability_mode_ck;
ALTER TABLE mcp_api_keys
  ADD CONSTRAINT mcp_api_keys_capability_mode_ck
    CHECK (capability_mode IN ('inherit', 'explicit'));

ALTER TABLE mcp_api_keys
  DROP CONSTRAINT IF EXISTS mcp_api_keys_enabled_tools_valid_ck;
ALTER TABLE mcp_api_keys
  ADD CONSTRAINT mcp_api_keys_enabled_tools_valid_ck
    CHECK (apiome.mcp_enabled_tools_is_valid(enabled_tools));

ALTER TABLE mcp_api_keys
  DROP CONSTRAINT IF EXISTS mcp_api_keys_inherit_empty_tools_ck;
ALTER TABLE mcp_api_keys
  ADD CONSTRAINT mcp_api_keys_inherit_empty_tools_ck
    CHECK (capability_mode <> 'inherit' OR enabled_tools = '[]'::jsonb);

COMMENT ON COLUMN mcp_api_keys.capability_mode IS
  'Per-key MCP tool grant mode (#4767, MTG-1.3): inherit = use live tenant default '
  'enable-set at resolve time; explicit = enabled_tools is authoritative. Orthogonal '
  'to scope_json (data scope) and to AGX api_keys.kind=agent. Changing tenant defaults '
  'does not rewrite explicit keys.';

COMMENT ON COLUMN mcp_api_keys.enabled_tools IS
  'jsonb array of MTG-1.1 tool ids enabled for this key when capability_mode=explicit '
  '(#4767, MTG-1.3). Must be [] when capability_mode=inherit. Write-time trigger enforces '
  'enable-set ⊆ tenant ceiling (tenant_mcp_policy_tools.in_ceiling).';

-- ---------------------------------------------------------------------------
-- Write-time: key enable-set ⊆ tenant ceiling
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION apiome.trg_mcp_api_keys_capability_ceiling()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_default_mode text;
  v_tool text;
  v_in_ceiling boolean;
BEGIN
  -- inherit stores no explicit list; resolve-time defaults apply (MTG-1.4).
  IF NEW.capability_mode = 'inherit' THEN
    RETURN NEW;
  END IF;

  SELECT default_mode INTO v_default_mode
  FROM apiome.tenant_mcp_policies
  WHERE tenant_id = NEW.tenant_id;

  -- Unseeded tenants (pre MTG-1.5): treat as full ceiling.
  IF v_default_mode IS NULL THEN
    v_default_mode := 'all';
  END IF;

  FOR v_tool IN
    SELECT jsonb_array_elements_text(NEW.enabled_tools)
  LOOP
    SELECT in_ceiling INTO v_in_ceiling
    FROM apiome.tenant_mcp_policy_tools
    WHERE tenant_id = NEW.tenant_id
      AND tool_id = v_tool;

    IF FOUND THEN
      IF NOT v_in_ceiling THEN
        RAISE EXCEPTION
          'MCP key enable-set exceeds tenant ceiling: tool "%" is not in ceiling',
          v_tool
          USING ERRCODE = 'check_violation';
      END IF;
    ELSIF v_default_mode = 'explicit' THEN
      RAISE EXCEPTION
        'MCP key enable-set exceeds tenant ceiling: tool "%" is not in ceiling',
        v_tool
        USING ERRCODE = 'check_violation';
    END IF;
    -- default_mode all | inherit_registry: absent rows mean allowed (full catalog).
  END LOOP;

  RETURN NEW;
END;
$$;

COMMENT ON FUNCTION apiome.trg_mcp_api_keys_capability_ceiling() IS
  'BEFORE INSERT/UPDATE on mcp_api_keys: when capability_mode=explicit, reject any '
  'enabled_tools id outside the tenant ceiling (#4767, MTG-1.3).';

DROP TRIGGER IF EXISTS trg_mcp_api_keys_capability_ceiling ON mcp_api_keys;
CREATE TRIGGER trg_mcp_api_keys_capability_ceiling
  BEFORE INSERT OR UPDATE OF capability_mode, enabled_tools, tenant_id
  ON mcp_api_keys
  FOR EACH ROW
  EXECUTE FUNCTION apiome.trg_mcp_api_keys_capability_ceiling();
