#!/usr/bin/env python3
"""
Enhance thin GitHub issues with proper descriptions, acceptance criteria, and tech details.
A "thin" issue has a body that's just the one-liner from the summary table.

Usage: python3 enhance_thin_issues.py <file.md>
"""

import re
import subprocess
import sys
import time
import json
import os

REPO = 'KenSuenobu/objectified-commercial'
REPO_DIR = '/home/kenji/Development/apiome'

BODY_FOOTER_MARKER = '---\n\n**Part of Epic:**'

def get_issue_body(issue_num):
    """Fetch current body of a GitHub issue."""
    result = subprocess.run(
        ['gh', 'issue', 'view', str(issue_num), '--json', 'body', '--jq', '.body'],
        capture_output=True, text=True, cwd=REPO_DIR
    )
    return result.stdout.strip() if result.returncode == 0 else None


def update_issue_body(issue_num, new_body):
    """Update GitHub issue body."""
    result = subprocess.run(
        ['gh', 'issue', 'edit', str(issue_num), '--body', new_body],
        capture_output=True, text=True, cwd=REPO_DIR
    )
    if result.returncode == 0:
        print(f"    Updated #{issue_num}")
        return True
    print(f"    ERROR updating #{issue_num}: {result.stderr[:100]}", file=sys.stderr)
    return False


def is_thin(body):
    """Check if an issue body is thin (no acceptance criteria, just a one-liner)."""
    if not body:
        return True
    # Strip the footer
    stripped = body.split(BODY_FOOTER_MARKER)[0].strip()
    # Thin if: no acceptance criteria section, short, no code blocks
    has_ac = 'acceptance criteria' in stripped.lower() or 'acceptance:' in stripped.lower()
    has_code = '```' in stripped
    has_api = '/api/' in stripped or 'endpoint' in stripped.lower()
    return not (has_ac or has_code or has_api) or len(stripped) < 200


def get_tech_stack(content):
    """Extract tech stack from file header blockquote."""
    m = re.search(r'\*\*Tech Stack\*\*:(.+?)(?:\n\n|---)', content, re.DOTALL)
    if m:
        return m.group(1).strip().replace('\n', ', ')
    return 'Next.js, TypeScript, PostgreSQL, Redis, OpenAPI 3.1'


def get_epic_name(content, ref):
    """Get the epic name for a given issue ref."""
    parts = ref.split('.')
    if not parts:
        return 'Unknown Epic'
    epic_num = parts[0]
    m = re.search(rf'^## Epic {epic_num}(?:\s*\(#\d+\))?: (.+)$', content, re.MULTILINE)
    return m.group(1).strip() if m else 'Unknown Epic'


def get_epic_issue_num(content, ref):
    """Get the epic GitHub issue number for a given issue ref."""
    parts = ref.split('.')
    if not parts:
        return None
    epic_num = parts[0]
    m = re.search(rf'^## Epic {epic_num}\s*\(#(\d+)\)', content, re.MULTILINE)
    return int(m.group(1)) if m else None


def build_enhanced_body(issue, tech_stack, epic_name, epic_issue_num, feature_label):
    """Build an enhanced body for a thin issue."""
    title = issue['title']
    desc = issue['description']
    ref = issue['ref']
    labels = issue['labels']
    mvp = issue['mvp']

    # Determine issue type from labels and title
    is_rest = 'rest' in labels or 'api' in title.lower() or 'endpoint' in title.lower()
    is_ui = any(t in title.lower() for t in ['ui', 'dashboard', 'panel', 'widget', 'page', 'view', 'modal', 'button', 'form', 'editor'])
    is_data = any(t in title.lower() for t in ['model', 'schema', 'table', 'migration', 'database', 'data'])
    is_infra = any(t in title.lower() for t in ['integration', 'connector', 'export', 'import', 'sync', 'queue', 'cache', 'redis'])
    is_security = any(t in title.lower() for t in ['security', 'auth', 'permission', 'encrypt', 'audit', 'log', 'key', 'token', 'mfa'])

    lines = []
    lines.append(f"## {title}")
    lines.append("")
    lines.append(desc)
    lines.append("")

    # Add implementation notes based on type
    if is_data:
        lines.extend([
            "## Implementation Notes",
            "",
            f"Design and implement the database schema components required for this feature.",
            f"Ensure proper indexing for query performance, foreign key constraints for data integrity,",
            f"and include a Drizzle ORM migration file.",
            "",
        ])
    elif is_ui:
        lines.extend([
            "## Implementation Notes",
            "",
            f"Implement the UI component following the existing design system patterns.",
            f"Use Radix UI primitives and Tailwind CSS for styling. Ensure responsive behavior",
            f"and proper loading/error states throughout.",
            "",
        ])
    elif is_rest:
        lines.extend([
            "## Implementation Notes",
            "",
            f"Implement the REST endpoint(s) with proper authentication middleware, input validation,",
            f"and error handling. Document the endpoint in the OpenAPI 3.1 spec.",
            "",
        ])
    else:
        lines.extend([
            "## Implementation Notes",
            "",
            f"Implement this feature as part of the {epic_name} epic. Ensure proper",
            f"integration with existing systems and follow established code patterns.",
            "",
        ])

    # Acceptance criteria
    lines.append("## Acceptance Criteria")
    lines.append("")

    if is_data:
        lines.extend([
            f"- Database migration creates the required tables/columns with correct types and constraints",
            f"- Indexes applied for performance-critical query patterns",
            f"- Foreign key constraints enforce referential integrity",
            f"- Seed/fixture data available for development environment",
            f"- All columns documented with comments in the migration file",
        ])
    elif is_ui:
        lines.extend([
            f"- Component renders correctly on desktop (1440px) and tablet (768px) breakpoints",
            f"- Loading state shown during async data fetch",
            f"- Error state handled gracefully with user-friendly message",
            f"- Empty state shown when no data is available",
            f"- Keyboard navigation and screen reader accessibility (WCAG 2.1 AA)",
        ])
    elif is_rest:
        lines.extend([
            f"- Endpoint returns correct HTTP status codes (200, 201, 400, 401, 403, 404, 429, 500)",
            f"- Input validation rejects malformed requests with descriptive 400 errors",
            f"- Authentication required; unauthenticated requests return 401",
            f"- Endpoint documented in OpenAPI 3.1 spec with request/response schemas",
            f"- Rate limiting applied consistent with platform-wide limits",
        ])
    elif is_security:
        lines.extend([
            f"- Feature does not expose sensitive data in API responses or logs",
            f"- Changes are audit-logged with actor, timestamp, and affected resource",
            f"- Permissions checked before any data access or mutation",
            f"- Security edge cases documented and tested",
            f"- Passes OWASP security review checklist for this feature category",
        ])
    else:
        lines.extend([
            f"- Feature works end-to-end in a clean development environment",
            f"- Edge cases handled gracefully (empty state, error state, concurrent access)",
            f"- Integration with dependent systems verified",
            f"- No regression in existing functionality",
            f"- Documentation updated if public-facing behavior changes",
        ])

    if mvp:
        lines.append(f"- Feature is included in MVP scope and required for initial release")

    lines.append("")

    # Tech details
    lines.append("## Technical Details")
    lines.append("")
    lines.append(f"**Tech Stack:** {tech_stack}")
    lines.append(f"**Epic:** {epic_name}")
    lines.append(f"**Ticket Ref:** `{ref}`")
    if mvp:
        lines.append(f"**MVP:** Yes — required for initial product launch")

    lines.append("")
    lines.append("---")
    lines.append("")
    if epic_issue_num:
        lines.append(f"**Part of Epic:** [{epic_name}](https://github.com/{REPO}/issues/{epic_issue_num})")
    else:
        lines.append(f"**Part of Epic:** {epic_name}")
    lines.append(f"**Feature Area:** `{feature_label}`")

    return "\n".join(lines)


