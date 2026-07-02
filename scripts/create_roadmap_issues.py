#!/usr/bin/env python3
"""
Idempotent GitHub issue creator for FUTURE_FEATURE_ROADMAP markdown files.

For each file:
1. Fetches all existing GitHub issues with the feature label
2. Matches by title to avoid duplicates
3. Creates only missing issues
4. Updates the markdown file with all issue numbers

Usage: python3 create_roadmap_issues.py <file.md> [<file2.md> ...]
"""

import re
import subprocess
import sys
import os
import time
import json

REPO = 'KenSuenobu/objectified-commercial'
REPO_DIR = '/home/kenji/Development/apiome'


def run_gh_json(args):
    """Run a gh command expecting JSON output. Returns parsed JSON or None on failure."""
    cmd = ['gh'] + args
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_DIR)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def create_issue_api(title, body, labels):
    """Create a GitHub issue via API and return the issue number."""
    label_str = ','.join(labels)
    # Use gh issue create which reliably outputs the URL
    result = subprocess.run(
        ['gh', 'issue', 'create',
         '--title', title,
         '--body', body,
         '--label', label_str],
        capture_output=True, text=True, cwd=REPO_DIR
    )
    if result.returncode != 0:
        # Check for rate limit
        if '403' in result.stderr or 'secondary rate limit' in result.stderr.lower():
            print(f"    Rate limited — waiting 120s...", file=sys.stderr)
            time.sleep(120)
            # Retry once
            result = subprocess.run(
                ['gh', 'issue', 'create',
                 '--title', title,
                 '--body', body,
                 '--label', label_str],
                capture_output=True, text=True, cwd=REPO_DIR
            )
        if result.returncode != 0:
            print(f"    ERROR creating '{title}': {result.stderr[:200]}", file=sys.stderr)
            return None

    url = result.stdout.strip()
    if not url:
        # gh issue create sometimes silently fails during secondary rate limiting
        # Verify via API that the issue was actually created
        time.sleep(2)
        result2 = subprocess.run(
            ['gh', 'api',
             f'repos/{REPO}/issues?per_page=1',
             '--jq', f'.[] | select(.title == "{title}") | .number'],
            capture_output=True, text=True, cwd=REPO_DIR
        )
        if result2.stdout.strip():
            try:
                num = int(result2.stdout.strip())
                print(f"    Created #{num} (verified): {title[:70]}")
                return num
            except ValueError:
                pass
        print(f"    WARN: gh issue create returned no URL for '{title[:50]}'", file=sys.stderr)
        return None

    m = re.search(r'/issues/(\d+)', url)
    if m:
        num = int(m.group(1))
        print(f"    Created #{num}: {title[:70]}")
        return num
    return None


def fetch_existing_issues_by_label(feature_label):
    """Fetch all existing issues with the given label via REST API. Returns dict of title → number."""
    all_issues = {}
    page = 1
    while True:
        result = subprocess.run(
            ['gh', 'api',
             f'repos/{REPO}/issues?labels={feature_label}&per_page=100&page={page}&state=open'],
            capture_output=True, text=True, cwd=REPO_DIR
        )
        if result.returncode != 0:
            break
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            break
        if not data:
            break
        for item in data:
            all_issues[item['title']] = item['number']
        if len(data) < 100:
            break
        page += 1
    return all_issues


def fetch_existing_issues(feature_label):
    """Fetch all existing issues with the given label. Returns dict of title → number."""
    return fetch_existing_issues_by_label(feature_label)


def fetch_existing_epics(feature_label):
    """Fetch all existing epic issues with the given label. Returns dict of title → number."""
    all_issues = fetch_existing_issues_by_label(feature_label)
    return {title: num for title, num in all_issues.items() if title.startswith('[Epic]')}


def parse_labels_from_cell(cell):
    """Extract label names from a table cell like '`enhancement`, `mvp`, `ai`'."""
    return re.findall(r'`([^`]+)`', cell)


