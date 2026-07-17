# Email canonicalization — duplicate merge runbook

**Ticket:** OLO-1.1 (#4186) · **Migration:** `V180__email_canonicalization_4186.sql`

## What the migration did

`apiome.users.email` is now stored canonically (`lower(trim(email))`) and a **functional partial
unique index**, `uq_users_email_lower`, makes duplicate-cased signups impossible for live accounts:

```sql
CREATE UNIQUE INDEX uq_users_email_lower
    ON apiome.users (lower(email))
    WHERE deleted_at IS NULL;
```

If, before the migration, two or more **active** accounts collapsed to the same normalized address
(e.g. `Ada@Example.com` and `ada@example.com`), the migration did **not** merge them. Instead it:

1. Recorded every colliding row in `apiome.email_canonicalization_conflicts`.
2. Kept the **earliest-created** account of each group active (`action_taken = 'kept_active'`).
3. **Quarantined** the rest — `deleted_at = now()`, `enabled = false` — so their data is preserved
   and the unique index could build (`action_taken = 'quarantined'`).

No account data was combined. Reconciling a quarantined account into its canonical sibling is a
manual, operator-driven decision — this runbook.

## 1. Find the conflicts

If there were no collisions the audit table is empty and there is nothing to do:

```sql
SELECT count(*) FROM apiome.email_canonicalization_conflicts;
```

List each colliding group, canonical row first:

```sql
SELECT normalized_email,
       user_id,
       original_email,
       is_canonical,
       action_taken,
       detected_at
FROM apiome.email_canonicalization_conflicts
ORDER BY normalized_email, is_canonical DESC, detected_at;
```

- `is_canonical = true` → the surviving, still-active account.
- `action_taken = 'quarantined'` → soft-deleted; awaiting your decision.

## 2. Decide per group

For each `normalized_email` group, inspect the accounts and any data they own (tenant memberships,
API keys, projects — join on `user_id`) to decide which is the person's real account. Common
outcomes:

- **Canonical is correct, quarantined ones are stale/abandoned.** Leave them soft-deleted. Done.
- **A quarantined account is the one that should survive.** Reassign its owned rows to the canonical
  `user_id`, then keep the canonical account. See below.
- **Both are legitimately separate people who happened to share a cased address.** This should be
  impossible for a real email, but if it occurs, give one a corrected address and reactivate it
  (`enabled = true`, `deleted_at = NULL`) — note the unique index will reject reactivation while its
  normalized address still matches a live account, which is the intended guardrail.

## 3. Merge (reassign, then retire the duplicate)

Run inside a transaction. Reassign the duplicate's owned rows to the surviving account, then leave
the duplicate soft-deleted. Adjust the table list to your schema:

```sql
BEGIN;

-- Example: move tenant memberships from the duplicate to the survivor. Repeat for every table that
-- references users(id) (api_keys, projects, audit rows, ...). Use ON CONFLICT / DISTINCT where the
-- survivor may already hold the same row.
UPDATE apiome.tenant_users
   SET user_id = :survivor_id
 WHERE user_id = :duplicate_id
   AND NOT EXISTS (
       SELECT 1 FROM apiome.tenant_users t2
        WHERE t2.tenant_id = tenant_users.tenant_id
          AND t2.user_id = :survivor_id
   );

-- Keep the duplicate soft-deleted (it already is after V180); record the resolution for the trail.
UPDATE apiome.email_canonicalization_conflicts
   SET action_taken = 'merged'
 WHERE user_id = :duplicate_id;

COMMIT;
```

## 4. Verify

Confirm no two live accounts share a normalized address (should always return zero rows — the index
guarantees it):

```sql
SELECT lower(email), count(*)
FROM apiome.users
WHERE deleted_at IS NULL
GROUP BY lower(email)
HAVING count(*) > 1;
```

Once every group is resolved, the audit table can be left in place as a permanent record — it is not
consulted at runtime.
