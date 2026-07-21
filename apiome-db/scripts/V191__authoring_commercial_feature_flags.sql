-- Seed the Authoring suite's commercial feature flags: scribe, slate, hosted.
--
-- UXE-1.1 (apiome-ui `lib/commercial-products.ts`, COMMERCIAL_PRODUCT_FLAG_NAMES) gates the
-- Authoring product group on three flags — `scribe`, `slate` and `hosted` — and the Authoring
-- shell (`private-suite/designer/lib/authoring/surfaces.ts`) locks each surface behind the same
-- names. V097 seeded only the Design-era flags (designer, paths, ai_assistant, repositories),
-- so these three were referenced by the app but never existed as rows. Entitlement resolution
-- (`tenant_has_feature_flag` precedence: user override → tenant override → license bundle)
-- starts from the flag row itself, so with no row nobody could reach Scribe or Slate through
-- any path — no license, override, or admin grant could help.
--
-- URL patterns use the suite-embedded `/ade/authoring/*` prefixes registered by the host
-- (`private-suite/host/src/authoring-nav.ts`), matching how V097's rows carry `/ade/*` paths.
--
-- Not preview: like `designer` and `paths`, these gate licensed commercial products in the
-- suite navigation, not experimental features. The surfaces themselves already state which
-- backends are still pending; a Preview badge here would say something different and wrong.
SET search_path TO apiome, public;

-- ─── Seed: Authoring feature flags ───────────────────────────────────────────

INSERT INTO apiome.feature_flags (name, label, description, url_patterns, is_preview, enabled)
VALUES
    ('scribe',
     'Scribe',
     'AI-assisted API documentation authoring — content workspace, coverage dashboard, '
     'guides and README generation.',
     '["/ade/authoring/scribe", "/ade/authoring/guides"]',
     false, true),

    ('slate',
     'Slate',
     'Documentation portal builder — visual builder, theme editor, navigation, content '
     'blocks, responsive preview and build history.',
     '["/ade/authoring/slate"]',
     false, true),

    ('hosted',
     'Managed Hosting',
     'Managed delivery for published portals — releases, cache, security, edge functions '
     'and delivery insights.',
     '["/ade/authoring/releases", "/ade/authoring/cache", "/ade/authoring/security", "/ade/authoring/edge", "/ade/authoring/insights"]',
     false, true)
ON CONFLICT (name) DO NOTHING;

-- ─── Seed: license ↔ feature flag associations ───────────────────────────────
-- Paid and Sponsor plans include the Authoring suite; Free does not — the same
-- split V116 applied to primitives-registry. Admins can still grant any of the
-- three per-user or per-tenant through the existing feature-flag panels.

INSERT INTO apiome.license_feature_flags (license_id, feature_flag_id)
SELECT l.id, ff.id
FROM   apiome.licenses l
CROSS  JOIN apiome.feature_flags ff
WHERE  l.name IN ('Paid', 'Sponsor')
  AND  ff.name IN ('scribe', 'slate', 'hosted')
ON CONFLICT DO NOTHING;
