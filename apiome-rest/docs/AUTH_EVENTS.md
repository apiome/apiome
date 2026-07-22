# Authentication audit events (`apiome.auth_events`) — OLO-1.6 (#4191)

A durable, append-only record of **who signed in / up, with which provider, and which identities
were linked** — the evidence support and security review need, and the source the Profile
login-history surface (#1607, #534, #2418) reads from.

## What is recorded

Every sign-in, sign-up, provider link and unlink attempt — **success or failure** — produces one
row in `apiome.auth_events` (migration `V193`). The ledger reuses the `access_audit` (V120) pattern:
append-only and hash-chained, written **best-effort** so a failed audit insert can never fail or
block the authentication it records.

| Column            | Meaning |
|-------------------|---------|
| `event_type`      | `sign_in`, `sign_up`, `link`, `unlink` |
| `outcome`         | `success` or `failure` (DB-constrained) |
| `user_id`         | Resolved user, or `NULL` for failed sign-ins and pre-account sign-up attempts |
| `user_label`      | Canonical email, retained independent of the `users` row so history survives account deletion |
| `provider`        | `github` / `gitlab` / `azure` / `credentials`, or `NULL` when unknown |
| `error_code`      | Stable auth error code on failure (see `account_resolution.AUTH_ERROR_CODES`, OLO-1.5) |
| `ip_hash`         | **Salted SHA-256** of the client IP — the raw address is never stored |
| `user_agent_hash` | **Salted SHA-256** of the client User-Agent — the raw header is never stored |
| `detail`          | Structured context, e.g. `{"auto_linked": true}` on a verified-email auto-link |
| `prev_hash` / `entry_hash` | Hash-chain fields for tamper-evidence (a global chain — auth precedes any tenant context) |

## How events are written

The account-resolution engine (`app.account_resolution`, OLO-1.3) already decides the outcome of an
arriving identity. `app.auth_events.event_from_decision(decision, facts)` maps that decision onto an
`AuthEvent`, and `Database.log_auth_event(event, ip_hash=…, user_agent_hash=…)` appends it:

```python
from app import auth_events
from app.account_resolution import resolve_account_decision

decision = resolve_account_decision(facts)
event = auth_events.event_from_decision(decision, facts)
db.log_auth_event(
    event,
    ip_hash=auth_events.hash_client_value(request_ip, salt=deployment_salt),
    user_agent_hash=auth_events.hash_client_value(user_agent, salt=deployment_salt),
)
# ...then act on `decision` as usual.
```

Decision → event mapping:

| Resolution action      | `event_type` | `outcome` | Notes |
|------------------------|--------------|-----------|-------|
| `ACTION_SIGN_IN`       | `sign_in`    | success   | known identity |
| `ACTION_SIGNUP`        | `sign_up`    | success   | new verified-email account |
| `ACTION_AUTO_LINK`     | `link`       | success   | `detail.auto_linked = true` |
| `ACTION_LINK_TO_SESSION` | `link`     | success   | explicit "link another provider" |
| `ACTION_REJECT`        | `sign_in` / `sign_up` / `link` | failure | carries `error_code`; type recovered from intent |

Raw IP / User-Agent are **never** passed to the ledger — only the salted SHA-256 hashes produced by
`hash_client_value`, which correlate events from the same address/device without retaining
directly-identifying network PII.

## Querying per user

```python
db.list_auth_events_for_user(user_id, limit=100)  # newest first
```

Returns the user's own events (the login-history read path). Failed sign-ins with no resolved user
are intentionally excluded; they remain queryable by operators directly on the table for security
review.

## Retention

- **Default window:** **365 days** (`auth_events.DEFAULT_AUTH_EVENT_RETENTION_DAYS`) — a full annual
  cycle for support and security review while bounding table growth.
- **Enforcement:** `Database.prune_auth_events(retention_days=…)` deletes rows strictly older than
  the window. Pruning is **tail-only** (oldest rows first), so the retained suffix of the hash chain
  stays contiguous and independently verifiable. Run it from a scheduled maintenance job.
- **Data minimisation:** deployments with stricter requirements pass a smaller `retention_days`. No
  raw IP or User-Agent is ever persisted, so the ledger holds no directly-identifying network PII
  regardless of window.
