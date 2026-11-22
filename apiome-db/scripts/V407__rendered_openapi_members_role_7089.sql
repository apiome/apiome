-- A version_documents role for the members' OpenAPI document (COA-5.13, #7089).
--
-- apiome-rest keeps each revision's rendered documents in the document store and links them to
-- the revision with a version_documents row (V403). Until now there was one rendered OpenAPI
-- document, role 'rendered_openapi': the public one GET /v1/schema serves (OpenAPI 3.1, without
-- the operations marked x-private).
--
-- The UI now reads the document it shows a workspace member from REST as well
-- (GET /v1/versions/{tenant}/{project}/{version}/document): OpenAPI 3.2, with the private
-- operations kept. It is a second document of the same revision, so it gets its own role,
-- 'rendered_openapi_members'. With a shared role the lifecycle job would take each of the two for
-- a stale copy of the other and delete it (app.document_lifecycle drops a rendered link once a
-- newer link of the same role exists).
--
-- Both CHECK constraints that name the rendered roles are replaced:
--
--   * version_documents_role_check            — the closed list of roles;
--   * version_documents_rendered_provenance   — a rendered row records its content stamp,
--     generator and generator version.
--
-- Online: each new constraint is added NOT VALID (no table scan under the ACCESS EXCLUSIVE lock)
-- and validated in a separate statement, which takes a SHARE UPDATE EXCLUSIVE lock and does not
-- block reads or writes. Every existing row satisfies both: the role list only grows, and no row
-- has the new role yet.
--
-- Rollback notes (delete the rows of the new role first, or the old constraint cannot be added):
--   DELETE FROM apiome.version_documents WHERE role = 'rendered_openapi_members';
--   ALTER TABLE apiome.version_documents DROP CONSTRAINT version_documents_role_check;
--   ALTER TABLE apiome.version_documents ADD CONSTRAINT version_documents_role_check
--       CHECK (role IN ('original', 'original_part', 'rendered_openapi', 'rendered_canonical', 'frozen_schema'));
--   ALTER TABLE apiome.version_documents DROP CONSTRAINT version_documents_rendered_provenance;
--   ALTER TABLE apiome.version_documents ADD CONSTRAINT version_documents_rendered_provenance
--       CHECK (role NOT IN ('rendered_openapi', 'rendered_canonical')
--              OR (content_stamp IS NOT NULL AND generator IS NOT NULL AND generator_version IS NOT NULL));

SET search_path TO apiome, public;

ALTER TABLE apiome.version_documents
    DROP CONSTRAINT IF EXISTS version_documents_role_check;

ALTER TABLE apiome.version_documents
    ADD CONSTRAINT version_documents_role_check
        CHECK (role IN ('original', 'original_part', 'rendered_openapi', 'rendered_openapi_members',
                        'rendered_canonical', 'frozen_schema'))
        NOT VALID;

ALTER TABLE apiome.version_documents
    VALIDATE CONSTRAINT version_documents_role_check;

ALTER TABLE apiome.version_documents
    DROP CONSTRAINT IF EXISTS version_documents_rendered_provenance;

ALTER TABLE apiome.version_documents
    ADD CONSTRAINT version_documents_rendered_provenance
        CHECK (role NOT IN ('rendered_openapi', 'rendered_openapi_members', 'rendered_canonical')
               OR (content_stamp IS NOT NULL AND generator IS NOT NULL
                   AND generator_version IS NOT NULL))
        NOT VALID;

ALTER TABLE apiome.version_documents
    VALIDATE CONSTRAINT version_documents_rendered_provenance;

COMMENT ON COLUMN apiome.version_documents.role IS
    'original (the captured file, or a fileset''s manifest) | original_part (one file of a fileset) | '
    'rendered_openapi (public, GET /v1/schema) | rendered_openapi_members (what a member reads, '
    'COA-5.13) | rendered_canonical | frozen_schema.';
