-- Slate Edge unified observability, residency, usage and budget control plane: release-correlated
-- metrics, structured logs, trace waterfalls, sampled and redacted live tail, OpenTelemetry export,
-- synthetic regional health, stage-by-stage data residency, metered and modelled service usage,
-- forecasts and budget alerts (UXE-3.4, private-suite#2476).
--
-- Observability is the first surface in this family where the dangerous failure is not doing too
-- much but believing too much. A cache rule that does not fire wastes a purge; a WAF rule that does
-- not fire leaves an attacker unblocked; a capability that is wrongly granted turns the edge into
-- an SSRF relay. All three are bad, and all three are visible. A latency chart that is quietly
-- modelled rather than measured is worse than any of them, because it is acted upon: somebody
-- reads a p95, concludes the release is healthy, and promotes it. The same is true one step
-- further along, where §29.6 asks for spend, forecast and overage — a modelled cost presented as a
-- bill is not a disappointing estimate but an invented invoice. So this migration is less about
-- storing signals than about making every stored signal state, in a column, whether anything
-- actually observed it.
--
-- The shape here is not invented. `ROADMAP_AUTHORING_PLATFORM.md` §29.6 names the pieces
-- (release-correlated request, cache, origin, function and security metrics; searchable structured
-- logs, a trace waterfall, live tail with sampling and OpenTelemetry export; synthetic health from
-- key regions with regression annotations after promotion; regional controls that distinguish
-- ingress, TLS termination, decrypted processing, cache storage, function execution and log/data
-- storage, with the UX stating what a residency option does NOT cover; and daily usage and spend by
-- delivery, build, function, log and AI service with forecast, included quota, overage, cache
-- savings and configurable budget alerts). §28.4 adds that every chart carries time range,
-- environment/release/version, comparison, drill-down and export, and that low-volume data uses
-- privacy thresholds. §29.7 assigns the surface to roles: the Platform operator gets logs, traces,
-- regions and budgets; the Author gets content and search insights; the Auditor gets read-only
-- evidence and an exportable audit. These tables are that specification expressed in SQL.
--
--   1. `apiome.slate_insight_policies`         — one policy per environment. Owns retention
--                                                windows, sampling, the privacy threshold, and
--                                                whether anything is actually observing this lane.
--   2. `apiome.slate_residency_lanes`          — the six processing stages §29.6 distinguishes,
--                                                each with the promise it makes and the sentence
--                                                stating what it does not cover.
--   3. `apiome.slate_insight_metric_series`    — release-correlated metric points. Every row says
--                                                whether it was measured or modelled.
--   4. `apiome.slate_insight_logs`             — structured log records with allowlisted, expiring
--                                                evidence.
--   5. `apiome.slate_insight_traces`           — one trace per correlated request.
--   6. `apiome.slate_insight_trace_spans`      — the waterfall: spans within a trace.
--   7. `apiome.slate_insight_live_tail_sessions` — who tailed what, at what sample rate, under what
--                                                rate limit, and until when the capture expires.
--   8. `apiome.slate_insight_otlp_exports`     — OpenTelemetry export destinations. This table has
--                                                no column able to hold a header value.
--   9. `apiome.slate_insight_synthetic_checks` — synthetic probes defined per region.
--  10. `apiome.slate_insight_synthetic_results` — their results, and post-promotion annotations.
--  11. `apiome.slate_insight_usage_records`    — daily usage and spend per service. Metered rows
--                                                may be billed; modelled rows cannot.
--  12. `apiome.slate_insight_budgets`          — included quota, budget amount and alert
--                                                thresholds.
--  13. `apiome.slate_insight_budget_alerts`    — alerts that fired, and what they were computed
--                                                from.
--  14. `apiome.slate_insight_audit`            — append-only; UPDATE and DELETE are refused.
--
-- Correlation is a schema fact, not a join convention (acceptance criterion 1). §29.6 opens by
-- requiring that metrics, logs, traces, security and cost share release, environment and region
-- correlation, and the issue restates it first because separate provider dashboards are exactly
-- what makes a release impossible to connect to its latency. The obvious implementation is to let
-- each signal carry whatever identifiers its source happened to have, and reconcile them in the
-- query layer. That produces a surface where a chart and the drill-down beneath it disagree about
-- which rows they mean. Here every signal table — metrics, logs, traces, synthetic results and
-- usage — carries `environment_id NOT NULL`, `release_id` and `region` in the same three columns
-- with the same names and the same types, so correlating them is a fact of the schema and a signal
-- that cannot be correlated cannot be written in the first place.
--
-- Every signal states whether it was observed (acceptance criterion 1, continued). `basis` is
-- `modelled` or `edge-observed` on `slate_insight_metric_series`, `slate_insight_logs`,
-- `slate_insight_traces` and `slate_insight_synthetic_results`, and each carries
-- `CHECK (basis <> 'edge-observed' OR edge_attached)`. Nothing observes these lanes, so every row
-- this system can write is `modelled`, and the constraint means that is not a habit but an
-- impossibility. The alternative — a single `synthetic` boolean defaulted TRUE — was rejected for
-- the same reason V189 rejected a `granted` column: a bug that writes the wrong value would
-- silently promote a model to a measurement, and the failure would be invisible precisely where it
-- matters most.
--
-- Residency states what it does not cover (acceptance criterion 2). §29.6 asks for regional
-- controls distinguishing ingress, TLS termination, decrypted processing, cache storage, function
-- execution and log/data storage, and then adds the unusual requirement that the UX state what a
-- residency option does not cover. `slate_residency_lanes` therefore has one row per stage — the
-- stage is a CHECK-constrained enum, not free text, so a lane cannot be omitted by never being
-- named — and `uncovered_sentence TEXT NOT NULL`. NOT NULL is the whole point. A residency claim
-- with no stated gap is not a stronger promise than one with a gap; it is the same promise with
-- the gap unwritten, and it is the version somebody quotes to a regulator. Making the sentence
-- mandatory means a lane cannot be recorded as covering everything by saying nothing.
--
-- Live tail is sampled, redacted, rate-limited and auditable, and each is a column (acceptance
-- criterion 3). `sample_rate` is bounded above by the policy's ceiling and below by zero,
-- `max_events_per_second` is NOT NULL, the actor triple records who opened the stream, and
-- `retain_until` expires the capture. Log and trace evidence is redacted by ALLOWLIST — the same
-- `evidence - ARRAY[...] = '{}'::jsonb` CHECK V188 used for security events and V189 for
-- invocations — rather than filtered by a denylist, so storing a cookie or an authorization header
-- in a tail capture is impossible rather than discouraged. That inheritance is deliberate: live
-- tail is the single most tempting place in the product to capture a whole request "just while we
-- debug this", and it is the one surface where the request body is on screen by definition.
--
-- Export cannot claim a delivery it did not make (acceptance criterion 3, continued).
-- `slate_insight_otlp_exports.last_delivery_state` is CHECK-constrained against `edge_attached` in
-- the same way `slate_cache_purges.outcome` was in V187: nothing can read `delivered` while
-- nothing is attached to deliver it. And, exactly as `slate_function_secret_refs` has no column
-- able to hold a secret value, this table has no column able to hold a header value — an OTLP
-- endpoint is authenticated by headers, those headers are bearer tokens, and a table that could
-- store one eventually would. It stores `header_secret_ref` and resolves at the boundary.
--
-- Cost reconciles with billing, or is not billed (acceptance criterion 4). This is where the
-- family's honesty rule stops being about credibility and becomes about money. §29.6 wants
-- forecast, included quota, overage, top drivers and measured cache savings, and the issue requires
-- they reconcile with billing. `slate_insight_usage_records` carries the same `basis` column as
-- every other signal, plus `billable BOOLEAN NOT NULL DEFAULT FALSE` and
-- `CHECK (billable = FALSE OR basis = 'metered')`. A modelled number can be charted, forecast,
-- compared and exported; it cannot be invoiced. `cache_savings_amount` is separately nullable and
-- carries its own CHECK requiring a metered basis, because "measured cache savings" computed from a
-- model is a discount nobody gave. Forecasts live in their own nullable columns rather than as
-- ordinary rows, so a projection can never be summed into a total as though it had happened.
--
-- Low-volume data is suppressed rather than rounded (§28.4). `slate_insight_policies` carries
-- `privacy_threshold`, and metric rows carry `sample_count` and `suppressed`. Below the threshold
-- the value is withheld and the row says so, rather than being perturbed: a suppressed cell is
-- legible to a reader and to an auditor, while a quietly fuzzed one is a number that looks exact
-- and is not. The default of 10 is invented rather than derived and should be replaced when the
-- product has real traffic, in the same spirit as V189's 0.9 near-ceiling ratio and 90-day grant
-- window.
--
-- Scope boundary, stated plainly. `deploy/` in this repository is a single Caddyfile. There is no
-- CDN, no WAF, no isolate pool and no collector behind it, so nothing here measures anything at
-- all. These tables record observability POLICY, the residency promises a lane has made, the
-- MODELLED signals a surface can chart against them, the export destinations that would receive
-- them, and the EVIDENCE and AUDIT trail around every change — all of which are real, persisted and
-- auditable. What they do not do is observe a request, because nothing is in the request path to
-- observe one. V186 said this about regions, V187 about eviction, V188 about mitigation and V189
-- about execution; the reason it is repeated here in stronger terms is that the previous three
-- surfaces are read as controls and this one is read as truth. A fabricated p95 or a fabricated
-- invoice is not an inert unenforced rule — it is a number somebody acts on. So the boundary is
-- enforced in six places rather than three: `slate_insight_policies.edge_attached` is FALSE for
-- every row this system can write; `CHECK (basis <> 'edge-observed' OR edge_attached)` on metrics,
-- logs, traces and synthetic results makes it impossible to record a measurement nothing took;
-- `CHECK (stream_state <> 'attached' OR edge_attached)` makes it impossible to claim a live tail is
-- receiving anything; `CHECK (last_delivery_state <> 'delivered' OR edge_attached)` makes it
-- impossible to claim an export arrived; `CHECK (billable = FALSE OR basis = 'metered')` makes it
-- impossible to bill a model; and `CHECK (cache_savings_amount IS NULL OR basis = 'metered')` makes
-- it impossible to credit one. The collector, the meter and the runtime tier are UXE-3.4's
-- successor work; this is the control plane they will report into.

SET search_path TO apiome, public;

-- ─── 1. Insight policy (one per environment) ─────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_insight_policies (
    id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id                UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    site_id                  UUID NOT NULL REFERENCES apiome.slate_sites(id) ON DELETE CASCADE,
    -- Observability posture is a property of a lane, not of a site: staging may retain logs for a
    -- day and tail them freely while production retains for a month and tails under approval.
    -- UNIQUE makes "one policy per environment" a database fact rather than a convention.
    environment_id           UUID NOT NULL UNIQUE
                             REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    -- Whether this lane collects signals at all. FALSE by default: collection is opted into, never
    -- inherited, because the default posture for request data is not to hold it.
    telemetry_enabled        BOOLEAN NOT NULL DEFAULT FALSE,
    -- Optimistic-concurrency token, deliberately mirroring slate_cache_policies.policy_version,
    -- slate_security_policies.policy_version and slate_function_policies.policy_version. Two
    -- operators editing retention during the same incident must not silently overwrite each other.
    policy_version           BIGINT NOT NULL DEFAULT 0,
    -- Whether a managed collector is wired to this lane. FALSE means every signal here is modelled,
    -- not measured. Stored rather than inferred so that when a collector is attached later,
    -- historical rows stay truthful about what was true when they were written.
    edge_attached            BOOLEAN NOT NULL DEFAULT FALSE,
    -- NULL today. Named now so attaching a collector is a data change, not a schema change.
    edge_provider            TEXT,
    -- Retention windows, per signal class rather than one shared number. §29.6 treats metrics, logs
    -- and traces as different things, and they have genuinely different liabilities: an aggregate
    -- metric is cheap to keep and carries no request data, while a log line is request data by
    -- definition. Separate columns mean keeping metrics for a year does not force keeping logs for
    -- a year, which a single window would.
    metric_retention_days    INTEGER NOT NULL DEFAULT 90 CHECK (metric_retention_days > 0),
    log_retention_days       INTEGER NOT NULL DEFAULT 14 CHECK (log_retention_days > 0),
    trace_retention_days     INTEGER NOT NULL DEFAULT 7 CHECK (trace_retention_days > 0),
    -- Default head sampling rate for traces, as a fraction. Bounded on both sides: above 1.0 is
    -- meaningless and below 0 is not a rate.
    default_sample_rate      NUMERIC(6, 5) NOT NULL DEFAULT 0.05000
                             CHECK (default_sample_rate >= 0 AND default_sample_rate <= 1),
    -- Ceiling a live tail session may not exceed. Stored on the lane rather than only per session,
    -- so opening a session cannot raise the lane's worst case without an audited policy write. The
    -- same reasoning as V189's per-lane CPU and memory ceilings.
    max_tail_sample_rate     NUMERIC(6, 5) NOT NULL DEFAULT 0.01000
                             CHECK (max_tail_sample_rate >= 0 AND max_tail_sample_rate <= 1),
    max_tail_events_per_sec  INTEGER NOT NULL DEFAULT 100 CHECK (max_tail_events_per_sec > 0),
    -- Minimum population before an aggregate may be shown (§28.4 privacy thresholds). Invented
    -- rather than derived; see the header. At least 1, because a threshold of 0 is no threshold.
    privacy_threshold        INTEGER NOT NULL DEFAULT 10 CHECK (privacy_threshold >= 1),
    created_at               TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at               TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by_actor_id      UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    updated_by_actor_name    TEXT NOT NULL,
    updated_by_actor_key     TEXT NOT NULL,
    -- Retention below the floor ordinary incident review needs is the change that quietly destroys
    -- the evidence a later investigation wanted. Recording WHY is the part that survives review.
    retention_waiver_reason  TEXT,
    CONSTRAINT slate_insight_policies_short_log_retention_needs_reason
        CHECK (log_retention_days >= 7 OR retention_waiver_reason IS NOT NULL)
);

COMMENT ON TABLE apiome.slate_insight_policies IS
    'Observability policy for one Slate environment (UXE-3.4, private-suite#2476): retention windows per signal class, sampling ceilings, privacy threshold, concurrency token and whether a collector is attached.';
COMMENT ON COLUMN apiome.slate_insight_policies.tenant_id IS
    'Owning tenant. Denormalized onto every slate_* table so queries and unique constraints stay tenant-scoped without multi-way joins.';
COMMENT ON COLUMN apiome.slate_insight_policies.site_id IS
    'Site the environment belongs to, denormalized so policy lookups do not need a two-hop join.';
COMMENT ON COLUMN apiome.slate_insight_policies.environment_id IS
    'Environment this policy governs. UNIQUE: a lane has exactly one insight policy.';
COMMENT ON COLUMN apiome.slate_insight_policies.telemetry_enabled IS
    'Whether this lane collects signals at all. FALSE by default: the default posture for request data is not to hold it.';
COMMENT ON COLUMN apiome.slate_insight_policies.policy_version IS
    'Optimistic-concurrency token, incremented on every policy, residency, export, budget or check write. Mirrors slate_cache_policies, slate_security_policies and slate_function_policies; a stale expected value is refused, never merged.';
COMMENT ON COLUMN apiome.slate_insight_policies.edge_attached IS
    'Whether a managed collector observes this lane. FALSE for every row this system can currently write: nothing is in the request path, so every signal is modelled rather than measured.';
COMMENT ON COLUMN apiome.slate_insight_policies.edge_provider IS
    'Name of the attached collector tier, or NULL when none.';
COMMENT ON COLUMN apiome.slate_insight_policies.metric_retention_days IS
    'How long aggregate metrics are kept. Separate from logs and traces because an aggregate carries no request data and is cheap to retain.';
COMMENT ON COLUMN apiome.slate_insight_policies.log_retention_days IS
    'How long structured logs are kept. Shorter than metrics by default: a log line is request data by definition, and request data is a liability rather than an asset.';
COMMENT ON COLUMN apiome.slate_insight_policies.trace_retention_days IS
    'How long traces and their spans are kept. Shortest of the three: a trace is the most detailed record of a single request the platform holds.';
COMMENT ON COLUMN apiome.slate_insight_policies.default_sample_rate IS
    'Default head sampling rate for traces as a fraction of requests, bounded to [0, 1].';
COMMENT ON COLUMN apiome.slate_insight_policies.max_tail_sample_rate IS
    'Ceiling on any live tail session sample rate. A session may tighten this and cannot exceed it, so opening a tail cannot raise the lane worst case without an audited policy write.';
COMMENT ON COLUMN apiome.slate_insight_policies.max_tail_events_per_sec IS
    'Ceiling on live tail throughput. Rate limiting is a stored policy rather than a client courtesy.';
COMMENT ON COLUMN apiome.slate_insight_policies.privacy_threshold IS
    'Minimum population before an aggregate may be shown (roadmap §28.4). Below it a metric is suppressed and says so rather than being perturbed. The default of 10 is invented and should be replaced when the product has real traffic.';
COMMENT ON COLUMN apiome.slate_insight_policies.created_at IS
    'When the policy row was created.';
COMMENT ON COLUMN apiome.slate_insight_policies.updated_at IS
    'When the policy was last changed.';
COMMENT ON COLUMN apiome.slate_insight_policies.updated_by_actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_insight_policies.updated_by_actor_name IS
    'Display name of the actor, stored so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_insight_policies.updated_by_actor_key IS
    'Immutable identity of the actor captured at write time, so an offboarded operator still reads as a distinct person in history.';
COMMENT ON COLUMN apiome.slate_insight_policies.retention_waiver_reason IS
    'Why log retention was set below the seven-day floor. Required in that case: shortening retention destroys the evidence a later investigation wanted, and an unexplained shortening is the one nobody can defend.';

CREATE INDEX IF NOT EXISTS idx_slate_insight_policies_tenant
    ON apiome.slate_insight_policies (tenant_id);
CREATE INDEX IF NOT EXISTS idx_slate_insight_policies_site
    ON apiome.slate_insight_policies (site_id);

-- ─── 2. Residency lanes (one row per processing stage) ───────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_residency_lanes (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id      UUID NOT NULL
                        REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    -- The six stages §29.6 distinguishes, as a closed enum rather than free text. A stage that
    -- could be named freely is a stage that can be omitted by never being mentioned, and the whole
    -- value of this table is that the reader can see all six and compare them. Ordered along the
    -- request path: where it arrives, where it is decrypted, where it is processed in the clear,
    -- where it is stored hot, where code runs on it, and where it comes to rest.
    stage               TEXT NOT NULL
                        CHECK (stage IN ('ingress', 'tls-termination', 'decrypted-processing',
                                         'cache-storage', 'function-execution',
                                         'log-data-storage')),
    -- What crossing a border means for this stage specifically. Same vocabulary as
    -- slate_function_policies.default_residency_class, most restrictive first, because a reader
    -- comparing the function lane here against the function policy there must not have to
    -- translate between two spellings of the same promise.
    residency_class     TEXT NOT NULL DEFAULT 'in-region-only'
                        CHECK (residency_class IN ('in-region-only', 'region-pinned',
                                                   'unrestricted')),
    -- Regions this stage is confined to. TEXT[] to match slate_release_regions.region_id, which is
    -- itself unconstrained: there is no canonical region registry to point at.
    regions             TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    -- The sentence stating what this residency option does NOT cover, required by §29.6 and NOT
    -- NULL for the reason the header gives: a claim with no stated gap is not a stronger promise,
    -- it is the same promise with the gap unwritten, and it is the version somebody quotes to a
    -- regulator. Making it mandatory means a lane cannot claim to cover everything by saying
    -- nothing.
    uncovered_sentence  TEXT NOT NULL,
    -- Whether this stage's placement is a promise the platform can keep today or a statement of
    -- intent. FALSE while nothing is in the request path; kept as a column so that attaching a
    -- real edge upgrades a promise rather than rewriting history.
    enforced            BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by_actor_id UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    updated_by_actor_name TEXT NOT NULL,
    updated_by_actor_key  TEXT NOT NULL,
    -- Same rule as slate_function_policies: loosening to unrestricted requires a stated reason.
    residency_waiver_reason TEXT,
    CONSTRAINT slate_residency_lanes_unrestricted_needs_reason
        CHECK (residency_class <> 'unrestricted' OR residency_waiver_reason IS NOT NULL),
    -- A stage confined to named regions must name at least one. 'in-region-only' with an empty
    -- region set reads as the strictest possible promise and means nothing at all.
    CONSTRAINT slate_residency_lanes_confined_needs_regions
        CHECK (residency_class = 'unrestricted' OR cardinality(regions) > 0),
    -- One row per stage per lane, which is what makes "all six are shown" a query rather than a
    -- hope.
    UNIQUE (environment_id, stage)
);

COMMENT ON TABLE apiome.slate_residency_lanes IS
    'Data residency per processing stage for one Slate environment (UXE-3.4, private-suite#2476): where ingress, TLS termination, decrypted processing, cache storage, function execution and log/data storage happen, and what each placement does not cover.';
COMMENT ON COLUMN apiome.slate_residency_lanes.tenant_id IS
    'Owning tenant, denormalized as on every slate_* table.';
COMMENT ON COLUMN apiome.slate_residency_lanes.environment_id IS
    'Environment this residency lane belongs to.';
COMMENT ON COLUMN apiome.slate_residency_lanes.stage IS
    'Which of the six processing stages from roadmap §29.6 this row describes. A closed enum rather than free text: a freely named stage can be omitted by never being mentioned, and the value of this table is that all six can be compared side by side.';
COMMENT ON COLUMN apiome.slate_residency_lanes.residency_class IS
    'in-region-only, region-pinned or unrestricted, most restrictive first. Same vocabulary as slate_function_policies.default_residency_class so the two surfaces cannot spell the same promise differently.';
COMMENT ON COLUMN apiome.slate_residency_lanes.regions IS
    'Regions this stage is confined to. TEXT[] to match slate_release_regions.region_id; there is no canonical region registry to reference.';
COMMENT ON COLUMN apiome.slate_residency_lanes.uncovered_sentence IS
    'What this residency option does not cover, required by roadmap §29.6. NOT NULL: a residency claim with no stated gap is the same promise with the gap unwritten, and is the version that gets quoted to a regulator.';
COMMENT ON COLUMN apiome.slate_residency_lanes.enforced IS
    'Whether this placement is enforced today. FALSE while nothing is in the request path, so the surface reports a declared intent rather than an active control.';
COMMENT ON COLUMN apiome.slate_residency_lanes.created_at IS
    'When the lane row was created.';
COMMENT ON COLUMN apiome.slate_residency_lanes.updated_at IS
    'When the lane was last changed.';
COMMENT ON COLUMN apiome.slate_residency_lanes.updated_by_actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_residency_lanes.updated_by_actor_name IS
    'Display name of the actor, stored so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_residency_lanes.updated_by_actor_key IS
    'Immutable identity of the actor captured at write time.';
COMMENT ON COLUMN apiome.slate_residency_lanes.residency_waiver_reason IS
    'Why this stage was loosened to unrestricted. Required in that case, matching slate_function_policies.';

CREATE INDEX IF NOT EXISTS idx_slate_residency_lanes_tenant
    ON apiome.slate_residency_lanes (tenant_id);
CREATE INDEX IF NOT EXISTS idx_slate_residency_lanes_environment
    ON apiome.slate_residency_lanes (environment_id);

-- ─── 3. Metric series ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_insight_metric_series (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id      UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    -- The three correlation columns, identical in name and type across every signal table here.
    -- See the header: correlation is a schema fact, and a signal that cannot be correlated cannot
    -- be written.
    environment_id UUID NOT NULL REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    release_id     UUID REFERENCES apiome.slate_releases(id) ON DELETE SET NULL,
    -- TEXT to match slate_release_regions.region_id, which is itself unconstrained.
    region         TEXT NOT NULL DEFAULT 'auto',
    -- The five metric families §29.6 names, plus cost, so a spend chart correlates with a latency
    -- chart through the same columns rather than through a parallel structure. A closed enum for
    -- the same reason the residency stages are closed.
    metric_family  TEXT NOT NULL
                   CHECK (metric_family IN ('request', 'cache', 'origin', 'function', 'security',
                                            'cost')),
    -- The specific series, e.g. 'requests', 'cache-hit-ratio', 'latency-p95', 'error-rate'. Free
    -- text rather than an enum: the family is the closed vocabulary the UI groups and filters by,
    -- while the series within a family will grow, and pinning it would make adding a percentile a
    -- migration.
    metric_key     TEXT NOT NULL,
    -- Half-open window [window_start, window_end). Stored rather than derived from a bucket size,
    -- so a series can carry mixed resolutions — a year of daily points and a day of minute points —
    -- without the reader having to know which table they came from.
    window_start   TIMESTAMP WITH TIME ZONE NOT NULL,
    window_end     TIMESTAMP WITH TIME ZONE NOT NULL,
    value          NUMERIC(20, 6),
    unit           TEXT NOT NULL DEFAULT 'count',
    -- Population behind this point, used against slate_insight_policies.privacy_threshold.
    sample_count   BIGINT NOT NULL DEFAULT 0 CHECK (sample_count >= 0),
    -- Withheld because the population was below the threshold. When TRUE, value is NULL: the row
    -- says it is suppressed rather than reporting a number that has been perturbed into looking
    -- exact.
    suppressed     BOOLEAN NOT NULL DEFAULT FALSE,
    -- Whether anything measured this. See the header.
    basis          TEXT NOT NULL DEFAULT 'modelled'
                   CHECK (basis IN ('modelled', 'edge-observed')),
    edge_attached  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT slate_insight_metric_series_window_ordered
        CHECK (window_end > window_start),
    CONSTRAINT slate_insight_metric_series_observed_needs_edge
        CHECK (basis <> 'edge-observed' OR edge_attached),
    -- A suppressed point must not also carry the value it suppressed, and a reported point must
    -- carry one. Asserted from both sides, because a one-sided rule would let a suppressed row
    -- keep the number in the column and leave it to every future reader to remember not to read it.
    CONSTRAINT slate_insight_metric_series_suppressed_has_no_value
        CHECK ((suppressed AND value IS NULL) OR (NOT suppressed AND value IS NOT NULL))
);

COMMENT ON TABLE apiome.slate_insight_metric_series IS
    'Release-correlated metric points for one Slate environment (UXE-3.4, private-suite#2476). Every row states whether it was measured or modelled, and suppressed rows carry no value.';
COMMENT ON COLUMN apiome.slate_insight_metric_series.tenant_id IS
    'Owning tenant, denormalized as on every slate_* table.';
COMMENT ON COLUMN apiome.slate_insight_metric_series.environment_id IS
    'Environment the point belongs to. One of the three correlation columns shared by every signal table in this migration.';
COMMENT ON COLUMN apiome.slate_insight_metric_series.release_id IS
    'Release the point is attributed to, or NULL when it spans releases. ON DELETE SET NULL so retiring a release does not delete its history.';
COMMENT ON COLUMN apiome.slate_insight_metric_series.region IS
    'Region the point was attributed to. TEXT to match slate_release_regions.region_id.';
COMMENT ON COLUMN apiome.slate_insight_metric_series.metric_family IS
    'request, cache, origin, function, security or cost — the families roadmap §29.6 names, plus cost so spend correlates through the same columns as latency rather than a parallel structure.';
COMMENT ON COLUMN apiome.slate_insight_metric_series.metric_key IS
    'The specific series within the family, e.g. latency-p95. Free text: the family is the closed vocabulary the UI filters by, while series grow, and pinning them would make adding a percentile a migration.';
COMMENT ON COLUMN apiome.slate_insight_metric_series.window_start IS
    'Inclusive start of the aggregation window.';
COMMENT ON COLUMN apiome.slate_insight_metric_series.window_end IS
    'Exclusive end of the aggregation window. Stored rather than derived from a bucket size so one series can carry mixed resolutions.';
COMMENT ON COLUMN apiome.slate_insight_metric_series.value IS
    'The aggregated value, or NULL when suppressed.';
COMMENT ON COLUMN apiome.slate_insight_metric_series.unit IS
    'Unit of the value, e.g. count, ratio, milliseconds or a currency code.';
COMMENT ON COLUMN apiome.slate_insight_metric_series.sample_count IS
    'Population behind the point, compared against slate_insight_policies.privacy_threshold.';
COMMENT ON COLUMN apiome.slate_insight_metric_series.suppressed IS
    'Whether the value was withheld for falling below the privacy threshold. A suppressed cell is legible to a reader and an auditor; a quietly perturbed one looks exact and is not.';
COMMENT ON COLUMN apiome.slate_insight_metric_series.basis IS
    'modelled or edge-observed. Every row this system can write is modelled, and the CHECK against edge_attached makes that an impossibility rather than a habit.';
COMMENT ON COLUMN apiome.slate_insight_metric_series.edge_attached IS
    'Whether a collector observed this lane when the row was written. Captured per row so history stays truthful after a collector is attached.';
COMMENT ON COLUMN apiome.slate_insight_metric_series.created_at IS
    'When the point was recorded.';

CREATE INDEX IF NOT EXISTS idx_slate_insight_metric_series_tenant
    ON apiome.slate_insight_metric_series (tenant_id);
CREATE INDEX IF NOT EXISTS idx_slate_insight_metric_series_correlation
    ON apiome.slate_insight_metric_series (environment_id, metric_family, window_start);
CREATE INDEX IF NOT EXISTS idx_slate_insight_metric_series_release
    ON apiome.slate_insight_metric_series (release_id)
    WHERE release_id IS NOT NULL;

-- ─── 4. Structured logs ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_insight_logs (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id      UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id UUID NOT NULL REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    release_id     UUID REFERENCES apiome.slate_releases(id) ON DELETE SET NULL,
    region         TEXT NOT NULL DEFAULT 'auto',
    at             TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Ordered by increasing urgency so a range filter is a comparison rather than a set membership
    -- test.
    level          TEXT NOT NULL DEFAULT 'info'
                   CHECK (level IN ('debug', 'info', 'warn', 'error')),
    -- Which subsystem emitted the line, sharing the metric family vocabulary so a drill-down from a
    -- chart into logs filters on a value that means the same thing in both places. A dimension a
    -- chart and an event list disagree about is a drill-down landing on the wrong rows.
    source         TEXT NOT NULL
                   CHECK (source IN ('request', 'cache', 'origin', 'function', 'security',
                                     'build')),
    message        TEXT NOT NULL,
    -- Trace this line belongs to, as a bare UUID rather than an FK: traces expire on a shorter
    -- retention than logs, and a log line whose trace has aged out is still worth reading.
    trace_ref      UUID,
    -- Redacted by ALLOWLIST, not filtered by denylist. jsonb key subtraction leaves the empty
    -- object only when every key present is permitted, so storing a cookie or an authorization
    -- header here is impossible rather than discouraged. Inherited verbatim from V188 security
    -- events and V189 invocations.
    evidence       JSONB NOT NULL DEFAULT '{}'::jsonb,
    basis          TEXT NOT NULL DEFAULT 'modelled'
                   CHECK (basis IN ('modelled', 'edge-observed')),
    edge_attached  BOOLEAN NOT NULL DEFAULT FALSE,
    -- The audit row lives forever; the captured request data does not.
    retain_until   TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT slate_insight_logs_evidence_allowlisted
        CHECK (evidence - ARRAY['method', 'path', 'query', 'userAgent', 'country', 'region',
                                'clientIpPrefix', 'statusCode', 'durationMs', 'cacheStatus',
                                'functionRef', 'variant', 'ruleRef', 'outcome'] = '{}'::jsonb),
    CONSTRAINT slate_insight_logs_observed_needs_edge
        CHECK (basis <> 'edge-observed' OR edge_attached),
    CONSTRAINT slate_insight_logs_retention_after_event
        CHECK (retain_until > at)
);

COMMENT ON TABLE apiome.slate_insight_logs IS
    'Structured, searchable log records for one Slate environment (UXE-3.4, private-suite#2476), with allowlisted and expiring evidence.';
COMMENT ON COLUMN apiome.slate_insight_logs.tenant_id IS
    'Owning tenant, denormalized as on every slate_* table.';
COMMENT ON COLUMN apiome.slate_insight_logs.environment_id IS
    'Environment the line belongs to.';
COMMENT ON COLUMN apiome.slate_insight_logs.release_id IS
    'Release the line is attributed to, or NULL. ON DELETE SET NULL so retiring a release does not delete its logs.';
COMMENT ON COLUMN apiome.slate_insight_logs.region IS
    'Region the line came from. TEXT to match slate_release_regions.region_id.';
COMMENT ON COLUMN apiome.slate_insight_logs.at IS
    'When the line was emitted.';
COMMENT ON COLUMN apiome.slate_insight_logs.level IS
    'debug, info, warn or error, ordered by increasing urgency so a range filter is a comparison rather than a set membership test.';
COMMENT ON COLUMN apiome.slate_insight_logs.source IS
    'Emitting subsystem, sharing the metric family vocabulary so a drill-down from a chart filters on a value meaning the same thing in both places.';
COMMENT ON COLUMN apiome.slate_insight_logs.message IS
    'The log message.';
COMMENT ON COLUMN apiome.slate_insight_logs.trace_ref IS
    'Trace this line belongs to. Deliberately not a foreign key: traces expire on a shorter retention than logs, and a line whose trace has aged out is still worth reading.';
COMMENT ON COLUMN apiome.slate_insight_logs.evidence IS
    'Allowlisted request evidence. The CHECK subtracts the permitted keys and requires the empty object, so an unlisted key such as a cookie or authorization header cannot be stored at all.';
COMMENT ON COLUMN apiome.slate_insight_logs.basis IS
    'modelled or edge-observed. Every row this system can write is modelled.';
COMMENT ON COLUMN apiome.slate_insight_logs.edge_attached IS
    'Whether a collector observed this lane when the row was written.';
COMMENT ON COLUMN apiome.slate_insight_logs.retain_until IS
    'When this line must be deleted, derived from slate_insight_policies.log_retention_days. Request data is a liability rather than an asset: the audit row lives forever, the captured line does not.';

CREATE INDEX IF NOT EXISTS idx_slate_insight_logs_tenant
    ON apiome.slate_insight_logs (tenant_id);
CREATE INDEX IF NOT EXISTS idx_slate_insight_logs_correlation
    ON apiome.slate_insight_logs (environment_id, at);
CREATE INDEX IF NOT EXISTS idx_slate_insight_logs_release
    ON apiome.slate_insight_logs (release_id)
    WHERE release_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_slate_insight_logs_trace
    ON apiome.slate_insight_logs (trace_ref)
    WHERE trace_ref IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_slate_insight_logs_retention
    ON apiome.slate_insight_logs (retain_until);

-- ─── 5. Traces ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_insight_traces (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id      UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id UUID NOT NULL REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    release_id     UUID REFERENCES apiome.slate_releases(id) ON DELETE SET NULL,
    region         TEXT NOT NULL DEFAULT 'auto',
    -- W3C trace-context trace id, 32 lowercase hex characters. Constrained by shape so an OTLP
    -- export cannot be handed an identifier a collector will reject.
    trace_id       TEXT NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    started_at     TIMESTAMP WITH TIME ZONE NOT NULL,
    duration_ms    INTEGER NOT NULL CHECK (duration_ms >= 0),
    route          TEXT NOT NULL,
    method         TEXT NOT NULL DEFAULT 'GET',
    status_code    INTEGER CHECK (status_code IS NULL OR (status_code >= 100 AND status_code < 600)),
    -- Whether this trace was kept by head sampling, and at what rate, so a reader can tell a rare
    -- event from a rarely sampled one. Without the rate a waterfall showing three traces means
    -- nothing: it may be three requests or three of thirty thousand.
    sample_rate    NUMERIC(6, 5) NOT NULL DEFAULT 1.00000
                   CHECK (sample_rate > 0 AND sample_rate <= 1),
    basis          TEXT NOT NULL DEFAULT 'modelled'
                   CHECK (basis IN ('modelled', 'edge-observed')),
    edge_attached  BOOLEAN NOT NULL DEFAULT FALSE,
    retain_until   TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT slate_insight_traces_observed_needs_edge
        CHECK (basis <> 'edge-observed' OR edge_attached),
    CONSTRAINT slate_insight_traces_retention_after_start
        CHECK (retain_until > started_at),
    UNIQUE (environment_id, trace_id)
);

COMMENT ON TABLE apiome.slate_insight_traces IS
    'One trace per correlated request for one Slate environment (UXE-3.4, private-suite#2476), carrying the sampling rate that produced it.';
COMMENT ON COLUMN apiome.slate_insight_traces.tenant_id IS
    'Owning tenant, denormalized as on every slate_* table.';
COMMENT ON COLUMN apiome.slate_insight_traces.environment_id IS
    'Environment the trace belongs to.';
COMMENT ON COLUMN apiome.slate_insight_traces.release_id IS
    'Release the trace is attributed to, or NULL.';
COMMENT ON COLUMN apiome.slate_insight_traces.region IS
    'Region that handled the traced request. TEXT to match slate_release_regions.region_id.';
COMMENT ON COLUMN apiome.slate_insight_traces.trace_id IS
    'W3C trace-context trace id, 32 lowercase hex characters. Shape-constrained so an OTLP export cannot be handed an identifier a collector will reject.';
COMMENT ON COLUMN apiome.slate_insight_traces.started_at IS
    'When the traced request began.';
COMMENT ON COLUMN apiome.slate_insight_traces.duration_ms IS
    'Total wall-clock duration of the trace in milliseconds.';
COMMENT ON COLUMN apiome.slate_insight_traces.route IS
    'Route pattern the request matched.';
COMMENT ON COLUMN apiome.slate_insight_traces.method IS
    'HTTP method of the traced request.';
COMMENT ON COLUMN apiome.slate_insight_traces.status_code IS
    'Response status, or NULL when the request did not complete.';
COMMENT ON COLUMN apiome.slate_insight_traces.sample_rate IS
    'Head sampling rate that kept this trace. Stored so a reader can distinguish a rare event from a rarely sampled one: without it, three traces may be three requests or three of thirty thousand.';
COMMENT ON COLUMN apiome.slate_insight_traces.basis IS
    'modelled or edge-observed. Every row this system can write is modelled.';
COMMENT ON COLUMN apiome.slate_insight_traces.edge_attached IS
    'Whether a collector observed this lane when the row was written.';
COMMENT ON COLUMN apiome.slate_insight_traces.retain_until IS
    'When this trace and its spans must be deleted, derived from slate_insight_policies.trace_retention_days.';

CREATE INDEX IF NOT EXISTS idx_slate_insight_traces_tenant
    ON apiome.slate_insight_traces (tenant_id);
CREATE INDEX IF NOT EXISTS idx_slate_insight_traces_correlation
    ON apiome.slate_insight_traces (environment_id, started_at);
CREATE INDEX IF NOT EXISTS idx_slate_insight_traces_release
    ON apiome.slate_insight_traces (release_id)
    WHERE release_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_slate_insight_traces_retention
    ON apiome.slate_insight_traces (retain_until);

-- ─── 6. Trace spans (the waterfall) ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_insight_trace_spans (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id     UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    -- A real FK with CASCADE, unlike slate_function_revisions.function_id: a span of a deleted
    -- trace is not evidence of anything, because a waterfall is only meaningful as a whole. The
    -- opposite policy from the revision table, and deliberately so.
    trace_id      UUID NOT NULL REFERENCES apiome.slate_insight_traces(id) ON DELETE CASCADE,
    -- W3C span ids, 16 lowercase hex characters. parent_span_ref is NULL for the root span.
    span_id       TEXT NOT NULL CHECK (span_id ~ '^[0-9a-f]{16}$'),
    parent_span_ref TEXT CHECK (parent_span_ref IS NULL OR parent_span_ref ~ '^[0-9a-f]{16}$'),
    name          TEXT NOT NULL,
    -- Which tier the span happened in, sharing the log source vocabulary minus build, because a
    -- build does not occur inside a request.
    component     TEXT NOT NULL
                  CHECK (component IN ('request', 'cache', 'origin', 'function', 'security')),
    -- Offset from the trace start rather than an absolute timestamp. A waterfall is drawn from
    -- offsets, and storing them directly means the rendering cannot disagree with the ordering.
    start_offset_ms INTEGER NOT NULL CHECK (start_offset_ms >= 0),
    duration_ms   INTEGER NOT NULL CHECK (duration_ms >= 0),
    status        TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'error')),
    -- Same allowlist discipline as the log table, with the span-relevant keys only.
    attributes    JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT slate_insight_trace_spans_attributes_allowlisted
        CHECK (attributes - ARRAY['route', 'method', 'statusCode', 'cacheStatus', 'functionRef',
                                  'variant', 'ruleRef', 'region', 'outcome'] = '{}'::jsonb),
    -- A span cannot be its own parent. Cheap to assert and produces an infinite loop in any
    -- waterfall renderer if it is ever violated.
    CONSTRAINT slate_insight_trace_spans_not_own_parent
        CHECK (parent_span_ref IS NULL OR parent_span_ref <> span_id),
    UNIQUE (trace_id, span_id)
);

