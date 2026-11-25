-- Bi-directional verdicts in the matrix — PFX-2.3 (#6927).
--
-- A consumer's pact can be checked two ways: a Pact verifier replays it against the running
-- provider (a *native* result, V434), or Apiome compares it with the OpenAPI document the provider
-- published (a *provider contract*, V438) with the PFX-2.2 comparison engine. This migration lets
-- `verification_result` hold the second kind next to the first, so the matrix and can-i-deploy
-- read both the same way:
--
--   kind                 — `native` (published by a Pact verifier) or `bidirectional` (written by
--                          Apiome from a comparison). Every existing row is `native`.
--   provider_contract_id — for `bidirectional`: the provider contract the pact was compared with.
--   comparison           — for `bidirectional`: the comparison payload (verdict, summary, and per
--                          interaction the checks, failures, warnings and fidelity notes).
--
-- Rules kept by the database:
--
--   1. **A kind's columns go together.** A native result has no contract and no comparison; a
--      bi-directional one has both, and its comparison is a JSON object.
--   2. **One comparison per pair.** A pact version is compared with a provider version once
--      (a unique index over the bi-directional rows). A provider version's contract never changes
--      (V438), so comparing them again would give the same answer. A new provider contract is a
--      new provider version, so it is compared afresh.
--   3. **Nothing crosses a provider.** The contract is referenced by `(id, provider_id)`, so a
--      result can only cite a contract of the provider it verifies.
--   4. **A result goes with its contract.** Deleting the contract deletes its results (it only
--      goes with its provider, which takes the results with it anyway).
--
-- Rows stay immutable: the V434 trigger compares whole rows, so the new columns are covered.
--
-- Online: three columns added to `verification_result` (the default is a constant, so no
-- rewrite), one CHECK validated by one scan (one row per verification), one foreign key, two indexes.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP INDEX IF EXISTS apiome.verification_result_bidirectional_pair_key;
--   DROP INDEX IF EXISTS apiome.idx_verification_result_provider_contract;
--   ALTER TABLE apiome.verification_result
--       DROP CONSTRAINT IF EXISTS verification_result_kind_shape_check,
--       DROP CONSTRAINT IF EXISTS verification_result_provider_contract_fk,
--       DROP COLUMN IF EXISTS comparison,
--       DROP COLUMN IF EXISTS provider_contract_id,
--       DROP COLUMN IF EXISTS kind;

SET search_path TO apiome, public;

ALTER TABLE verification_result
    ADD COLUMN IF NOT EXISTS kind VARCHAR(16) NOT NULL DEFAULT 'native',
    ADD COLUMN IF NOT EXISTS provider_contract_id UUID,
    ADD COLUMN IF NOT EXISTS comparison JSONB;

-- Rules 1, 3 and 4.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'verification_result_kind_shape_check'
          AND conrelid = 'apiome.verification_result'::regclass
    ) THEN
        ALTER TABLE apiome.verification_result
            ADD CONSTRAINT verification_result_kind_shape_check CHECK (
                (kind = 'native' AND provider_contract_id IS NULL AND comparison IS NULL)
                OR (kind = 'bidirectional' AND provider_contract_id IS NOT NULL
                    AND comparison IS NOT NULL AND jsonb_typeof(comparison) = 'object')
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'verification_result_provider_contract_fk'
          AND conrelid = 'apiome.verification_result'::regclass
    ) THEN
        ALTER TABLE apiome.verification_result
            ADD CONSTRAINT verification_result_provider_contract_fk
                FOREIGN KEY (provider_contract_id, provider_id)
                REFERENCES apiome.provider_contract (id, provider_id) ON DELETE CASCADE;
    END IF;
END;
$$;

-- Rule 2: the key a comparison is written under (`ON CONFLICT … DO NOTHING`).
CREATE UNIQUE INDEX IF NOT EXISTS verification_result_bidirectional_pair_key
    ON verification_result (pact_version_id, provider_version_id)
    WHERE kind = 'bidirectional';

-- The referential check of the contract, and "which results did this contract produce".
CREATE INDEX IF NOT EXISTS idx_verification_result_provider_contract
    ON verification_result (provider_contract_id, provider_id)
    WHERE provider_contract_id IS NOT NULL;

COMMENT ON COLUMN verification_result.kind IS
    'native (published by a Pact verifier) or bidirectional (an Apiome pact-to-OpenAPI comparison, PFX-2.3)';
COMMENT ON COLUMN verification_result.provider_contract_id IS
    'For bidirectional: the provider contract the pact was compared with';
COMMENT ON COLUMN verification_result.comparison IS
    'For bidirectional: the comparison payload (verdict, summary, per-interaction findings and fidelity)';
