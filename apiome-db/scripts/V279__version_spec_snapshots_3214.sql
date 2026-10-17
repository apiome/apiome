-- Frozen OpenAPI snapshots of published versions (#3214, CLI 4.7 `apiome versions freeze`).
--
-- GET /v1/schema/{tenant}/{project}/{version} builds the OpenAPI document from the version's
-- live classes, properties and paths on every request, so editing a published version's classes
-- changes what consumers download. SDK generators need a schema that never moves. Freezing a
-- published version (POST /v1/versions/{t}/{p}/{id}/freeze-schema) stores the document's exact
-- bytes here; while a row exists, /v1/schema serves those bytes verbatim instead of regenerating.
--
--   content            the exact response body served (UTF-8 JSON, Starlette JSONResponse form).
--   sha256 / size_bytes  of content — what the CLI shows and consumers can verify against.
--   class_count / property_count / path_count   what the snapshot holds (for the CLI summary).
--   download_count     successful GET /v1/schema fetches of the snapshot. Unfreezing (DELETE
--                      …/freeze-schema) is refused once it is above zero, unless a tenant
--                      administrator forces it — someone may already depend on the bytes.
--
-- Unfreezing deletes the row; the version goes back to live generation. Deleting the version
-- deletes its snapshot.

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS apiome.version_spec_snapshots (
    version_id UUID PRIMARY KEY REFERENCES apiome.versions(id) ON DELETE CASCADE,
    content BYTEA NOT NULL,
    sha256 CHAR(64) NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    class_count INTEGER NOT NULL DEFAULT 0,
    property_count INTEGER NOT NULL DEFAULT 0,
    path_count INTEGER NOT NULL DEFAULT 0,
    frozen_by UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    frozen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    download_count BIGINT NOT NULL DEFAULT 0 CHECK (download_count >= 0),
    last_downloaded_at TIMESTAMPTZ
);

COMMENT ON TABLE apiome.version_spec_snapshots IS
  'Frozen OpenAPI document of a published version (#3214). While present, GET /v1/schema serves content verbatim.';
COMMENT ON COLUMN apiome.version_spec_snapshots.content IS
  'Exact response bytes served by GET /v1/schema for this version while frozen.';
COMMENT ON COLUMN apiome.version_spec_snapshots.download_count IS
  'Successful GET /v1/schema fetches of the snapshot; > 0 blocks unfreeze unless a tenant admin forces it.';

DO $$
BEGIN
    RAISE NOTICE 'apiome.version_spec_snapshots created (#3214, CLI 4.7).';
END $$;