COMMENT ON TABLE apiome.slate_insight_trace_spans IS
    'Spans within a trace (UXE-3.4, private-suite#2476), stored as offsets from the trace start so the waterfall rendering cannot disagree with the ordering.';
COMMENT ON COLUMN apiome.slate_insight_trace_spans.tenant_id IS
    'Owning tenant, denormalized as on every slate_* table.';
COMMENT ON COLUMN apiome.slate_insight_trace_spans.trace_id IS
    'Trace this span belongs to. A real foreign key with CASCADE, unlike slate_function_revisions.function_id: a span of a deleted trace is not evidence of anything, because a waterfall is only meaningful whole.';
COMMENT ON COLUMN apiome.slate_insight_trace_spans.span_id IS
    'W3C trace-context span id, 16 lowercase hex characters.';
COMMENT ON COLUMN apiome.slate_insight_trace_spans.parent_span_ref IS
    'Parent span id, or NULL for the root span.';
COMMENT ON COLUMN apiome.slate_insight_trace_spans.name IS
    'Span name, e.g. edge.cache.lookup.';
COMMENT ON COLUMN apiome.slate_insight_trace_spans.component IS
    'Tier the span occurred in, sharing the log source vocabulary minus build, because a build does not occur inside a request.';
COMMENT ON COLUMN apiome.slate_insight_trace_spans.start_offset_ms IS
    'Offset from the trace start in milliseconds. Stored rather than an absolute timestamp because a waterfall is drawn from offsets.';
