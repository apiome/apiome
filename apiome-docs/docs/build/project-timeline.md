---
title: "Project activity timeline"
description: "Who published, merged, tagged or changed protection, linked to each revision."
sidebar_position: 1.45
tags: [versions, branches, merge, tags, audit, api]
---

A project's **activity timeline** lists what happened to its versions, newest first: who published
a revision, merged a branch, created or moved a tag, or changed a protection policy. Each event that
concerns a revision carries that revision's id, the same id the
[revision history](./revision-history.md) queries use, so you can go from an event to its place in
the history graph and back.

```text
project timeline:
  [t1] actor=X action=version.publish  revision=R2 mergeFrom=R1 (feature)
  [t2] actor=Y action=branch.protection_policy  branch=main (default branch)
```

## What is recorded

| Kind | Actions | Revision on the event |
| --- | --- | --- |
| `publish` | `version.publish` | The published revision; for a merge revision, `mergeFromRevisionId` is the revision merged in |
| `merge` | `version.merge`, `version.rollback` | The new merge or rollback revision; a merge also names the source branch and its tip |
| `tag` | `tag.create`, `tag.update`, `tag.delete` | The revision the tag points at (before deletion for a delete); a move also records `fromRevisionId` |
| `protection` | `branch.protection_policy`, `tag.protection_policy`, `version.revision_lock`, admin overrides and denied attempts, publish and compatibility-gate overrides, default-branch promotion | The locked revision or the tagged revision; none for a branch policy, which names the branch and whether it is the default branch |
| `other` | Everything else in the workflow ledger: push, pull, publish-gate assessments, changelog and change-report runs | When the action concerns one |

Events are written when the action succeeds. Failed merges and denied attempts on protected tags,
branches and locked revisions are recorded as well, with outcome `failure` or `denied`.

## Who sees what

- The timeline belongs to one project in one workspace. Events from other projects and other
  workspaces never appear.
- Reading it needs the **versions: view** permission.
- **Workspace administrators** see every event. Everyone else sees only actions that happened
  (outcome `success`, `allowed` or `policy_change`); failed and denied attempts are left out, and the
  response says `"restricted": true`.

## With the API

```http
GET /v1/versions/{tenant}/{project}/timeline?kind=publish,merge&revisionId=…&actorId=…&since=…&until=…&limit=50&cursor=…
```

| Parameter | Meaning |
| --- | --- |
| `kind` | `publish`, `merge`, `tag`, `protection` or `other`; repeat it or separate kinds with commas |
| `revisionId` | Only events that concern this revision |
| `actorId` | Only events by this user |
| `since`, `until` | Inclusive time bounds (ISO 8601) |
| `limit` | Events per page: 50 by default, at most 200 |
| `cursor` | The `nextCursor` of the previous page |

Each event has `id`, `kind`, `action`, `outcome`, `actorId`, `occurredAt`, `revisionId`,
`versionLabel`, `mergeFromRevisionId`, `mergeFromBranch`, `branchName`, `tagName`, the ledger's
`detail` and, when it concerns a revision, `links`:

| Link | Opens |
| --- | --- |
| `links.revision` | The revision itself |
| `links.ancestors` | Its ancestors in the [revision history](./revision-history.md#ancestors) graph |
| `links.timeline` | This timeline narrowed to the revision (`?revisionId=`) |

To go the other way, from a revision in the history graph to what happened to it, ask for the
timeline with `revisionId` set to that revision's `revisionId`. The full request and response shapes
are in the [REST reference](../reference/rest/versions.md).

| Error | Cause |
| --- | --- |
| `INVALID_KIND` (400) | `kind` names something other than the five kinds |
| 400 | `revisionId` or `actorId` is not a UUID, a time bound is not ISO 8601, or the cursor is invalid |
| 404 | The project does not exist in this workspace |

## Where the events are stored

The timeline reads two append-only ledgers as one stream:

| Ledger | Holds |
| --- | --- |
| `workflow_audit` | Publish, merge, rollback, push, pull, tag changes and gate decisions |
| `version_protection_audit` | Protection policy changes, admin overrides and denied attempts |

The workspace-wide workflow ledger also has its own list,
`GET /v1/versions/{tenant}/workflow-audit`.

## Retention

Timeline events are kept until the workspace is deleted; nothing prunes them today. A retention
policy, such as one set for compliance, hooks in at these points:

- **Pruning.** Both ledgers are indexed on workspace and time (`tenant_id, created_at`), so a
  retention job deletes one workspace's rows older than its cutoff from **both** ledgers with one
  bounded statement each. Delete from both at once, or the timeline shows protection events without
  the publishes and merges around them.
- **Export before pruning.** Read the rows you must keep elsewhere first: the timeline (`since` /
  `until`, page by `cursor`) or the workflow-audit list.
- **Deleted revisions and tags.** Events outlive the revision or tag they mention: the ids stay, and
  a deleted revision keeps its `versionLabel`.
- **Deleted users.** A user's events stay, with `actorId` cleared.
- **Deleted workspace.** Every event of the workspace is deleted with it.

## Related

- [Revision history and merge base](./revision-history.md): ancestors and merge-base queries.
- [Version dialogs](./version-dialogs.mdx#git-like-features): branches, tags, merges and protection.
- [Reviews](../govern/reviews.mdx): publish gates and force-publish reasons, which appear here as
  `protection` events.
