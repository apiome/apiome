-- Cap'n Proto ordinals and file ids in the export field-identity store (#4179, MFX-30.2).
--
-- Problem: V141 sized the store for protobuf field numbers — INTEGER, 1..536870911. Cap'n Proto
-- numbers its struct fields, enumerants and methods from @0, and its file id is a 64-bit value
-- (top bit always set). Neither fits the column or its check.
--
-- Solution: widen field_number to BIGINT and relax the check for the 'capnproto' target only:
-- its rows may be 0 or larger than a protobuf number. The emitter stores the file id with its
-- top bit cleared (the bit is always set, so it is restored on load), which keeps the value
-- inside BIGINT. Every other target keeps the original 1..536870911 range.
--
-- Rollback notes: delete the capnproto rows first, then restore the V141 shape:
--   DELETE FROM apiome.export_field_identities WHERE target = 'capnproto';
--   ALTER TABLE apiome.export_field_identities
--     DROP CONSTRAINT IF EXISTS export_field_identities_number_check;
--   ALTER TABLE apiome.export_field_identities ALTER COLUMN field_number TYPE INTEGER;
--   ALTER TABLE apiome.export_field_identities ADD CONSTRAINT export_field_identities_number_check
--     CHECK (field_number >= 1 AND field_number <= 536870911);

SET search_path TO apiome, public;

ALTER TABLE apiome.export_field_identities
    ALTER COLUMN field_number TYPE BIGINT;

ALTER TABLE apiome.export_field_identities
    DROP CONSTRAINT IF EXISTS export_field_identities_number_check;

ALTER TABLE apiome.export_field_identities
    ADD CONSTRAINT export_field_identities_number_check
        CHECK (
            (target = 'capnproto' AND field_number >= 0)
            OR (field_number >= 1 AND field_number <= 536870911)
        );

COMMENT ON COLUMN apiome.export_field_identities.field_number IS
  'The stable number assigned on first export. 1..536870911 for protobuf-style targets; for '
  'capnproto (#4179) an @N ordinal from 0, a field layout code, or the file id with its top bit '
  'cleared.';
