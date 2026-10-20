#!/usr/bin/env python3
"""
Generate / refresh CLX-4.3 rule transparency docs.

Writes:
  - apiome-docs/docs/build/lint-rules.md (schema packs, with blocking transparency fields)
  - apiome-docs/docs/govern/mcp-surface-lint-rules.md
  - apiome-docs/docs/govern/mcp-conformance-rules.md
  - apiome-docs/docs/govern/mcp-trust-posture-rules.md
  - the generated security-score block of apiome-docs/docs/build/axis-score.md (between the
    ``security-score:begin`` / ``security-score:end`` markers): the formula constants, every
    published per-rule weight and the OWASP API Top 10 categories — ASP-1.3 (#5921) requires
    the weights to be documented from code, never typed by hand.

Each page is a docs-site page (DOCS-1.2, #5619), so it opens with Docusaurus front matter.

Run from apiome-rest:
    uv run python scripts/generate_lint_rule_docs.py
"""

from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
src = project_root / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

from app.axis_score import ALGORITHM_DOCS_PAGE  # noqa: E402
from app.docs_site import render_front_matter  # noqa: E402
from app.lint_rule_registry import LINT_RULE_DOCS_PAGE, builtin_rule_descriptors  # noqa: E402
from app.owasp_api import CATALOG_REFERENCE, CATALOG_REVISION, RISK_IDS, RISKS  # noqa: E402
from app.schema_lint import GRADE_THRESHOLDS, PER_RULE_PENALTY_CAP, SEVERITY_PENALTY  # noqa: E402
from app.security_score import (  # noqa: E402
    DEFAULT_SECURITY_RULE_WEIGHT,
    published_weights,
    rule_owasp_ids,
    rules_by_owasp_risk,
)
from app.mcp_conformance import RULE_REGISTRY as CONFORMANCE_RULES  # noqa: E402
from app.mcp_lint import RULE_CATALOGUE  # noqa: E402
import app.mcp_probe  # noqa: E402,F401  — registers proven posture bridge rules
from app.mcp_trust_posture import RULE_REGISTRY as POSTURE_RULES  # noqa: E402
from app.scanner_rule_transparency import (  # noqa: E402
    MCP_CONFORMANCE_RULES_DOCS_PAGE,
    MCP_POSTURE_RULES_DOCS_PAGE,
    MCP_SURFACE_RULES_DOCS_PAGE,
    get_blocking_meta,
)

MONOREPO = project_root.parent

#: Markers delimiting the generated block inside the hand-written axis-score page.
SECURITY_BLOCK_BEGIN = "<!-- security-score:begin -->"
SECURITY_BLOCK_END = "<!-- security-score:end -->"


HEADER_SCHEMA = render_front_matter(
    "Built-in lint rules",
    "Every built-in lint rule: stable id, default severity and rationale.",
    7,
    ["lint", "reference"],
) + """\
<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_lint_rule_docs.py -->

Reference for every built-in lint rule in the rule-catalog registry (GOV-1.2). Each rule's
**id is stable** — it is exactly the string lint findings carry in their `rule` field, so a
violation always links back to the rule documented here. The **default severity** is what the
rule applies when no style guide overrides it.

Blocking (`error`) rules additionally publish reference, remediation, false-positive guidance,
fixture id, and scan-mode requirements (CLX-4.3 / #4861). See
[scanner evaluation](https://github.com/apiome/apiome/blob/main/apiome-rest/docs/scanner_evaluation.md).

Fetch this catalog programmatically with `GET /v1/lint/rules` (see
[Lint and check quality](./lint-and-quality.md)).
"""


def _blocking_section(rule_id: str) -> list[str]:
    meta = get_blocking_meta(rule_id)
    if meta is None:
        return []
    return [
        f"- **Reference:** {meta.reference}",
        f"- **Remediation:** {meta.remediation}",
        f"- **False-positive guidance:** {meta.false_positive_guidance}",
        f"- **Fixture:** `{meta.fixture_id}`",
        f"- **Scan modes:** {', '.join(f'`{m}`' for m in meta.scan_modes)}",
        "",
    ]


def _transparency_section(descriptor) -> list[str]:
    """Render the transparency block for one catalogued schema rule, blocking or not.

    A blocking rule's block comes from the CLX-4.3 catalogue. A non-blocking rule whose pack
    publishes its own remediation and fixture (FMT-5.5) gets the same treatment from the
    enriched catalog payload, so the reference page does not tell a reader how to fix a rule
    only when that rule can fail a gate.
    """
    blocking = _blocking_section(descriptor.rule_id)
    if blocking:
        return blocking
    payload = descriptor.as_dict()
    if not payload.get("remediation"):
        return []
    lines = [f"- **Remediation:** {payload['remediation']}"]
    if payload.get("fixture_id"):
        lines.append(f"- **Fixture:** `{payload['fixture_id']}`")
    lines.append("")
    return lines


