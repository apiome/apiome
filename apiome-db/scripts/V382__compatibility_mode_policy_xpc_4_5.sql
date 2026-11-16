-- =====================================================================================
-- V382 — Compatibility mode policy on style guides (XPC-4.5, #5749)
-- =====================================================================================
--
-- XPC-4.1–4.4 (#5745–#5748) taught the Avro, JSON Schema, Protobuf and AsyncAPI classifiers to
-- grade a change by **compatibility mode** (Confluent's BACKWARD / FORWARD / FULL / NONE) and,
-- for Protobuf, by **buf breaking category** (WIRE / WIRE_JSON / PACKAGE / FILE). Nothing let a
-- tenant say which one a project is held to. XPC-4.5 adds that policy, so
-- `POST /v1/diff/{tenant}/classified`, `POST /v1/versions/{tenant}/{project}/compatibility`, the
-- CI diff gate and the publish guardrail all default to it.
--
-- The roadmap numbered this migration V276; that number was taken by an earlier migration by the
-- time XPC-4.5 shipped, so it lands as V382 with the same content.
--
-- Three columns, one policy:
--   compatibility_mode          — BACKWARD (DEFAULT, Confluent's default) | FORWARD | FULL | NONE.
--   compatibility_transitive    — when true, a change is checked against every earlier revision,
--                                 not only the base (BACKWARD_TRANSITIVE and friends). DEFAULT false.
--   protobuf_breaking_category  — the buf breaking category Protobuf diffs are graded at:
--                                 WIRE | WIRE_JSON (DEFAULT) | PACKAGE | FILE.
--
-- They sit on `style_guides` beside the CTG-3.4 (#4478) `breaking_publish_policy` column for the
-- same reason it does: publish-time governance resolves through the GOV-1.4 guide chain (project
-- assignment → tenant assignment → tenant default), which gives per-project policy for free. The
-- application freezes the three values into `style_guide_revisions.policy` on every guide edit
-- (GOV-1.6, V236), so a past verdict can be explained by the policy it ran under.
--
-- Additive and backwards compatible: existing guides adopt the defaults, which are exactly the
-- grades the classifiers already produce, so nothing changes until a tenant edits the policy.
--
-- Rollback notes (additive only):
--   ALTER TABLE apiome.style_guides DROP COLUMN IF EXISTS compatibility_mode;
--   ALTER TABLE apiome.style_guides DROP COLUMN IF EXISTS compatibility_transitive;
--   ALTER TABLE apiome.style_guides DROP COLUMN IF EXISTS protobuf_breaking_category;
-- =====================================================================================

SET search_path TO apiome, public;

ALTER TABLE apiome.style_guides
    ADD COLUMN IF NOT EXISTS compatibility_mode TEXT NOT NULL DEFAULT 'BACKWARD';

ALTER TABLE apiome.style_guides
    ADD COLUMN IF NOT EXISTS compatibility_transitive BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE apiome.style_guides
    ADD COLUMN IF NOT EXISTS protobuf_breaking_category TEXT NOT NULL DEFAULT 'WIRE_JSON';

-- Closed vocabularies, added separately so a re-run against an already-migrated database is a
-- no-op rather than a duplicate-constraint error. They mirror apiome-rest's
-- `app.compatibility_policy` vocabulary.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'style_guides_compatibility_mode_ck'
          AND conrelid = 'apiome.style_guides'::regclass
    ) THEN
        ALTER TABLE apiome.style_guides
            ADD CONSTRAINT style_guides_compatibility_mode_ck
            CHECK (compatibility_mode IN ('BACKWARD', 'FORWARD', 'FULL', 'NONE'));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'style_guides_protobuf_breaking_category_ck'
          AND conrelid = 'apiome.style_guides'::regclass
    ) THEN
        ALTER TABLE apiome.style_guides
            ADD CONSTRAINT style_guides_protobuf_breaking_category_ck
            CHECK (protobuf_breaking_category IN ('WIRE', 'WIRE_JSON', 'PACKAGE', 'FILE'));
    END IF;
END
$$;

COMMENT ON COLUMN style_guides.compatibility_mode IS
    'Compatibility mode diffs, compatibility checks and the publish guardrail grade by: BACKWARD | FORWARD | FULL | NONE (XPC-4.5, #5749)';

COMMENT ON COLUMN style_guides.compatibility_transitive IS
    'When true, a change is checked against every earlier revision, not only the base (the *_TRANSITIVE modes; XPC-4.5, #5749)';

COMMENT ON COLUMN style_guides.protobuf_breaking_category IS
    'buf breaking category Protobuf diffs are graded at: WIRE | WIRE_JSON | PACKAGE | FILE (XPC-4.5, #5749)';