COMMENT ON COLUMN apiome.slate_insight_trace_spans.duration_ms IS
    'Span duration in milliseconds.';
COMMENT ON COLUMN apiome.slate_insight_trace_spans.status IS
    'ok or error.';
COMMENT ON COLUMN apiome.slate_insight_trace_spans.attributes IS
    'Allowlisted span attributes, using the same jsonb key subtraction CHECK as the log evidence column.';

CREATE INDEX IF NOT EXISTS idx_slate_insight_trace_spans_tenant
    ON apiome.slate_insight_trace_spans (tenant_id);
CREATE INDEX IF NOT EXISTS idx_slate_insight_trace_spans_trace
    ON apiome.slate_insight_trace_spans (trace_id, start_offset_ms);

-- ─── 7. Live tail sessions ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_insight_live_tail_sessions (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id            UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id       UUID NOT NULL REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    -- Sampling, rate limiting and redaction are columns rather than client behaviour, because the
    -- acceptance criterion requires the tail to BE sampled, redacted and rate-limited rather than
    -- to be requested politely that way. A session that did not record its rate cannot be audited
    -- for having exceeded one.
    sample_rate          NUMERIC(6, 5) NOT NULL
                         CHECK (sample_rate > 0 AND sample_rate <= 1),
    max_events_per_sec   INTEGER NOT NULL CHECK (max_events_per_sec > 0),
    -- The allowlist that was in force for this session, stored so a capture reviewed a year later
    -- can be checked against the redaction it actually ran under rather than today's.
    redaction_allowlist  TEXT[] NOT NULL,
    -- Optional server-side filter the session ran with, recorded because "what were you looking
    -- at" is the question an auditor asks about a tail.
    filter_expression    TEXT,
    stream_state         TEXT NOT NULL DEFAULT 'closed'
                         CHECK (stream_state IN ('closed', 'requested', 'attached', 'refused')),
    started_at           TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at             TIMESTAMP WITH TIME ZONE,
    events_delivered     BIGINT NOT NULL DEFAULT 0 CHECK (events_delivered >= 0),
    -- Who opened the stream. The actor triple rather than a bare user id, so an offboarded
    -- operator still reads as a distinct person in the audit.
    opened_by_actor_id   UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    opened_by_actor_name TEXT NOT NULL,
    opened_by_actor_key  TEXT NOT NULL,
    reason               TEXT NOT NULL,
    edge_attached        BOOLEAN NOT NULL DEFAULT FALSE,
    retain_until         TIMESTAMP WITH TIME ZONE NOT NULL,
    -- Nothing is in the request path, so a session can be requested and refused but never attached.
    CONSTRAINT slate_insight_live_tail_sessions_attached_needs_edge
        CHECK (stream_state <> 'attached' OR edge_attached),
    -- And a session that never attached cannot have delivered anything. The pair is what makes the
    -- events_delivered column safe to sum.
    CONSTRAINT slate_insight_live_tail_sessions_delivery_needs_attach
        CHECK (events_delivered = 0 OR edge_attached),
    CONSTRAINT slate_insight_live_tail_sessions_ordered
        CHECK (ended_at IS NULL OR ended_at >= started_at),
    CONSTRAINT slate_insight_live_tail_sessions_retention_after_start
        CHECK (retain_until > started_at)
);

