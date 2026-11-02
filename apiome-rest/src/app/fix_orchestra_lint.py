"""FIX Orchestra lint pack — MFI-20.4 (#3988).

Native, deterministic quality rules for FIX Orchestra repositories, layered on the canonical lint
engine (MFI-4.1 :mod:`app.lint_engine`) the way the Thrift pack (:mod:`app.thrift_lint`) is. The
:class:`FixOrchestraRulePack` is registered under the ``fix-orchestra`` format key, so it runs with
the always-on common pack on every Orchestra artifact. The rules read only the canonical model
:mod:`app.fix_orchestra_normalizer` builds:

* **fix-orchestra.message-msgtype-declared** (error) — a message without a ``msgType`` cannot be
  routed: tag 35 is how a counterparty tells messages apart.
* **fix-orchestra.msgtype-unique** (error) — two base-scenario messages share a ``msgType``: a
  received message matches both definitions.
* **fix-orchestra.message-not-empty** (warning) — a message declares no fields, components or
  groups.
* **fix-orchestra.codeset-not-empty** (warning) — a code set declares no codes, so the field it
  types can carry no value.
* **fix-orchestra.code-values-unique** (error) — two codes of a code set share a wire value.
* **fix-orchestra.conditional-rule-declared** (warning) — a ``conditional`` field declares no
  rule, so nothing says when it is required.
* **fix-orchestra.repository-version-declared** (info) — the repository names no FIX ``version``.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from .canonical_model import CanonicalApi, TypeKind
from .lint_engine import LintRule, RulePack

__all__ = ["FixOrchestraRulePack"]


def _is_message(type_: Any) -> bool:
    return type_.extras.get("fix_kind") == "message"


def _check_message_msgtype_declared(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Every message must carry a ``msgType``."""
    for api_type in sorted(api.types, key=lambda t: t.key):
        if _is_message(api_type) and not api_type.extras.get("fix_msg_type"):
            yield (
                f"types.{api_type.key}",
                f"Message '{api_type.name}' declares no msgType; a counterparty cannot route it. "
                "Set msgType to its tag-35 value, e.g. 'D' for NewOrderSingle.",
            )


def _check_msgtype_unique(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """No two base-scenario messages may share a ``msgType``."""
    messages: Mapping[str, Any] = {}
    listed = api.extras.get("fix_messages")
    if not isinstance(listed, list):
        return
    by_type: Dict[str, List[str]] = {}
    for message in listed:
        if not isinstance(message, Mapping):
            continue
        msg_type, name, scenario = message.get("msgType"), message.get("name"), message.get("scenario")
        if msg_type and name and scenario in (None, "base"):
            by_type.setdefault(str(msg_type), []).append(str(name))
    for msg_type, names in sorted(by_type.items()):
        if len(names) > 1:
            yield (
                f"messages.{msg_type}",
                f"msgType '{msg_type}' is declared by {', '.join(sorted(names))}; a received "
                "message matches more than one definition.",
            )
    del messages


def _check_message_not_empty(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """A message should declare at least one field, component or group."""
    for api_type in sorted(api.types, key=lambda t: t.key):
        if _is_message(api_type) and not api_type.fields:
            yield (
                f"types.{api_type.key}",
                f"Message '{api_type.name}' declares no fields, components or groups.",
            )


def _check_codeset_not_empty(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """A code set should declare at least one code."""
    for api_type in sorted(api.types, key=lambda t: t.key):
        if api_type.kind is TypeKind.ENUM and api_type.extras.get("fix_kind") == "codeSet" and not api_type.enum_values:
            yield (
                f"types.{api_type.key}",
                f"Code set '{api_type.name}' declares no codes; a field typed by it can carry no value.",
            )


def _check_code_values_unique(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """No two codes of a code set may share a wire value."""
    for api_type in sorted(api.types, key=lambda t: t.key):
        if api_type.kind is not TypeKind.ENUM or api_type.extras.get("fix_kind") != "codeSet":
            continue
        counts = Counter(str(value.value) for value in api_type.enum_values if value.value is not None)
        for wire, count in sorted(counts.items()):
            if count > 1:
                names = sorted(v.name for v in api_type.enum_values if str(v.value) == wire)
                yield (
                    f"types.{api_type.key}",
                    f"Code set '{api_type.name}' gives the value '{wire}' to {', '.join(names)}; "
                    "a received value cannot be told apart.",
                )


def _check_conditional_rule_declared(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """A ``conditional`` field should carry the rule that says when it is required."""
    for api_type in sorted(api.types, key=lambda t: t.key):
        for field in sorted(api_type.fields, key=lambda f: f.key):
            if field.extras.get("fix_presence") != "conditional":
                continue
            rules = field.constraints.extras.get("fix_rules") if field.constraints else None
            if not rules:
                yield (
                    f"types.{api_type.key}.fields.{field.key}",
                    f"Field '{field.name}' is conditional but declares no rule; nothing says when "
                    "it is required. Add a <fixr:rule presence=\"required\"> with its <fixr:when>.",
                )


def _check_repository_version_declared(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """The repository should name the FIX version it describes."""
    if not api.extras.get("fix_repository_version"):
        yield (
            "repository.version",
            "The repository declares no version; name the FIX version it describes, e.g. "
            "'FIX.4.4' or 'FIX.Latest_EP280'.",
        )


class FixOrchestraRulePack(RulePack, register=True):
    """Native rules for FIX Orchestra artifacts (see the module docstring)."""

    format = "fix-orchestra"
    pack_id = "fix-orchestra"

    _RULES: Tuple[LintRule, ...] = (
        LintRule(
            rule_id="fix-orchestra.message-msgtype-declared",
            category="structure",
            severity="error",
            description="Every message must declare a msgType.",
            check=_check_message_msgtype_declared,
        ),
        LintRule(
            rule_id="fix-orchestra.msgtype-unique",
            category="structure",
            severity="error",
            description="No two base-scenario messages may share a msgType.",
            check=_check_msgtype_unique,
        ),
        LintRule(
            rule_id="fix-orchestra.message-not-empty",
            category="structure",
            severity="warning",
            description="A message should declare at least one field, component or group.",
            check=_check_message_not_empty,
        ),
        LintRule(
            rule_id="fix-orchestra.codeset-not-empty",
            category="structure",
            severity="warning",
            description="A code set should declare at least one code.",
            check=_check_codeset_not_empty,
        ),
        LintRule(
            rule_id="fix-orchestra.code-values-unique",
            category="structure",
            severity="error",
            description="No two codes of a code set may share a wire value.",
            check=_check_code_values_unique,
        ),
        LintRule(
            rule_id="fix-orchestra.conditional-rule-declared",
            category="structure",
            severity="warning",
            description="A conditional field should declare the rule that says when it is required.",
            check=_check_conditional_rule_declared,
        ),
        LintRule(
            rule_id="fix-orchestra.repository-version-declared",
            category="documentation",
            severity="info",
            description="The repository should name the FIX version it describes.",
            check=_check_repository_version_declared,
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the FIX Orchestra native rules in deterministic execution order."""
        return list(self._RULES)
