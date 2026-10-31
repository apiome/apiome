"""Fidelity rules for example-based collections — MFX-31.2 (#4290).

A collection (Postman, and the other collection emitters of MFX-EPIC-31) is *example*-based, not
schema-based: exporting to one trades every schema for a sample. Without saying so, the conversion
would look lossless where it is not. :class:`ExampleCollectionFidelityRulePack` names each trade as
its own report item, with the reason, on the operation it happens to:

* **typed schemas → example bodies** (``APPROX``): the request schema becomes one example body; its
  constraints are not enforced by the collection;
* **unions / ``oneOf`` → one representative example** (``APPROX``): only one alternative is shown;
* **response schemas → example responses** (``APPROX``): each single-status response becomes a saved
  example, from which a re-import infers the schema again; a status range (``4XX``, ``default``) has no
  code to save under (``DROP``);
* **generated example values** (``SYNTH``): the values are generated from the schema, not taken
  from the source;
* **RPC streaming** (``DROP``): a streamed exchange is saved as one request and one response;
* **auth** beyond the collection's own auth types: OpenID Connect is written as a bearer token and a
  generic ``Authorization`` / ``Cookie`` requirement as a header holding a reference (``APPROX``);
  any other scheme has no form (``DROP``); only one scheme per request is written (``APPROX``);
* **field constraints** (``APPROX``): kept by the example, not enforced.

Event channels, event operations and operations with no HTTP binding stay the base pack's ``DROP``
(:class:`app.client_collection_emit.ClientCollectionFidelityRulePack`), and so does a named type's
declaration — a re-import infers body types under names of its own, so a source type is as likely to
vanish as to come back changed. A model imported from the same collection format is written back as
it was read and reports nothing.
"""

from __future__ import annotations

from typing import List, Optional

from .canonical_model import CanonicalApi, CanonicalField, Message, MessageRole, Operation, StreamingMode, Type
from .canonical_security import AUTH_SCHEME_HEADERS, operation_security_schemes
from .client_collection_emit import PAIR_SCHEMES, ClientCollectionFidelityRulePack, reachable_unions
from .fidelity_rulepack import FidelityVerdict
from .lossiness import LossinessKind, LossinessReport, LossinessSeverity

__all__ = ["ExampleCollectionFidelityRulePack"]

_STATUS_CODES = frozenset(str(code) for code in range(100, 600))


def _status(message: Message) -> str:
    return str(message.status_code or message.extras.get("http_status") or "")


def _has_body(message: Message) -> bool:
    return message.payload is not None or bool(message.payload_schema)


def _payload_label(message: Message) -> str:
    """How a body's schema is named in a message: its type (``Pet``, ``Pet[]``) or ``an inline schema``."""
    ref = message.payload
    if ref is None:
        return "an inline schema"
    suffix = ""
    while ref.item is not None:
        ref, suffix = ref.item, suffix + "[]"
    return f"{ref.name or 'an inline schema'}{suffix}"


