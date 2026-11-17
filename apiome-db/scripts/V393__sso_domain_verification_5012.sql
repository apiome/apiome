-- Enterprise SSO domains — ownership proved by DNS, per workspace (EID-1.2, #5012)
--
-- V312 made `sso_provider_domain.domain` unique across the installation the moment it was typed
-- in. That was fine while only the installation admin could add one. Now a workspace owner adds
-- their own domains, and an *unverified* row must not lock anyone else out: otherwise a workspace
-- could type `acme.com`, never prove it, and stop Acme registering its own domain.
--
-- So uniqueness moves to where it matters:
--
--   * (provider_id, domain) is unique — a provider lists a domain once;
--   * a **verified** domain is unique installation-wide — one domain routes to one IdP.
--
-- Several workspaces may hold the same domain unverified. The first to publish its DNS TXT
-- challenge wins; the others are refused `sso-domain-claimed` when they add or verify it. Only
-- verified domains ever route (V312), so a pending row captures nothing.
--
-- Idempotent.

SET search_path TO apiome, public;

ALTER TABLE apiome.sso_provider_domain
    DROP CONSTRAINT IF EXISTS sso_provider_domain_domain_key;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'sso_provider_domain_provider_domain_key'
          AND conrelid = 'apiome.sso_provider_domain'::regclass
    ) THEN
        ALTER TABLE apiome.sso_provider_domain
            ADD CONSTRAINT sso_provider_domain_provider_domain_key UNIQUE (provider_id, domain);
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS sso_provider_domain_verified_uq
    ON apiome.sso_provider_domain (domain)
    WHERE verified_at IS NOT NULL;

-- Looking a domain up by name (who has verified it?) no longer has the old unique index to use.
CREATE INDEX IF NOT EXISTS sso_provider_domain_domain_idx ON apiome.sso_provider_domain (domain);

COMMENT ON TABLE apiome.sso_provider_domain IS
    'EID-1.1 (#5011), EID-1.2 (#5012): email domains an SSO provider signs in. Only verified domains route; a verified domain is unique installation-wide, an unverified one is not.';
