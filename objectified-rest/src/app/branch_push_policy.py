"""
Evaluate branch push policy: block direct push when merge path is required (#2583).

Project metadata may define glob patterns::

    {
      "branchPushPolicy": {
        "patterns": [
          { "pattern": "main", "requireMergePath": true },
          { "pattern": "release/*", "requireMergePath": true }
        ]
      }
    }

Per-branch column ``version_branches.require_merge_path`` OR a matching pattern enables the rule.
Tenant administrators may bypass (direct push) for break-glass workflows.
"""

from __future__ import annotations

import fnmatch
import json
from typing import Any, Dict, Mapping, Optional


def _metadata_as_dict(metadata: Any) -> Dict[str, Any]:
    if metadata is None:
        return {}
    if isinstance(metadata, dict):
        return metadata
    if isinstance(metadata, str):
        try:
            parsed = json.loads(metadata)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def project_patterns_require_merge_path(metadata: Any, branch_name: str) -> bool:
    """True if project ``branchPushPolicy.patterns`` matches ``branch_name`` with requireMergePath."""
    m = _metadata_as_dict(metadata)
    policy = m.get("branchPushPolicy") or m.get("branch_push_policy")
    if not isinstance(policy, Mapping):
        return False
    raw = policy.get("patterns") or policy.get("Patterns")
    if not isinstance(raw, list):
        return False
    bn = (branch_name or "").strip()
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        pat = entry.get("pattern") or entry.get("Pattern")
        if not isinstance(pat, str) or not pat.strip():
            continue
        want = entry.get("requireMergePath")
        if want is None:
            want = entry.get("require_merge_path")
        if not bool(want):
            continue
        if fnmatch.fnmatchcase(bn, pat.strip()):
            return True
    return False


def effective_require_merge_path(
    *,
    project_metadata: Any,
    branch_row: Mapping[str, Any],
) -> bool:
    """Whether this push target branch requires the merge workflow (not a direct tip push)."""
    if bool(branch_row.get("require_merge_path")):
        return True
    name = str(branch_row.get("name") or "")
    return project_patterns_require_merge_path(project_metadata, name)
