#!/usr/bin/env python3
"""Create GitHub issues for FUTURE_FEATURE_ROADMAP_ROLES.md (RP-XX format)."""
import re
import subprocess
import sys
import time
import json

REPO = 'KenSuenobu/objectified-commercial'
REPO_DIR = '/home/kenji/Development/apiome'
FEATURE_LABEL = 'roles'

ROLES_FILE = f'{REPO_DIR}/FUTURE_FEATURE_ROADMAP_ROLES.md'

# Epic issue numbers (already created)
EPIC_MAP = {
    1: 1543,  # Foundation — Membership Model & Auth Context
    2: 1547,  # Policy Matrix & REST Enforcement
    3: 1553,  # UI Role-Awareness & UX
    4: 1558,  # Session Governance & MFA Policy
    5: 1564,  # Audit & Ownership
}

def create_issue(title, body, labels):
    label_str = ','.join(labels)
    result = subprocess.run(
        ['gh', 'issue', 'create', '--title', title, '--body', body, '--label', label_str],
        capture_output=True, text=True, cwd=REPO_DIR
    )
    if result.returncode != 0:
        if '403' in result.stderr or 'secondary rate' in result.stderr.lower():
            print(f"  Rate limited, waiting 120s...")
            time.sleep(120)
            result = subprocess.run(
                ['gh', 'issue', 'create', '--title', title, '--body', body, '--label', label_str],
                capture_output=True, text=True, cwd=REPO_DIR
            )
    url = result.stdout.strip()
    if not url:
        # Check if it was actually created
        time.sleep(2)
        r2 = subprocess.run(
            ['gh', 'api', f'repos/{REPO}/issues?per_page=1',
             '--jq', f'.[] | select(.title == "{title}") | .number'],
            capture_output=True, text=True, cwd=REPO_DIR
        )
        if r2.stdout.strip():
            try:
                num = int(r2.stdout.strip())
                print(f"  Created #{num} (verified): {title[:70]}")
                return num
            except ValueError:
                pass
        print(f"  WARN: no URL for '{title[:60]}'", file=sys.stderr)
        return None
    m = re.search(r'/issues/(\d+)', url)
    if m:
        num = int(m.group(1))
        print(f"  Created #{num}: {title[:70]}")
        return num
    return None


def fetch_existing(label):
    """Fetch existing issues by REST API."""
    result = subprocess.run(
        ['gh', 'api', f'repos/{REPO}/issues?labels={label}&per_page=100'],
        capture_output=True, text=True, cwd=REPO_DIR
    )
    if result.returncode != 0 or not result.stdout.strip():
        return {}
    try:
        data = json.loads(result.stdout)
        return {i['title']: i['number'] for i in data}
    except json.JSONDecodeError:
        return {}


def parse_rp_issues(content):
    """Parse RP-XX formatted issues from the ROLES file."""
    issues = []
    # Match rows like: | 1.1 (RP-01) | Title | Desc | Labels | MVP | Parallel |
    row_pat = re.compile(
        r'^\|\s*(\d+\.\d+)\s*\(RP-(\d+)\)\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*(Yes|No)\s*\|\s*(Yes|No)',
        re.MULTILINE
    )
    for m in row_pat.finditer(content):
        ref = m.group(1).strip()
        rp_num = int(m.group(2))
        title = m.group(3).strip()
        desc = m.group(4).strip()
        labels_cell = m.group(5).strip()
        mvp = m.group(6).strip() == 'Yes'
        labels = re.findall(r'`([^`]+)`', labels_cell)
        epic_num = int(ref.split('.')[0])
        issues.append({
            'ref': ref,
            'rp': f'RP-{rp_num:02d}',
            'title': title,
            'description': desc,
            'labels': labels,
            'mvp': mvp,
            'epic_num': epic_num,
            'detail': None,
        })

    # Parse detailed descriptions for RP-XX
    detail_pat = re.compile(
        r'^#### (\d+\.\d+)\s*\(RP-(\d+)\)\s*[—–-]+\s*(.+?)$(.*?)(?=^#### |\Z)',
        re.MULTILINE | re.DOTALL
    )
    details = {}
    for m in detail_pat.finditer(content):
        ref = m.group(1).strip()
        body = m.group(4).strip()
        body = re.sub(r'\n---\s*$', '', body).strip()
        details[ref] = body

    for issue in issues:
        if issue['ref'] in details:
            issue['detail'] = details[issue['ref']]

    return issues


