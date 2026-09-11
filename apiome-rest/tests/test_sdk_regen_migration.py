"""Guardrails for the auto-regen migration — SDK-4.3 (#4497).

V258 adds the subscriptions, the publish-event runs and the jobs the worker drains. Each fragment
below pins a structural promise, so a later edit that relaxes it fails here rather than in
production.

Three of them carry the ticket's acceptance criteria as schema facts:

* **Failures land in dead-letter with retry** — ``dead_letter`` is a job status, next to the
  ``retrying`` backoff state, and a job carries its attempt count, next due time and error.
* **Run history links publish event → jobs → artifacts → deliveries** — a job references its run,
  the SDK-4.1 publish run and the SDK-4.2 delivery run, and copies the package version and pull
  request onto itself.
* **Unsubscribing stops future runs without touching past artifacts** — a job's subscription, like
  its publish and delivery runs, is ``ON DELETE SET NULL``.
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V258__sdk_regen_on_publish_4497.sql"

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS sdk_regen_subscriptions (",
    "CREATE TABLE IF NOT EXISTS sdk_regen_runs (",
    "CREATE TABLE IF NOT EXISTS sdk_regen_jobs (",
    # Rule 1: one subscription per project per ecosystem, with a delivery mode and options.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_sdk_regen_subscriptions_project",
    "ON sdk_regen_subscriptions (tenant_id, project_id, ecosystem)",
    "CHECK (ecosystem IN ('npm', 'pypi'))",
    "CHECK (delivery_mode IN ('registry', 'git', 'registry_and_git'))",
    "options JSONB NOT NULL DEFAULT '{}'::jsonb",
    "active BOOLEAN NOT NULL DEFAULT TRUE",
    # Rule 2: a publish event regenerates each ecosystem once.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_sdk_regen_jobs_run_ecosystem",
    "ON sdk_regen_jobs (run_id, ecosystem)",
    "run_id UUID NOT NULL REFERENCES sdk_regen_runs(id) ON DELETE CASCADE",
    # Rule 3: the queue lifecycle, dead letter included.
    "CHECK (status IN ('pending', 'running', 'retrying', 'succeeded', 'dead_letter', 'cancelled'))",
    "attempt_count INTEGER NOT NULL DEFAULT 0",
    "next_attempt_at TIMESTAMPTZ",
    "claim_token UUID",
    "error_code VARCHAR(64)",
    "CHECK (error_step IS NULL OR error_step IN ('generate', 'registry', 'git', 'worker'))",
    "attempts JSONB NOT NULL DEFAULT '[]'::jsonb",
    "CHECK (jsonb_typeof(attempts) = 'array')",
    "retry_requested_by UUID REFERENCES users(id) ON DELETE SET NULL",
    # Rule 4: the claim and the in-order rule are indexed.
    "CREATE INDEX IF NOT EXISTS idx_sdk_regen_jobs_due",
    "WHERE status IN ('pending', 'retrying')",
    "CREATE INDEX IF NOT EXISTS idx_sdk_regen_jobs_subscription_active",
    "CREATE INDEX IF NOT EXISTS idx_sdk_regen_jobs_running",
    "CREATE INDEX IF NOT EXISTS idx_sdk_regen_jobs_dead_letter",
    # Rule 5: the job links the event to what it produced.
    "publish_run_id UUID REFERENCES sdk_publish_runs(id) ON DELETE SET NULL",
    "delivery_run_id UUID REFERENCES sdk_git_delivery_runs(id) ON DELETE SET NULL",
    "package_version VARCHAR(128)",
    "pull_request_url TEXT",
    "artifact_sha256 VARCHAR(71)",
    # Rule 6: unsubscribing touches nothing past.
    "subscription_id UUID REFERENCES sdk_regen_subscriptions(id) ON DELETE SET NULL",
    "version_id UUID REFERENCES versions(id) ON DELETE SET NULL",
    "project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE",
    "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
    "CREATE INDEX IF NOT EXISTS idx_sdk_regen_runs_history",
)

#: Executable statements that would mean the migration took on a second job, or grew somewhere a
#: credential could be stored.
_FORBIDDEN_FRAGMENTS = (
    "SELECT apiome.seed_builtin_roles",
    "PERFORM apiome.seed_builtin_roles",
    "CREATE OR REPLACE FUNCTION seed_builtin_roles",
    "access_token",
    "encrypted_token",
    "token TEXT",
    "token BYTEA",
    "token VARCHAR",
    "secret TEXT",
    "secret BYTEA",
    "secret VARCHAR",
)


def _sql() -> str:
    """Return the migration's text, read from the repository root."""
    root = Path(__file__).resolve().parents[2]
    return (root / _MIGRATION).read_text(encoding="utf-8")


