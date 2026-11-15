-- gRPC and Connect contract protocols — XPC-3.2 (#5742).
--
-- Problem: V371 constrained ``verification_target.protocol`` and ``verification_run.protocol`` to
-- the two contract-suite adapters that existed then, ``http`` and ``graphql``. The gRPC/Connect
-- adapter compiles a Protobuf version into one set of cases per unary method, executed either over
-- the Connect protocol (JSON POSTed to ``/{package.Service}/{Method}`` through the HTTP runner) or
-- over a native gRPC channel. A target has to say which, and a run has to record which.
--
-- Solution: widen both CHECK constraints to the adapter list in app.contract_protocols
-- (CONTRACT_PROTOCOLS): ``http``, ``graphql``, ``grpc``, ``connect``.
--
--   * ``verification_target.protocol`` — ``connect`` (cases are POSTed as JSON to
--                                        ``{base_url}/{package.Service}/{Method}``) or ``grpc``
--                                        (a native channel to base_url's host and port, TLS for
--                                        https, descriptors read through server reflection).
--   * ``verification_run.protocol``    — the target protocol the run was executed over.
--
-- Only the constraints change: no column is added, no row is touched (V212's immutability
-- triggers on ``verification_run`` are not involved), and every existing value stays valid.
--
-- Idempotent: safe to re-run (each constraint is dropped if present, then re-added).
--
-- Rollback notes (only once no row holds 'grpc' or 'connect'):
--   ALTER TABLE apiome.verification_target DROP CONSTRAINT IF EXISTS verification_target_protocol_check;
--   ALTER TABLE apiome.verification_target ADD CONSTRAINT verification_target_protocol_check
--       CHECK (protocol IN ('http', 'graphql'));
--   ALTER TABLE apiome.verification_run DROP CONSTRAINT IF EXISTS verification_run_protocol_check;
--   ALTER TABLE apiome.verification_run ADD CONSTRAINT verification_run_protocol_check
--       CHECK (protocol IN ('http', 'graphql'));

SET search_path TO apiome, public;

ALTER TABLE apiome.verification_target
    DROP CONSTRAINT IF EXISTS verification_target_protocol_check;
ALTER TABLE apiome.verification_target
    ADD CONSTRAINT verification_target_protocol_check
        CHECK (protocol IN ('http', 'graphql', 'grpc', 'connect'));

ALTER TABLE apiome.verification_run
    DROP CONSTRAINT IF EXISTS verification_run_protocol_check;
ALTER TABLE apiome.verification_run
    ADD CONSTRAINT verification_run_protocol_check
        CHECK (protocol IN ('http', 'graphql', 'grpc', 'connect'));

COMMENT ON COLUMN apiome.verification_target.protocol IS
    'http | graphql | grpc | connect — what the target speaks; a run whose suite it cannot execute is refused (XPC-1.2, XPC-3.2)';
COMMENT ON COLUMN apiome.verification_run.protocol IS
    'http | graphql | grpc | connect — the target protocol the suite was executed over (XPC-1.2, XPC-3.2)';