COMMENT ON TABLE apiome.slate_insight_live_tail_sessions IS
    'Live tail sessions for one Slate environment (UXE-3.4, private-suite#2476): who tailed what, at what sample rate, under what rate limit and redaction allowlist, and when the capture expires.';
COMMENT ON COLUMN apiome.slate_insight_live_tail_sessions.tenant_id IS
    'Owning tenant, denormalized as on every slate_* table.';
COMMENT ON COLUMN apiome.slate_insight_live_tail_sessions.environment_id IS
    'Environment that was tailed.';
COMMENT ON COLUMN apiome.slate_insight_live_tail_sessions.sample_rate IS
    'Sampling rate the session ran at, bounded above by slate_insight_policies.max_tail_sample_rate. A column rather than client behaviour: a session that did not record its rate cannot be audited for exceeding one.';
COMMENT ON COLUMN apiome.slate_insight_live_tail_sessions.max_events_per_sec IS
    'Rate limit the session ran under, bounded above by slate_insight_policies.max_tail_events_per_sec.';
COMMENT ON COLUMN apiome.slate_insight_live_tail_sessions.redaction_allowlist IS
    'The evidence allowlist in force for this session, stored so a capture reviewed later can be checked against the redaction it actually ran under rather than the current one.';
COMMENT ON COLUMN apiome.slate_insight_live_tail_sessions.filter_expression IS
    'Server-side filter the session ran with, or NULL. Recorded because what an operator was looking at is the question an auditor asks about a tail.';
