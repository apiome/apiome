"""Guardrails for the notification inbox migration — COL-3.1 (#4521).

V263 adds ``notifications``. Each fragment below pins a structural promise the REST layer and the
notification centre (COL-3.2) rely on, so a later edit that relaxes one fails here rather than in
production:

* **One row per recipient**, in one tenant, pointing at one project and version.
* **A closed type vocabulary**, as a CHECK rather than an ENUM, and a payload that is an object.
* **``read_at`` NULL means unread**, with a partial index for the badge's count.
* **The cap is the database's** — a statement-level trigger prunes past the newest rows per user.
* **Marking read is the only mutation** — a trigger refuses every other change.
* **Scope and lifetime** — tenant, recipient, project, and version cascade; the actor survives.

The comparison is run against the SQL with ``--`` comments removed, so prose cannot satisfy it.
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V263__notifications_col_3_1.sql"

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS notifications (",
    # Scope and lifetime.
    "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
    "user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE",
    "actor_id UUID REFERENCES users(id) ON DELETE SET NULL",
    "project_id UUID REFERENCES projects(id) ON DELETE CASCADE",
    "version_id UUID REFERENCES versions(id) ON DELETE CASCADE",
    # The row itself.
    "type VARCHAR(32) NOT NULL",
    "payload JSONB NOT NULL DEFAULT '{}'::jsonb",
    "CHECK (jsonb_typeof(payload) = 'object')",
    "read_at TIMESTAMP WITH TIME ZONE,",
    # Reads.
    "CREATE INDEX IF NOT EXISTS idx_notifications_user_created",
    "ON notifications (user_id, created_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_notifications_user_unread",
    "ON notifications (user_id, type) WHERE read_at IS NULL",
    # Retention.
    "AFTER INSERT ON notifications",
    "REFERENCING NEW TABLE AS inserted",
    "FOR EACH STATEMENT",
    "EXECUTE FUNCTION apiome.notifications_enforce_retention();",
    "PARTITION BY n.user_id ORDER BY n.created_at DESC, n.id DESC",
    "WHERE ranked.position > retention_cap",
    # Immutability.
    "BEFORE UPDATE ON notifications",
    "EXECUTE FUNCTION apiome.notifications_guard_immutable();",
    "(NEW.actor_id IS DISTINCT FROM OLD.actor_id AND NEW.actor_id IS NOT NULL)",
)

#: Statements that would mean the migration took on a second job.
_FORBIDDEN_FRAGMENTS = (
    "seed_builtin_roles",
    "role_permissions",
    "CREATE TYPE",
    "notification_preferences",
)


def _statements() -> str:
    """The migration's executable text, ``--`` comments removed, read from the repository root."""
    root = Path(__file__).resolve().parents[2]
    sql = (root / _MIGRATION).read_text(encoding="utf-8")
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def test_migration_keeps_every_structural_promise():
    statements = _statements()
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in statements]
    assert not missing, f"V263 no longer keeps: {missing}"


def test_migration_adds_no_rbac_resource_no_enum_type_and_no_preferences():
    statements = _statements()
    present = [fragment for fragment in _FORBIDDEN_FRAGMENTS if fragment in statements]
    assert not present, f"V263 took on a second job: {present}"


def test_the_type_vocabulary_matches_the_rest_models():
    from app.notifications import NOTIFICATION_TYPES

    statements = _statements()
    for name in NOTIFICATION_TYPES:
        assert f"'{name}'" in statements, name
    # And nothing the API does not know: every quoted type in the CHECK is one of ours.
    check = statements[statements.index("CHECK (type IN (") : statements.index("payload JSONB")]
    quoted = {fragment.split("'")[0] for fragment in check.split("'")[1::2]}
    assert quoted == set(NOTIFICATION_TYPES)


def test_the_retention_cap_matches_the_constant_the_api_advertises():
    from app.notifications import RETENTION_PER_USER

    assert f"retention_cap CONSTANT INTEGER := {RETENTION_PER_USER};" in _statements()


def test_the_immutability_trigger_leaves_read_at_alone():
    statements = _statements()
    guarded = [
        "tenant_id",
        "user_id",
        "type",
        "payload",
        "project_id",
        "version_id",
        "created_at",
    ]
    for column in guarded:
        assert f"NEW.{column} IS DISTINCT FROM OLD.{column}" in statements, column
    assert "NEW.read_at IS DISTINCT FROM OLD.read_at" not in statements


def test_the_migration_version_is_unique():
    scripts = Path(__file__).resolve().parents[2] / "apiome-db" / "scripts"
    versions = [path.name.split("__", 1)[0] for path in scripts.glob("V*__*.sql")]
    assert versions.count("V263") == 1
