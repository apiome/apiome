-- Export presets deliver with several profiles — MFX-46.4 (#4382).
--
-- Export studio lets an export be delivered with up to five delivery profiles (MFX-38.4), but a preset
-- (MFX-39.3, V358) held one (`export_presets.delivery_profile_id`), so saving a studio session as a preset
-- and applying it again lost every profile but the first. `export_preset_delivery_profiles` holds a
-- preset's profiles in order; a deleted profile drops out of every preset (ON DELETE CASCADE), a deleted
-- preset takes its rows with it.
--
-- `export_presets.delivery_profile_id` stays: the application keeps it equal to the first profile, so a
-- reader that only knows the single profile (an older CLI) still sees one. The ordered list here is the
-- authority. Existing presets are backfilled with their one profile.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.export_preset_delivery_profiles;
-- Presets then deliver with their first profile only (the `delivery_profile_id` column is untouched).

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS export_preset_delivery_profiles (
    preset_id UUID NOT NULL REFERENCES export_presets(id) ON DELETE CASCADE,
    delivery_profile_id UUID NOT NULL REFERENCES export_delivery_profiles(id) ON DELETE CASCADE,
    -- 0-based order the profiles deliver in; a job takes at most five.
    position SMALLINT NOT NULL
        CONSTRAINT export_preset_delivery_profiles_position_check CHECK (position BETWEEN 0 AND 4),
    PRIMARY KEY (preset_id, delivery_profile_id),
    CONSTRAINT export_preset_delivery_profiles_position_unique UNIQUE (preset_id, position)
);

COMMENT ON TABLE export_preset_delivery_profiles IS
    'MFX-46.4 (#4382): the delivery profiles an export preset delivers with, in order (at most five).';

-- A profile's presets (a deleted profile cascades; the Delivery tab can name where a profile is used).
CREATE INDEX IF NOT EXISTS idx_export_preset_delivery_profiles_profile
    ON export_preset_delivery_profiles (delivery_profile_id);

-- Every existing preset keeps its one profile.
INSERT INTO export_preset_delivery_profiles (preset_id, delivery_profile_id, position)
SELECT id, delivery_profile_id, 0
FROM export_presets
WHERE delivery_profile_id IS NOT NULL
ON CONFLICT DO NOTHING;
