---
title: "Revision history and merge base"
description: "How revisions link to their parents, and the ancestors and merge-base queries."
sidebar_position: 1.4
tags: [versions, branches, merge, api]
---

Every version of a project is a **revision** in a history graph. A revision can have up to two
parents, which is what makes the history a graph rather than a list. Apiome answers two questions
about that graph: which revisions came before a given one (its **ancestors**), and where two lines
of history last met (their **merge base**). The branch, merge and history-graph tools in
[Version dialogs](./version-dialogs.mdx#git-like-features) are built on these.

## How revisions link

| A revision… | Parents | Example |
| --- | --- | --- |
| created on its own | none — it is a **root** | The first version of a project, a version created from **New version**, an import |
| that continues a line of history | one, the **first parent** | A repository refresh, a revision on a branch |
| that merges two branches | two: the first parent and the **merge parent** | The result of **Merge branches…** |
| forked from another project | none in this project | A fork records where it came from separately, and starts a new root |

A revision with no parent is a root on purpose, not missing data. Versions created before branch and
merge support existed, and versions created on their own today, are roots: the history graph shows
them unconnected, and two of them have no merge base.

## Ancestors

The ancestors of a revision are every revision reachable by following parents, both parents of a
merge included. Each one comes with its **distance**: the fewest parent steps from the revision you
started at (that revision itself is 0).

A **history window** is the same walk from several starting revisions at once, such as every branch
tip, cut off after a number of steps. It is what the history graph draws: one request returns every
revision in the window with both of its parent ids, so the graph never asks for revisions one by one.

## Merge base

The merge base of two revisions is their best common ancestor: a revision both histories contain
that is not an ancestor of another such revision. It is where the two lines of history split, and it
is the "base" side of a three-way merge.

- When one revision is an ancestor of the other, the merge base is the older one.
- When the histories share no revision — two separate roots — there is **no merge base**, and a merge
  between them cannot be previewed.
- When two branches have merged into each other (a criss-cross history), there can be more than one
  best common ancestor. All of them are listed, and the most recently created one is the merge base.

## With the API

| Request | Returns |
| --- | --- |
| `GET /v1/versions/{tenant}/{project}/{revision}/ancestors?depth=50&limit=500` | The revision and its ancestors within `depth` parent steps |
| `GET /v1/versions/{tenant}/{project}/revision-graph/history?tip=…&tip=…&depth=50&limit=500` | A history window from the named tips — every branch tip when `tip` is left out |
| `GET /v1/versions/{tenant}/{project}/revision-graph/merge-base?a=…&b=…` | The merge base of two revisions, every candidate, and whether the histories are disjoint |

Each revision in a window has `revisionId`, `versionLabel`, `parentRevisionId`,
`mergeParentRevisionId`, `createdAt` and `distance`. Revisions are ordered nearest the tips first,
then newest first. The full request and response shapes are in the
[REST reference](../reference/rest/versions.md).

### Limits

| Setting | Default | Maximum |
| --- | --- | --- |
| `depth` — parent steps from the tips | 50 | 1,000 |
| `limit` — revisions returned | 500 | 5,000 |
| `tip` — starting revisions per request | every branch tip | 50 |

When the depth or the limit cuts the history short, the response says `"truncated": true`; ask again
from the oldest revisions you received to page further back. Every request reads the history in a
single database query, however many revisions it covers.

| Error code | Cause |
| --- | --- |
| `REVISION_NOT_FOUND` (404) | A named revision does not exist, or was deleted |
| `REVISION_PROJECT_MISMATCH` (400) | A named revision belongs to a different project |
| `TIPS_REQUIRED` (400) | No `tip` was given and the project has no branches |
| `TOO_MANY_TIPS` (400) | More than 50 tips |

## Related

- [Version dialogs](./version-dialogs.mdx#git-like-features): branch, merge and history-graph tools.
- [Versions](./versions.mdx): a project's timeline of versions.
- [Project activity timeline](./project-timeline.md): who published, merged, tagged or changed
  protection, linked to these revisions.
