-- Mock runtime cache invalidation: NOTIFY on published version changes (#4416, SIM-1.1).
SET search_path TO apiome, public;

CREATE OR REPLACE FUNCTION apiome.notify_mock_spec_published()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_tenant_slug text;
  v_project_slug text;
  v_version_label text;
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF NEW.published IS NOT TRUE AND OLD.published IS NOT TRUE THEN
      RETURN NEW;
    END IF;
    IF NEW.published IS NOT DISTINCT FROM OLD.published
       AND NEW.updated_at IS NOT DISTINCT FROM OLD.updated_at THEN
      RETURN NEW;
    END IF;
  ELSIF TG_OP = 'INSERT' THEN
    IF NEW.published IS NOT TRUE THEN
      RETURN NEW;
    END IF;
  ELSE
    RETURN NEW;
  END IF;

  SELECT t.slug, p.slug, NEW.version_id
    INTO v_tenant_slug, v_project_slug, v_version_label
  FROM apiome.projects p
  INNER JOIN apiome.tenants t ON t.id = p.tenant_id
  WHERE p.id = NEW.project_id
    AND p.deleted_at IS NULL
    AND t.deleted_at IS NULL;

  IF v_tenant_slug IS NULL OR v_project_slug IS NULL OR v_version_label IS NULL THEN
    RETURN NEW;
  END IF;

  PERFORM pg_notify(
    'apiome_mock_spec_published',
    v_tenant_slug || '/' || v_project_slug || '/' || v_version_label
  );
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trigger_versions_notify_mock_spec_published ON apiome.versions;
CREATE TRIGGER trigger_versions_notify_mock_spec_published
  AFTER INSERT OR UPDATE OF published, updated_at ON apiome.versions
  FOR EACH ROW
  EXECUTE FUNCTION apiome.notify_mock_spec_published();

COMMENT ON FUNCTION apiome.notify_mock_spec_published() IS
  'Emit apiome_mock_spec_published NOTIFY with tenant/project/version slugs when a revision is published or republished (#4416).';
