# Copy and voice audit — every route's four states (HIVE-10.4)

**Ticket:** HIVE-10.4 ([#5340](https://github.com/apiome/apiome/issues/5340)).
**Authority:** `docs/mockups/DESIGN.md` §10 *Content & voice*.

## The rules

- **Titles are nouns** ("Projects", "No published versions"): sentence case, with no full stop or "!".
- **Buttons are verbs** ("New project", "Try again").
- **Descriptions** answer "what is this for?" or "what do I do next?" in **14 words or fewer**.
- **No "Manage …" or "Configure …" titles**, and no "… Management" or "… Configuration".
- **Errors say what happened and what to do.** Every `ErrorState` and `ErrorBanner` has a retry or an
  action. Every complete "Failed to … / Couldn't … / Unable to …" message names a next step.
- **No copy that says nothing:** no "No records found", "No data", "Something went wrong",
  "An error occurred" or "Unknown error".
- **Empty states use the honeycomb art** (`ui/EmptyState`). Loading copy names what is loading
  ("Loading projects…") and spells the ellipsis "…".

These rules are enforced by `tests/copy-voice.test.ts`. It reads every string in `src/` through
`tests/helpers/copy-scan.ts`. `tests/copy-audit-routes.test.ts` keeps this table in step with the
routes.

## How to read the table

Each state cell takes one of three forms:

- **✅** followed by the copy that state shows, and the mechanism when it isn't the shared primitive.
- **n/a —** followed by why the state cannot occur.
- **⚠️ follow-up —** for a behavioural gap the review found. These are a missing workspace gate, an
  error swallowed into an empty state, or a banner that dismisses itself. They are recorded here for a
  follow-up rather than fixed in this copy pass.

## Routes

| Route | Empty | Loading | Error | Gated | Notes |
|---|---|---|---|---|---|
| `/` | n/a — redirects to /login | n/a — redirects | n/a — redirects | n/a — redirects | redirect only |
| `/ade` | n/a — launcher, always has applications | n/a — server-rendered | n/a — a summary failure hides the chips | n/a — the launcher works without a workspace | launcher |
| `/ade/dashboard` | ✅ No projects yet · No recent activity | ✅ skeletons (aria-label: Workspace statistics, loading) | ⚠️ follow-up — a load failure is only logged; panels fall back to empty states | n/a — user-scoped stats; tenant-only actions hidden | Home |
| `/ade/dashboard/api-keys` | ✅ No API keys yet · No API keys match these filters | ✅ DataTable skeleton (sr: Loading API keys…) | ✅ DataTable: Couldn’t load this list + retry | ✅ Pick a workspace first — API keys belong to a workspace. | |
| `/ade/dashboard/audit` | ✅ No audit events for this filter · No audit events match these filters | ✅ DataTable skeleton (sr: Loading the access ledger…) | ✅ Alert: The audit log didn’t load. Refresh the page to try again. | ⚠️ follow-up — no gate; a no-workspace read shows as an error Alert | |
| `/ade/dashboard/catalog` | ✅ Your catalog is empty · No catalog items match your filters or search | ✅ skeleton (sr: Loading catalog…) | ✅ cards: The catalog could not be loaded · table: Couldn’t load this list | ✅ Pick a workspace first — The catalog is scoped to one workspace. | |
| `/ade/dashboard/catalog/[id]` | ✅ No quality score yet · No quality issues recorded | ✅ Loading catalog item… | ✅ Catalog item not found (404) · Catalog item didn’t load + retry | n/a — deep link from a workspace list; a no-workspace read lands in the error state | detail page |
| `/ade/dashboard/export/studio` | ✅ panel: Open the Export Studio from a source | ✅ Loading Export Studio… | ✅ Alert: the source or job error | n/a — scoped by the artifact in the URL; signed out says “Sign in to use the Export Studio.” | |
| `/ade/dashboard/help` | ✅ search: No guides match “…” | n/a — static page, no fetch | n/a — static page, no fetch | n/a — no workspace needed | |
| `/ade/dashboard/linked-accounts` | ✅ No linked accounts | ✅ Loading linked accounts… | ✅ Alert: Failed to load linked accounts. Refresh the page to try again. | n/a — user-scoped identities | |
| `/ade/dashboard/lint-workspace` | ✅ No lint findings in this workspace · No findings match the current filters | ✅ DataTable (sr: Loading the findings queue…) | ✅ DataTable: Couldn’t load this list + “Could not load the findings queue…” | ✅ Pick a workspace first — Lint posture belongs to one workspace. | trend/rank failures fall back to empties (follow-up) |
| `/ade/dashboard/mcp` | ✅ No MCP endpoints yet · No matches | ✅ skeleton (sr: Loading the MCP catalog…) | ✅ Couldn’t load the MCP catalog + retry | ✅ Pick a workspace first — The MCP catalog is scoped to one workspace. | |
| `/ade/dashboard/mcp/[endpointId]` | ✅ Not yet discovered · No capabilities | ✅ skeleton (sr: Loading endpoint…) | ✅ Endpoint unavailable; each insight panel: ErrorState + Try again | n/a — detail deep link | detail page |
| `/ade/dashboard/mcp/agents` | ✅ No agent keys yet · No agent calls in this period | ✅ Loading agent keys… · Loading usage… | ✅ Agent keys could not be loaded · Usage could not be loaded | ✅ Pick a workspace first — Agent access belongs to a workspace. | |
| `/ade/dashboard/mcp/analytics` | ✅ No servers in the catalog yet | ✅ Loading catalog analytics… | ✅ Catalog analytics unavailable | ✅ Pick a workspace first — Switch to a workspace to see… | |
| `/ade/dashboard/mcp/capabilities` | ✅ No capabilities found | ✅ DataTable (sr: Loading capabilities…) | ✅ Could not load the capability directory + retry | ✅ Pick a workspace first — Switch to a workspace to browse… | |
| `/ade/dashboard/mcp/compare` | ✅ No discovered MCP servers to compare yet | ✅ Loading the MCP catalog… | ✅ Could not load the MCP catalog · Comparison unavailable | ✅ Pick a workspace first — Switch to a workspace to compare… | |
| `/ade/dashboard/members` | ✅ No members yet · No members match these filters | ✅ DataTable (sr: Loading members…) | ✅ DataTable: Couldn’t load this list + “Failed to load members…” | ⚠️ follow-up — no gate; a no-workspace read lands in the table’s error state | |
| `/ade/dashboard/notifications` | ✅ Nothing yet · Nothing matches these filters · Every notification type is switched off | ✅ Reading your inbox… (role=status) | ✅ Alert: the read error / “Failed to read notifications…” | ⚠️ follow-up — with no workspace the inbox shows “Nothing yet” | |
| `/ade/dashboard/primitives` | ✅ No namespaces yet · No primitives match | ✅ DataTable (sr: Loading primitives…) | ⚠️ follow-up — a list failure is a toast only, then “No primitives match” | ✅ Pick a workspace first — The type registry belongs to one workspace. | |
| `/ade/dashboard/primitives/[id]` | ✅ No type in view references this one · No relative $ref values | ✅ Loading type detail… | ✅ This type could not be loaded + retry | n/a — detail deep link | |
| `/ade/dashboard/profile` | ✅ No linked accounts | ✅ Loading profile… | ⚠️ follow-up — a sign-in-methods read failure shows as “No linked accounts” | n/a — user-scoped | |
| `/ade/dashboard/projects` | ✅ No projects yet · No projects match your filters or search | ✅ skeleton (sr: Loading projects…) | ⚠️ follow-up — table: Couldn’t load this list; the card view shows “No projects yet” on failure | ✅ Pick a workspace first — Projects are scoped to one workspace. | |
| `/ade/dashboard/projects/[projectId]/consumers` | ✅ No consumers registered yet · No consumer matches | ✅ DataTable (sr: Loading consumers…) | ✅ Couldn’t load this project’s consumers + retry | n/a — project deep link | |
| `/ade/dashboard/published` | ✅ No published versions · No matching versions | ✅ DataTable (sr: Loading published versions…) | ✅ Couldn’t load published versions + retry | ✅ Pick a workspace first — Published versions belong to one workspace. | |
| `/ade/dashboard/repositories` | ✅ No repositories yet · No matches | ✅ skeleton (sr: Loading repositories…) | ✅ grid: Could not load repositories · table: Couldn’t load this list | ✅ Pick a workspace first — Repositories are registered against one workspace. | |
| `/ade/dashboard/repositories/[id]` | n/a — redirects to ./preview | n/a — redirects | n/a — redirects | n/a — redirects | redirect only |
| `/ade/dashboard/repositories/[id]/preview` | ✅ Diff not available yet · Nothing to plot | ✅ Loading repository… | ✅ Repository unavailable + retry | ✅ Pick a workspace first — Repositories are registered against one workspace. | error also toasts (follow-up) |
| `/ade/dashboard/repositories/catalog` | ✅ No specs discovered yet · No specs match these filters | ✅ DataTable (sr: Loading discovered specs…) | ✅ Could not load the spec catalog + retry | ✅ Pick a workspace first — The spec catalog spans one workspace’s repositories. | |
| `/ade/dashboard/repositories/new` | ✅ No linked accounts yet · No repositories on this account | ✅ Loading linked accounts… · Loading repositories… | ✅ Couldn’t load repositories + retry | ✅ Pick a workspace first — A repository is registered against one workspace. | |
| `/ade/dashboard/repositories/telemetry` | n/a — fixed metric cards; unread counters show an Alert | ✅ Loading quota telemetry… | ✅ Quota telemetry unavailable + retry | ✅ Pick a workspace first — Quota telemetry is metered per workspace. | |
| `/ade/dashboard/repositories/webhook-ip-allowlist` | ✅ No additional ranges | ✅ Loading the allowlist… | ✅ Allowlist unavailable + retry | ✅ Pick a workspace first — The webhook allowlist is scoped to one workspace. | |
| `/ade/dashboard/roles` | ✅ No roles defined yet · No role selected · No role matches “…” | ✅ skeletons (sr: Loading roles… · Loading the role…) | ✅ Alert: Failed to load roles. Refresh the page to try again. + Retry | ⚠️ follow-up — no gate; a no-workspace read shows as an error Alert | |
| `/ade/dashboard/sdk-settings` | n/a — a settings form with defaults | ✅ skeleton (sr: Loading SDK settings…) | ✅ Alert: Could not load these settings. Refresh the page to try again. | ⚠️ follow-up — no gate; a no-workspace read shows as an Alert | |
| `/ade/dashboard/style-guides` | ✅ No style guides yet · No style guides match these filters | ✅ DataTable (sr: Loading style guides…) | ✅ DataTable: Couldn’t load this list + “Failed to load style guides…” | ⚠️ follow-up — no gate; a no-workspace read lands in the table’s error state | |
| `/ade/dashboard/style-guides/[guideId]` | ✅ Style guide not found · No policy versions yet | ✅ skeleton (sr: Loading the rule catalog…) | ⚠️ follow-up — a failed read renders “Style guide not found”; its error Alert is unreachable | n/a — detail deep link | |
| `/ade/dashboard/tenants` | ✅ No tenants yet · No tenants match these filters | ✅ DataTable (sr: Loading tenants…) | ✅ DataTable: Couldn’t load this list + “Could not load your tenants…” | n/a — this page is the workspace list and picker | |
| `/ade/dashboard/versions` | ✅ No projects yet · No versions yet · No revisions match… | ⚠️ follow-up — the project read has no loading state; “No projects yet” shows until it lands | ⚠️ follow-up — project and version read failures are logged, then the lists empty | ✅ Pick a workspace first — Versions belong to one workspace. | |
| `/ade/dashboard/versions/sunset-timeline` | ✅ No deprecation or sunset entries | ✅ Loading the sunset timeline… · Loading schedule… | ✅ Couldn’t load the sunset schedule + retry | ✅ Pick a workspace first — Deprecation and sunset dates belong to one workspace. | |
| `/ade/database` | ✅ No project selected · No table selected · No matching rows | ✅ Running the query… | ⚠️ follow-up — the query read has no catch; a table-list failure shows as empty | ⚠️ follow-up — the picker is disabled without a workspace, yet the empty state says “Pick a project” | legacy layout |
| `/ade/migration` | ✅ No project selected · Pick two different versions · No rows in this table yet | ✅ Loading rows… | ⚠️ follow-up — the row read has no catch; a class-list failure shows as empty | ⚠️ follow-up — the picker is disabled without a workspace; “No project selected” is a dead end | legacy layout |
| `/ade/reviews/[id]` | ✅ No threads · First publication | ✅ Loading review… | ✅ This review didn’t load + retry | n/a — review deep link | |
| `/ade/studio` | n/a — redirects to the Studio app | n/a — redirects | n/a — redirects | n/a — redirects | redirect only |
| `/ade/studio/code` | n/a — redirects to the Studio app | n/a — redirects | n/a — redirects | n/a — redirects | redirect only |
| `/ade/studio/editor` | n/a — redirects to the Studio app | n/a — redirects | n/a — redirects | n/a — redirects | redirect only |
| `/ade/studio/paths` | n/a — redirects to the Studio app | n/a — redirects | n/a — redirects | n/a — redirects | redirect only |
| `/admin` | n/a — sign-in form | ✅ button: Authenticating… | ✅ Sign-in didn’t go through. Try again. | n/a — the admin console has its own auth | |
| `/admin/dashboard` | n/a — static overview | n/a — static | n/a — static | n/a — the admin console has its own auth | admin |
| `/admin/dashboard/feature-flags` | ✅ No feature flags yet · No flags in this package | ✅ Loading feature flags… | ⚠️ follow-up — the error banner dismisses itself after 5 s; non-success responses are ignored | n/a — the admin console has its own auth | admin; legacy layout |
| `/admin/dashboard/licenses` | ✅ No license plans defined | ✅ Loading licenses… · Loading flag packages… · Loading license assignments… | ⚠️ follow-up — the error banner dismisses itself after 5 s; non-success responses are ignored | n/a — the admin console has its own auth | admin; legacy layout |
| `/admin/dashboard/settings` | ✅ No providers configured | ✅ Loading provider configuration… | ✅ Could not load provider configuration + Retry | n/a — the admin console has its own auth | admin |
| `/admin/dashboard/templates` | ✅ No property templates | ✅ skeleton rows (sr: Loading templates…) | ⚠️ follow-up — the error banner dismisses itself after 5 s; non-success responses are ignored | n/a — the admin console has its own auth | admin |
| `/admin/dashboard/tenants` | ✅ No tenants · No users in this tenant | ✅ Loading tenants… | ⚠️ follow-up — the error banner dismisses itself after 5 s | n/a — the admin console has its own auth | admin |
| `/admin/dashboard/users` | ✅ No users · No pending signups | ✅ Loading users… | ⚠️ follow-up — the error banner dismisses itself after 5 s; non-success responses are ignored | n/a — the admin console has its own auth | admin |
| `/design-system/command-palette` | ✅ palette: Nothing matches “…” | n/a — gallery specimen | n/a — gallery specimen | n/a — gallery specimen | gallery |
| `/design-system/hive` | ✅ specimen: No projects yet · No projects match your filters | ✅ specimen: Publishing version 2.4.0… | ✅ specimen: Catalog analytics unavailable · Couldn’t load projects | ✅ specimen: Pick a workspace first | gallery |
| `/design-system/mcp` | ✅ specimen: No endpoints yet | ✅ specimen: Loading catalog… | ✅ specimen: This didn’t load | n/a — gallery specimen | gallery |
| `/design-system/page-header` | n/a — gallery specimen | n/a — gallery specimen | n/a — gallery specimen | n/a — gallery specimen | gallery |
| `/design-system/shortcuts` | n/a — gallery specimen | n/a — gallery specimen | n/a — gallery specimen | n/a — gallery specimen | gallery |
| `/login` | n/a — sign-in form | ✅ SSO tile: Connecting… | ✅ banner: the mapped auth error, or “Sign-in didn’t finish…” | n/a — public page | |
| `/login/2fa` | n/a — code form | ✅ button: Verifying… · Sending… | ✅ Alert: That code was not accepted… | n/a — public auth page | |
| `/signup/oauth` | n/a — sign-up form | ✅ button: Creating your workspace… | ✅ Alert: Your account wasn’t created. Try again. | n/a — without a token it redirects to /login | |

## Follow-ups this review found

These are behaviour, not copy, so they are out of scope for this copy pass:

1. **Workspace gates.** Six routes have no `GatedState`: audit, members, roles, sdk-settings,
   style-guides and notifications. The `/ade` onboarding guard only catches users with no workspace at
   all.
2. **Swallowed errors.** On these screens a failed read shows as an empty state:
   - Home
   - Primitives
   - Profile
   - Projects (card view)
   - The style-guide editor
   - Versions
   - Database
   - Migration
   - Lint-workspace trends and ranks
3. **Admin banners** dismiss themselves after 5 s and ignore non-success responses: licenses, feature
   flags, templates, tenants and users.
4. **Duplicate errors.** These show the same error as a toast and as an `ErrorState`:
   - Repository preview
   - Discovered specs
   - Quota telemetry
   - Webhook allowlist
   - Add repository
5. **Raw server messages.** About 484 `x instanceof Error ? x.message` sites pass a server's own text
   through, and 62 "Failed to …: " prefixes append one. The copy gate holds both counts at that
   ceiling.
