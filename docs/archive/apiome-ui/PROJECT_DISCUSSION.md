# Project Discussion panel (COL-1.3)

Every comment thread of a project in one list, so "what is still open on this project?" has an
answer without opening each element in Studio. Built on the COL-1.1 comment API
(`apiome-rest/docs/comments.md`) for [apiome#4515](https://github.com/apiome/apiome/issues/4515).

## Where it is

**Versions** (`/ade/dashboard/versions?projectId=…`) → **Discussion** tab. The tab's count is the
project's unresolved (`open`) threads. It is hidden when there are none.

## What you see

- **Filters** in the toolbar. Each filter re-reads the list from apiome-rest:
  - **Status**: Open (default), Resolved, Orphaned, All. Each chip shows its total under the other
    filters.
  - **Mentions me**: only threads where a comment mentions you.
  - **Element type**: All elements, Classes, Properties, Paths, Operations, Versions.
- **One row per thread**, newest activity first:
  - the element name, its kind, the thread status and the version;
  - the opening comment, its author, the last activity and the reply count;
  - **N unresolved on this element**, which is the number the element's badge shows in Studio.
- **Load more** reads the next 50 threads.

Element names use the same spelling as an orphaned thread's stored label: `Customer`,
`Customer.email`, `/customers/{id}`, `GET /customers/{id}`.

## Opening a thread in Studio

The element name links to the Studio workspace with the COL-1.2 deep link:

```
<studio>/workspace?projectId=…&versionId=…&lens=schemas|paths&sel=…&comment=<type>:<id>&thread=<id>
```

This selects the element, puts it on the canvas and opens its thread popover with the thread
expanded. An **orphaned** thread's element no longer exists, so its link opens the version
(`?projectId&versionId`), where Studio lists orphaned threads for relinking (COL-1.4).

The Studio route comes from `getStudioWorkspaceRoute()` (`lib/external-links.ts`). It is
`NEXT_PUBLIC_STUDIO_URL` + `/workspace`, or `/workspace` on the studio surface. Without a
configured suite, rows are drawn without links.

## How the counts agree with Studio

Studio's badge rule (`designer/src/lib/comments/comment-thread-model.ts`) is: a thread counts while
its `status` is `open`, grouped by `anchor_type` + `anchor_id`. `unresolvedCommentCounts` in
`lib/comment-discussion.ts` is a copy of that rule. The summary route applies it to the project's
open threads as apiome-rest returns them, so each row count equals the badge. The tab count is
apiome-rest's own `status=open` total.

## Code map (`apiome-ui`)

| Piece | File |
|---|---|
| Rules: filters, whitelist, counts, labels, deep link | `lib/comment-discussion.ts` |
| Element names for thread anchors (tenant- and project-scoped SQL) | `lib/db/comment-anchor-labels.ts` |
| List route (REST proxy + anchor context) | `src/app/api/projects/[projectId]/comment-threads/route.ts` |
| Summary route (status totals, per-element counts) | `src/app/api/projects/[projectId]/comment-threads/summary/route.ts` |
| Shared auth and REST paging | `src/app/api/projects/[projectId]/comment-threads/comment-threads-proxy.ts` |
| Panel and tab count hook | `src/app/components/ade/discussion/*` |
| Tab | `src/app/ade/dashboard/versions/page.tsx` |
| Styles | `.disc-*` in `src/app/globals.css` |

Tests: `tests/comment-discussion-model.test.ts`, `tests/comment-anchor-labels.test.ts`,
`tests/api/project-comment-threads-route.test.ts`, `tests/project-discussion-panel.test.tsx`,
`tests/discussion-css.test.ts`, and the Discussion case in `tests/versions-hive-redesign.test.tsx`.
Browser checks (layout, axe) are in `e2e/project-discussion.spec.ts`. Regenerate its fixture with
`DISCUSSION_FIXTURE_DUMP=1 npx jest -c jest.config.ts tests/project-discussion-panel.test.tsx -t fixtures`.

## Permissions and limits

- apiome-rest decides access. Every read needs `projects:view` on the project, and the tenant comes
  from the session.
- The browser can only send `status`, `anchor_type`, `mentions_me`, `limit` and `offset`. Anything
  else is dropped before the request reaches apiome-rest.
- Element names are looked up only for threads apiome-rest returned. The lookup is bound to your
  tenant and the project in the URL. If it fails, rows fall back to `<Kind> <id>` and link without
  a selection. The list still loads.
- Per-element counts read up to 2,000 open threads (ten pages of 200). Past that, the panel says
  the counts are capped. The tab and chip totals stay exact.
- The panel is read-only. Reply, resolve and relink in Studio.
