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

## Phase 1: Create Issues

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
- Mark issue number in ROADMAP for each issue created for reference

