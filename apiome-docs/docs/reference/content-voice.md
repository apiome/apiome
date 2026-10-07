---
title: "Content and voice"
description: "How empty, loading, error and gated states read, and the per-route checklist."
sidebar_position: 9
tags: [content]
---

How every empty, loading, error and gated state in `apiome-ui` reads, and how that is kept
true. The rule comes from [`DESIGN.md` §10](https://github.com/apiome/apiome/blob/main/docs/mockups/DESIGN.md#10-content--voice) (and the
voice line in §2); HIVE-10.4 ([#5340](https://github.com/apiome/apiome/issues/5340)) brought
every route into line with it.

## The rules

| Thing | Rule | Yes | No |
| --- | --- | --- | --- |
| Page title | A noun | "Users", "SDK settings" | "User Management", "Configure SDKs" |
| Button | A verb | "New feature flag", "Close" | "OK", "Submit" |
| Description | What it is for, in **≤ 14 words** | "Create a key to reach this tenant's data over the REST API." | Two sentences of background |
| Empty state | The situation, then the way out | "No matching records. Try a different search, or view all records." | "No records found." |
| Error | What happened **and** what to do | "Could not load branches — try again." | "Could not load branches" |
| Loading | Name the thing, in the content's shape | Skeleton + "Loading records…" | A bare "Loading…" |

## The four surfaces

Use the shared components from `src/app/components/ui`. They already draw the honeycomb art
and handle the live regions, so a screen only has to supply the words.

- **Empty**: `EmptyState` (`default`, `compact` or `inline`; add `dashed` when a filter
  emptied the list). Honey art for "nothing yet", `tone="neutral"` for "nothing matches".
- **Loading**: `LoadingState` with a `Skeleton*` preset shaped like the content, and a
  `message` that names it.
- **Error**: `ErrorState` when the failure replaces the content, `ErrorBanner` when the rest
  of the page still works. Pass `onRetry` whenever there is something to retry.
- **Gated**: `GatedState` when the page needs something first, such as a workspace or a
  linked account.

## What enforces it

**At runtime**, every shared error surface makes sure a failure names a next action
(`lib/copy-voice.ts`):

| Surface | Behaviour |
| --- | --- |
| `ErrorState`, `ErrorBanner` | With no retry or action, a string description gains "— try again." A missing description becomes "Reload the page, or try again in a moment." |
| `Alert` (`danger` / `error`) | A bare failure string with no `actions` gains "— try again." |
| `toast.error` (`components/ui/toast`) | A failure ("Failed to…", "Could not…", "…error", a 4xx/5xx code) gains "— try again." |
| `AlertDialog` (danger) and `useDialog` `perform` failures | Same as `toast.error`. |

A message that already names an action ("Could not sign out. Try again.") is left alone. So
is a message that states a rule ("System primitives cannot be edited", "That name is taken"),
because retrying cannot fix it. Rich (React node) messages are never rewritten.

**At test time**, `tests/copy-voice-gate.test.ts` parses every source under `src/` with the
TypeScript compiler and fails when:

- a literal `title` / `description` on `EmptyState`, `ErrorState`, `GatedState`,
  `ErrorBanner` or `PageHeader`, or a `*_EMPTY_TITLE` / `*_EMPTY_DESC` constant, breaks the
  rules above (over 14 words, "No … found", "Manage …", "… Management");
- any JSX text is "No records found"-class copy;
- an admin navigation title is not a noun;
- a component imports `toast` from `sonner` instead of `components/ui/toast`.

The runtime behaviour is pinned in `tests/copy-voice-surfaces.test.tsx`.

## Route checklist

Every route was reviewed in HIVE-10.4. Each state column shows which shared surface
covers that state on the route (✓), or why the state doesn't apply.

- **n/a**: the route draws no data (a redirect or a static gallery).
- **—**: the route has no such state. For example, the page needs no workspace, or it has no
  list that can be empty.
- **✓¹**: no dedicated error component. Failures reach the reader through the voiced
  `toast.error` or a danger `Alert`.

The ✓ marks come from the shared components each route imports (directly or through its
own feature components). The notes record what HIVE-10.4 changed there.

| Route | Empty | Loading | Error | Gated | Notes |
| --- | :-: | :-: | :-: | :-: | --- |
| `/ade/dashboard/api-keys` | ✓ | ✓ | ✓ | ✓ |  |
| `/ade/dashboard/audit` | ✓ | ✓ | ✓¹ | — | Load failure shown in a danger `Alert`, now voiced. Empty description shortened. |
| `/ade/dashboard/catalog/[id]` | ✓ | ✓ | ✓ | — | Missing item: "Catalog item unavailable" + Back to Catalog / Try again. |
| `/ade/dashboard/catalog` | ✓ | ✓ | ✓ | ✓ |  |
| `/ade/dashboard/export/studio` | ✓ | ✓ | ✓ | — |  |
| `/ade/dashboard/help` | n/a | n/a | n/a | ✓ | Static guide index; no fetch to fail. |
| `/ade/dashboard/linked-accounts` | ✓ | ✓ | ✓¹ | — | Danger `Alert` voiced; PAT error copy no longer "No linked account found". |
| `/ade/dashboard/lint-workspace` | ✓ | ✓ | ✓ | ✓ | Queue empty shortened. |
| `/ade/dashboard/mcp/[endpointId]` | ✓ | ✓ | ✓ | — | Seven MCP panel empties shortened; snapshot empty rewritten. |
| `/ade/dashboard/mcp/agents` | ✓ | ✓ | ✓ | ✓ | Toolsets and usage empties shortened. |
| `/ade/dashboard/mcp/analytics` | ✓ | ✓ | ✓ | ✓ | Catalog-insight empty shortened. |
| `/ade/dashboard/mcp/capabilities` | ✓ | ✓ | ✓ | ✓ | "No capabilities found" → "No capabilities match". |
| `/ade/dashboard/mcp/compare` | ✓ | ✓ | ✓ | ✓ | Compare empty shortened. |
| `/ade/dashboard/mcp` | ✓ | ✓ | ✓ | ✓ |  |
| `/ade/dashboard/members` | ✓ | ✓ | ✓ | — | Invite empty shortened. |
| `/ade/dashboard/notifications` | — | — | ✓¹ | ✓ | Load failure: `Alert` with a Try again action. |
| `/ade/dashboard` | ✓ | ✓ | ✓¹ | — | Home. "Continue working" empty state shortened to ≤ 14 words. |
| `/ade/dashboard/primitives/[id]` | ✓ | ✓ | ✓ | — |  |
| `/ade/dashboard/primitives` | ✓ | ✓ | ✓ | ✓ | "No Primitives Found" → "No matching primitives". |
| `/ade/dashboard/profile` | ✓ | ✓ | ✓¹ | — | Save failures raise voiced toasts; 2FA errors name the fix ("Enter your current password…"). |
| `/ade/dashboard/projects/[projectId]/consumers` | ✓ | ✓ | ✓ | — |  |
| `/ade/dashboard/projects` | ✓ | ✓ | ✓ | ✓ |  |
| `/ade/dashboard/published` | ✓ | ✓ | ✓ | ✓ |  |
| `/ade/dashboard/repositories/[id]` | — | — | ✓¹ | ✓ | Server shell; the detail client is covered under `/repositories`. |
| `/ade/dashboard/repositories/[id]/preview` | ✓ | ✓ | ✓ | ✓ |  |
| `/ade/dashboard/repositories/catalog` | ✓ | ✓ | ✓ | ✓ |  |
| `/ade/dashboard/repositories/new` | ✓ | ✓ | ✓ | ✓ |  |
| `/ade/dashboard/repositories` | ✓ | ✓ | ✓ | ✓ | Empty description shortened (24 → 11 words). |
| `/ade/dashboard/repositories/telemetry` | ✓ | ✓ | ✓ | ✓ |  |
| `/ade/dashboard/repositories/webhook-ip-allowlist` | ✓ | ✓ | ✓ | ✓ |  |
| `/ade/dashboard/roles` | ✓ | ✓ | ✓¹ | — | Danger `Alert` voiced; both empty descriptions shortened. |
| `/ade/dashboard/sdk-settings` | — | ✓ | ✓¹ | — | Danger `Alert` voiced. Title is a noun ("SDK settings"). |
| `/ade/dashboard/style-guides/[guideId]` | ✓ | ✓ | ✓¹ | — | Catalog errors in danger `Alert`, voiced. Rule-filter empty shortened. |
| `/ade/dashboard/style-guides` | ✓ | ✓ | ✓ | — | Empty description shortened. |
| `/ade/dashboard/tenants` | ✓ | ✓ | ✓ | ✓ | "Not a member" empty description shortened. |
| `/ade/dashboard/versions` | ✓ | ✓ | ✓ | ✓ | First-version empty description shortened. |
| `/ade/dashboard/versions/sunset-timeline` | ✓ | ✓ | ✓ | ✓ |  |
| `/ade/database` | ✓ | ✓ | ✓¹ | — | "No records found" → inline `EmptyState`; bare "Loading…" → `LoadingState`. |
| `/ade/migration` | ✓ | ✓ | ✓¹ | — | "No records found" / "No records." → inline `EmptyState`; skeleton loading. |
| `/ade` | — | — | ✓¹ | — | Launcher; data resolved on the server. Signed-out renders the brand hero. |
| `/ade/reviews/[id]` | ✓ | ✓ | ✓ | ✓ | "Nothing published" compare empty shortened. |
| `/ade/studio/code` | n/a | n/a | n/a | ✓ | Redirect only. |
| `/ade/studio/editor` | n/a | n/a | n/a | ✓ | Redirect only. |
| `/ade/studio` | n/a | n/a | n/a | ✓ | Redirect only. |
| `/ade/studio/paths` | n/a | n/a | n/a | ✓ | Redirect only. |
| `/admin/dashboard/feature-flags` | ✓ | ✓ | ✓¹ | — | Shares the licenses client: flag empty is an `EmptyState` with "New feature flag". |
| `/admin/dashboard/licenses` | ✓ | ✓ | ✓¹ | — | Title "License Management" → "Licenses"; three empties and four loaders converted. |
| `/admin/dashboard` | — | — | ✓¹ | — | Overview. Card titles are nouns ("Users", "Payments", "System settings"). |
| `/admin/dashboard/settings` | — | — | ✓¹ | — | Title "System Configuration" → "System settings". |
| `/admin/dashboard/templates` | ✓ | ✓ | ✓¹ | — | "No templates found" → dashed "No matching templates". |
| `/admin/dashboard/tenants` | ✓ | ✓ | ✓¹ | — | Title → "Tenants"; three empties and the loader converted. |
| `/admin/dashboard/users` | ✓ | — | ✓¹ | ✓ | Title → "Users"; "No users found" / "No pending signups" → `EmptyState`. |
| `/admin` | — | — | ✓¹ | ✓ | Admin sign-in form; its fallback error already says "try again". |
| `/design-system/command-palette` | n/a | n/a | n/a | n/a | Static gallery. |
| `/design-system` | ✓ | ✓ | ✓ | ✓ | The design system route; draws the whole feedback set. |
| `/design-system/hive` | n/a | n/a | n/a | n/a | Redirects to `/design-system`. |
| `/design-system/mcp` | ✓ | ✓ | ✓ | ✓ | Gallery of MCP primitives. |
| `/design-system/page-header` | n/a | n/a | n/a | n/a | Static gallery. |
| `/design-system/shortcuts` | n/a | n/a | n/a | n/a | Static gallery. |
| `/login/2fa` | — | — | ✓ | — | Shares `auth-error-copy` with sign-in. |
| `/login` | — | — | ✓ | ✓ | Auth errors come from `auth-error-copy` (mapped codes, each with a way forward). |
| `/` | n/a | n/a | n/a | ✓ | Redirects to the launcher or sign-in; no content of its own. |
| `/signup/oauth` | — | — | ✓ | ✓ | OAuth errors in danger `Alert`, voiced. |
