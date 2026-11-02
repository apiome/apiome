"""XML-RPC breaking-change classifier — MFI-21.6 (#3996).

An XML-RPC method takes **positional, required** params and returns **one** value; a struct is
a bag of named members a receiver reads by name. The format-agnostic baseline
(:class:`~app.breaking_change.BuiltinBreakingChangeClassifier`) cannot see inside the request
message's param list (it is folded into ``extras``) and grades every new struct member as a
dangerous mandatory field; this classifier grades the method's signature and leaves everything
else to the baseline.

Rule ids (all ``xmlrpc.*``):

======================================  ===========  ============================================
Rule                                    Severity     When
======================================  ===========  ============================================
``xmlrpc.param-removed``                breaking     the call has fewer params: positions shift
``xmlrpc.param-added``                  breaking     the call has more params: old callers send
                                                     too few and the server faults
``xmlrpc.param-type-changed``           breaking     a param at the same position changed type
``xmlrpc.result-type-changed``          dangerous    the response's value changed type: callers
                                                     that read the old shape break
``xmlrpc.sample-changed``               safe         only the sample values changed
``xmlrpc.fault-changed``                safe         only the fault's code or string changed
``xmlrpc.member-removed``               breaking     a struct member is gone
``xmlrpc.member-type-changed``          breaking     a struct member changed type
``xmlrpc.member-added-to-call``         dangerous    a member was added to a request struct:
                                                     old callers omit it
``xmlrpc.member-added-to-response``     safe         a member was added to a response struct:
                                                     readers ignore what they do not know
======================================  ===========  ============================================
"""

from __future__ import annotations

from typing import Any, List, Mapping, Optional, Tuple

from .breaking_change import BuiltinBreakingChangeClassifier, ChangeClassification, Severity
from .canonical_model import CanonicalApi
from .diff import ChangeKind, EntityCategory, EntityChange

__all__ = ["XmlRpcBreakingChangeClassifier"]

_FORMAT_KEY = "xmlrpc"


def _extras(projection: Any) -> Mapping[str, Any]:
    """The ``extras`` of a self-projection dict."""
    extras = projection.get("extras") if isinstance(projection, Mapping) else None
    return extras if isinstance(extras, Mapping) else {}


def _params(projection: Any) -> List[Mapping[str, Any]]:
    listed = _extras(projection).get("xmlrpc_params")
    return [p for p in listed if isinstance(p, Mapping)] if isinstance(listed, list) else []