def parse_epic_sections(content):
    """
    Parse markdown content and return list of epics with their issues.
    Also extracts existing issue numbers if already present in the file.
    """
    epics = []
    epic_pattern = re.compile(r'^## Epic (\d+)(?:\s*\(#(\d+)\))?: (.+)$', re.MULTILINE)
    epic_matches = list(epic_pattern.finditer(content))

    for i, epic_match in enumerate(epic_matches):
        epic_num = int(epic_match.group(1))
        existing_epic_issue = int(epic_match.group(2)) if epic_match.group(2) else None
        epic_name = epic_match.group(3).strip()

        start = epic_match.start()
        end = epic_matches[i + 1].start() if i + 1 < len(epic_matches) else len(content)
        section = content[start:end]

        issues = []

        # Match table rows with optional existing issue number
        # Pattern: | 1.1 | or | 1.1 (#NNN) |
        table_row = re.compile(
            r'^\|\s*(\d+\.\d+)(?:\s*\(#(\d+)\))?\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*(Yes|No)\s*\|\s*(Yes|No)',
            re.MULTILINE
        )
        for row in table_row.finditer(section):
            ref = row.group(1).strip()
            existing_num = int(row.group(2)) if row.group(2) else None
            title = row.group(3).strip()
            desc = row.group(4).strip()
            labels_cell = row.group(5).strip()
            mvp = row.group(6).strip() == 'Yes'
            labels = parse_labels_from_cell(labels_cell)

            issues.append({
                'ref': ref,
                'title': title,
                'description': desc,
                'labels': labels,
                'mvp': mvp,
                'detail': None,
                'epic_name': epic_name,
                'epic_num': epic_num,
                'existing_num': existing_num,
            })

        # Parse detailed descriptions
        detail_pattern = re.compile(
            r'^#### (\d+\.\d+)(?:\s*\(#\d+\))?\s*[—–-]+\s*(.+?)$(.*?)(?=^#### |\Z)',
            re.MULTILINE | re.DOTALL
        )
        details = {}
        for dm in detail_pattern.finditer(section):
            ref = dm.group(1).strip()
            detail_body = dm.group(3).strip()
            detail_body = re.sub(r'\n---\s*$', '', detail_body).strip()
            details[ref] = detail_body

        for issue in issues:
            if issue['ref'] in details:
                issue['detail'] = details[issue['ref']]

        epics.append({
            'number': epic_num,
            'name': epic_name,
            'issues': issues,
            'existing_num': existing_epic_issue,
        })

    return epics


def get_feature_label(filename):
    """Derive the feature-area label from the filename."""
    base = os.path.basename(filename)
    name = re.sub(r'^FUTURE_FEATURE_ROADMAP_', '', base)
    name = re.sub(r'\.md$', '', name)
    return name.lower().replace('_', '-')


def build_epic_body(epic, feature_label):
    """Build the body text for an epic parent issue."""
    lines = [
        f"## Epic {epic['number']}: {epic['name']}",
        "",
        f"This is the parent epic for all issues related to **{epic['name']}**.",
        "",
        "### Sub-issues",
        "",
    ]
    for issue in epic['issues']:
        mvp_marker = " *(MVP)*" if issue['mvp'] else ""
        lines.append(f"- [ ] {issue['ref']} — {issue['title']}{mvp_marker}")
    lines.append("")
    lines.append(f"**Feature Area:** `{feature_label}`")
    return "\n".join(lines)


def build_issue_body(issue, epic_issue_num, feature_label):
    """Build the body for a sub-issue."""
    lines = []
    if issue['detail']:
        lines.append(issue['detail'])
    else:
        lines.append(issue['description'])

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"**Part of Epic:** [{issue['epic_name']}](https://github.com/{REPO}/issues/{epic_issue_num})")
    lines.append(f"**Feature Area:** `{feature_label}`")
    return "\n".join(lines)


def update_markdown(content, issue_map, epic_map):
    """Update markdown content with issue numbers. Returns updated content."""
    updated = content

    # Update epic headings: ## Epic N: Name → ## Epic N (#NNN): Name
    def replace_epic_ref(m):
        epic_n = int(m.group(1))
        existing = m.group(2)  # existing number if present
        name = m.group(3)
        num = epic_map.get(epic_n)
        if num and not existing:
            return f'## Epic {epic_n} (#{num}): {name}'
        elif existing:
            return m.group(0)  # already has number
        return m.group(0)

    updated = re.sub(
        r'^## Epic (\d+)(?:\s*\(#(\d+)\))?: (.+)$',
        replace_epic_ref,
        updated,
        flags=re.MULTILINE
    )

    # Update summary table rows: | 1.1 | Title | → | 1.1 (#N) | Title |
    def replace_table_ref(m):
        ref = m.group(1)
        existing = m.group(2)  # existing number if present
        rest = m.group(3)
        num = issue_map.get(ref)
        if num and not existing:
            return f'| {ref} (#{num}) |{rest}'
        elif existing:
            return m.group(0)  # already has number
        return m.group(0)

    updated = re.sub(
        r'^\|\s*(\d+\.\d+)(?:\s*\(#(\d+)\))?\s*\|([^|])',
        replace_table_ref,
        updated,
        flags=re.MULTILINE
    )

    # Update detailed section headers: #### 1.1 — Title → #### 1.1 (#N) — Title
    def replace_detail_ref(m):
        ref = m.group(1)
        existing = m.group(2)  # existing number if present
        sep = m.group(3)
        title = m.group(4)
        num = issue_map.get(ref)
        if num and not existing:
            return f'#### {ref} (#{num}) {sep} {title}'
        elif existing:
            return m.group(0)
        return m.group(0)

    updated = re.sub(
        r'^#### (\d+\.\d+)(?:\s*\(#(\d+)\))?\s*([—–-]+)\s*(.+)$',
        replace_detail_ref,
        updated,
        flags=re.MULTILINE
    )

    return updated


