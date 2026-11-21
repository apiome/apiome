"""Fidelity verdicts for what a cross-format export changes outside any one construct — COA-3.1 (#7052).

A target's :class:`~app.fidelity_rulepack.FidelityRulePack` names the losses its own vocabulary
causes (a dropped union, a demoted constraint). An export from *another* format also changes things
no capability axis describes, and a report that leaves them out is silent about a real difference:

* the **paradigm** — an agent card written as OpenAPI reads back as a REST API
  (:func:`paradigm_change_verdict`);
* the **key** of a construct the target can only write under another name — a namespace-qualified
  type in a format with no namespaces, an RPC method placed on an HTTP path
  (:func:`rekey_verdicts`);
* the **source format's own metadata** — an API gateway's route policy, a dbt model's tags — for
  which the target has no field (:func:`source_metadata_verdict`);
* the **document envelope** — an identifier, a namespace, a version the target has no place for or
  must invent (:func:`envelope_verdicts`);
* **agents and skills** — which only the agent formats describe (:func:`agent_loss_items`).

The helpers are pure and shared by every pack that needs them, so the same loss reads the same way
whichever target reports it.
"""

from __future__ import annotations

from typing import Any, Collection, Iterable, List, Mapping, Optional, Tuple

from .canonical_model import ApiParadigm, CanonicalApi
from .fidelity_rulepack import FidelityVerdict
from .lossiness import LossinessKind, LossinessSeverity, LossItem

__all__ = [
    "agent_loss_items",
    "envelope_verdicts",
    "paradigm_change_verdict",
    "paradigm_label",
    "rekey_verdicts",
    "source_metadata_keys",
    "source_metadata_verdict",
]

#: How many metadata keys a :func:`source_metadata_verdict` message spells out before it counts.
_NAMED_KEYS = 4


#: Paradigms a message spells otherwise than their value with spaces.
_PARADIGM_LABELS = {ApiParadigm.REST: "REST", ApiParadigm.RPC: "RPC", ApiParadigm.GRAPH: "GraphQL"}


def paradigm_label(paradigm: ApiParadigm) -> str:
    """The paradigm as a message reads it (``data_schema`` → ``"data schema"``, ``rpc`` → ``"RPC"``)."""
    return _PARADIGM_LABELS.get(paradigm) or paradigm.value.replace("_", " ")


def _with_article(label: str) -> str:
    """``label`` behind its indefinite article (``"an RPC"``, ``"a REST"``, ``"an event"``)."""
    return f"{'an' if label[0].lower() in 'aei' or label == 'RPC' else 'a'} {label}"


def paradigm_change_verdict(
    api: CanonicalApi, target_paradigm: ApiParadigm, *, target_label: str
) -> Optional[FidelityVerdict]:
    """The root ``APPROX`` of an export whose target describes another kind of API.

    Args:
        api: The source model.
        target_paradigm: The paradigm a document of the target reads back as.
        target_label: The target's label (``"OpenAPI 3.1"``).

    Returns:
        ``None`` when the source already has the target's paradigm; otherwise a ``warn`` ``APPROX``
        recorded on the artifact root.
    """
    if api.paradigm is target_paradigm:
        return None
    source, target = paradigm_label(api.paradigm), paradigm_label(target_paradigm)
    return FidelityVerdict.approx(
        message=f"{target_label} describes {target} APIs; this {source} API is written in {target} "
        f"terms and reads back as {_with_article(target)} API",
        target_mapping=f"{api.paradigm.value} → {target_paradigm.value}",
    )


def rekey_verdicts(
    source_key: str, emitted_key: str, *, target_label: str, noun: str, reason: str
) -> Optional[Tuple[FidelityVerdict, Tuple[str, FidelityVerdict]]]:
    """The pair of verdicts for a construct the target writes under another key.

    A re-import knows the construct only by its new key, so the source key disappears (``DROP``) and
    the new one appears (``SYNTH``) — the pattern of the Arazzo pack (COA-1.4). Both are ``info``:
    the construct itself is written.

    Args:
        source_key: The construct's key in the source model.
        emitted_key: The key a re-import of the export gives it.
        target_label: The target's label.
        noun: What is re-keyed (``"type"``, ``"operation"``, ``"service"``).
        reason: Why the key changes, as a clause (``"has no namespaces"``).

    Returns:
        ``None`` when the key is unchanged; otherwise ``(drop, (emitted_key, synth))`` — the first
        for the source construct, the second for
        :meth:`~app.fidelity_rulepack.FidelityRulePack.synthesized_verdicts`.
    """
    if source_key == emitted_key:
        return None
    mapping = f"{source_key} → {emitted_key}"
    drop = FidelityVerdict.drop(
        message=f"{target_label} {reason}; {noun} {source_key!r} is written as {emitted_key!r} and "
        "reads back under that key",
        severity=LossinessSeverity.INFO,
        target_mapping=mapping,
    )
    synth = FidelityVerdict.synth(
        message=f"{noun} {source_key!r} as {target_label} writes it",
        target_mapping=mapping,
    )
    return drop, (emitted_key, synth)


