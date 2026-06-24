-- Onboarding (#3614): a shared, idempotent routine that provisions a curated, PUBLISHED sample
-- project ("Pet Store") for a tenant so a fresh tenant is never empty.
--
-- One function is reused by every tenant-creation path: the dev seed, OAuth self-signup, the admin
-- tenant-create panel, and the objectified-db CLI. It is idempotent (a no-op if the sample already
-- exists for the tenant) and self-contained — it inserts the full project graph and marks the
-- version published + public so the spec renders end-to-end in Browse (which regenerates the spec
-- live from classes/properties; see objectified-rest GET /v1/schema/...). It also writes the frozen
-- odb.class_schema rows so the sample behaves exactly like a UI-published version.

SET search_path TO odb, public;

CREATE OR REPLACE FUNCTION odb.provision_sample_project(p_tenant_id uuid, p_creator_id uuid)
RETURNS uuid
LANGUAGE plpgsql
AS $$
DECLARE
  v_project_id  uuid;
  v_version_id  uuid;
  v_cat_id      uuid;
  v_tag_id      uuid;
  v_pet_id      uuid;
  v_prop_id     uuid;
  v_prop_name   uuid;
  v_prop_status uuid;
BEGIN
  -- Idempotent: skip when the curated sample already exists for this tenant.
  IF EXISTS (
    SELECT 1 FROM odb.projects
    WHERE tenant_id = p_tenant_id AND slug = 'petstore-sample'
  ) THEN
    RETURN NULL;
  END IF;

  -- Project
  INSERT INTO odb.projects (tenant_id, creator_id, name, description, slug, enabled)
  VALUES (
    p_tenant_id, p_creator_id, 'Pet Store (sample)',
    'A curated sample API to explore Objectified: classes, a published version, and a browsable spec.',
    'petstore-sample', true
  )
  RETURNING id INTO v_project_id;

  -- Published, PUBLIC version (visibility = public is required for Browse to surface it).
  INSERT INTO odb.versions (
    project_id, creator_id, version_id, description, change_log,
    enabled, published, published_at, visibility
  )
  VALUES (
    v_project_id, p_creator_id, '1.0.0',
    'Initial sample version.', 'Seeded sample project for onboarding.',
    true, true, CURRENT_TIMESTAMP, 'public'
  )
  RETURNING id INTO v_version_id;

  -- Classes (base schema is a plain object; fields come from class_properties below).
  INSERT INTO odb.classes (version_id, name, description, schema, enabled)
  VALUES (v_version_id, 'Category', 'A grouping for pets (e.g. Dogs, Cats).', '{"type":"object"}'::jsonb, true)
  RETURNING id INTO v_cat_id;

  INSERT INTO odb.classes (version_id, name, description, schema, enabled)
  VALUES (v_version_id, 'Tag', 'A label that can be applied to a pet.', '{"type":"object"}'::jsonb, true)
  RETURNING id INTO v_tag_id;

  INSERT INTO odb.classes (version_id, name, description, schema, enabled)
  VALUES (v_version_id, 'Pet', 'A pet available in the store.', '{"type":"object"}'::jsonb, true)
  RETURNING id INTO v_pet_id;

  -- Project-level reusable property definitions (unique per project name).
  INSERT INTO odb.properties (project_id, name, description, data, enabled)
  VALUES (v_project_id, 'id', 'Unique identifier.', '{"type":"integer","format":"int64","description":"Unique identifier."}'::jsonb, true)
  RETURNING id INTO v_prop_id;

  INSERT INTO odb.properties (project_id, name, description, data, enabled)
  VALUES (v_project_id, 'name', 'Display name.', '{"type":"string","description":"Display name."}'::jsonb, true)
  RETURNING id INTO v_prop_name;

  INSERT INTO odb.properties (project_id, name, description, data, enabled)
  VALUES (v_project_id, 'status', 'Pet availability status.', '{"type":"string","enum":["available","pending","sold"],"description":"Pet availability status."}'::jsonb, true)
  RETURNING id INTO v_prop_status;

  -- class_properties: the per-class fields the spec generator reads from cp.data
  -- ("required": true promotes a field into the class-level required array).
  INSERT INTO odb.class_properties (class_id, property_id, name, description, data) VALUES
    (v_cat_id, v_prop_id,   'id',   'Unique identifier.', '{"type":"integer","format":"int64","description":"Unique identifier.","required":true}'::jsonb),
    (v_cat_id, v_prop_name, 'name', 'Display name.',      '{"type":"string","description":"Display name.","required":true}'::jsonb);

  INSERT INTO odb.class_properties (class_id, property_id, name, description, data) VALUES
    (v_tag_id, v_prop_id,   'id',   'Unique identifier.', '{"type":"integer","format":"int64","description":"Unique identifier.","required":true}'::jsonb),
    (v_tag_id, v_prop_name, 'name', 'Display name.',      '{"type":"string","description":"Display name.","required":true}'::jsonb);

  INSERT INTO odb.class_properties (class_id, property_id, name, description, data) VALUES
    (v_pet_id, v_prop_id,     'id',     'Unique identifier.',      '{"type":"integer","format":"int64","description":"Unique identifier.","required":true}'::jsonb),
    (v_pet_id, v_prop_name,   'name',   'Display name.',           '{"type":"string","description":"Display name.","required":true}'::jsonb),
    (v_pet_id, v_prop_status, 'status', 'Pet availability status.', '{"type":"string","enum":["available","pending","sold"],"description":"Pet availability status."}'::jsonb);

  -- Frozen published schemas (mirror publish_version so data-records work; valid JSON Schema 2020-12).
  INSERT INTO odb.class_schema (version_id, class_id, schema) VALUES
    (v_version_id, v_cat_id, '{"$schema":"https://json-schema.org/draft/2020-12/schema","type":"object","title":"Category","properties":{"id":{"type":"integer","format":"int64","description":"Unique identifier."},"name":{"type":"string","description":"Display name."}},"required":["id","name"]}'::jsonb),
    (v_version_id, v_tag_id, '{"$schema":"https://json-schema.org/draft/2020-12/schema","type":"object","title":"Tag","properties":{"id":{"type":"integer","format":"int64","description":"Unique identifier."},"name":{"type":"string","description":"Display name."}},"required":["id","name"]}'::jsonb),
    (v_version_id, v_pet_id, '{"$schema":"https://json-schema.org/draft/2020-12/schema","type":"object","title":"Pet","properties":{"id":{"type":"integer","format":"int64","description":"Unique identifier."},"name":{"type":"string","description":"Display name."},"status":{"type":"string","enum":["available","pending","sold"],"description":"Pet availability status."}},"required":["id","name"]}'::jsonb);

  RETURN v_project_id;
END;
$$;

COMMENT ON FUNCTION odb.provision_sample_project(uuid, uuid) IS
  'Idempotently provision the curated "Pet Store" sample project (published + public) for a tenant, owned by the given creator. Returns the new project id, or NULL if the sample already exists for the tenant. Shared by the dev seed, OAuth signup, admin tenant-create, and the objectified-db CLI.';
