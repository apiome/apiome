# Portal consumer feedback (COL-4.4, #4528)

A signed-in Browse **reader** (PCX-1.1, see `portal_auth.md`) can give feedback on a published spec. Feedback is
an ordinary COL-1.1 comment thread with `origin = 'consumer'` (apiome-db V379), so the owning team sees it in the
Discussion panel, tagged `consumer`, and answers and resolves it with the tools it already uses.

## Reader routes (tag `portal-feedback`)

Base: `/v1/portal/{tenant}/feedback/{project}/{version}/threads`. Every route needs a live reader session for
`{tenant}` (`Authorization: Reader <token>`), else `401 portal-session-invalid`.

| Route | Does |
|---|---|
| `GET …/threads` | The reader's **own** threads on the version, with every message (`from_team` marks team replies). |
| `POST …/threads` | Open a thread: `{"target": "version", "body"}` or `{"target": "operation", "method", "path", "body"}`. |
| `POST …/threads/{id}/comments` | Reply in the reader's own thread. |
| `POST …/threads/{id}/resolve`, `…/reopen` | The same status change the team makes. |

Refusals: `404 feedback-version-not-found` (unknown, unpublished or private version — the same answer for all),
`404 feedback-operation-not-found`, `404 feedback-thread-not-found` (unknown, internal, or another reader's thread —
never `403`, so ids cannot be probed), `400 comment-empty-body`, `409 comment-thread-orphaned`,
`429 comment-rate-limited` (shared per-user comment budget).

## Rules

- **Readers see only their own threads.** One customer's feedback never reaches another.
- **Nothing internal leaks.** Responses carry no user ids, no `mentions`, no tenant/project ids; an `orphaned`
  thread reads as `open` with no operation.
- **No mentions from readers.** Reader messages are stored with empty `mentions` and no notifier.
- **Anchors.** The version, or one operation resolved by method + path (`version_path.pathname`,
  `path_operation.operation`) to the COL-1.1 `operation` anchor.
- **No workspace notifications to readers.** `thread_resolved_notifier` excludes a consumer thread's opener;
  team members who took part are still notified when the reader resolves.

## Team side

`GET /v1/tenants/{tenant}/projects/{project}/comment-threads?origin=consumer|internal` filters; every thread
carries `origin`. Replying, resolving and reopening use the existing routes unchanged.

Code: `app/consumer_feedback.py` (models, codes), `app/consumer_feedback_store.py`, `app/consumer_feedback_routes.py`.