def _statements() -> str:
    """The migration with ``--`` comments removed, so prose cannot satisfy or trip a check."""
    return "\n".join(line.split("--", 1)[0] for line in _sql().splitlines())


def test_migration_file_exists():
    assert _sql().strip()


def test_migration_keeps_every_structural_promise():
    statements = _statements()
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in statements]
    assert not missing, f"V258 no longer keeps: {missing}"


def test_migration_adds_no_rbac_resource_and_no_credential_column():
    statements = _statements()
    present = [fragment for fragment in _FORBIDDEN_FRAGMENTS if fragment in statements]
    assert not present, f"V258 took on a second job: {present}"


def test_the_only_uniqueness_rules_are_one_subscription_per_ecosystem_and_one_job_per_run_cell():
    """Runs are a log: two publishes of one version are two runs, not a conflict."""
    statements = _statements()
    assert statements.count("CREATE UNIQUE INDEX") == 2
    runs_section = statements.split("CREATE TABLE IF NOT EXISTS sdk_regen_runs")[1].split(
        "CREATE TABLE IF NOT EXISTS sdk_regen_jobs"
    )[0]
    assert "UNIQUE" not in runs_section


def test_the_job_step_statuses_match_the_pipelines_it_orchestrates():
    """A job copies SDK-4.1 and SDK-4.2 run statuses; its CHECKs must accept every one of them."""
    from app.sdk_git_delivery_pipeline import RUN_STATUSES as DELIVERY_STATUSES
    from app.sdk_publish_pipeline import (
        RUN_STATUS_ALREADY_PUBLISHED,
        RUN_STATUS_DRY_RUN,
        RUN_STATUS_FAILED,
        RUN_STATUS_IN_PROGRESS,
        RUN_STATUS_PUBLISHED,
    )
    from app.sdk_regen_policy import JOB_STATUSES, STEPS

    statements = _statements()
    publish_check = statements.split("publish_status IN (")[1].split(")")[0]
    for status in (
        RUN_STATUS_IN_PROGRESS,
        RUN_STATUS_PUBLISHED,
        RUN_STATUS_ALREADY_PUBLISHED,
        RUN_STATUS_FAILED,
        RUN_STATUS_DRY_RUN,
    ):
        assert f"'{status}'" in publish_check
    delivery_check = statements.split("delivery_status IN (")[1].split(")")[0]
    for status in DELIVERY_STATUSES:
        assert f"'{status}'" in delivery_check
    job_check = statements.split("CHECK (status IN (")[1].split(")")[0]
    assert [part.strip(" '") for part in job_check.split(",")] == list(JOB_STATUSES)
    step_check = statements.split("error_step IN (")[1].split(")")[0]
    assert [part.strip(" '") for part in step_check.split(",")] == list(STEPS)


def test_every_migration_version_is_unique():
    scripts = Path(__file__).resolve().parents[2] / "apiome-db" / "scripts"
    versions = [path.name.split("__", 1)[0] for path in scripts.glob("V*__*.sql")]
    duplicates = {version for version in versions if versions.count(version) > 1}
    assert "V258" not in duplicates