def main():
    with open(ROLES_FILE) as f:
        content = f.read()

    existing = fetch_existing(FEATURE_LABEL)
    print(f"Found {len(existing)} existing '{FEATURE_LABEL}' issues")

    issues = parse_rp_issues(content)
    print(f"Found {len(issues)} issues in ROLES file")

    # Map ref -> issue number
    issue_map = {}

    for issue in issues:
        title = issue['title']
        epic_issue_num = EPIC_MAP.get(issue['epic_num'], 0)
        epic_name_map = {
            1: 'Foundation — Membership Model & Auth Context',
            2: 'Policy Matrix & REST Enforcement',
            3: 'UI Role-Awareness & UX',
            4: 'Session Governance & MFA Policy',
            5: 'Audit & Ownership',
        }
        epic_name = epic_name_map.get(issue['epic_num'], 'Unknown Epic')

        if title in existing:
            num = existing[title]
            print(f"  Already exists #{num}: {issue['rp']} {title[:50]}")
            issue_map[issue['ref']] = num
            continue

        # Build body
        if issue['detail']:
            body = issue['detail']
        else:
            body = issue['description']
        body += f"\n\n---\n\n**Part of Epic:** [{epic_name}](https://github.com/{REPO}/issues/{epic_issue_num})\n**Feature Area:** `{FEATURE_LABEL}`\n**Ticket Reference:** `{issue['rp']}`"

        labels = list(issue['labels'])
        if 'ai-generated' not in labels:
            labels.append('ai-generated')
        if FEATURE_LABEL not in labels:
            labels.append(FEATURE_LABEL)

        print(f"  Creating {issue['rp']}: {title[:60]}...")
        num = create_issue(title, body, labels)
        if num:
            issue_map[issue['ref']] = num
        time.sleep(2)

    # Update the ROLES markdown file with RP-XX issue numbers
    print(f"\nUpdating ROLES file with {len(issue_map)} issue numbers...")
    updated = content

    # Update table rows: | 1.1 (RP-01) | → | 1.1 (RP-01) (#NNN) |
    def replace_row(m):
        ref = m.group(1).strip()
        rp = m.group(2).strip()
        rest = m.group(3)
        num = issue_map.get(ref)
        if num:
            return f'| {ref} ({rp}) (#{num}) |{rest}'
        return m.group(0)

    updated = re.sub(
        r'^\|\s*(\d+\.\d+)\s*(RP-\d+)\s*\|([^|])',
        replace_row,
        updated,
        flags=re.MULTILINE
    )

    # Update detail headers: #### 1.1 (RP-01) — Title → #### 1.1 (RP-01) (#NNN) — Title
    def replace_detail(m):
        ref = m.group(1).strip()
        rp = m.group(2).strip()
        sep = m.group(3)
        title = m.group(4)
        num = issue_map.get(ref)
        if num:
            return f'#### {ref} ({rp}) (#{num}) {sep} {title}'
        return m.group(0)

    updated = re.sub(
        r'^#### (\d+\.\d+)\s*\((RP-\d+)\)\s*([—–-]+)\s*(.+)$',
        replace_detail,
        updated,
        flags=re.MULTILINE
    )

    with open(ROLES_FILE, 'w') as f:
        f.write(updated)

    print(f"Done. Updated ROLES file.")
    missing = set(i['ref'] for i in issues) - set(issue_map.keys())
    if missing:
        print(f"WARNING: {len(missing)} missing: {sorted(missing)}")


if __name__ == '__main__':
    main()
