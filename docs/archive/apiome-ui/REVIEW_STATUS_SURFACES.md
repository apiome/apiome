# Review status surfaces (COL-2.4)

The pill that says a revision is in review, on the screens people already work on — so an approval
never stalls because nobody knew it was waiting, and the COL-2.3 publish gate is never the first
thing a publisher hears about a review.

Reviews themselves are COL-2.1 (`apiome-rest/docs/reviews.md`); the page every pill links to is
COL-2.2 (`REVIEW_PAGE.md`).

## The pill

Three states, spelled exactly as `reviews.state` stores them, so the tone comes from the shared
status vocabulary rather than from any screen:

| State | Pill | Tone |
|---|---|---|
| `in_review` | In review | warn (amber) — the same tone as the `review` lifecycle word |
| `approved` | Approved | ok (green) |
| `changes_requested` | Changes requested | danger (red) — it is what the publish gate blocks on |

A **withdrawn** review is never a pill: withdrawing is how you say there is nothing to look at. A
revision with **no** open review is a draft and already says so with its lifecycle badge, so no
second pill is drawn.

Every pill is a link to `/ade/reviews/{id}`. Its accessible name names the revision as well as the
state (`v1.2.0 — in review · open the review`), because "In review" on a project card does not say
*what* is in review — and because colour is never the only signal.

## Where it appears

- **Version rows** — `/ade/dashboard/versions`, in the Status cell, beside the lifecycle badge.
  Draft and In review are two different facts about a row, and someone about to publish needs both.
- **Project cards and the projects table** — `/ade/dashboard/projects`, in the same Status place in
  both views. A project may have several open reviews and there is room for one pill, so the **most
  urgent** speaks for the rest — changes requested, then in review, then approved, ties broken by
  the most recent activity — and a `+N` chip says how many are behind it. The pill links to the
  review it names.
- **The publish dialog** — a fourth card above the three publish gates: the state, the round, the
  round's tally, and a link to the review. It reports the *review*, not the policy: how many
  approvals this workspace requires is a style-guide setting apiome-rest resolves at publish time,
  so the panel says what an armed policy would make of the review and never promises a verdict. It
  blocks nothing — the dialog's four blockers are unchanged.
- **Home → Needs attention** — `/ade/dashboard`, as a fourth source beside sunsets, lint gates and
  key expiry. Only two situations are rows, because only they are *tasks*:
  - a review is waiting on **your** decision in its current round (amber);
  - a review **you requested** came back with changes requested (red).

## Where the data comes from

`GET /api/reviews/status`, optionally `?projectId=`, answering `{success, reviews}`.

apiome-rest addresses reviews per project, so a projects list with fifty cards would cost fifty
upstream calls to draw at most fifty pills. The route is one tenant-bound statement instead
(`lib/db/review-status.ts`) — the same seam `/api/database/versions/has-class-schema` uses:

- the tenant comes from the **session**, never from the caller, and is asserted on the review *and*
  its project;
- deleted projects, deleted revisions and withdrawn reviews are excluded;
- the tally counts the **current round only** — the round COL-2.3's gate counts, since an earlier
  round's approvals are history;
- the row count is capped in SQL (`OPEN_REVIEW_LIMIT`);
- a `projectId` that is not a UUID is a 400, so a typo cannot abort the statement as a 500.

Home does **not** use this route: it is server-rendered and runs its own section query in
`lib/db/dashboard-home.ts`, which is also the only read that needs to know who the reader is.

## Staying fresh

The ticket asks for states that update after decisions without stale caches, and a decision is
recorded on another page — usually in another tab. So `useOpenReviews`:

- fetches with `cache: 'no-store'`;
- refetches when the tab becomes **visible** again, which is what a reviewer coming back from the
  review page does;
- refetches when its inputs change, and when a screen asks it to — the Versions screen does after a
  publish.

A failed read draws no pill and no error. A pill is an aid, not the page.

## Code map

- `lib/review-status.ts` — the framework-free rules: the wire row, the labels, `reviewPageHref`,
  `indexReviewsByVersion`, `summarizeProjectReviews`, `reviewPillTitle`, and the parsers that drop a
  row rather than draw a pill linking to `/ade/reviews/undefined`.
- `lib/db/review-status.ts` — the tenant-bound read.
- `src/app/api/reviews/status/route.ts` — the BFF route.
- `src/app/hooks/useOpenReviews.ts` — the shared client read.
- `src/app/components/ade/reviews/ReviewStatusPill.tsx` — the pill.
  It stops click and Enter from propagating, because on the projects table it sits in a `DataTable`
  row whose own activation opens the project's revisions.
- `src/app/components/ade/reviews/ReviewStatusPanel.tsx` — the publish dialog's card.
- `src/app/components/ui/statusVocabulary.ts` — the three states' tones.
- `lib/db/dashboard-home{,-model}.ts` — Home's own query and `reviewAttention`.
- Styles are the `REVIEW STATUS SURFACES (COL-2.4)` section of `globals.css` (`.rvs-*`).

## Not in this ticket

**Nothing in the UI requests a review yet.** COL-2.1 built the API and COL-2.2 the page, but there
is no "Request review" affordance and no roadmap ticket for one, so until a review is requested
through apiome-rest these pills have nothing to draw. That gap is flagged rather than filled here.

Publishing also still does not close a version's open review (left open by COL-2.3), so a published
revision can keep an open review — and the pill reports it, because that is what is true.

## Tests

- `tests/review-status-model.test.ts` — the rules.
- `tests/review-status-read.test.ts` — the statement and its coercions.
- `tests/api/review-status-route.test.ts` — the BFF route's refusals and scope.
- `tests/review-status-surfaces.test.tsx` — the four surfaces, the freshness rules, and axe.
- `tests/review-status-css.test.ts` — the stylesheet section.
- `tests/dashboard-home-model.test.ts` — `reviewAttention`.