def render_schema(descriptors) -> str:
    lines = [HEADER_SCHEMA]
    by_pack: dict = {}
    for d in descriptors:
        by_pack.setdefault(d.pack, []).append(d)
    for pack in sorted(by_pack):
        lines.append(f"\n## Pack: `{pack}`\n")
        for d in by_pack[pack]:
            lines.append(f"### `{d.rule_id}` {{#{d.docs_anchor}}}\n")
            lines.append(f"- **Category:** {d.category}")
            lines.append(f"- **Default severity:** {d.default_severity}")
            lines.append(f"- **Rationale:** {d.rationale}")
            if d.owasp_ids:
                lines.append(f"- **OWASP API:** {', '.join(d.owasp_ids)}")
            if d.weight is not None:
                lines.append(f"- **Security weight:** {d.weight:.1f}")
            section = _transparency_section(d)
            lines.extend(section)
            if not section:
                lines.append("")
    return "\n".join(lines)


def render_security_score_block() -> str:
    """Render the generated security-score block for the axis-score page (ASP-1.3, #5921).

    Everything in it is read from code: the severity penalties, the per-rule cap and the
    grade bands (:mod:`app.schema_lint`), the published per-rule weights
    (:func:`app.security_score.published_weights`) and the OWASP API Security Top 10
    categories with how many catalogued rules cite each (:mod:`app.owasp_api`).
    """
    lines = [
        SECURITY_BLOCK_BEGIN,
        "<!-- GENERATED BLOCK — do not edit by hand.",
        "     Regenerate with: cd apiome-rest && uv run python scripts/generate_lint_rule_docs.py -->",
        "",
        "#### Constants",
        "",
        "| Constant | Value |",
        "|---|---|",
    ]
    for severity in ("error", "warning", "info"):
        lines.append(f"| `{severity}` penalty | {SEVERITY_PENALTY[severity]:g} |")
    lines.append(f"| Per-rule penalty cap | {PER_RULE_PENALTY_CAP:g} |")
    lines.append(f"| Default rule weight | {DEFAULT_SECURITY_RULE_WEIGHT:.1f} |")
    bands = ", ".join(
        f"{grade} ≥ {threshold}" for threshold, grade in GRADE_THRESHOLDS if grade != "F"
    )
    lines.append(f"| Grade bands | {bands}, else F |")
    lines += [
        "",
        "#### Published rule weights",
        "",
        "| Rule | Weight | OWASP API | In the catalog |",
        "|---|---|---|---|",
    ]
    for row in published_weights():
        owasp = ", ".join(row["owasp"]) if row["owasp"] else "—"
        status = "yes" if row["registered"] else "reserved — the rule has not shipped yet"
        lines.append(f"| `{row['rule_id']}` | {row['weight']:.1f} | {owasp} | {status} |")
    lines += [
        "",
        f"Every other `security` rule weighs {DEFAULT_SECURITY_RULE_WEIGHT:.1f}.",
        "",
        f"#### OWASP API Security Top 10 ({CATALOG_REVISION}) categories",
        "",
        f"Reference: {CATALOG_REFERENCE}",
        "",
        "| Id | Category | Rules in the catalog |",
        "|---|---|---|",
    ]
    by_risk = rules_by_owasp_risk(rule_owasp_ids())
    for risk_id in RISK_IDS:
        risk = RISKS[risk_id]
        lines.append(f"| {risk_id} | [{risk.title}]({risk.reference}) | {len(by_risk[risk_id])} |")
    lines += ["", SECURITY_BLOCK_END]
    return "\n".join(lines)


def splice_security_score_block(page: Path) -> None:
    """Replace the marked block of ``page`` with :func:`render_security_score_block`.

    The axis-score page is hand-written around the block, so only the text between the
    markers is regenerated.

    Raises:
        ValueError: when the page carries no marker pair to splice into.
    """
    text = page.read_text(encoding="utf-8")
    begin = text.find(SECURITY_BLOCK_BEGIN)
    end = text.find(SECURITY_BLOCK_END)
    if begin < 0 or end < 0 or end < begin:
        raise ValueError(f"{page} has no {SECURITY_BLOCK_BEGIN} … {SECURITY_BLOCK_END} block")
    end += len(SECURITY_BLOCK_END)
    page.write_text(text[:begin] + render_security_score_block() + text[end:], encoding="utf-8")


