-- MCP discovery sweep observability (#3676, V2-MCP-19.4 / MCAT-5.4): one row per sweep tick, and the
-- link from each job a tick created back to that tick.
--
-- The periodic re-discovery sweep (MCAT-5.1/5.2) enqueues `trigger = 'sweep'` jobs every tick, but a
-- tick leaves no record of its own: an operator cannot tell when the sweep last ran, how long it took,
-- or which jobs belong to which run — and a tick with nothing due, or one halted by the kill switch,
-- leaves no trace at all. This migration adds:
--
--   * mcp_discovery_sweep_runs           — one row per tick: when it started and finished, what it was
--                                          configured with, how many endpoints were due, how many runs
--                                          it dispatched, how many coalesced onto an already-active job
--                                          and how many failed to enqueue, and whether it completed or
--                                          was halted. The outcome counters (changed / unchanged /
--                                          failed / in flight) are deliberately NOT stored here: they
--                                          are computed from the linked job rows at read time, so they
--                                          always reconcile with the job log.
--   * mcp_discovery_jobs.sweep_run_id    — the tick that created the job (NULL for manual and registry
--                                          jobs, and for sweep jobs created before this migration).
--                                          ON DELETE SET NULL: pruning old runs keeps their jobs.
--
-- Retention is enforced by the application (old runs are pruned as new ones are recorded), so the
-- table stays bounded at roughly one row per tick for the retention window.
SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS mcp_discovery_sweep_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- When the tick began and finished; finished_at is NULL while it is still draining.
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP WITH TIME ZONE,

    -- `running` while the tick drains, `completed` once every dispatched run has finished, `halted`
    -- when the APIOME_MCP_DISCOVERY_ENABLED kill switch stopped the tick before it selected anything,
    -- `failed` when the tick itself raised (e.g. due-selection failed) — individual endpoint failures
    -- are job outcomes and never fail the tick.
    status VARCHAR(16) NOT NULL DEFAULT 'running',

    -- The bounds the tick ran under, so a run can be read without knowing the config at the time.
    max_concurrency INTEGER,
    endpoint_timeout_seconds INTEGER,

    -- Endpoints selected as due; runs the tick dispatched (each one a linked job); endpoints whose
    -- job coalesced onto an already-active one; endpoints whose enqueue raised.
    due_count INTEGER NOT NULL DEFAULT 0,
    dispatched_count INTEGER NOT NULL DEFAULT 0,
    deduplicated_count INTEGER NOT NULL DEFAULT 0,
    enqueue_failed_count INTEGER NOT NULL DEFAULT 0,

    CONSTRAINT mcp_discovery_sweep_runs_status_check
        CHECK (status IN ('running', 'completed', 'halted', 'failed')),
    CONSTRAINT mcp_discovery_sweep_runs_counts_check
        CHECK (due_count >= 0 AND dispatched_count >= 0
               AND deduplicated_count >= 0 AND enqueue_failed_count >= 0)
);

-- The status endpoint reads the most recent runs first; pruning deletes the oldest.
CREATE INDEX IF NOT EXISTS idx_mcp_discovery_sweep_runs_started_at
    ON mcp_discovery_sweep_runs(started_at DESC);

ALTER TABLE mcp_discovery_jobs
    ADD COLUMN IF NOT EXISTS sweep_run_id UUID
        REFERENCES mcp_discovery_sweep_runs(id) ON DELETE SET NULL;

-- Per-run outcome counts aggregate a run's jobs; only sweep jobs carry the link.
CREATE INDEX IF NOT EXISTS idx_mcp_discovery_jobs_sweep_run_id
    ON mcp_discovery_jobs(sweep_run_id) WHERE sweep_run_id IS NOT NULL;

COMMENT ON TABLE mcp_discovery_sweep_runs IS
    'One row per MCP discovery sweep tick (#3676): timing, bounds, due/dispatched/coalesced/enqueue-failed counts and status. Outcome counts are computed from the jobs linked by mcp_discovery_jobs.sweep_run_id.';
COMMENT ON COLUMN mcp_discovery_sweep_runs.status IS
    'running while the tick drains; completed once every dispatched run finished; halted when the APIOME_MCP_DISCOVERY_ENABLED kill switch stopped it; failed when the tick itself raised.';
COMMENT ON COLUMN mcp_discovery_sweep_runs.due_count IS
    'Endpoints selected as due for re-discovery by this tick.';
COMMENT ON COLUMN mcp_discovery_sweep_runs.dispatched_count IS
    'Discovery runs this tick created and drove; each is a job with sweep_run_id = this run.';
COMMENT ON COLUMN mcp_discovery_sweep_runs.deduplicated_count IS
    'Due endpoints whose job coalesced onto an already-active job (not run again by this tick).';
COMMENT ON COLUMN mcp_discovery_sweep_runs.enqueue_failed_count IS
    'Due endpoints whose job could not be enqueued (e.g. a transient database error).';
COMMENT ON COLUMN mcp_discovery_jobs.sweep_run_id IS
    'The sweep tick that created this job (#3676); NULL for manual/registry jobs and sweep jobs older than V363.';