class XmlRpcBreakingChangeClassifier(BuiltinBreakingChangeClassifier, register=True):
    """Grade an XML-RPC diff by the method's positional params, result and struct members."""

    format = _FORMAT_KEY
    classifier_id = "xmlrpc-signature"

    def classify_change(
        self, change: EntityChange, base: CanonicalApi, target: CanonicalApi
    ) -> ChangeClassification:
        """Grade one change; what the XML-RPC rules do not cover uses the baseline.

        Args:
            change: The diff change to grade.
            base: The description the diff starts from.
            target: The description the diff ends at.

        Returns:
            The :class:`ChangeClassification` for ``change``.
        """
        graded: Optional[Tuple[Severity, str, str]] = None
        if change.category is EntityCategory.MESSAGE:
            graded = self._grade_message(change)
        elif change.category is EntityCategory.OPERATION:
            graded = self._grade_operation(change)
        elif change.category is EntityCategory.FIELD:
            graded = self._grade_member(change, base, target)
        elif change.category is EntityCategory.TYPE:
            graded = self._grade_struct(change)
        if graded is None:
            return super().classify_change(change, base, target)
        severity, rule_id, rationale = graded
        return ChangeClassification(
            category=change.category,
            kind=change.kind,
            key=change.key,
            severity=severity,
            rule_id=rule_id,
            rationale=rationale,
        )

    @staticmethod
    def _grade_message(change: EntityChange) -> Optional[Tuple[Severity, str, str]]:
        """The request's positional params or the response's value."""
        if change.kind is not ChangeKind.MODIFIED:
            return None
        before, after = change.before or {}, change.after or {}
        if "xmlrpc_params" in _extras(before) or "xmlrpc_params" in _extras(after):
            old, new = _params(before), _params(after)
            if len(new) < len(old):
                return (
                    Severity.BREAKING,
                    "xmlrpc.param-removed",
                    f"the call {change.key!r} dropped from {len(old)} to {len(new)} params; "
                    "params are positional, so callers on the old description send the wrong ones",
                )
            if len(new) > len(old):
                return (
                    Severity.BREAKING,
                    "xmlrpc.param-added",
                    f"the call {change.key!r} grew from {len(old)} to {len(new)} params; every "
                    "param is required, so callers on the old description send too few and fault",
                )
            for index, (old_param, new_param) in enumerate(zip(old, new)):
                if old_param.get("schema") != new_param.get("schema"):
                    return (
                        Severity.BREAKING,
                        "xmlrpc.param-type-changed",
                        f"param {index} of {change.key!r} changed type from "
                        f"{old_param.get('schema')!r} to {new_param.get('schema')!r}",
                    )
            return (
                Severity.SAFE,
                "xmlrpc.sample-changed",
                f"the call {change.key!r} carries other sample values; the signature is unchanged",
            )
        if "xmlrpc_result_schema" in _extras(before) or "xmlrpc_result_schema" in _extras(after):
            old_schema = _extras(before).get("xmlrpc_result_schema")
            new_schema = _extras(after).get("xmlrpc_result_schema")
            moved = {field_change.field for field_change in change.fields}
            if old_schema != new_schema or "payload" in moved:
                return (
                    Severity.DANGEROUS,
                    "xmlrpc.result-type-changed",
                    f"the response {change.key!r} changed its value type from {old_schema!r} to "
                    f"{new_schema!r}; callers that read the old shape break",
                )
            return (
                Severity.SAFE,
                "xmlrpc.sample-changed",
                f"the response {change.key!r} carries another sample value; the type is unchanged",
            )
        return None

    @staticmethod
    def _grade_operation(change: EntityChange) -> Optional[Tuple[Severity, str, str]]:
        """Only the fault's code or string moved."""
        if change.kind is not ChangeKind.MODIFIED:
            return None
        before, after = _extras(change.before), _extras(change.after)
        if "xmlrpc_kind" not in before or before.get("xmlrpc_kind") != after.get("xmlrpc_kind"):
            return None
        moved = {field_change.field for field_change in change.fields}
        if moved <= {"extras"}:
            return (
                Severity.SAFE,
                "xmlrpc.fault-changed",
                f"the fault of {change.key!r} changed from {before.get('xmlrpc_fault_code')!r} "
                f"{before.get('xmlrpc_fault_string')!r} to {after.get('xmlrpc_fault_code')!r} "
                f"{after.get('xmlrpc_fault_string')!r}; the method's signature is unchanged",
            )
        return None

    @staticmethod
    def _grade_member(
        change: EntityChange, base: CanonicalApi, target: CanonicalApi
    ) -> Optional[Tuple[Severity, str, str]]:
        """A struct member added, removed or re-typed."""
        api = target if change.kind is ChangeKind.ADDED else base
        owner = next(
            (t for t in api.types if t.extras.get("xmlrpc_kind") == "struct" and change.key.startswith(f"{t.key}.")),
            None,
        )
        if owner is None:
            return None
        if change.kind is ChangeKind.REMOVED:
            return (
                Severity.BREAKING,
                "xmlrpc.member-removed",
                f"member {change.key!r} was removed; readers that look it up by name find nothing",
            )
        if change.kind is ChangeKind.ADDED:
            if api.extras.get("xmlrpc_kind") == "methodCall":
                return (
                    Severity.DANGEROUS,
                    "xmlrpc.member-added-to-call",
                    f"member {change.key!r} was added to a request struct; callers on the old "
                    "description omit it",
                )
            return (
                Severity.SAFE,
                "xmlrpc.member-added-to-response",
                f"member {change.key!r} was added to a response struct; readers ignore members "
                "they do not know",
            )
        moved = {field_change.field for field_change in change.fields}
        if "type" in moved:
            before, after = change.before or {}, change.after or {}
            return (
                Severity.BREAKING,
                "xmlrpc.member-type-changed",
                f"member {change.key!r} changed type from {before.get('type')!r} to {after.get('type')!r}",
            )
        return None

    @staticmethod
    def _grade_struct(change: EntityChange) -> Optional[Tuple[Severity, str, str]]:
        """A struct whose only change is its sample values."""
        if change.kind is not ChangeKind.MODIFIED or _extras(change.before).get("xmlrpc_kind") != "struct":
            return None
        moved = {field_change.field for field_change in change.fields}
        if moved <= {"extras"}:
            return (
                Severity.SAFE,
                "xmlrpc.sample-changed",
                f"struct {change.key!r} carries other sample values; its members are unchanged",
            )
        return None