COMMENT ON COLUMN apiome.slate_insight_live_tail_sessions.stream_state IS
    'closed, requested, attached or refused. Can never be attached while nothing is in the request path.';
COMMENT ON COLUMN apiome.slate_insight_live_tail_sessions.started_at IS
    'When the session was opened.';
COMMENT ON COLUMN apiome.slate_insight_live_tail_sessions.ended_at IS
    'When the session closed, or NULL while open.';
COMMENT ON COLUMN apiome.slate_insight_live_tail_sessions.events_delivered IS
    'How many events the session delivered. Constrained to zero unless a collector was attached, which is what makes this column safe to sum.';
COMMENT ON COLUMN apiome.slate_insight_live_tail_sessions.opened_by_actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_insight_live_tail_sessions.opened_by_actor_name IS
    'Display name of the actor, stored so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_insight_live_tail_sessions.opened_by_actor_key IS
    'Immutable identity of the actor captured at write time.';
COMMENT ON COLUMN apiome.slate_insight_live_tail_sessions.reason IS
    'Why the tail was opened. Required: live tail is the surface where request data is on screen by definition, and an unexplained capture is the one nobody can defend.';
COMMENT ON COLUMN apiome.slate_insight_live_tail_sessions.edge_attached IS
    'Whether a collector served this lane when the session was opened.';
COMMENT ON COLUMN apiome.slate_insight_live_tail_sessions.retain_until IS
    'When the session record and any capture must be deleted.';

CREATE INDEX IF NOT EXISTS idx_slate_insight_live_tail_sessions_tenant
    ON apiome.slate_insight_live_tail_sessions (tenant_id);
CREATE INDEX IF NOT EXISTS idx_slate_insight_live_tail_sessions_environment
    ON apiome.slate_insight_live_tail_sessions (environment_id, started_at);
CREATE INDEX IF NOT EXISTS idx_slate_insight_live_tail_sessions_retention
    ON apiome.slate_insight_live_tail_sessions (retain_until);

-- ─── 8. OpenTelemetry export destinations ────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_insight_otlp_exports (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id      UUID NOT NULL REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    label               TEXT NOT NULL,
    endpoint            TEXT NOT NULL,
    protocol            TEXT NOT NULL DEFAULT 'http/protobuf'
                        CHECK (protocol IN ('grpc', 'http/protobuf')),
    -- Which signals this destination receives. An array rather than three booleans so a
    -- destination that takes only traces is one row rather than a row with two falses, and so
    -- adding a fourth signal class is not a schema change.
    signals             TEXT[] NOT NULL DEFAULT ARRAY['metrics', 'traces']::TEXT[],
    -- The name of the secret holding this destination's authorization header, and NOTHING ELSE.
    -- Exactly as slate_function_secret_refs has no column able to hold a secret value, this table
    -- has no column able to hold a header value. An OTLP endpoint is authenticated by headers,
    -- those headers are bearer tokens, and a table that could store one eventually would. A CHECK
    -- would only have made it validated; an absent column makes it impossible.
    header_secret_ref   TEXT,
    enabled             BOOLEAN NOT NULL DEFAULT FALSE,
    -- Delivery state, ordered from least to most claimed. `delivered` is the only value that
    -- asserts something arrived, and it is the one constrained against edge_attached.
    last_delivery_state TEXT NOT NULL DEFAULT 'never-attempted'
                        CHECK (last_delivery_state IN ('never-attempted', 'pending', 'failed',
                                                       'delivered')),
    last_delivery_at    TIMESTAMP WITH TIME ZONE,
    last_failure_reason TEXT,
    edge_attached       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by_actor_id UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    updated_by_actor_name TEXT NOT NULL,
    updated_by_actor_key  TEXT NOT NULL,
    -- Nothing collects, so nothing can have been delivered. Same shape as V187's
    -- CHECK (outcome <> 'dispatched' OR edge_attached) on cache purges.
    CONSTRAINT slate_insight_otlp_exports_delivered_needs_edge
        CHECK (last_delivery_state <> 'delivered' OR edge_attached),
    -- A failure must say why. A destination reading `failed` with no reason is the state an
    -- operator cannot act on.
    CONSTRAINT slate_insight_otlp_exports_failure_needs_reason
        CHECK (last_delivery_state <> 'failed' OR last_failure_reason IS NOT NULL),
    -- Only the signal classes §29.6 names.
    CONSTRAINT slate_insight_otlp_exports_known_signals
        CHECK (signals <@ ARRAY['metrics', 'logs', 'traces']::TEXT[]
               AND cardinality(signals) > 0),
    UNIQUE (environment_id, label)
);

COMMENT ON TABLE apiome.slate_insight_otlp_exports IS
    'OpenTelemetry export destinations for one Slate environment (UXE-3.4, private-suite#2476). This table has no column able to hold a header value: authorization is a secret reference resolved at the boundary.';
COMMENT ON COLUMN apiome.slate_insight_otlp_exports.tenant_id IS
    'Owning tenant, denormalized as on every slate_* table.';
COMMENT ON COLUMN apiome.slate_insight_otlp_exports.environment_id IS
    'Environment whose signals this destination receives.';
COMMENT ON COLUMN apiome.slate_insight_otlp_exports.label IS
    'Operator-facing name, unique per environment.';
COMMENT ON COLUMN apiome.slate_insight_otlp_exports.endpoint IS
    'Collector endpoint URL.';
COMMENT ON COLUMN apiome.slate_insight_otlp_exports.protocol IS
    'grpc or http/protobuf.';
COMMENT ON COLUMN apiome.slate_insight_otlp_exports.signals IS
    'Which signal classes this destination receives. An array rather than three booleans so a traces-only destination is one row, and adding a signal class is not a schema change.';
