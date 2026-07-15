-- CI, webhook, SARIF, and attestable lint outputs (#4860, CLX-4.2).
--
-- Problem: the ``lint.waiver.expiring`` webhook (new in CLX-4.2) must fire exactly once per
-- granted waiver as its expiry approaches. ``lint_finding_decisions`` (V169) records
-- ``expires_at`` but has no marker of whether the expiry notification was already sent, so a
-- periodic sweep would re-enqueue the same event on every tick and on every replica.
--
-- Solution: an ``expiry_notified_at`` timestamp the sweep claims atomically
-- (UPDATE ... WHERE expiry_notified_at IS NULL ... FOR UPDATE SKIP LOCKED). The application
-- resets it to NULL whenever a decision is (re-)granted as ``waived`` with a new expiry, so a
-- renewed waiver notifies again for its new expiry. A partial index keeps the sweep's scan
-- cheap: only unnotified active waivers are indexed.
--
-- Rollback notes:
--   DROP INDEX IF EXISTS apiome.idx_lint_finding_decisions_expiry_due;
--   ALTER TABLE apiome.lint_finding_decisions DROP COLUMN IF EXISTS expiry_notified_at;

SET search_path TO apiome, public;

ALTER TABLE apiome.lint_finding_decisions
    ADD COLUMN IF NOT EXISTS expiry_notified_at TIMESTAMP WITH TIME ZONE;

COMMENT ON COLUMN apiome.lint_finding_decisions.expiry_notified_at IS
    'When the lint.waiver.expiring webhook was enqueued for this waiver; NULL = not yet '
    'notified. Reset to NULL by the application when a waiver is granted or renewed with a '
    'new expiry (#4860).';

CREATE INDEX IF NOT EXISTS idx_lint_finding_decisions_expiry_due
    ON apiome.lint_finding_decisions (expires_at)
    WHERE state = 'waived' AND expiry_notified_at IS NULL;
