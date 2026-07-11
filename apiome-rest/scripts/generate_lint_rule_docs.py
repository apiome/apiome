#!/usr/bin/env python3
"""
Generate the built-in lint-rule reference page from the rule-catalog registry (GOV-1.2, #4428).

Renders every descriptor in :mod:`app.lint_rule_registry` to ``docs/guide/lint-rules.md`` at the
monorepo root — the page every registry ``docs_anchor`` points into. Each rule gets an explicit
``<a id="...">`` marker matching its anchor slug, so links stay valid regardless of how a
renderer slugifies headings. Re-run this script whenever a rule is added or its metadata changes;
``tests/test_lint_rule_registry.py`` fails if the page and the registry drift apart.

Run from the apiome-rest directory:
    uv run python scripts/generate_lint_rule_docs.py
    # or
    PYTHONPATH=src python scripts/generate_lint_rule_docs.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the app package is importable, mirroring scripts/generate_openapi.py.
project_root = Path(__file__).resolve().parent.parent
src = project_root / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

from app.lint_rule_registry import builtin_rule_descriptors  # noqa: E402

HEADER = """\
# Built-in lint rules

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_lint_rule_docs.py -->

Reference for every built-in lint rule in the rule-catalog registry (GOV-1.2). Each rule's
**id is stable** — it is exactly the string lint findings carry in their `rule` field, so a
violation always links back to the rule documented here. The **default severity** is what the
rule applies when no style guide overrides it.

Fetch this catalog programmatically with `GET /v1/lint/rules` (see
[lint-and-quality.md](lint-and-quality.md)).
"""


def render(descriptors) -> str:
    """Render the descriptors to the full markdown page, grouped by pack."""
    lines = [HEADER]
    by_pack: dict = {}
    for d in descriptors:
        by_pack.setdefault(d.pack, []).append(d)
    for pack in sorted(by_pack):
        lines.append(f"\n## Pack: `{pack}`\n")
        for d in by_pack[pack]:
            lines.append(f'<a id="{d.docs_anchor}"></a>')
            lines.append(f"### `{d.rule_id}`\n")
            lines.append(f"- **Category:** {d.category}")
            lines.append(f"- **Default severity:** {d.default_severity}")
            lines.append(f"- **Rationale:** {d.rationale}\n")
    return "\n".join(lines)


def main() -> None:
    out_path = project_root.parent / "docs" / "guide" / "lint-rules.md"
    out_path.write_text(render(builtin_rule_descriptors()), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