COMMENT ON COLUMN apiome.slate_insight_otlp_exports.header_secret_ref IS
    'Name of the secret holding the authorization header, or NULL. The value itself has no column here, mirroring slate_function_secret_refs: an absent column makes exposure a schema impossibility rather than a validation.';
COMMENT ON COLUMN apiome.slate_insight_otlp_exports.enabled IS
    'Whether export to this destination is turned on.';
COMMENT ON COLUMN apiome.slate_insight_otlp_exports.last_delivery_state IS
    'never-attempted, pending, failed or delivered, ordered from least to most claimed. Cannot read delivered while nothing is attached to deliver.';
COMMENT ON COLUMN apiome.slate_insight_otlp_exports.last_delivery_at IS
    'When delivery was last attempted, or NULL.';
COMMENT ON COLUMN apiome.slate_insight_otlp_exports.last_failure_reason IS
    'Why the last delivery failed. Required when the state is failed: a failure with no reason is a state an operator cannot act on.';
COMMENT ON COLUMN apiome.slate_insight_otlp_exports.edge_attached IS
    'Whether a collector served this lane when the row was written.';
COMMENT ON COLUMN apiome.slate_insight_otlp_exports.created_at IS
    'When the destination was created.';
COMMENT ON COLUMN apiome.slate_insight_otlp_exports.updated_at IS
    'When the destination was last changed.';
COMMENT ON COLUMN apiome.slate_insight_otlp_exports.updated_by_actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_insight_otlp_exports.updated_by_actor_name IS
    'Display name of the actor, stored so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_insight_otlp_exports.updated_by_actor_key IS
    'Immutable identity of the actor captured at write time.';

CREATE INDEX IF NOT EXISTS idx_slate_insight_otlp_exports_tenant
    ON apiome.slate_insight_otlp_exports (tenant_id);
CREATE INDEX IF NOT EXISTS idx_slate_insight_otlp_exports_environment
    ON apiome.slate_insight_otlp_exports (environment_id);

-- ─── 9. Synthetic checks ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_insight_synthetic_checks (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id      UUID NOT NULL REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    label               TEXT NOT NULL,
    target_path         TEXT NOT NULL DEFAULT '/',
    method              TEXT NOT NULL DEFAULT 'GET',
    -- Regions the probe runs from. §29.6 asks for synthetic health from key regions, so the region
    -- set is the point of the row rather than an attribute of it.
    regions             TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    interval_seconds    INTEGER NOT NULL DEFAULT 300 CHECK (interval_seconds >= 60),
    expected_status     INTEGER NOT NULL DEFAULT 200
                        CHECK (expected_status >= 100 AND expected_status < 600),
    -- Latency budget the probe is judged against, so a "healthy" verdict means something
    -- specific rather than "it answered".
    latency_budget_ms   INTEGER NOT NULL DEFAULT 1000 CHECK (latency_budget_ms > 0),
    enabled             BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by_actor_id UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    updated_by_actor_name TEXT NOT NULL,
    updated_by_actor_key  TEXT NOT NULL,
    CONSTRAINT slate_insight_synthetic_checks_enabled_needs_regions
        CHECK (NOT enabled OR cardinality(regions) > 0),
    UNIQUE (environment_id, label)
);

COMMENT ON TABLE apiome.slate_insight_synthetic_checks IS
    'Synthetic health probes defined per region for one Slate environment (UXE-3.4, private-suite#2476).';
COMMENT ON COLUMN apiome.slate_insight_synthetic_checks.tenant_id IS
    'Owning tenant, denormalized as on every slate_* table.';
COMMENT ON COLUMN apiome.slate_insight_synthetic_checks.environment_id IS
    'Environment the probe targets.';
COMMENT ON COLUMN apiome.slate_insight_synthetic_checks.label IS
    'Operator-facing name, unique per environment.';
COMMENT ON COLUMN apiome.slate_insight_synthetic_checks.target_path IS
    'Path the probe requests.';
COMMENT ON COLUMN apiome.slate_insight_synthetic_checks.method IS
    'HTTP method the probe uses.';
COMMENT ON COLUMN apiome.slate_insight_synthetic_checks.regions IS
    'Regions the probe runs from. Roadmap §29.6 asks for health from key regions, so the region set is the point of the row rather than an attribute of it.';
COMMENT ON COLUMN apiome.slate_insight_synthetic_checks.interval_seconds IS
    'How often the probe runs, floored at 60 seconds so a check cannot be turned into a load generator.';
COMMENT ON COLUMN apiome.slate_insight_synthetic_checks.expected_status IS
    'Status the probe treats as healthy.';
COMMENT ON COLUMN apiome.slate_insight_synthetic_checks.latency_budget_ms IS
    'Latency the probe is judged against, so a healthy verdict means something specific rather than that the endpoint answered at all.';
COMMENT ON COLUMN apiome.slate_insight_synthetic_checks.enabled IS
    'Whether the probe is active. Cannot be enabled without at least one region to run from.';
COMMENT ON COLUMN apiome.slate_insight_synthetic_checks.created_at IS
    'When the check was created.';
COMMENT ON COLUMN apiome.slate_insight_synthetic_checks.updated_at IS
    'When the check was last changed.';
COMMENT ON COLUMN apiome.slate_insight_synthetic_checks.updated_by_actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_insight_synthetic_checks.updated_by_actor_name IS
    'Display name of the actor, stored so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_insight_synthetic_checks.updated_by_actor_key IS
    'Immutable identity of the actor captured at write time.';

CREATE INDEX IF NOT EXISTS idx_slate_insight_synthetic_checks_tenant
    ON apiome.slate_insight_synthetic_checks (tenant_id);
CREATE INDEX IF NOT EXISTS idx_slate_insight_synthetic_checks_environment
    ON apiome.slate_insight_synthetic_checks (environment_id);

-- ─── 10. Synthetic results and regression annotations ────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_insight_synthetic_results (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id      UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    check_id       UUID NOT NULL
                   REFERENCES apiome.slate_insight_synthetic_checks(id) ON DELETE CASCADE,
    environment_id UUID NOT NULL REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    release_id     UUID REFERENCES apiome.slate_releases(id) ON DELETE SET NULL,
    region         TEXT NOT NULL DEFAULT 'auto',
    at             TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    outcome        TEXT NOT NULL
                   CHECK (outcome IN ('healthy', 'degraded', 'failed', 'not-run')),
    status_code    INTEGER CHECK (status_code IS NULL OR (status_code >= 100 AND status_code < 600)),
    latency_ms     INTEGER CHECK (latency_ms IS NULL OR latency_ms >= 0),
    -- §29.6 asks for automatic regression annotations after promotion. An annotation is a property
    -- of a result rather than its own table, because a regression that is not attached to the
    -- probe run that found it is an alert with no evidence behind it.
    annotation_kind TEXT
                   CHECK (annotation_kind IS NULL
                          OR annotation_kind IN ('post-promotion-regression',
                                                 'post-promotion-recovery')),
    annotation_note TEXT,
    basis          TEXT NOT NULL DEFAULT 'modelled'
                   CHECK (basis IN ('modelled', 'edge-observed')),
    edge_attached  BOOLEAN NOT NULL DEFAULT FALSE,
    retain_until   TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT slate_insight_synthetic_results_observed_needs_edge
        CHECK (basis <> 'edge-observed' OR edge_attached),
    -- An annotation must say what it observed, and a note without a kind is a comment nobody can
    -- filter on. Asserted both ways so the pair cannot half-exist.
    CONSTRAINT slate_insight_synthetic_results_annotation_paired
        CHECK ((annotation_kind IS NULL AND annotation_note IS NULL)
               OR (annotation_kind IS NOT NULL AND annotation_note IS NOT NULL)),
    -- A post-promotion annotation without the release it followed cannot be drilled into, which is
    -- the only thing an operator wants to do with it.
    CONSTRAINT slate_insight_synthetic_results_annotation_needs_release
        CHECK (annotation_kind IS NULL OR release_id IS NOT NULL),
    CONSTRAINT slate_insight_synthetic_results_retention_after_run
        CHECK (retain_until > at)
);

COMMENT ON TABLE apiome.slate_insight_synthetic_results IS
    'Synthetic probe results and post-promotion regression annotations (UXE-3.4, private-suite#2476).';
COMMENT ON COLUMN apiome.slate_insight_synthetic_results.tenant_id IS
    'Owning tenant, denormalized as on every slate_* table.';
COMMENT ON COLUMN apiome.slate_insight_synthetic_results.check_id IS
    'Probe that produced this result.';
COMMENT ON COLUMN apiome.slate_insight_synthetic_results.environment_id IS
    'Environment the probe targeted.';
COMMENT ON COLUMN apiome.slate_insight_synthetic_results.release_id IS
    'Release active when the probe ran, or NULL. Required when the row carries a post-promotion annotation.';
COMMENT ON COLUMN apiome.slate_insight_synthetic_results.region IS
    'Region the probe ran from. TEXT to match slate_release_regions.region_id.';
COMMENT ON COLUMN apiome.slate_insight_synthetic_results.at IS
    'When the probe ran.';
COMMENT ON COLUMN apiome.slate_insight_synthetic_results.outcome IS
    'healthy, degraded, failed or not-run. not-run exists because a probe that never executed is not the same as one that failed, and collapsing them would page somebody for a scheduler outage.';
COMMENT ON COLUMN apiome.slate_insight_synthetic_results.status_code IS
    'Status the probe received, or NULL when it did not complete.';
COMMENT ON COLUMN apiome.slate_insight_synthetic_results.latency_ms IS
    'Observed latency, or NULL when the probe did not complete.';
COMMENT ON COLUMN apiome.slate_insight_synthetic_results.annotation_kind IS
    'post-promotion-regression or post-promotion-recovery, or NULL. An annotation is a property of the probe run that found it, because a regression detached from its evidence is an alert nobody can verify.';
COMMENT ON COLUMN apiome.slate_insight_synthetic_results.annotation_note IS
    'What the annotation observed. Paired with annotation_kind by CHECK so neither can exist alone.';
COMMENT ON COLUMN apiome.slate_insight_synthetic_results.basis IS
    'modelled or edge-observed. Every row this system can write is modelled.';
COMMENT ON COLUMN apiome.slate_insight_synthetic_results.edge_attached IS
    'Whether a collector served this lane when the row was written.';
COMMENT ON COLUMN apiome.slate_insight_synthetic_results.retain_until IS
    'When this result must be deleted.';

CREATE INDEX IF NOT EXISTS idx_slate_insight_synthetic_results_tenant
    ON apiome.slate_insight_synthetic_results (tenant_id);
CREATE INDEX IF NOT EXISTS idx_slate_insight_synthetic_results_check
    ON apiome.slate_insight_synthetic_results (check_id, at);
