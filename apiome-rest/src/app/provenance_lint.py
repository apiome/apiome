"""Inference-provenance lint pack — the inferred-construct ratio as a coverage signal, FMT-8.6 (#5467).

The shared vocabulary (:mod:`app.inference_provenance`) says, per construct, whether the source
declared it, Apiome inferred it, or Apiome synthesized it. This pack turns that into one lint
finding a reviewer and a style guide can act on:

* ``provenance.inferred-construct-ratio`` reports what share of the artifact's constructs are
  inferred — "62% of this item's constructs are inferred (13 of 21)". It fires only when at
  least one construct is inferred, so a declarative source (OpenAPI, protobuf, a TypeScript
  module) never carries it, and it is one finding per artifact, so it costs the score at most
  one ``info`` penalty under the default guide.

The rule ships at ``info``. A style guide that wants inferred surfaces kept out of published
APIs raises it to ``error``: every lint entry point applies the guide, and an ``error``
finding blocks publication (GOV-2.5) until it is fixed — by importing a declared source — or
the publish is forced with a reason.

The pack runs for every format (it is one of :func:`app.lint_engine.unconditional_rule_packs`)
because inference is a property of the model, not of one syntax.
"""

from __future__ import annotations

from typing import ClassVar, Iterable, List, Tuple

from .canonical_model import CanonicalApi
from .inference_provenance import summarize_provenance
from .lint_engine import LintRule, RulePack

__all__ = ["INFERRED_RATIO_RULE_ID", "ProvenanceRulePack", "inferred_ratio_message"]

#: The stable id of the inferred-construct-ratio rule.
INFERRED_RATIO_RULE_ID = "provenance.inferred-construct-ratio"


def inferred_ratio_message(inferred: int, synthesized: int, total: int, percent: int) -> str:
    """The finding message for an artifact with inferred constructs.

    Args:
        inferred: How many constructs are inferred.
        synthesized: How many are synthesized.
        total: How many constructs the artifact has.
        percent: ``inferred / total`` as a whole percentage.

    Returns:
        ``"62% of this item's constructs are inferred (13 of 21)."`` plus a synthesized count
        when there are any.
    """
    message = f"{percent}% of this item's constructs are inferred ({inferred} of {total})."
    if synthesized:
        message += f" {synthesized} more are synthesized by Apiome."
    return message


def _check_inferred_construct_ratio(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Report the inferred share of the artifact's constructs, when any are inferred."""
    summary = summarize_provenance(api)
    if summary.inferred:
        yield (
            "api",
            inferred_ratio_message(
                summary.inferred, summary.synthesized, summary.total, summary.inferred_percent
            ),
        )


class ProvenanceRulePack(RulePack):
    """The unconditional pack that reports how much of an artifact Apiome inferred."""

    pack_id: ClassVar[str] = "provenance"

    _RULES: ClassVar[Tuple[LintRule, ...]] = (
        LintRule(
            rule_id=INFERRED_RATIO_RULE_ID,
            category="provenance",
            severity="info",
            description=(
                "Reports the share of constructs Apiome inferred rather than read from a "
                "declaration; raise it to error in a style guide to keep inferred APIs from "
                "being published."
            ),
            check=_check_inferred_construct_ratio,
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the pack's rules in execution order."""
        return list(self._RULES)
