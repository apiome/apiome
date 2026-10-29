-- FlatBuffers field ids in the export field-identity store (#4178, MFX-30.1).
--
-- Problem: a FlatBuffers table numbers its fields from id 0 (a union takes two ids, its hidden
-- `_type` field at N-1 and its value at N). V337 allows 0 only for the 'capnproto' target, so the
-- first field of every exported table could not be stored.
--
-- Solution: let the 'flatbuffers' target store ids from 0 up to 65534 (a vtable holds 16-bit offsets,
-- so flatc caps a table's fields below that). Every other target keeps its V337 range.
--
-- Rollback notes: delete the flatbuffers rows first, then restore the V337 check:
--   DELETE FROM apiome.export_field_identities WHERE target = 'flatbuffers';
--   ALTER TABLE apiome.export_field_identities
--     DROP CONSTRAINT IF EXISTS export_field_identities_number_check;
--   ALTER TABLE apiome.export_field_identities ADD CONSTRAINT export_field_identities_number_check
--     CHECK ((target = 'capnproto' AND field_number >= 0)
--            OR (field_number >= 1 AND field_number <= 536870911));

SET search_path TO apiome, public;

ALTER TABLE apiome.export_field_identities
    DROP CONSTRAINT IF EXISTS export_field_identities_number_check;

ALTER TABLE apiome.export_field_identities
    ADD CONSTRAINT export_field_identities_number_check
        CHECK (
            (target = 'capnproto' AND field_number >= 0)
            OR (target = 'flatbuffers' AND field_number >= 0 AND field_number <= 65534)
            OR (field_number >= 1 AND field_number <= 536870911)
        );

COMMENT ON COLUMN apiome.export_field_identities.field_number IS
  'The stable number assigned on first export. 1..536870911 for protobuf-style targets; for '
  'capnproto (#4179) an @N ordinal from 0, a field layout code, or the file id with its top bit '
  'cleared; for flatbuffers (#4178) a table field id from 0 to 65534.';
