-- Contract protocol on verification targets and runs — XPC-1.2 (#5730).
--
-- Problem: a contract suite used to be HTTP only, so a verification target was implicitly an HTTP
-- base URL and every run was implicitly an HTTP run. The GraphQL protocol adapter compiles a
-- GraphQL version into cases that are POSTed to one endpoint and judged by their response envelope.
-- Pointing such a suite at an HTTP target (or the reverse) cannot produce meaningful evidence, and
-- guessing which a target is from its URL would be exactly the kind of inference evidence must
-- not rest on.
--
-- Solution: two additive columns, constrained to the contract-suite adapter list
-- (app.contract_protocols.CONTRACT_PROTOCOLS).
--
--   * ``verification_target.protocol`` — what the target speaks: ``http`` (relative paths are
--                                        joined onto ``base_url``) or ``graphql`` (``base_url`` is
--                                        the GraphQL endpoint). A run whose suite speaks another
--                                        protocol is refused with ``target-protocol-mismatch``.
--   * ``verification_run.protocol``    — what the run was executed over, recorded with the rest of
--                                        the immutable evidence and carried into its exports.
--
-- Every existing target and run is HTTP, which is what the ``http`` default records. Adding a column
-- with a constant default does not rewrite or update existing rows, so V212's immutability triggers
-- on ``verification_run`` are not involved.
--
-- Idempotent: safe to re-run.
--
-- Rollback notes:
--   ALTER TABLE apiome.verification_run DROP COLUMN IF EXISTS protocol;
--   ALTER TABLE apiome.verification_target DROP COLUMN IF EXISTS protocol;

SET search_path TO apiome, public;

ALTER TABLE apiome.verification_target
    ADD COLUMN IF NOT EXISTS protocol TEXT NOT NULL DEFAULT 'http';

ALTER TABLE apiome.verification_run
    ADD COLUMN IF NOT EXISTS protocol TEXT NOT NULL DEFAULT 'http';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'verification_target_protocol_check'
          AND conrelid = 'apiome.verification_target'::regclass
    ) THEN
        ALTER TABLE apiome.verification_target
            ADD CONSTRAINT verification_target_protocol_check
                CHECK (protocol IN ('http', 'graphql'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'verification_run_protocol_check'
          AND conrelid = 'apiome.verification_run'::regclass
    ) THEN
        ALTER TABLE apiome.verification_run
            ADD CONSTRAINT verification_run_protocol_check
                CHECK (protocol IN ('http', 'graphql'));
    END IF;
END $$;

COMMENT ON COLUMN apiome.verification_target.protocol IS
    'http | graphql — what the target speaks; a run whose suite speaks another protocol is refused (XPC-1.2)';
COMMENT ON COLUMN apiome.verification_run.protocol IS
    'http | graphql — the protocol the suite was executed over (XPC-1.2)';
