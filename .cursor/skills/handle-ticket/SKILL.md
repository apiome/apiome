---
name: handle-ticket
description: Fetches the GitHub Issue for the current repo, implements it on branch ticket-<n>, tests, pushes, opens a PR with Copilot as reviewer, then returns to main.
---

# Handle ticket (`/handle-ticket <number>`)

When the user invokes **handle-ticket** with an issue number (for example `/handle-ticket 124`), treat that number as the **GitHub issue** in the **current repository** (e.g. `KenSuenobu/objectified` for this workspace). Follow this workflow end to end unless the user stops you or the environment blocks a step (auth, permissions, missing `gh`, etc.).

## 1. Load the issue into context

- Fetch the full issue **title, body, labels, and any linked/previous discussion** needed to understand scope. Prefer the **github** MCP so the ticket text is summarized and available in the conversation.
- **Do not invent** requirements; implement only what the issue and agreed clarifications describe.

## 2. Create and use branch `ticket-<number>`

- Ensure you have the latest **default branch** (usually `main`) via Github MCP: fetch origin and checkout main (or the repo’s default), then pull.
- Create and switch to **`ticket-<number>`** (example: issue `124` → `ticket-124`):
  - checkout -b ticket-<number>
- All implementation commits for this ticket belong on this branch.

## 3. Implement

- Apply **CLAUDE.md** / **copilot-instructions.md** and other workspace rules (tests, version bumps, no edits to reference-only trees, etc.).
- Implement the behavior **as specified in the issue**.
- If the issue is **ambiguous, underspecified, or contradicts the codebase**, **ask concise clarifying questions** before large changes.
- If the change is **large or risky** and the issue alone is not enough to proceed safely, **outline a short plan** in the chat (and optionally in the PR later), then execute after alignment or per issue instructions.
- If code becomes too large or unmanageable for your context, split the code into separate modules, helper functions, or utility classes.
- Keep the implementation simple.  The simpler the better, making the code easy to read and understand.
- Create comprehensive test cases for all new and changed functionality.
- Don't Repeat Yourself.

## 4. Verify from repository root

- From the **repository root**, run the project’s standard checks so this ticket doesn’t regress the monorepo:
  - Run **`yarn test`** (and any package-specific tests the issue touches, per READMEs).
  - Run **`yarn build`** where required by workspace rules (e.g. after substantive **objectified-ui** changes, run it in **objectified-ui** per **CLAUDE.md**; if the repo root defines a single build/test entry, use that consistently).
- Fix failures **you introduced or that block the ticket** before committing.

## 5. Perform an internal audit of the code changes

- After coding changes have been made, run an internal audit to make sure any potential misuses of the code are safeguarded and covered.
- Make sure that values for colors and positioning are not hard-coded, but used as a Tailwind CSS style and reused.
- Documentation in the code must be well written and succinct.
- Check code for potential reuse and branch that code out into separate modules where appropriate.
- Tests should have no warnings or errors.
- Tests should not have suppressions of any kind.
- Tests should be thorough.
- Don't Repeat Yourself.

## 6. Commit and push

- **Commit** with a clear message that references the issue (e.g. `Fix #124 — …` or `Addresses #124 — …`).
- **Push** the branch

## 7. Open a pull request

- Create a PR **from `ticket-<number>`** into the **default branch** using the GitHub MCP.
- **PR title:** concise; include or reference the issue number.
- **PR body:** summarize **what was done**, **why**, **how to test**, and **risk/notes**. Use a markdown checklist if it helps. Link the issue (e.g. `Closes #124` or `Fixes #124` if the team uses auto-close semantics).

## 8. Assign Copilot as reviewer

- **Request a review from GitHub Copilot** on the PR. Use the same reviewer login your org uses when typing **@Copilot** in the GitHub reviewer field (often the Copilot PR-review bot account—confirm via UI or org docs).  Use Github MCP to add **Copilot** as a reviewer and note that in a comment if needed.

## 9. Return to default branch

- After the PR is created (and push is complete), switch back locally:
  - checkout main (or the repo default branch), then optionally pull so the workspace matches upstream.

## Constraints

- **Scope:** Only change what the ticket requires; avoid unrelated refactors.
- **Secrets:** Never commit credentials or tokens.
- **Blocked:** If `gh` is not authenticated, tests cannot be run, or the issue is inaccessible, say so clearly and stop after doing what is possible safely.
