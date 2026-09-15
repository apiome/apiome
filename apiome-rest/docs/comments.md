# Comment threads (COL-1.1)

Element-anchored discussion for a project version: open a thread on a class, property, path,
operation, or the version itself; reply in Markdown; mention teammates; resolve and reopen.

- Storage: apiome-db `V259__comment_threads_4513.sql` (`comment_threads`, `comments`)
- Routes: `app/comment_routes.py`
- Rules: `app/comment_store.py`
- Mention parsing: `app/comment_mentions.py`
- Models and error codes: `app/comments.py`

This is the base for the Studio thread UI (COL-1.2), the Discussion panel (COL-1.3), anchor
resilience (COL-1.4), notification fan-out (COL-3.1), and review threads (COL-2.1).

## Model

A **thread** belongs to a tenant, a project, and a version. It is anchored by `anchor_type`
(`class | property | path | operation | version`) and `anchor_id`, the element's **primary key**.
It never stores canvas coordinates, so a thread stays on its element when the element moves.

| Anchor type | `anchor_id` is the id of |
|---|---|
| `class` | `classes` in the version |
| `property` | `class_properties` on a class of the version, or `properties` in the project's library |
| `path` | `version_path` in the version |
| `operation` | `path_operation` under a path of the version |
| `version` | the version itself (`anchor_id = version_id`; may be omitted when opening) |

The element must exist in that version when the thread is opened. What happens after the element
is deleted is COL-1.4's job.

A thread's `status` is `open` or `resolved`. Resolving records `resolved_by` and `resolved_at`.
Reopening clears both. `last_activity_at` moves on every reply and status change, and lists sort
by it.

A **comment** has a Markdown `body` (1–20,000 characters), an `author_id`, `mentions` (user ids),
`edited_at` (null until it is edited), and `created_at`.

## Endpoints

All paths are under `/v1/tenants/{tenant_slug}/projects/{project_ref}`. `project_ref` is a project
slug or id.

| Method | Path | Does |
|---|---|---|
| `GET` | `/comment-threads` | List threads (filters below), newest activity first |
| `POST` | `/comment-threads` | Open a thread with its first comment → `201` |
| `GET` | `/comment-threads/{thread_id}` | A thread with all its comments |
| `DELETE` | `/comment-threads/{thread_id}` | Delete a thread and its comments → `204` |
| `POST` | `/comment-threads/{thread_id}/resolve` | Resolve (no-op if already resolved) |
| `POST` | `/comment-threads/{thread_id}/reopen` | Reopen (no-op if already open) |
| `POST` | `/comment-threads/{thread_id}/comments` | Reply → `201` |
| `PATCH` | `/comment-threads/{thread_id}/comments/{comment_id}` | Edit a comment |
| `DELETE` | `/comment-threads/{thread_id}/comments/{comment_id}` | Delete a comment |

Open a thread:

```json
POST /v1/tenants/acme/projects/pets/comment-threads
{
  "version": "1.0.0",
  "anchor_type": "class",
  "anchor_id": "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0020",
  "body": "Should `nickname` be nullable, @bob.brown?"
}
```

`version` is a revision id or a version label.

List filters, which can be combined:

- `version`: a revision id or label. Returns every thread on that version, whatever its anchor type.
- `status`: `open` or `resolved`.
- `anchor_type`, `anchor_id`: one kind of element, or one element.
- `mentions_me=true`: threads where any comment mentions the caller.
- `limit` (1–200, default 50), `offset`.

The list response is `{threads, count, total, limit, offset}`. Each thread carries `comment_count`
and its `root_comment` (the opening comment).

Deleting a thread's **last** comment deletes the thread too. The response says so:
`{"deleted": true, "thread_deleted": true}`. A resolved thread still accepts replies and stays
resolved.

## Permissions

There is no comment RBAC resource.

| Action | Who |
|---|---|
| List, read, open a thread, reply, resolve, reopen | Anyone with `projects:view` (a Viewer can comment) |
| Edit or delete a comment | Its author, or a tenant administrator |
| Delete a thread | The member who opened it, or a tenant administrator |

"Tenant administrator" means a row in `tenant_administrators`, the same check the rest of the API
uses. A comment whose author has been deleted can only be moderated by an administrator. An API
key with no user behind it cannot comment, because every comment needs an author.

## Mentions

Mentions are resolved on the server, and a client cannot send its own. Each write resolves the
`@handle` tokens in the body against the tenant's **active and pending** members. An edit
resolves them again. The result is stored in `comments.mentions`, which COL-3.1 notifications and
the `mentions_me` filter both read.

A member answers to three handles, matched case-insensitively:

- their full email, `@jane.doe@example.com` (always unique);
- their email local part, `@jane.doe`;
- their display name with spaces and punctuation removed, `@JaneDoe`.

A handle that matches more than one member resolves to **nobody**. Use the full email to name one
of them. These are not mentions:

- an email address in prose;
- a URL path such as `https://medium.com/@jane`;
- an escaped `\@jane`;
- anything inside inline code or a fenced code block.

Trailing punctuation is ignored, so `thanks @jane.` mentions `jane`. Each comment stores at most
50 distinct mentions.

## Rate limits

Opening a thread and replying share one budget per user per tenant:
`APIOME_COMMENT_CREATE_RATE_LIMIT_PER_MINUTE` (default 30) over `APIOME_RATE_LIMIT_WINDOW_SECONDS`.
The global middleware still applies on top of this. Going over returns `429` with code
`comment-rate-limited` and `Retry-After` / `X-RateLimit-*` headers.
`APIOME_RATE_LIMIT_ENABLED=false` turns this limit off along with the others. The limiter runs in
process, so each replica counts separately.

## Errors

Refusals come back as `{"detail": {"code", "message"}}`:

| Status | Code |
|---|---|
| 400 | `comment-invalid-anchor` (missing or malformed `anchor_id`, or a version anchor naming another version), `comment-empty-body` |
| 403 | `comment-forbidden` (not the author, opener, or an admin); plain 403 without `projects:view` |
| 404 | `comment-project-not-found`, `comment-version-not-found`, `comment-anchor-not-found`, `comment-thread-not-found`, `comment-not-found` |
| 422 | Request validation (unknown `anchor_type`, a body over 20,000 characters, unknown fields such as `mentions`) |
| 429 | `comment-rate-limited` |

Threads are always read through the project in the URL. A thread id from a different project, or a
different tenant, returns `404`.
