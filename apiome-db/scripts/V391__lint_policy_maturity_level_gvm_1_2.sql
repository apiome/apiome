-- Maturity level on policy evaluations — GVM-1.2 (#5855).
--
-- apiome-rest's level engine (app.maturity_ladder.evaluate_ladder) judges every policy
-- evaluation whose pack carries a maturity ladder (GVM-1.1, V390). The full result is stored in
-- gate_results.maturity; this column repeats the level key so governance scorecards (GVM-1.4)
-- can aggregate levels without unpacking JSON.
--
--   maturity_level   the key of the highest level satisfied (e.g. 'silver'); NULL when the pack
--                    has no ladder or the subject meets no level — gate_results.maturity.reason
--                    tells the two apart ('no-ladder' is never stored: such rows carry no
--                    maturity block at all).
--
-- Rows are write-once (V169 trigger), so existing evaluations keep NULL; the next read of a
-- subject records a new evaluation when its result changed.
--
-- Idempotent. Rollback (additive only):
--   DROP INDEX IF EXISTS apiome.idx_lint_policy_evaluations_maturity_level;
--   ALTER TABLE apiome.lint_policy_evaluations DROP COLUMN IF EXISTS maturity_level;

SET search_path TO apiome, public;

ALTER TABLE lint_policy_evaluations
    ADD COLUMN IF NOT EXISTS maturity_level TEXT;

COMMENT ON COLUMN lint_policy_evaluations.maturity_level IS
    'Key of the highest maturity level satisfied (GVM-1.2, #5855); NULL when no ladder or no level is met — see gate_results.maturity';

CREATE INDEX IF NOT EXISTS idx_lint_policy_evaluations_maturity_level
    ON lint_policy_evaluations (maturity_level, evaluated_at DESC)
    WHERE maturity_level IS NOT NULL;

DO $$
BEGIN
    RAISE NOTICE 'apiome.lint_policy_evaluations.maturity_level added (GVM-1.2, #5855).';
END $$;
