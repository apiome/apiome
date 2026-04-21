# Objectified 05-2026

We continue to improve the platform based on your feedback with improvements and new features!

---

## Git-like Functionality
- Added a **git command palette** (⌘/Ctrl+G) on all Studio routes: fuzzy search for commit, branch, history/checkout, pull, sync-from-default, merge, and rollback, routing to the same dialogs as the canvas git menu; `?` or the Help row toggles a shortcuts cheatsheet; keybinding helpers live in `studio-keybindings.ts`.
- Added a **recent-activity ticker** under the canvas toolbar (when a named branch is active): the last three commits on that branch’s first-parent lineage, polled every 30s while the tab is visible, with each row opening Compare Version Schemas (revision vs branch tip, or parent→tip for the tip row) on the Versions dashboard.
- Default branch promotion and first-commit `main` bootstrap now turn on merge-path protection automatically (unless explicitly overridden); promotions are recorded in workflow audit as `version.default_branch_promoted`.
- Added default-branch foundations for git-like workflows: branch rows now support a single project default (`isDefault`) with promotion support and first-commit auto-bootstrap of `main`.
- Added branch divergence REST support with merge-base, ahead/behind counts, commit samples, and strong ETag-based 304 responses for stable canvas sync indicators.
- Added a canvas branch picker: check out any named branch from the floating toolbar or git menu, with a current-branch chip, unsaved-layout guard, and refreshed tips after commit or merge.
- Added an ahead/behind default-branch chip on the canvas (feature branches only): live divergence from the REST API, commit samples in the tooltip, refresh on sidebar sync, and one-click deep link into Compare Version Schemas (merge base → branch tip).
- Added a prominent **Commit** control on the canvas toolbar (with unsaved-layout dot, ⌘/Ctrl+Enter from the flow surface, read-only guardrails) that opens the existing commit dialog locked to the active branch when named branches exist.
- Added **Sync from main** under the canvas git menu (feature branches): one-click merge preview with the default branch as source and the active branch as target, disabled with an up-to-date hint when divergence behind is zero; successful merge refreshes the branch list and divergence chip.
- Added a **branch status** summary on the branch chip: hover (with delay) or click opens a popover with branch identity, divergence vs default, working-copy hints, draft-lock status, recent commits on the branch lineage, and a deep link to the Versions dashboard—composed from existing canvas data without new REST endpoints.
- Adds branch protection
- Adds tenancy administration check fixes

## UI
- Branch workflow is its own button in the canvas now, and compacted to fit most functionality that's in Versions now.
- Compacted the trending view in the projects page in the dashboard.
- Moved the add, import, and template buttons to the bottom of the classes and properties sidebar list so they don't obscure the lists.
- Added bottom header to show status of the canvas editor screens.

---

View our YouTube channel [here](https://www.youtube.com/@objectifieddev) for detailed tutorials and walkthroughs!

---

## Feedback

We'd love to hear your thoughts! Your feedback helps us make Objectified better.

---

**Thank you for using Objectified!**

*Last updated: April 20, 2026*

