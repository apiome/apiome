-- GLI-01 / #2720: Default branch semantics for version branches.
SET search_path TO odb, public;

ALTER TABLE version_branches
  ADD COLUMN IF NOT EXISTS is_default BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN version_branches.is_default IS
  'True when this row is the project default branch (main-like trunk).';

CREATE UNIQUE INDEX IF NOT EXISTS uq_version_branches_default_per_project
  ON version_branches(project_id)
  WHERE is_default = TRUE;

WITH latest_revision AS (
  SELECT DISTINCT ON (v.project_id)
         v.project_id,
         v.id AS revision_id
  FROM odb.versions v
  WHERE v.deleted_at IS NULL
  ORDER BY v.project_id, v.created_at DESC, v.id DESC
),
candidate_default AS (
  SELECT p.id AS project_id,
         COALESCE(
           (
             SELECT b.id
             FROM odb.version_branches b
             JOIN latest_revision lr ON lr.project_id = b.project_id
             WHERE b.project_id = p.id
               AND b.tip_version_id = lr.revision_id
             ORDER BY b.updated_at DESC NULLS LAST, b.created_at DESC, b.id
             LIMIT 1
           ),
           (
             SELECT b2.id
             FROM odb.version_branches b2
             WHERE b2.project_id = p.id
             ORDER BY b2.created_at ASC, b2.id
             LIMIT 1
           )
         ) AS branch_id
  FROM odb.projects p
  WHERE p.deleted_at IS NULL
)
UPDATE odb.version_branches b
SET is_default = TRUE,
    updated_at = CURRENT_TIMESTAMP
FROM candidate_default cd
WHERE b.id = cd.branch_id
  AND cd.branch_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1
    FROM odb.version_branches bx
    WHERE bx.project_id = b.project_id
      AND bx.is_default = TRUE
  );

WITH latest_revision AS (
  SELECT DISTINCT ON (v.project_id)
         v.project_id,
         v.id AS revision_id
  FROM odb.versions v
  WHERE v.deleted_at IS NULL
  ORDER BY v.project_id, v.created_at DESC, v.id DESC
)
INSERT INTO odb.version_branches
  (project_id, name, tip_version_id, created_by, branched_from_revision_id, is_default)
SELECT lr.project_id,
       'main',
       lr.revision_id,
       NULL,
       lr.revision_id,
       TRUE
FROM latest_revision lr
WHERE NOT EXISTS (
  SELECT 1
  FROM odb.version_branches b
  WHERE b.project_id = lr.project_id
);