def source_metadata_keys(extras: Optional[Mapping[str, Any]], written: Collection[str] = ()) -> List[str]:
    """The source-format metadata keys of one construct that the target does not write.

    Args:
        extras: The construct's ``extras`` bag.
        written: Keys the target carries (``operationId`` on an OpenAPI operation).

    Returns:
        The other keys with a value, sorted.
    """
    return sorted(
        key for key, value in (extras or {}).items()
        if key not in written and value not in (None, "", [], {})
    )


def source_metadata_verdict(
    keys: Iterable[str], *, source_format: str, target_label: str, noun: str
) -> Optional[FidelityVerdict]:
    """An ``info`` ``DROP`` for source-format metadata the target has no field for.

    Args:
        keys: The metadata keys that are not written (see :func:`source_metadata_keys`); those of a
            construct and of its parts (a record's fields, an operation's parameters) together.
        source_format: The source's format key (``"apigee"``), named in the message.
        target_label: The target's label.
        noun: The construct the metadata belongs to (``"operation"``, ``"type"``).

    Returns:
        ``None`` when ``keys`` is empty.
    """
    names = sorted(set(keys))
    if not names:
        return None
    shown = ", ".join(names[:_NAMED_KEYS])
    more = f" and {len(names) - _NAMED_KEYS} more" if len(names) > _NAMED_KEYS else ""
    return FidelityVerdict.drop(
        message=f"{target_label} has no field for the {source_format} metadata of this {noun} "
        f"({shown}{more}); it is not written",
        severity=LossinessSeverity.INFO,
        target_mapping=f"{source_format} metadata → dropped",
    )


def envelope_verdicts(
    api: CanonicalApi,
    *,
    target_label: str,
    keeps_id: bool = True,
    keeps_namespace: bool = True,
    keeps_title: bool = True,
    keeps_version: bool = True,
    default_version: Optional[str] = None,
) -> List[FidelityVerdict]:
    """The root verdicts for the parts of the document envelope a target cannot keep or must invent.

    Args:
        api: The source model.
        target_label: The target's label.
        keeps_id: Whether the target writes ``identity.id``.
        keeps_namespace: Whether the target writes ``identity.namespace``.
        keeps_title: Whether the target writes the title.
        keeps_version: Whether the target writes the version.
        default_version: The version the target writes when the source has none (``None`` when it
            writes no version in that case).

    Returns:
        One ``info`` ``DROP`` naming every envelope part that is not written, and one ``SYNTH`` for
        an invented version; ``[]`` when the envelope survives.
    """
    verdicts: List[FidelityVerdict] = []
    lost = []
    if not keeps_title and api.title:
        lost.append(f"title {api.title!r}")
    if not keeps_id and api.identity.id:
        lost.append(f"identifier {api.identity.id!r}")
    if not keeps_namespace and api.identity.namespace:
        lost.append(f"namespace {api.identity.namespace!r}")
    if not keeps_version and api.version:
        lost.append(f"version {api.version!r}")
    if lost:
        verdicts.append(FidelityVerdict.drop(
            message=f"{target_label} has no place for the document's {' and '.join(lost)}; "
            f"{'it is' if len(lost) == 1 else 'they are'} not written",
            severity=LossinessSeverity.INFO,
            target_mapping="document envelope → dropped",
        ))
    if default_version is not None and not api.version:
        verdicts.append(FidelityVerdict.synth(
            message=f"{target_label} requires a version and the source declares none; "
            f"{default_version!r} is written",
            target_mapping=f"version → {default_version}",
        ))
    return verdicts


def agent_loss_items(api: CanonicalApi, *, target_label: str) -> List[LossItem]:
    """``DROP`` items for each agent descriptor and skill of ``api``, for a target that has neither.

    Agents live outside the services a rule pack walks, so a pack appends these to its report (the
    pattern of the Arazzo pack, COA-1.4). A skill usually shares its key with an operation the target
    does write; the skill itself — its tags, examples and modes — is what is lost.

    Args:
        api: The source model.
        target_label: The target's label.

    Returns:
        One ``warn`` item per agent and one ``info`` item per skill; ``[]`` for a source with no agent.
    """
    items: List[LossItem] = []
    for agent in api.agents:
        items.append(LossItem(
            construct_key=agent.key,
            kind=LossinessKind.DROP,
            severity=LossinessSeverity.WARN,
            message=f"{target_label} has no agent descriptor; agent {agent.key!r} is not written",
            target_mapping="agent → dropped",
        ))
        for skill in agent.skills:
            items.append(LossItem(
                construct_key=skill.key,
                kind=LossinessKind.DROP,
                severity=LossinessSeverity.INFO,
                message=f"{target_label} has no agent skills; skill {skill.key!r} is not written as one",
                target_mapping="skill → dropped",
            ))
    return items
