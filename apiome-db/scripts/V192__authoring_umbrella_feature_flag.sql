-- Seed the Authoring suite umbrella feature flag: authoring (#83).
--
-- Hub tiles and the Authoring Overview destination gate on `authoring`, while product
-- surfaces continue to use `scribe` / `slate` / `hosted` (V191). Without this row the
-- umbrella flag cannot resolve through user override → tenant override → license bundle,
-- so entitled Paid/Sponsor tenants still never saw Authoring hub cards.
--
-- URL patterns cover both the suite-embedded `/ade/authoring` prefix and the standalone
-- studio `/authoring` surface registered by private-suite host.
--
-- Not preview: same commercial licensing posture as designer / paths / V191 flags.
SET search_path TO apiome, public;

-- ─── Seed: Authoring umbrella flag ───────────────────────────────────────────

INSERT INTO apiome.feature_flags (name, label, description, url_patterns, is_preview, enabled)
VALUES
    ('authoring',
     'Authoring',
     'Authoring suite umbrella — Overview hub, shared shell, and entry to Scribe/Slate. '
     'Product surfaces additionally require scribe, slate, or hosted.',
     '["/ade/authoring", "/authoring"]',
     false, true)
ON CONFLICT (name) DO NOTHING;

-- ─── Seed: license ↔ feature flag associations ───────────────────────────────
-- Paid and Sponsor plans include the Authoring suite; Free does not.

INSERT INTO apiome.license_feature_flags (license_id, feature_flag_id)
SELECT l.id, ff.id
FROM   apiome.licenses l
CROSS  JOIN apiome.feature_flags ff
WHERE  l.name IN ('Paid', 'Sponsor')
  AND  ff.name = 'authoring'
ON CONFLICT DO NOTHING;
