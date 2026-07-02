-- Primitives type-registry entitlement & feature gating (#3478)
--
-- Seeds the `primitives-registry` feature flag that gates the advanced Type Registry
-- surface (relative-$ref resolver, namespaces, registry settings, coverage stats, and the
-- import pipeline). Baseline primitives CRUD and /health are never gated.
--
-- Enforcement lives in apiome-rest: when APIOME_PRIMITIVES_REGISTRY_GATING is on,
-- the advanced routes require the calling tenant/user to hold this flag (per-user override >
-- per-tenant override > license default). When that operator switch is off (the default),
-- the flag is inert and every authenticated tenant reaches the advanced routes — so seeding
-- it here is safe and changes no behavior on its own.
--
-- Product default: bundle the entitlement into the Paid and Sponsor plans; the Free plan does
-- not include it. Admins can still grant/revoke it per-user or per-tenant via the existing
-- Feature-Flag panel, which lists this row automatically.
SET search_path TO apiome, public;

-- ─── Seed: primitives-registry feature flag ──────────────────────────────────

INSERT INTO apiome.feature_flags (name, label, description, url_patterns, is_preview, enabled)
VALUES
    ('primitives-registry',
     'Primitives Type Registry',
     'Advanced JSON Schema type registry: $ref resolver, namespaces, registry settings, '
     'coverage stats, and the import pipeline. Baseline primitives CRUD is always available.',
     '["/ade/dashboard/primitives", "/api/types", "/api/primitives/import", "/api/primitives/unresolved", "/api/primitives/imports"]',
     true, true)
ON CONFLICT (name) DO NOTHING;

-- ─── Seed: license ↔ feature flag associations ───────────────────────────────
-- Paid and Sponsor plans include the type registry; Free does not.

INSERT INTO apiome.license_feature_flags (license_id, feature_flag_id)
SELECT l.id, ff.id
FROM   apiome.licenses l
CROSS  JOIN apiome.feature_flags ff
WHERE  l.name = 'Paid'
  AND  ff.name = 'primitives-registry'
ON CONFLICT DO NOTHING;

INSERT INTO apiome.license_feature_flags (license_id, feature_flag_id)
SELECT l.id, ff.id
FROM   apiome.licenses l
CROSS  JOIN apiome.feature_flags ff
WHERE  l.name = 'Sponsor'
  AND  ff.name = 'primitives-registry'
ON CONFLICT DO NOTHING;