def parse_issues_from_file(content):
    """Parse all issues with their ref numbers from a FUTURE_FEATURE_ROADMAP file."""
    issues = []

    epic_pattern = re.compile(r'^## Epic (\d+)(?:\s*\(#(\d+)\))?: (.+)$', re.MULTILINE)
    epic_matches = list(epic_pattern.finditer(content))

    for i, epic_match in enumerate(epic_matches):
        epic_num = int(epic_match.group(1))
        epic_name = epic_match.group(3).strip()
        start = epic_match.start()
        end = epic_matches[i + 1].start() if i + 1 < len(epic_matches) else len(content)
        section = content[start:end]

        # Match rows: | N.M (#NNN) | Title | ...
        table_row = re.compile(
            r'^\|\s*(\d+\.\d+)(?:\s*\(#(\d+)\))?\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*(Yes|No)\s*\|\s*(Yes|No)',
            re.MULTILINE
        )

        # Build set of refs that have detailed descriptions
        detail_refs = set(re.findall(r'^#### (\d+\.\d+)', section, re.MULTILINE))

        for row in table_row.finditer(section):
            ref = row.group(1).strip()
            gh_num = int(row.group(2)) if row.group(2) else None
            title = row.group(3).strip()
            desc = row.group(4).strip()
            labels_cell = row.group(5).strip()
            mvp = row.group(6).strip() == 'Yes'
            labels = re.findall(r'`([^`]+)`', labels_cell)

            issues.append({
                'ref': ref,
                'gh_num': gh_num,
                'title': title,
                'description': desc,
                'labels': labels,
                'mvp': mvp,
                'has_detail': ref in detail_refs,
                'epic_num': epic_num,
                'epic_name': epic_name,
            })

    return issues


def process_file(filepath):
    """Process a single file and enhance thin issues."""
    print(f"\n{'='*60}")
    print(f"Enhancing: {os.path.basename(filepath)}")
    print(f"{'='*60}")

    with open(filepath) as f:
        content = f.read()

    feature_label = re.sub(r'^FUTURE_FEATURE_ROADMAP_', '', os.path.basename(filepath))
    feature_label = re.sub(r'\.md$', '', feature_label).lower().replace('_', '-')

    tech_stack = get_tech_stack(content)
    issues = parse_issues_from_file(content)

    thin_issues = [i for i in issues if i['gh_num'] and not i['has_detail']]
    print(f"  Total issues: {len(issues)}, thin (need enhancement): {len(thin_issues)}")

    for issue in thin_issues:
        num = issue['gh_num']
        current_body = get_issue_body(num)

        if current_body and not is_thin(current_body):
            print(f"    #{num} already has good content: {issue['ref']} {issue['title'][:40]}")
            continue

        print(f"    Enhancing #{num}: {issue['ref']} {issue['title'][:50]}...")

        epic_issue_num = get_epic_issue_num(content, issue['ref'])
        new_body = build_enhanced_body(
            issue, tech_stack, issue['epic_name'], epic_issue_num, feature_label
        )
        update_issue_body(num, new_body)
        time.sleep(1)

    print(f"  Done enhancing {os.path.basename(filepath)}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 enhance_thin_issues.py <file.md> [<file2.md> ...]")
        sys.exit(1)

    for filepath in sys.argv[1:]:
        if not os.path.exists(filepath):
            print(f"File not found: {filepath}", file=sys.stderr)
            continue
        process_file(filepath)


if __name__ == '__main__':
    main()
