---
name: implement
description: Fetches the GitHub Issue for the current repo, implements the work to be done.
---

# Implement (`/implement <number>`)

When user invokes **implement** with issue number, treat number as **GitHub issue** in **current repository**. Follow workflow end to end unless user terminates or environment blocks (auth, permissions, missing `gh`, etc.).

## Guidelines

- Apply **AGENTS.md**
- Only change what ticket requires: avoid unnecessary refactors.
- Never commit credentials or tokens.
- If blocked, stop, explain.

## Phase 1: Fetch issue

- Identify current repository from workspace context.
- Fetch full issue **title, body, labels, and any linked/previous discussion**:

```
gh issue view <number> --repo <owner>/<repo>
```

- Summarize issue clearly in conversation so full intent in context.
- Read the issue's **Documentation (Docusaurus)** section (every issue carries one; marker `<!-- apiome-docs-tasks:v1 -->`). If it is missing, apply the standard list from **Phase 3b** anyway.
- **NEVER invent requirements.**  If issue **ambiguous, underspecified, or contradicts the codebase**, SWITCH TO PLAN MODE, clarify, and stop.

## Phase 2: Branch setup

- Fetch and checkout latest default branch:

```bash
git checkout main
git pull origin main
```

- Create and switch to `ticket-<number>`:

```bash
git checkout -b ticket-<number>
```

- If branch already exists, report it and ask whether to reset or reuse.
- All implementation commits for ticket belong on this branch.

## Phase 3: Implementation

- Implement behavior **as specified in issue**, do not deviate.
- If description is **large or risky**, SWITCH TO PLAN MODE, outline a short plan in chat.
- Split code into separate modules, helper functions, or utility classes if context too large.
- Keep implementation **simple** - keep code easy to read and understand, fully document methods, inputs, and return variables.
- Create **comprehensive test cases** for all new and changed functionality.
- UI: Create integration UI tests when working on UI/UX features.
- Lint the code.

## Phase 3b: Documentation (mandatory — the Docusaurus site is part of the product)

The docs site is the `apiome-docs/` workspace (Docusaurus; #67). Documentation changes ship **in the same branch and PR** as the code. Work through the issue's **Documentation (Docusaurus)** checklist:

- **Pages:** find the pages under `apiome-docs/docs/**` that describe the surface you changed (sidebar groups: Getting started · Build · Bring in · Ship · Govern · Workspace & account · Admin & tools · Reference). Update copy, steps and tables so they match the product **as shipped**; add a new page (front matter: `title`, `description` ≤ 14 words, `sidebar_position`) when the issue adds a route, dialog, command or endpoint.
- **Screenshots:** for every UI change, add or update entries in `apiome-docs/screens.json` and regenerate with `yarn docs:screenshots -- --id <id>` (light + dark, 1440 × 900, comfortable density). Reference them with `<Screenshot id="…" alt="…"/>`. Never commit hand-captured images.
- **Reference:** REST change → bump the OpenAPI version (AGENTS.md) and regenerate the API reference; CLI or MCP change → regenerate the command / tool reference pages.
- **Release notes:** add an entry for the issue — `apiome-rest/CHANGELOG.md` for REST; the `release-notes/` post for anything user-visible; a What's new line for UI changes.
- **Gate:** `yarn workspace apiome-docs build` and `yarn docs:check` must pass — CI runs it on every PR (front matter, orphan pages, broken internal links, screenshots missing a theme or image, stale screenshots, stale REST reference; rules and fixes on `apiome-docs/docs/admin/contribute-to-the-docs.mdx`). A stale screenshot is recaptured with `yarn docs:screenshots -- --id <id>`; a screen drawn outside its route folder (dialog, shared panel) names its component in the manifest entry's `sources`.
- **If `apiome-docs/` does not exist yet on `main`:** write the same content under `docs/guide/` (one page per surface, same front matter) and list the files in the PR body under *Documentation* so #5619 migrates them. Do not skip the step.

## Phase 4: Internal Audit

- Ensure potential misuses of new code are safeguarded, covered, noted.
- UI: Use **CSS classes** - no hard-coded values.
- Documentation must be complete and simple — code comments **and** the Docusaurus pages from Phase 3b. Re-read each touched page as the user would: steps in order, bold UI nouns, buttons quoted as they read in the product, a current screenshot wherever the screen changes.
- Check for code reuse; extract repeated logic into separate reusable modules.
- ONLY RUN UNIT TESTS, DO NOT RUN E2E OR INTEGRATION TESTS

## Phase 5: Verify and Test

From **repository root**, run project's standard checks:

- Build project:

```bash
yarn build
```

Run package-specific builds required by workspace rules.

- Run tests:

```bash
yarn test
```

Run package-specific tests the issue touches, per READMEs.

- Test only unit tests
- Fix **any failures introduced that block ticket** and **any tests or build issues** before proceeding.

## Phase 6: Note Work

- Mark ticket complete in **ROADMAP** and REMOVE ITS ENTRY FROM THE ISSUES TABLE matching the issue number if applicable.
- Bump semver versions in modified projects (including `apiome-docs/package.json` when docs changed).
- Tick the items of the issue's **Documentation (Docusaurus)** checklist that the PR satisfies (edit the issue body) and note any that do not apply, with the reason.

## Phase 7: Commit, Push, Pull Request

### Commit

```bash
git add -A
git commit -m "Fix #<number> - <concise title>"
```

### Push

```bash
git push origin ticket-<number>
```

### Open the PR

Use `gh` to create Pull Request from `ticket-<number>` into default branch:

```bash
gh pr create \
  --title "Fix #<number> - <concise title>" \
  --body "<descriptive body>" \
  --base main \
  --head ticket-<number>
```

#### PR body must include:

- What was done and why
- How to test
- **Documentation:** the `apiome-docs` pages added or changed (paths), the screenshot ids regenerated, the reference pages regenerated, and the release-notes entry (the *Pull request checklist* on the Contribute to the docs page) — or, if the site is not on `main` yet, the `docs/guide/` files written for migration
- Risk/notes
- Issue link: `Closes #<number>` (or `Fixes #<number>`)
- Notate: `Made with <agent name> using model <model name>`

## Phase 8: Explain How to Test

- Note how to test what was done.
- Include steps with each important piece boldfaced (e.g. "**click button X**" or "**browse to Y**")
- Note example data to put into forms to test.

## Phase 9: Switch to Main

Switch back to `main`:

```bash
git checkout main
```