CREATE INDEX IF NOT EXISTS idx_slate_insight_synthetic_results_release
    ON apiome.slate_insight_synthetic_results (release_id)
    WHERE release_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_slate_insight_synthetic_results_retention
    ON apiome.slate_insight_synthetic_results (retain_until);

-- ─── 11. Usage and spend records ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_insight_usage_records (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id            UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id       UUID NOT NULL REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    release_id           UUID REFERENCES apiome.slate_releases(id) ON DELETE SET NULL,
    region               TEXT NOT NULL DEFAULT 'auto',
    -- The five services §29.6 names for daily usage and spend.
    service              TEXT NOT NULL
                         CHECK (service IN ('delivery', 'build', 'function', 'log', 'ai')),
    -- The day this record covers, as a date rather than a timestamp: §29.6 asks for daily usage,
    -- and a date makes "one row per service per day" expressible as a unique constraint.
    usage_date           DATE NOT NULL,
    quantity             NUMERIC(20, 6) NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    unit                 TEXT NOT NULL DEFAULT 'count',
    -- Money is stored as NUMERIC with an explicit currency, never as a float, and never without
    -- the currency beside it.
    amount               NUMERIC(20, 6) NOT NULL DEFAULT 0 CHECK (amount >= 0),
    currency             TEXT NOT NULL DEFAULT 'USD' CHECK (currency ~ '^[A-Z]{3}$'),
    -- How much of this fell inside the plan's included quota, so overage is a stored fact rather
    -- than a subtraction the UI and the invoice might perform differently.
    included_quantity    NUMERIC(20, 6) NOT NULL DEFAULT 0 CHECK (included_quantity >= 0),
    overage_quantity     NUMERIC(20, 6) NOT NULL DEFAULT 0 CHECK (overage_quantity >= 0),
    -- Measured savings attributable to cache, nullable and separately constrained: a saving
    -- computed from a model is a discount nobody gave.
    cache_savings_amount NUMERIC(20, 6) CHECK (cache_savings_amount IS NULL
                                               OR cache_savings_amount >= 0),
    -- Projection for this service and day, kept in its own column rather than as an ordinary row,
    -- so a forecast can never be summed into a total as though it had happened.
    forecast_amount      NUMERIC(20, 6) CHECK (forecast_amount IS NULL OR forecast_amount >= 0),
    basis                TEXT NOT NULL DEFAULT 'modelled'
                         CHECK (basis IN ('modelled', 'metered')),
    -- Whether this row may appear on an invoice. The single most consequential column in the
    -- migration.
    billable             BOOLEAN NOT NULL DEFAULT FALSE,
    edge_attached        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at           TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- A modelled number can be charted, forecast, compared and exported. It cannot be invoiced.
    CONSTRAINT slate_insight_usage_records_billable_needs_meter
        CHECK (billable = FALSE OR basis = 'metered'),
    -- Nor can a metered claim be made where nothing metered it.
    CONSTRAINT slate_insight_usage_records_metered_needs_edge
        CHECK (basis <> 'metered' OR edge_attached),
    -- And measured cache savings require a real measurement, for the same reason.
    CONSTRAINT slate_insight_usage_records_savings_needs_meter
        CHECK (cache_savings_amount IS NULL OR basis = 'metered'),
    -- Overage is what exceeded the included quota; it cannot exceed the quantity it came from.
    CONSTRAINT slate_insight_usage_records_overage_within_quantity
        CHECK (overage_quantity <= quantity),
    UNIQUE (environment_id, service, usage_date)
);

COMMENT ON TABLE apiome.slate_insight_usage_records IS
    'Daily usage and spend per service for one Slate environment (UXE-3.4, private-suite#2476). Metered rows may be billed; modelled rows cannot, by CHECK.';
COMMENT ON COLUMN apiome.slate_insight_usage_records.tenant_id IS
    'Owning tenant, denormalized as on every slate_* table.';
COMMENT ON COLUMN apiome.slate_insight_usage_records.environment_id IS
    'Environment the usage is attributed to.';
COMMENT ON COLUMN apiome.slate_insight_usage_records.release_id IS
    'Release the usage is attributed to, or NULL when it spans releases.';
COMMENT ON COLUMN apiome.slate_insight_usage_records.region IS
    'Region the usage is attributed to, so cost allocation correlates with latency through the same column.';
COMMENT ON COLUMN apiome.slate_insight_usage_records.service IS
    'delivery, build, function, log or ai — the services roadmap §29.6 names.';
COMMENT ON COLUMN apiome.slate_insight_usage_records.usage_date IS
    'The day this record covers. A date rather than a timestamp so one row per service per day is expressible as a unique constraint.';
COMMENT ON COLUMN apiome.slate_insight_usage_records.quantity IS
    'Quantity consumed.';
COMMENT ON COLUMN apiome.slate_insight_usage_records.unit IS
    'Unit of the quantity, e.g. requests, gigabytes or invocations.';
COMMENT ON COLUMN apiome.slate_insight_usage_records.amount IS
    'Spend for the day. NUMERIC with an explicit currency beside it, never a float.';
COMMENT ON COLUMN apiome.slate_insight_usage_records.currency IS
    'ISO 4217 currency code, shape-constrained.';
COMMENT ON COLUMN apiome.slate_insight_usage_records.included_quantity IS
    'How much of the quantity fell inside the plan quota.';
COMMENT ON COLUMN apiome.slate_insight_usage_records.overage_quantity IS
    'How much exceeded the quota. A stored fact rather than a subtraction the UI and the invoice might perform differently.';
COMMENT ON COLUMN apiome.slate_insight_usage_records.cache_savings_amount IS
    'Measured savings attributable to cache, or NULL. Requires a metered basis: a saving computed from a model is a discount nobody gave.';
COMMENT ON COLUMN apiome.slate_insight_usage_records.forecast_amount IS
    'Projected spend, in its own column rather than as an ordinary row, so a forecast can never be summed into a total as though it had happened.';
COMMENT ON COLUMN apiome.slate_insight_usage_records.basis IS
    'modelled or metered. Every row this system can write is modelled, because nothing meters these lanes.';
COMMENT ON COLUMN apiome.slate_insight_usage_records.billable IS
    'Whether this row may appear on an invoice. Constrained to FALSE unless the basis is metered: a modelled cost presented as a bill is not an estimate but an invented invoice.';
COMMENT ON COLUMN apiome.slate_insight_usage_records.edge_attached IS
    'Whether a meter served this lane when the row was written.';
COMMENT ON COLUMN apiome.slate_insight_usage_records.created_at IS
    'When the record was written.';

CREATE INDEX IF NOT EXISTS idx_slate_insight_usage_records_tenant
    ON apiome.slate_insight_usage_records (tenant_id);
CREATE INDEX IF NOT EXISTS idx_slate_insight_usage_records_correlation
    ON apiome.slate_insight_usage_records (environment_id, usage_date);
CREATE INDEX IF NOT EXISTS idx_slate_insight_usage_records_release
    ON apiome.slate_insight_usage_records (release_id)
    WHERE release_id IS NOT NULL;

-- ─── 12. Budgets ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_insight_budgets (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id      UUID NOT NULL REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    label               TEXT NOT NULL,
    -- NULL means the budget covers every service, which is different from a budget that covers
    -- none. Stored as a nullable scope rather than a separate all_services boolean, so the two
    -- cannot disagree.
    service             TEXT CHECK (service IS NULL
                                    OR service IN ('delivery', 'build', 'function', 'log', 'ai')),
    period              TEXT NOT NULL DEFAULT 'monthly'
                        CHECK (period IN ('daily', 'weekly', 'monthly')),
    amount              NUMERIC(20, 6) NOT NULL CHECK (amount > 0),
    currency            TEXT NOT NULL DEFAULT 'USD' CHECK (currency ~ '^[A-Z]{3}$'),
    -- Fractions of the budget at which an alert fires, e.g. {0.5, 0.8, 1.0}. An array rather than
    -- three columns because the count is a product decision that will change and should not be a
    -- migration when it does.
    alert_thresholds    NUMERIC(4, 3)[] NOT NULL DEFAULT ARRAY[0.800, 1.000]::NUMERIC(4, 3)[],
    -- Where alerts go. A reference rather than an address, for the same reason the OTLP table
    -- stores a secret reference: a webhook URL frequently contains its own credential.
    notify_channel_ref  TEXT,
    enabled             BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by_actor_id UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    updated_by_actor_name TEXT NOT NULL,
    updated_by_actor_key  TEXT NOT NULL,
    -- A budget with no threshold never alerts, which is a budget that does nothing.
    CONSTRAINT slate_insight_budgets_thresholds_present
        CHECK (cardinality(alert_thresholds) > 0),
    -- And every threshold sits above 0 and at or below 2.0, because alerting at twice the budget
    -- is a real practice and alerting at zero is not: a zero threshold is crossed by the first
    -- cent of spend and stays crossed, so it fires immediately and permanently and trains an
    -- operator to ignore the one alert that mattered. Element-wise rather than over the array as
    -- a whole, because a single bad member is the entire failure.
    CONSTRAINT slate_insight_budgets_thresholds_bounded
        CHECK (0 < ALL (alert_thresholds) AND 2.0 >= ALL (alert_thresholds)),
    UNIQUE (environment_id, label)
);

COMMENT ON TABLE apiome.slate_insight_budgets IS
    'Spend budgets and alert thresholds for one Slate environment (UXE-3.4, private-suite#2476).';
COMMENT ON COLUMN apiome.slate_insight_budgets.tenant_id IS
    'Owning tenant, denormalized as on every slate_* table.';
COMMENT ON COLUMN apiome.slate_insight_budgets.environment_id IS
    'Environment the budget governs.';
COMMENT ON COLUMN apiome.slate_insight_budgets.label IS
    'Operator-facing name, unique per environment.';
COMMENT ON COLUMN apiome.slate_insight_budgets.service IS
    'Service the budget is scoped to, or NULL for all services. A nullable scope rather than a separate all_services boolean, so the two cannot disagree.';
COMMENT ON COLUMN apiome.slate_insight_budgets.period IS
    'daily, weekly or monthly.';
COMMENT ON COLUMN apiome.slate_insight_budgets.amount IS
    'Budget amount for the period.';
COMMENT ON COLUMN apiome.slate_insight_budgets.currency IS
    'ISO 4217 currency code, shape-constrained.';
COMMENT ON COLUMN apiome.slate_insight_budgets.alert_thresholds IS
    'Fractions of the budget at which an alert fires. An array rather than fixed columns because the count is a product decision that should not require a migration to change.';
COMMENT ON COLUMN apiome.slate_insight_budgets.notify_channel_ref IS
    'Reference to the notification channel, not its address. A webhook URL frequently contains its own credential, so the same reasoning applies here as to the OTLP header reference.';
