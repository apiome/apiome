---
name: handle-ticket
description: Fetches the GitHub Issue for the current repo, implements it on branch ticket-<n>, tests, pushes, opens a PR with Copilot as reviewer, then returns to main.
---

# Implement (`/implement <number>`)

When the user invokes **implement** with an issue number (for example `/implement 124`), treat that number as the **GitHub issue** in the **current repository** (e.g. `KenSuenobu/objectified` for this workspace). Follow this workflow end to end unless the user stops you or the environment blocks a step (auth, permissions, missing `gh`, etc.).

## Phase 1 - Fetch the issue

1. Identify the current repository from the workspace context.
2. Fetch the full issue **title, body, labels, and any linked/previous discussion** needed to understand scope:

```
gh issue view <number> --repo <owner>/<repo>
```

3. Summarize the issue clearly in the conversation so the full intent is in context.
4. **Do not invent requirements.**  If the issue is **ambiguous, underspecified, or contradicts the codebase**, ask concise clarifying questions before proceeding.

## Phase 2 - Branch setup

1. Fetch and checkout the latest default branch:

```bash
git fetch origin
git checkout main
git pull origin main
```

2. Create and switch to `ticket-<number>`:

```bash
git checkout -b ticket-<number>
```

3. If the branch already exists, report it and ask whether to reset or reuse it.
4. All implementation commits for this ticket belong on this branch.

## Phase 3 - Implementation

- Apply **CLAUDE.md** / **copilot-instructions.md** and other workspace rules (tests, version bumps, no edits to reference-only trees, etc.).
- Implement the behavior **as specified in the issue**.
- If the change is **large or risky**, outline a short plan in the chat and wait for alignment before proceeding.
- Split code into separate modules, helper functions, or utility classes if context becomes too large or unmanageable.
- Keep the implementation **simple** - the simpler the better, making the code easy to read and understand.
- Create **comprehensive test cases** for all new and changed functionality.
- Don't Repeat Yourself.

## Phase 4 - Internal Audit

After coding changes are made, perform an internal audit before moving on:

- Ensure potential misuses of new code are safeguarded and covered.
- Verify colors and positioning use **Tailwind CSS classes** - no hard-coded values.
- Documentation must be well-written and succinct.
- Check for code reuse opportunities; extract repeated logic into separate modules.
- Tests must have **no warnings, no errors, and no suppressions** of any kind.
- Tests must be thorough.
- Don't Repeat Yourself.

## Phase 5 - Verify and Test

From the **repository root**, run the project's standard checks:

1. Build the project:

```bash
yarn build
```

Also run any package-specific builds required by workspace rules (e.g. `objectified-ui` per **CLAUDE.md**)

2. Run the tests:

```bash
yarn test
```

Also run any package-specific tests the issue touches, per READMEs.

3. Fix **any failures you introduced tor that block the ticket** before proceeding.
4. Do not proceed to Phase 6 if build or tests fail.

## Phase 6 - Note the Work

1. Mark the ticket complete in **ROADMAP** and remove its entry from the issues list matching the issue number.
2. Add a one-line summary of the work performed to **public/WHATS_NEW.md**.
3. Bump the patch version of the application in the **objectified-ui/package.json** when a change is made in **objectified-ui**.
4. Bump the patch version of pyproject.toml in **objectified-rest** when a change is made in that project.

## Phase 7 - Commit, Push, and PR

### Commit

```bash
git add -A
git commit -m "Fix #<number> - <concise description>"
```

### Push

```bash
git push origin ticket-<number>
```

### Open the PR

Use `gh` to create hte PR from `ticket-<number>` into the default branch:

```bash
gh pr create \
  --title "Fix #<number> - <concise title>" \
  --body "<body>" \
  --base main \
  --head ticket-<number>
```

#### PR body must include:

- What was done and why
- How to test it
- Risk/notes
- Issue link: `Closes #<number>` (or `Fixes #<number>`)

### Assign Copilot as Reviewer

Request a review from **Copilot** via `gh`.  Note the assignment in a PR comment if needed.

### Mark the Issue

Comment "Work completed as directed" on the GitHub issue.

## Phase 8 - Remain on the Branch

Do not switch back to `main` after the PR is opened. Stay on `ticket-<number>`.

## Constraints

- **Scope:** Only change what the ticket requires; avoid unrelated refactors.
- **Secrets:** Never commit credentials or tokens.
- **Blocked:** If `GitHub MCP` is not authenticated, tests cannot be run, or the issue is inaccessible, say so clearly and stop after doing what is possible safely.