class ExampleCollectionFidelityRulePack(ClientCollectionFidelityRulePack):
    """The example-collection rules (see the module docstring) on top of the client-collection rules.

    A subclass sets ``target_label``, ``format_key`` and ``auth_blocks`` (the canonical schemes the
    collection writes as an auth block of its own), and may override :meth:`request_verdict` for the
    wording of the request item.
    """

    #: Canonical schemes this collection writes as an auth block.
    auth_blocks: frozenset = frozenset()
    #: Whether the collection saves example responses (Postman does; Insomnia and Bruno exports
    #: save the call only, so their declared responses are dropped — MFX-31.3).
    carries_responses: bool = True

    def evaluate(self, api: CanonicalApi) -> LossinessReport:
        """Note the model and whether it came from this collection format, then run the drive loop."""
        self._api = api
        self._native = self.is_native(api)
        return super().evaluate(api)

    # -- operations ---------------------------------------------------------

    def request_verdict(self, operation: Operation) -> FidelityVerdict:
        """The item for the saved request itself (what a re-import infers again)."""
        return FidelityVerdict.approx(
            message=(
                f"{self.target_label} saves {operation.key!r} as one example request; a re-import infers the "
                "operation again from it, so parameter types and descriptions and extra tags are not carried"
            ),
            target_mapping="operation → saved request",
        )

    def operation_verdicts(self, operation: Operation) -> List[FidelityVerdict]:
        """The base pack's ``DROP`` for an operation with no request; else one item per trade."""
        base = super().operation_verdict(operation)
        if base.kind is not LossinessKind.APPROX:
            return [base]
        if getattr(self, "_native", False):
            return [FidelityVerdict.ok(message="request written back as it was read")]
        verdicts = [self.request_verdict(operation)]
        verdicts.extend(self._body_verdicts(operation))
        verdicts.extend(self._response_verdicts(operation))
        verdicts.extend(self._union_verdicts(operation))
        verdicts.extend(self._synth_verdicts(operation))
        verdicts.extend(self._streaming_verdicts(operation))
        verdicts.extend(self._auth_verdicts(operation))
        return verdicts

    def operation_verdict(self, operation: Operation) -> FidelityVerdict:
        """The most severe of :meth:`operation_verdicts` (a ``DROP`` when there is one, else the first)."""
        verdicts = self.operation_verdicts(operation)
        return next((v for v in verdicts if v.kind is LossinessKind.DROP), verdicts[0])

    def _body_verdicts(self, operation: Operation) -> List[FidelityVerdict]:
        request = next((m for m in operation.messages if m.role is MessageRole.REQUEST and _has_body(m)), None)
        if request is None:
            return []
        return [FidelityVerdict.approx(
            message=(
                f"{self.target_label}: the request schema ({_payload_label(request)}) of {operation.key!r} becomes "
                "one example body; its types and constraints are not enforced by the collection"
            ),
            target_mapping="request schema → example body",
        )]

    def _response_verdicts(self, operation: Operation) -> List[FidelityVerdict]:
        responses = [m for m in operation.messages if m.role in (MessageRole.RESPONSE, MessageRole.ERROR)]
        if not self.carries_responses:
            if not responses:
                return []
            return [FidelityVerdict.drop(
                message=(
                    f"{self.target_label} saves the request, not the reply; the declared response(s) of "
                    f"{operation.key!r} are not carried"
                ),
                target_mapping="responses → dropped",
            )]
        saved = sorted({_status(m) or "200" for m in responses if _status(m) in _STATUS_CODES or not _status(m)})
        typed = sorted({_status(m) or "200" for m in responses if _has_body(m) and (_status(m) or "200") in saved})
        ranges = sorted({_status(m) for m in responses if _status(m) and _status(m) not in _STATUS_CODES})
        verdicts: List[FidelityVerdict] = []
        if typed:
            verdicts.append(FidelityVerdict.approx(
                message=(
                    f"{self.target_label}: the response schema(s) for {', '.join(typed)} of {operation.key!r} "
                    "become saved example responses; a re-import infers the schemas again from those examples"
                ),
                target_mapping="response schema → example response",
            ))
        if ranges:
            verdicts.append(FidelityVerdict.drop(
                message=(
                    f"{self.target_label}: a saved example response has one status code; the {', '.join(ranges)} "
                    f"response(s) of {operation.key!r} are not saved"
                ),
                severity=LossinessSeverity.WARN,
                target_mapping="status range → dropped",
            ))
        return verdicts

    def _union_verdicts(self, operation: Operation) -> List[FidelityVerdict]:
        unions: List[str] = []
        for message in operation.messages:
            if message.role is not MessageRole.EVENT and _has_body(message):
                unions.extend(name for name in reachable_unions(self._api, message) if name not in unions)
        if not unions:
            return []
        return [FidelityVerdict.approx(
            message=(
                f"{self.target_label}: {', '.join(unions)} in the bodies of {operation.key!r} "
                f"{'has' if len(unions) == 1 else 'have'} several alternatives; the example shows one of them"
            ),
            severity=LossinessSeverity.WARN,
            target_mapping="union / oneOf → one representative example",
        )]

    def _synth_verdicts(self, operation: Operation) -> List[FidelityVerdict]:
        if not any(_has_body(m) for m in operation.messages if m.role is not MessageRole.EVENT):
            return []
        return [FidelityVerdict.synth(
            message=(
                f"{self.target_label}: the example values of {operation.key!r} are generated from the schemas, "
                "not taken from the source"
            ),
            severity=LossinessSeverity.INFO,
            target_mapping="schema → generated example values",
        )]

    def _streaming_verdicts(self, operation: Operation) -> List[FidelityVerdict]:
        if operation.streaming is StreamingMode.NONE:
            return []
        return [FidelityVerdict.drop(
            message=(
                f"{self.target_label} has no streaming; the {operation.streaming.value} exchange of "
                f"{operation.key!r} is saved as one request and one response"
            ),
            severity=LossinessSeverity.WARN,
            target_mapping="streaming → dropped",
        )]

    def _auth_verdicts(self, operation: Operation) -> List[FidelityVerdict]:
        schemes, scope = operation_security_schemes(self._api, operation)
        if scope != "operation" or not schemes:
            return []
        verdicts: List[FidelityVerdict] = []
        usable = [s for s in schemes if s in self.auth_blocks or s == "openIdConnect" or s in PAIR_SCHEMES]
        for scheme in schemes:
            if scheme in usable:
                continue
            verdicts.append(FidelityVerdict.drop(
                message=f"{self.target_label} has no auth type or header form for {scheme!r}; it is not carried",
                severity=LossinessSeverity.WARN,
                target_mapping="auth scheme → dropped",
            ))
        if usable:
            written = usable[0]
            if written == "openIdConnect":
                verdicts.append(FidelityVerdict.approx(
                    message=f"{self.target_label} writes OpenID Connect on {operation.key!r} as a bearer token",
                    target_mapping="openIdConnect → bearer token",
                ))
            elif written not in self.auth_blocks:
                header = AUTH_SCHEME_HEADERS.get(written, ("Authorization", ""))[0]
                verdicts.append(FidelityVerdict.approx(
                    message=(
                        f"{self.target_label} has no {written!r} auth type; {operation.key!r} sends it as the "
                        f"{header} header holding a variable reference"
                    ),
                    target_mapping="auth → credential header",
                ))
            if len(usable) > 1:
                verdicts.append(FidelityVerdict.approx(
                    message=(
                        f"{operation.key!r} accepts {', '.join(usable)}; a saved request has one auth, so "
                        f"{written!r} is written"
                    ),
                    target_mapping="several auth schemes → the first",
                ))
        return verdicts

    # -- types and fields -----------------------------------------------------

    def type_verdict(self, type_: Type) -> FidelityVerdict:
        """A source's own types were inferred from its examples, which are written back; else the base ``DROP``."""
        if getattr(self, "_native", False):
            return FidelityVerdict.ok(message="type inferred from an example body that is written back")
        return super().type_verdict(type_)

    def field_verdicts(self, field: CanonicalField) -> List[FidelityVerdict]:
        """A source's own fields were inferred from its examples: nothing is lost."""
        if getattr(self, "_native", False):
            return []
        return super().field_verdicts(field)

    def _constraints_verdict(self, field: CanonicalField) -> Optional[FidelityVerdict]:
        """Constraints shape the example but are not enforced by a collection."""
        verdict = super()._constraints_verdict(field)
        if verdict is None:
            return None
        return FidelityVerdict.approx(
            message=(
                f"{self.target_label} does not enforce validation constraints; the example satisfies them, but a "
                "request edited in the collection is not checked"
            ),
            target_mapping="constraints → not enforced",
        )
