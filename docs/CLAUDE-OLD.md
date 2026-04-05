# Claude instructions for objectified

This file is the **default engineering contract** for Claude (and compatible agents) working in the **KenSuenobu/objectified** repository. It mirrors [.github/copilot-instructions.md](.github/copilot-instructions.md). Keep that file and this one in sync when changing **repo-wide** rules.

## How this file works with applied skills

- **Baseline:** Unless a task-specific skill says otherwise, follow every section below.
- **Skills** live under `.cursor/skills/` (and similar). When the user **applies or invokes** a skill for the current task, follow that skill’s workflow, checks, and outputs **together with** this file.
- **If something conflicts:** For the **scoped work** the skill describes (for example “handle this ticket”), the **applied skill wins** on procedure and deliverables. This file still applies to **safety and repo conventions** (no edits to reference-only trees, tests, versioning bumps, etc.) unless the skill explicitly documents an exception approved for this repo.
- **Maintenance:** Put **durable, repo-wide** standards here or in `copilot-instructions.md`. Put **repeatable workflows** (ticket intake, release steps, etc.) in skills so this file stays stable and skills can evolve independently.

## Project Overview

Objectified is an OpenAPI 3.2.0 Specification Application that provides a visual editor for creating and editing Schema Objects and Properties.
It contains the following directory structure:

- **objectified-browse**: Browser Source-of-Truth application used to browse published OpenAPI Specifications
- **objectified-db**: Database schema written using PostgreSQL DDL, utilizes `schema-evolution-manager` tools to apply schema changes
- **objectified-rest**: Python project containing REST services used by the UI
- **objectified-ui**: UI application written in TypeScript using NextJS, React, Radix UI, monaco-editor, lucide-react, Tailwind CSS
- **objectified-web**: Objectified Web Presence

## General

- **GitHub issues** in **KenSuenobu/objectified** are the source of truth for what to implement.
- Use **github MCP** for GitHub access.
- Prefer **context7 MCP** for up-to-date library documentation and examples when available.
- **Python:** follow **PEP 8**.
- Ask questions only when blocked; keep clarification minimal.
- **Tests:** add or update unit tests as needed. Run the project test suite with `yarn test` (from the repo root unless a package README says otherwise). Fix regressions you introduce or uncover.
- Use **logging** where it aids operations and debugging.
- **`git`:** always pass `--no-pager` (for example `git --no-pager log`).
- **Version bumps:** when you change a **workspace package**, bump the **patch** version in that package’s `package.json`.
- **OpenAPI:** when you change an OpenAPI spec, bump the **patch** version **in that spec file** (per project convention).
- **DON'T REPEAT YOURSELF**
- **Simply code** where possible, keep code small and maintainable.  Split code into separate classes, files, and utility classes where possible to maintain manageability of the project overall.
- **This project is a commercial product** so it must be well tested, and well documented.  Not all implementations need to be documented.
- **DON'T REPEAT YOURSELF**

## REST (objectified-rest and related)

- Separate services by **domain**; use **tags** to group related endpoints consistently with the schema.
- Define and document endpoints in **OpenAPI** with clear descriptions and examples.
- Return **meaningful errors**, correct **HTTP status codes**, and enforce **authentication** and **authorization** for protected data.
- Use **pagination** for large lists; document pagination parameters.
- Cover **happy paths, edge cases, and failure cases** in tests; those tests must run in the normal suite.

## SQL (objectified-db)

- New scripts under `objectified-db/scripts/` must use an accurate **local timestamp** in the **filename** (consistent with existing scripts).
- Add **SQL tests** under `objectified-db/tests/` when appropriate; they must run as part of that package’s test workflow.
- Tests use the **`objectified_test`** database.
- Prefer **case-insensitive** comparisons with `LOWER() = LOWER()` where appropriate.
- Avoid **`LIKE` / `ILIKE`** except for **name** and **description** search; then sanitize input to prevent injection. Do not use them casually elsewhere.

## UI (objectified-ui)

- Support **light and dark** themes; **dark** should follow **system** preference by default.
- Use **Next.js**, **TypeScript**, **Tailwind CSS**, **Radix UI** for components, **lucide-react** for icons, and **monaco-editor** where editing UX requires it.
- Use **custom** alerts/confirms; do not use `alert()` / `confirm()` / `prompt()`.
- Prefer **named CSS classes** over heavy inline styling so themes apply consistently.
- After UI changes, run **integration tests** as appropriate for the project; **eliminate warnings** rather than leaving them.

## Next.js application

- Use **yarn** as the package manager.
- Use **TypeScript** for all application code.
- After substantive app changes, run **`yarn build`** in **objectified-ui** (or follow the package README if it defines a different verification command).

## Creating and moving files

- Create files using IDE or MCP-assisted workflows, not ad hoc shell heredocs unless the environment has no alternative.
- Prefer **one new file per change set** when practical; each file should be **complete** before moving on.
- When **moving** behavior between areas, preserve behavior **exactly** unless the issue explicitly requests a change.

## Summarization

- **Do not invent** tickets, issues, or facts. Summarize **only** from provided material.
- Write summaries **in the reply**; do not create new summary documents unless the user asks for a file.
