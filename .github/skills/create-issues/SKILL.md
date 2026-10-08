---
name: create-issues
description: Creates issues from a ROADMAP file
---

# Implement (`/create-issues <roadmap-file>`)

When user invokes **create-issues**, refer to `docs/<roadmap-file>.md` as the description of the work to be referenced.

## Guidelines

- Use `gh` command to create issues
- Reuse labels in issues, create where necessary
- Parent issues must be assigned using Relationships
- Projects and Milestones need not apply

## Create Issues

- Create GitHub issues in order of requirements listed in `docs/<roadmap-file>.md`
- Issues must contain:
  - Problem Statement
  - Solution/Scope
  - Acceptance Criteria
  - Parallelism/Dependencies
  - Technical Stack
  - Epic grouping
  - Relationship Reference where applicable
  - MVP indicator (v1) release candidate where applicable
  - Labels indicating all of the appropriate pairings for the issue
  - **Documentation (Docusaurus)** section — the standard block below, appended last with its marker, listing the concrete pages, screenshot ids, reference regeneration and release-notes entry the issue requires (epics: the overview page for the capability plus the rule that every child carries the section)

### Standard Documentation section (append verbatim, then fill the specifics)

```markdown
<!-- apiome-docs-tasks:v1 -->
## Documentation (Docusaurus)

> Standard for every issue — the docs site is `apiome-docs/` (Docusaurus; set up in #67), the contract and `yarn docs:check` gate are #5630, and the **implement** skill carries a mandatory Documentation phase. “Done” means the documentation changed in the same PR as the code.

- [ ] **Pages:** <pages under `apiome-docs/docs/**` to add or update, with sidebar group>
- [ ] **Screenshots:** <`screens.json` ids to add or refresh; light + dark, 1440 × 900; referenced with `<Screenshot id/>`>
- [ ] **Reference:** <OpenAPI version bump + API reference regen / CLI or MCP reference regen, or “n/a”>
- [ ] **Release notes:** <changelog / release-notes / What’s new entry>
- [ ] **Gate:** `yarn workspace apiome-docs build` and `yarn docs:check` pass (broken links, orphan pages, missing or stale screenshots fail; CI runs it on every PR); the PR body lists the pages and screenshot ids touched
```
- Mark issue number in ROADMAP for each issue created for reference
- Use ASCII drawings or Mermaid diagrams to illustrate changes or work

