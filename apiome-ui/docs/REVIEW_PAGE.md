# Review page (COL-2.2)

One page where a reviewer decides whether a draft version is ready to publish. It shows what changed,
the spec, and the discussion, so the reviewer never has to leave to make the decision.

## Where it is

`/ade/reviews/{reviewId}`, optionally with `?tab=changes|spec|discussion`.

The route renders inside the app shell (`src/app/ade/reviews/layout.tsx`). The page is
`src/app/components/ade/reviews/ReviewPageClient.tsx`. Reviews are created through apiome-rest
(COL-2.1, `apiome-rest/docs/reviews.md`); this page reads and decides them.

## What you see

- **Header**
  - The breadcrumb (Projects › project › Review) and the title, "Review of v2.0.0".
  - The review's state: In review, Approved, Changes requested, or Withdrawn.
  - Who requested it, the round, and the round's tally ("1 of 2 approved · 1 pending").
- **Changes** (the default tab) compares the version with the project's **newest published version**.
  - **Classified** (default): the live CTG classification (`POST /v1/diff/{tenant}/classified`).
    Breaking changes come first, grouped by path or component the way a stored changelog is.
  - **Plain diff**: the two OpenAPI documents side by side. It is also shown, with a notice, whenever
    the classified diff is unavailable.
  - With nothing published, the tab says this would be the first publication.
- **Spec**: the version's OpenAPI document, read-only, as JSON or YAML, with Copy.
- **Discussion**: the Discussion panel (COL-1.3), narrowed to this version's threads, open ones first.
- **Reviewers** (beside the tabs): each reviewer's decision and note in the current round, then
  every earlier round exactly as it was recorded.
- **Decision bar** (sticky at the foot): **Request changes** and **Approve**, with a note.
  - The note is optional with Approve and **required** with Request changes.
  - The bar only offers the buttons to a pending reviewer of a round that can still take decisions.
    Otherwise it says why there is nothing to decide: already decided, a change request decided the
    round, the spec changed, not a reviewer, or withdrawn.

## Loading

Every tab loads lazily. A pane mounts the first time its tab is shown and stays mounted, so
switching back never reloads it. The plain diff builds its two documents only when it is first
shown.

## BFF routes

All routes live under `src/app/api/reviews/[reviewId]/` and share `review-proxy.ts`.

| Route | Does |
|---|---|
| `GET /api/reviews/{id}` | The review, its project (name, slug) and the viewer's user id |
| `POST /api/reviews/{id}/decision` | `{decision: "approve" \| "request_changes", note?}` → the review after the decision |
| `GET /api/reviews/{id}/changes` | Head, baseline, classified changes, or `initialPublication` / `classifiedError` |
| `GET /api/reviews/{id}/spec?side=head\|base` | The version's (or the baseline's) OpenAPI document as JSON text |

Each route takes the tenant from the session, never from the browser.

- **Finding the project.** The URL has no project in it, so the route looks up the review's project
  with one query bound to the caller's tenant (`lib/db/review-project.ts`). A review from another
  tenant is a 404.
- **Access checks.** Each route then reads the review from apiome-rest, which checks
  `projects:view`. Changes and Spec also list the project's versions, which checks `versions:view`.
  Nothing is built before those reads succeed.
- **Documents.** They are built the same way as the Versions screen's spec viewer
  (`buildOpenApiSpecJsonForVersion`), and only for revisions apiome-rest listed.
- **Refusals.** apiome-rest refusals keep their status and their `review-*` code. The page turns the
  code into a sentence (`REVIEW_ERROR_MESSAGES`) and re-reads the review when the refusal means it
  has moved on.

The note rule is enforced twice: by the bar, and again by the decision route.

## Code map

- `lib/review-page.ts` holds the framework-free rules:
  - wire types, tabs, and the header badge and tally;
  - `decisionBarModel`, `validateDecisionNote`, and refusal messages;
  - `pathGroupForPointer` (mirrors apiome-rest's `changelog_generator.path_group_for_pointer`);
  - `groupReviewChanges` and `newestPublishedRevision`.
- `ReviewChangesPanel`, `ReviewSpecPanel`, `ReviewReviewers` and `ReviewDecisionBar` are the four panes.
- `src/app/components/ade/versions/specRendering.ts` holds the JSON/YAML rendering shared with the
  Versions spec viewer.
- `ProjectDiscussionPanel` gained an optional `versionId`. The comment-thread BFF forwards `version`
  only as a revision id.
- Styles are the `REVIEW PAGE (COL-2.2)` section of `globals.css` (`.rvw-*`).

## Tests

- `tests/review-page-model.test.ts` covers the rules.
- `tests/review-project-lookup.test.ts` covers the tenant-bound lookup.
- `tests/api/review-routes.test.ts` covers the BFF routes.
- `tests/review-page.test.tsx` covers the page in jsdom: header, lazy tabs, both decisions, refusals,
  and read-only bar states.
- `tests/review-page-css.test.ts` covers the stylesheet section.
- `e2e/journey/review-page.spec.ts` is the live-stack journey, run with `yarn test:e2e:journey`.
  - A reviewer approves one review and requests changes on another, entirely on the page.
  - It checks that no document is built until asked for.
  - It seeds its own tenant, users, project and versions (`e2e/journey/support/review-fixture.ts`)
    and requests both reviews through apiome-rest as the requester, so each round carries the spec
    fingerprint apiome-rest computes.
