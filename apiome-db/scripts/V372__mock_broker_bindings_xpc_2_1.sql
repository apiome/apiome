-- Mock broker bindings — XPC-2.1 (#5735).
--
-- An AsyncAPI mock over Kafka needs a broker to publish to (XPC-2.2) and a conformance run needs
-- one to consume from (XPC-2.3). Locally that is the opt-in `docker compose --profile broker`
-- Redpanda; for a tenant's own cluster it is this table: one row per (version, protocol) that says
-- where the broker is, how to reach it, and the SASL credential to present, sealed.
--
-- (The roadmap names this migration V275; that number was taken by
-- V275__encrypt_linked_account_tokens_4960.sql long before this ticket shipped, so it is V372.)
--
-- Four rules shape the schema:
--
--   1. **The credential is ciphertext, and only ciphertext.** `credential_ciphertext` is an
--      envelope-encrypted blob (AES-256-GCM data key wrapped by a versioned master key from
--      `APIOME_BROKER_CREDENTIAL_ENCRYPTION_KEYS`; app.envelope_crypto, the same scheme as the
--      V268 upstream vault, sealed under its own magic `OMBB`). `key_version` records which master
--      key sealed it. Both the SASL username and the password are sealed. There is no column a
--      plaintext secret, or a digest of one, could be written to.
--
--   2. **A credential exists exactly when a SASL mechanism does.** No mechanism ⇒ no ciphertext
--      and no key version (an unauthenticated dev broker); a mechanism ⇒ both. Enforced below.
--
--   3. **The address is a normalized host list, never a URL.** `bootstrap` is one to sixteen
--      `host:port` entries, lower-cased, no scheme, userinfo, path or whitespace. The application
--      resolves every host and refuses a private or otherwise non-public address
--      (app.ssrf_guard's address rule) before a row is written; the CHECK is the backstop for
--      the shape only, since the database cannot resolve names.
--
--   4. **One binding per version and protocol.** `kafka` today; `mqtt` and `amqp` are reserved
--      for XPC-2.5 and refused by the application until then. Rotation replaces the credential
--      in place on the same row.
--
-- Mutations (create / rotate / delete / test) are recorded in `apiome.access_audit` by the
-- application as `mock.broker_binding.*`, metadata only.
--
-- **No new RBAC resource.** A broker binding is part of a version's mock configuration, so the API
-- is guarded by the existing `versions` resource, like every other `…/mock/*` setting.
--
-- Idempotent: safe to re-run.
--
-- Rollback notes:
--   DROP TABLE IF EXISTS apiome.mock_broker_bindings;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS mock_broker_bindings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,

    -- Rule 4: kafka now; mqtt / amqp reserved for XPC-2.5.
    protocol VARCHAR(16) NOT NULL
        CONSTRAINT mock_broker_bindings_protocol_check
            CHECK (protocol IN ('kafka', 'mqtt', 'amqp')),

    -- Rule 3: normalized `host:port` entries (an IPv6 literal is bracketed).
    bootstrap TEXT[] NOT NULL
        CONSTRAINT mock_broker_bindings_bootstrap_count_check
            CHECK (cardinality(bootstrap) BETWEEN 1 AND 16),
    CONSTRAINT mock_broker_bindings_bootstrap_shape_check
        CHECK (
            array_to_string(bootstrap, ',')
                ~ '^[^,/@[:space:]A-Z]+:[0-9]{1,5}(,[^,/@[:space:]A-Z]+:[0-9]{1,5})*$'
        ),

    -- TLS flags: connect over TLS, and whether the broker's certificate is verified.
    tls_enabled BOOLEAN NOT NULL DEFAULT false,
    tls_verify BOOLEAN NOT NULL DEFAULT true,

    -- Rule 2: the SASL mechanism, and the sealed username/password that goes with it.
    sasl_mechanism VARCHAR(16)
        CONSTRAINT mock_broker_bindings_sasl_mechanism_check
            CHECK (sasl_mechanism IN ('PLAIN', 'SCRAM-SHA-256', 'SCRAM-SHA-512')),
    credential_ciphertext BYTEA,
    key_version INTEGER
        CONSTRAINT mock_broker_bindings_key_version_check CHECK (key_version >= 1),
    CONSTRAINT mock_broker_bindings_credential_check CHECK (
        (sasl_mechanism IS NULL AND credential_ciphertext IS NULL AND key_version IS NULL)
        OR (
            sasl_mechanism IS NOT NULL
            AND credential_ciphertext IS NOT NULL
            AND key_version IS NOT NULL
        )
    ),

    -- The Kafka client.id prefix the mock and the probe present, so the broker's logs and quotas
    -- can tell Apiome's connections apart.
    client_id_prefix VARCHAR(64) NOT NULL DEFAULT 'apiome-mock'
        CONSTRAINT mock_broker_bindings_client_id_prefix_check
            CHECK (client_id_prefix ~ '^[A-Za-z0-9._-]{1,64}$'),

    -- Provenance. ON DELETE SET NULL: a departing user must not take the binding with them.
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    rotated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- NULL until the credential is first rotated.
    rotated_at TIMESTAMPTZ
);

-- Rule 4, enforced: one binding per (version, protocol).
CREATE UNIQUE INDEX IF NOT EXISTS idx_mock_broker_bindings_version_protocol
    ON mock_broker_bindings (version_id, protocol);

-- Every read is scoped by tenant and version.
CREATE INDEX IF NOT EXISTS idx_mock_broker_bindings_tenant_version
    ON mock_broker_bindings (tenant_id, version_id);

COMMENT ON TABLE mock_broker_bindings IS
    'XPC-2.1 (#5735): where a version''s hosted mock publishes events (and a conformance run '
    'consumes them): broker protocol, bootstrap hosts, TLS flags, SASL mechanism and the sealed '
    'credential. Write-only through the API: no route returns the credential.';

COMMENT ON COLUMN mock_broker_bindings.bootstrap IS
    'Normalized host:port entries (lower-case, IPv6 bracketed). Every host is resolved and '
    'SSRF-checked by the application before a row is written and again before each connect.';

COMMENT ON COLUMN mock_broker_bindings.credential_ciphertext IS
    'Envelope-encrypted SASL credential (app.envelope_crypto, vault magic OMBB): '
    '{"username","password"}. NULL exactly when sasl_mechanism is NULL. Never plaintext.';

COMMENT ON COLUMN mock_broker_bindings.key_version IS
    'Which APIOME_BROKER_CREDENTIAL_ENCRYPTION_KEYS master key sealed the credential. Bound into '
    'the GCM AAD, so a row cannot be re-tagged to another version.';

COMMENT ON COLUMN mock_broker_bindings.rotated_at IS
    'When the credential was last replaced in place (NULL until the first rotation).';