COMMENT ON COLUMN apiome.slate_insight_budgets.enabled IS
    'Whether the budget is active.';
COMMENT ON COLUMN apiome.slate_insight_budgets.created_at IS
    'When the budget was created.';
COMMENT ON COLUMN apiome.slate_insight_budgets.updated_at IS
    'When the budget was last changed.';
COMMENT ON COLUMN apiome.slate_insight_budgets.updated_by_actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_insight_budgets.updated_by_actor_name IS
    'Display name of the actor, stored so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_insight_budgets.updated_by_actor_key IS
    'Immutable identity of the actor captured at write time.';

CREATE INDEX IF NOT EXISTS idx_slate_insight_budgets_tenant
    ON apiome.slate_insight_budgets (tenant_id);
CREATE INDEX IF NOT EXISTS idx_slate_insight_budgets_environment
    ON apiome.slate_insight_budgets (environment_id);

-- ─── 13. Budget alerts ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_insight_budget_alerts (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id        UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    budget_id        UUID NOT NULL
                     REFERENCES apiome.slate_insight_budgets(id) ON DELETE CASCADE,
    environment_id   UUID NOT NULL REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    at               TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    threshold        NUMERIC(4, 3) NOT NULL CHECK (threshold > 0),
    -- What the alert was computed from, stored beside the alert rather than recomputed on read.
    -- An alert that cannot show its arithmetic is one nobody trusts the second time it fires.
    observed_amount  NUMERIC(20, 6) NOT NULL CHECK (observed_amount >= 0),
    budget_amount    NUMERIC(20, 6) NOT NULL CHECK (budget_amount > 0),
    currency         TEXT NOT NULL DEFAULT 'USD' CHECK (currency ~ '^[A-Z]{3}$'),
    period_start     DATE NOT NULL,
    period_end       DATE NOT NULL,
    -- Whether the amount behind this alert was metered or modelled. An alert fired from a model is
    -- still worth showing — it is what a forecast is for — but it must say so, because "you have
    -- exceeded your budget" reads as a statement of fact.
    basis            TEXT NOT NULL DEFAULT 'modelled'
                     CHECK (basis IN ('modelled', 'metered')),
    -- Whether the alert was actually delivered anywhere. Same shape as the OTLP delivery state:
    -- nothing dispatches, so nothing can claim to have arrived.
    delivery_state   TEXT NOT NULL DEFAULT 'not-dispatched'
                     CHECK (delivery_state IN ('not-dispatched', 'pending', 'failed', 'delivered')),
    edge_attached    BOOLEAN NOT NULL DEFAULT FALSE,
    acknowledged_at  TIMESTAMP WITH TIME ZONE,
    acknowledged_by_actor_id   UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    acknowledged_by_actor_name TEXT,
    acknowledged_by_actor_key  TEXT,
    CONSTRAINT slate_insight_budget_alerts_period_ordered
        CHECK (period_end >= period_start),
    CONSTRAINT slate_insight_budget_alerts_delivered_needs_edge
        CHECK (delivery_state <> 'delivered' OR edge_attached),
    -- An acknowledgement is a person and a time together, or neither.
    CONSTRAINT slate_insight_budget_alerts_acknowledgement_complete
        CHECK ((acknowledged_at IS NULL AND acknowledged_by_actor_key IS NULL)
               OR (acknowledged_at IS NOT NULL AND acknowledged_by_actor_key IS NOT NULL
                   AND acknowledged_by_actor_name IS NOT NULL)),
    -- One alert per budget, threshold and period. Without this a scheduler retry re-alerts on
    -- every pass and the surface teaches operators to ignore it.
    UNIQUE (budget_id, threshold, period_start)
);

COMMENT ON TABLE apiome.slate_insight_budget_alerts IS
    'Budget alerts that fired, with the arithmetic behind them (UXE-3.4, private-suite#2476).';
COMMENT ON COLUMN apiome.slate_insight_budget_alerts.tenant_id IS
    'Owning tenant, denormalized as on every slate_* table.';
COMMENT ON COLUMN apiome.slate_insight_budget_alerts.budget_id IS
    'Budget that fired.';
COMMENT ON COLUMN apiome.slate_insight_budget_alerts.environment_id IS
    'Environment the alert belongs to.';
COMMENT ON COLUMN apiome.slate_insight_budget_alerts.at IS
    'When the alert fired.';
COMMENT ON COLUMN apiome.slate_insight_budget_alerts.threshold IS
    'Fraction of the budget that was crossed.';
COMMENT ON COLUMN apiome.slate_insight_budget_alerts.observed_amount IS
    'Spend observed when the alert fired. Stored beside the alert rather than recomputed on read: an alert that cannot show its arithmetic is one nobody trusts the second time.';
COMMENT ON COLUMN apiome.slate_insight_budget_alerts.budget_amount IS
    'Budget amount the observation was compared against, captured at fire time so later edits to the budget do not rewrite history.';
COMMENT ON COLUMN apiome.slate_insight_budget_alerts.currency IS
    'ISO 4217 currency code, shape-constrained.';
COMMENT ON COLUMN apiome.slate_insight_budget_alerts.period_start IS
    'Inclusive start of the budget period the alert covers.';
COMMENT ON COLUMN apiome.slate_insight_budget_alerts.period_end IS
    'Inclusive end of the budget period the alert covers.';
COMMENT ON COLUMN apiome.slate_insight_budget_alerts.basis IS
    'modelled or metered. An alert fired from a model is worth showing, but must say so: you have exceeded your budget reads as a statement of fact.';
COMMENT ON COLUMN apiome.slate_insight_budget_alerts.delivery_state IS
    'not-dispatched, pending, failed or delivered. Cannot read delivered while nothing is attached to dispatch it.';
COMMENT ON COLUMN apiome.slate_insight_budget_alerts.edge_attached IS
    'Whether a dispatcher served this lane when the alert fired.';
COMMENT ON COLUMN apiome.slate_insight_budget_alerts.acknowledged_at IS
    'When the alert was acknowledged, or NULL.';
COMMENT ON COLUMN apiome.slate_insight_budget_alerts.acknowledged_by_actor_id IS
    'Acknowledging user, when still present.';
COMMENT ON COLUMN apiome.slate_insight_budget_alerts.acknowledged_by_actor_name IS
    'Display name of the acknowledging actor.';
COMMENT ON COLUMN apiome.slate_insight_budget_alerts.acknowledged_by_actor_key IS
    'Immutable identity of the acknowledging actor, paired with the timestamp by CHECK so an acknowledgement is a person and a time together or neither.';

CREATE INDEX IF NOT EXISTS idx_slate_insight_budget_alerts_tenant
    ON apiome.slate_insight_budget_alerts (tenant_id);
CREATE INDEX IF NOT EXISTS idx_slate_insight_budget_alerts_budget
    ON apiome.slate_insight_budget_alerts (budget_id, at);
CREATE INDEX IF NOT EXISTS idx_slate_insight_budget_alerts_environment
    ON apiome.slate_insight_budget_alerts (environment_id, at);

-- ─── 14. Append-only audit ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.slate_insight_audit (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id      UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    environment_id UUID NOT NULL REFERENCES apiome.slate_environments(id) ON DELETE CASCADE,
    at             TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor_id       UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
    actor_name     TEXT NOT NULL,
    actor_key      TEXT NOT NULL,
    actor_kind     TEXT NOT NULL DEFAULT 'user'
                   CHECK (actor_kind IN ('user', 'automation')),
    -- What was acted on. Closed enum: an audit whose subject vocabulary can grow silently is one
    -- that cannot be filtered reliably a year later.
    subject_kind   TEXT NOT NULL
                   CHECK (subject_kind IN ('policy', 'residency-lane', 'otlp-export',
                                           'live-tail', 'synthetic-check', 'budget',
                                           'budget-alert', 'export')),
    subject_id     TEXT,
    summary        TEXT NOT NULL,
    detail         JSONB NOT NULL DEFAULT '{}'::jsonb
);

COMMENT ON TABLE apiome.slate_insight_audit IS
    'Append-only audit of every observability, residency, export and budget change (UXE-3.4, private-suite#2476). UPDATE and DELETE are refused by trigger.';
COMMENT ON COLUMN apiome.slate_insight_audit.tenant_id IS
    'Owning tenant, denormalized as on every slate_* table.';
COMMENT ON COLUMN apiome.slate_insight_audit.environment_id IS
    'Environment the change applied to.';
COMMENT ON COLUMN apiome.slate_insight_audit.at IS
    'When the change was made.';
COMMENT ON COLUMN apiome.slate_insight_audit.actor_id IS
    'Acting user, when still present.';
COMMENT ON COLUMN apiome.slate_insight_audit.actor_name IS
    'Display name of the actor, stored so history survives user deletion.';
COMMENT ON COLUMN apiome.slate_insight_audit.actor_key IS
    'Immutable identity of the actor captured at write time.';
COMMENT ON COLUMN apiome.slate_insight_audit.actor_kind IS
    'user or automation, so a scheduled retention sweep is distinguishable from an operator.';
COMMENT ON COLUMN apiome.slate_insight_audit.subject_kind IS
    'What was acted on. A closed enum: an audit whose subject vocabulary can grow silently cannot be filtered reliably a year later.';
COMMENT ON COLUMN apiome.slate_insight_audit.subject_id IS
    'Identifier of the subject, as text because subjects span several tables and one of them is a lane stage rather than a UUID.';
COMMENT ON COLUMN apiome.slate_insight_audit.summary IS
    'One-sentence description of the change, as shown to a reader.';
COMMENT ON COLUMN apiome.slate_insight_audit.detail IS
    'Structured detail of the change.';

CREATE INDEX IF NOT EXISTS idx_slate_insight_audit_tenant
    ON apiome.slate_insight_audit (tenant_id);
CREATE INDEX IF NOT EXISTS idx_slate_insight_audit_environment
    ON apiome.slate_insight_audit (environment_id, at);
CREATE INDEX IF NOT EXISTS idx_slate_insight_audit_subject
    ON apiome.slate_insight_audit (subject_kind, subject_id);

-- The audit is evidence, and evidence that can be edited is not evidence. UPDATE and DELETE raise
-- rather than silently doing nothing, so a caller that tries learns it was refused. Mirrors the
-- equivalent guards in V187, V188 and V189.
CREATE OR REPLACE FUNCTION apiome.slate_insight_audit_append_only()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'slate_insight_audit is append-only: % is not permitted', TG_OP
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_slate_insight_audit_append_only ON apiome.slate_insight_audit;
CREATE TRIGGER trg_slate_insight_audit_append_only
    BEFORE UPDATE OR DELETE ON apiome.slate_insight_audit
    FOR EACH ROW EXECUTE FUNCTION apiome.slate_insight_audit_append_only();