def _mcp_header(title: str, description: str, position: int, body: str) -> str:
    """Render an MCP rule page's front matter, generated-file warning and intro paragraph."""
    return (
        render_front_matter(title, description, position, ["mcp", "governance", "reference"])
        + "<!-- GENERATED FILE — do not edit by hand.\n"
        "     Regenerate with: cd apiome-rest && uv run python scripts/generate_lint_rule_docs.py -->\n\n"
        f"{body}\n"
    )


def render_surface() -> str:
    lines = [
        _mcp_header(
            "MCP surface lint rules",
            "Every lint rule Apiome applies to an MCP server's tool surface.",
            4,
            "Catalog for :mod:`app.mcp_lint`. Blocking rules include CLX-4.3 transparency "
            "fields. Fetch via `GET /v1/mcp/lint/rules`.",
        )
    ]
    for rule_id in sorted(RULE_CATALOGUE):
        category, severity = RULE_CATALOGUE[rule_id]
        meta = get_blocking_meta(rule_id)
        anchor = rule_id.replace(".", "-")
        lines.append(f"### `{rule_id}` {{#{anchor}}}\n")
        lines.append(f"- **Category:** {category}")
        lines.append(f"- **Severity:** {severity}")
        if meta:
            lines.append(f"- **Rationale:** {meta.rationale}")
            lines.extend(_blocking_section(rule_id))
        else:
            lines.append("")
    return "\n".join(lines)


def render_conformance() -> str:
    lines = [
        _mcp_header(
            "MCP conformance rules",
            "Every MCP conformance rule, with its specification reference and severity.",
            3,
            "Catalog for :mod:`app.mcp_conformance`. Every rule cites an MCP specification "
            "reference. Blocking rules include CLX-4.3 transparency fields. "
            "Fetch via `GET /v1/mcp/conformance/rules`.",
        )
    ]
    for rule in sorted(CONFORMANCE_RULES.values(), key=lambda r: r.rule_id):
        anchor = rule.rule_id.replace(".", "-")
        lines.append(f"### `{rule.rule_id}` {{#{anchor}}}\n")
        lines.append(f"- **Category:** {rule.category}")
        lines.append(f"- **Severity:** {rule.severity}")
        lines.append(f"- **Spec version:** {rule.spec_version}")
        lines.append(f"- **Spec reference:** {rule.spec_reference}")
        lines.append(f"- **Rationale:** {rule.rationale}")
        lines.append(f"- **Requires transcript:** {rule.requires_transcript}")
        lines.extend(_blocking_section(rule.rule_id))
        if get_blocking_meta(rule.rule_id) is None:
            lines.append("")
    return "\n".join(lines)


def render_posture() -> str:
    lines = [
        _mcp_header(
            "MCP trust-posture rules",
            "Trust-posture rules for MCP servers, mapped to the OWASP MCP Top 10.",
            5,
            "Catalog for :mod:`app.mcp_trust_posture`, mapped to the OWASP MCP Top 10. "
            "Blocking rules include CLX-4.3 transparency fields. "
            "Fetch via `GET /v1/mcp/trust-posture/rules`.",
        )
    ]
    for rule in sorted(POSTURE_RULES.values(), key=lambda r: r.rule_id):
        anchor = rule.rule_id.replace(".", "-")
        lines.append(f"### `{rule.rule_id}` {{#{anchor}}}\n")
        lines.append(f"- **Origin:** {rule.origin}")
        lines.append(f"- **Severity:** {rule.severity}")
        lines.append(f"- **OWASP:** {', '.join(rule.owasp_ids)}")
        lines.append(f"- **Reference:** {rule.reference}")
        lines.append(f"- **Requires:** {rule.requires}")
        lines.append(f"- **Rationale:** {rule.rationale}")
        lines.extend(_blocking_section(rule.rule_id))
        if get_blocking_meta(rule.rule_id) is None:
            lines.append("")
    return "\n".join(lines)


def main() -> None:
    out_schema = MONOREPO / LINT_RULE_DOCS_PAGE
    out_schema.write_text(render_schema(builtin_rule_descriptors()), encoding="utf-8")
    print(f"Wrote {out_schema}")

    mapping = {
        MCP_SURFACE_RULES_DOCS_PAGE: render_surface(),
        MCP_CONFORMANCE_RULES_DOCS_PAGE: render_conformance(),
        MCP_POSTURE_RULES_DOCS_PAGE: render_posture(),
    }
    for page, body in mapping.items():
        path = MONOREPO / page
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        print(f"Wrote {path}")

    axis_page = MONOREPO / ALGORITHM_DOCS_PAGE
    splice_security_score_block(axis_page)
    print(f"Updated security-score block in {axis_page}")


if __name__ == "__main__":
    main()