def process_file(filepath):
    """Process a single FUTURE_FEATURE_ROADMAP file and create GitHub issues."""
    print(f"\n{'='*60}")
    print(f"Processing: {os.path.basename(filepath)}")
    print(f"{'='*60}")

    with open(filepath, 'r') as f:
        content = f.read()

    feature_label = get_feature_label(filepath)
    print(f"Feature label: {feature_label}")

    # Fetch existing issues to avoid duplicates
    print(f"  Fetching existing issues with label '{feature_label}'...")
    existing_by_title = fetch_existing_issues(feature_label)
    existing_epics = fetch_existing_epics(feature_label)
    print(f"  Found {len(existing_by_title)} existing issues, {len(existing_epics)} existing epics")

    epics = parse_epic_sections(content)
    total_issues = sum(len(e['issues']) for e in epics)
    print(f"  Found {len(epics)} epics with {total_issues} issues in file")

    # Map to track ref → issue_num and epic_number → epic_issue_num
    issue_map = {}
    epic_map = {}

    # Load already-recorded numbers from the file
    for epic in epics:
        if epic['existing_num']:
            epic_map[epic['number']] = epic['existing_num']
        for issue in epic['issues']:
            if issue['existing_num']:
                issue_map[issue['ref']] = issue['existing_num']

    for epic in epics:
        epic_title = f"[Epic] {epic['name']}"

        # Check if epic already exists
        if epic['existing_num']:
            epic_map[epic['number']] = epic['existing_num']
            print(f"\n  Epic already recorded #{epic['existing_num']}: {epic['name']}")
        elif epic_title in existing_by_title:
            epic_map[epic['number']] = existing_by_title[epic_title]
            print(f"\n  Epic already exists #{existing_by_title[epic_title]}: {epic['name']}")
        elif epic_title in existing_epics:
            epic_map[epic['number']] = existing_epics[epic_title]
            print(f"\n  Epic already exists #{existing_epics[epic_title]}: {epic['name']}")
        else:
            # Create the epic
            epic_labels = ['epic', 'ai-generated', feature_label]
            if any(i['mvp'] for i in epic['issues']):
                epic_labels.append('mvp')

            epic_body = build_epic_body(epic, feature_label)
            print(f"\n  Creating epic: {epic_title}")
            num = create_issue_api(epic_title, epic_body, epic_labels)
            if num is None:
                print(f"  Failed to create epic '{epic_title}', continuing with next epic...", file=sys.stderr)
                continue
            epic_map[epic['number']] = num
            time.sleep(2)

        epic_num = epic_map.get(epic['number'])

        # Create sub-issues
        for issue in epic['issues']:
            if issue['ref'] in issue_map:
                print(f"    Already recorded #{issue_map[issue['ref']]}: {issue['ref']} {issue['title'][:50]}")
                continue

            if issue['title'] in existing_by_title:
                num = existing_by_title[issue['title']]
                print(f"    Already exists #{num}: {issue['ref']} {issue['title'][:50]}")
                issue_map[issue['ref']] = num
                continue

            sub_labels = list(issue['labels'])
            if 'ai-generated' not in sub_labels:
                sub_labels.append('ai-generated')
            if feature_label not in sub_labels:
                sub_labels.append(feature_label)

            body = build_issue_body(issue, epic_num or 0, feature_label)
            num = create_issue_api(issue['title'], body, sub_labels)
            if num:
                issue_map[issue['ref']] = num
            time.sleep(2)

    # Always update the markdown file with whatever we have
    print(f"\n  Updating markdown file with {len(issue_map)} issues + {len(epic_map)} epics...")
    updated = update_markdown(content, issue_map, epic_map)
    with open(filepath, 'w') as f:
        f.write(updated)

    print(f"  Done. {os.path.basename(filepath)}")

    # Report any missing
    all_refs = set()
    for epic in epics:
        all_refs.update(issue['ref'] for issue in epic['issues'])
    missing = all_refs - set(issue_map.keys())
    if missing:
        print(f"  WARNING: {len(missing)} issues still missing: {sorted(missing)[:10]}")

    return issue_map, epic_map


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 create_roadmap_issues.py <file.md> [<file2.md> ...]")
        sys.exit(1)

    for filepath in sys.argv[1:]:
        if not os.path.exists(filepath):
            print(f"File not found: {filepath}", file=sys.stderr)
            continue
        process_file(filepath)


if __name__ == '__main__':
    main()
