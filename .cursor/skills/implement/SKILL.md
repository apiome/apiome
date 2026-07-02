---
name: handle-ticket
description: Fetches the GitHub Issue for the current repo, implements it on branch ticket-<n>, tests, pushes, opens a PR with Copilot as reviewer, then returns to main.
---

# Implement (`/implement <number>`)

When user invokes **implement** with issue number (for example `/implement 124`), treat number as **GitHub issue** in **current repository** (e.g. `KenSuenobu/apiome` for this workspace). Follow workflow end to end unless user terminates or environment blocks (auth, permissions, missing `gh`, etc.).

## Guidelines

- Apply **.cursorrules**
- Use context7 MCP for latest documentation.
- Only change what ticket requires: avoid unnecessary refactors.
- Never commit credentials or tokens.
- If blocked, stop, explain.
- Python favor PEP8.  Follow `import this` rules.
- Obey semver.
- Don't Repeat Yourself.

## Phase 1: Fetch issue

- Identify current repository from workspace context.
- Fetch full issue **title, body, labels, and any linked/previous discussion** for scope:

```
gh issue view <number> --repo <owner>/<repo>
```

- Summarize issue clearly in conversation so full intent in context.
- **NEVER invent requirements.**  If issue **ambiguous, underspecified, or contradicts the codebase**, SWITCH TO PLAN MODE and clarify.

## Phase 2: Branch setup

- Fetch and checkout latest default branch:

```bash
git com
git pom
```

- Create and switch to `ticket-<number>`:

```bash
git cob ticket-<number>
```

- If branch already exists, report it and ask whether to reset or reuse.
- All implementation commits for ticket belong on this branch.

## Phase 3: Implementation

- Implement behavior **as specified in issue**.
- If change **large or risky**, SWITCH TO PLAN MODE, outline a short plan in chat.
- Split code into separate modules, helper functions, or utility classes if context too large.
- Keep implementation **simple** - keep code easy to read and understand.
- Create **comprehensive test cases** for all new and changed functionality.

## Phase 4: Internal Audit

After coding changes are made, perform internal audit before moving on:

- Ensure potential misuses of new code are safeguarded and covered.
- Use **Tailwind CSS classes** - no hard-coded values.
- Documentation must be complete and succinct.
- Check for code reuse; extract repeated logic into separate modules.
- Tests must **be thorough**, have **no warnings, no errors, and no suppressions** of any kind.

## Phase 5: Verify and Test

From **repository root**, run project's standard checks:

- Build project:

```bash
yarn build
```

Also run package-specific builds required by workspace rules.

- Run tests:

```bash
yarn test
```

Also run package-specific tests the issue touches, per READMEs.

- Fix **any failures you introduced that block the ticket** before proceeding.
- Repeat Phase 5 if either step fails.  If steps 1 and 2 are successful, continue to Phase 6.
- Check code to see if improvements can be made before issuing a Pull Request.

## Phase 6: Note Work

- Mark ticket complete in **ROADMAP** and REMOVE ITS ENTRY FROM THE ISSUES TABLE matching the issue number.
- Add one-line summary of work performed to **public/WHATS_NEW.md**.
- Bump patch version of application in **apiome-ui/package.json** when change is made in **apiome-ui**.
- Bump patch version of pyproject.toml in **apiome-rest** when change is made there.

## Phase 7: Commit, Push, Pull Request

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

Use `gh` to create Pull Request from `ticket-<number>` into default branch:

```bash
gh pr create \
  --title "Fix #<number> - <concise title>" \
  --body "<body>" \
  --base main \
  --head ticket-<number>
```

#### PR body must include:

- What was done and why
- How to test
- Risk/notes
- Issue link: `Closes #<number>` (or `Fixes #<number>`)

### Mark Issue

Comment "Work completed as directed" on GitHub issue.

## Phase 8: Explain How to Test

- Note how to test what was done.
- Include steps with each important piece boldfaced (e.g. "**click button X**" or "**browse to Y**")
- Note example data to put into forms to test.

## Phase 9: Remain on Branch

Do not switch back to `main`.
