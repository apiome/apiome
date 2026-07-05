"""Fidelity computation engine — MFX-2.2 (#3839), rule-pack driven (MFX-2.3, #3840).

MFX-2.1 (:mod:`app.lossiness`) defines *the shape* of a fidelity report — an ordered
list of :class:`~app.lossiness.LossItem`, each recording what happened to one
construct (``DROP`` / ``APPROX`` / ``SYNTH`` / ``OK``) and how much it matters
(``info`` / ``warn`` / ``critical``). This module is *the engine that produces one*:
given a source :class:`~app.canonical_model.CanonicalApi` and a target, it predicts
each construct's fate **before** any emit runs.

It is the headline of MFX-EPIC-2 (the fidelity / lossiness engine): a cross-format
export honestly tells the user *what it will lose* — a discriminated union a target
can't carry, a numeric constraint demoted to a doc comment, a protobuf field number
the source never had — rather than dropping detail silently.

**Rule packs decide; the engine drives.** The per-construct decisions live in a
:class:`~app.fidelity_rulepack.FidelityRulePack` (MFX-2.3) — the pluggable SPI that
maps canonical constructs → target handling, so each format epic can refine *how*
its target degrades a construct. This engine is now a thin facade over that SPI: it
resolves which pack to use (a target's own pack, or the profile-derived
:class:`~app.fidelity_rulepack.CapabilityRulePack` default) and delegates the walk
to :meth:`~app.fidelity_rulepack.FidelityRulePack.evaluate`.

The two public entry points stay stable for callers (the export dispatch in
MFX-3.2, the dry-run preview in MFX-2.5):

* :func:`compute_lossiness` — from a raw :class:`~app.emitter.CapabilityProfile` (or
  an explicit rule pack);
* :func:`compute_lossiness_for_emitter` — from an emitter, honouring the pack the
  emitter declares.

Both are **pure and deterministic**: no network, no database, no clock. Given the
same inputs they return an equal report, which :class:`~app.lossiness.LossinessReport`
sorts into a stable canonical order — so a preview and the report attached to the
eventual export are byte-identical.
"""

from __future__ import annotations

from typing import Optional, Union

from .canonical_model import CanonicalApi
from .emitter import CapabilityProfile, Emitter
from .fidelity_rulepack import CapabilityRulePack, FidelityRulePack
from .lossiness import LossinessReport

__all__ = [
    "compute_lossiness",
    "compute_lossiness_for_emitter",
]


def compute_lossiness(
    api: CanonicalApi,
    profile: CapabilityProfile,
    *,
    target_label: str = "the target",
    rule_pack: Optional[FidelityRulePack] = None,
) -> LossinessReport:
    """Compute the fidelity :class:`~app.lossiness.LossinessReport` for one export.

    Walks ``api`` construct by construct and predicts each construct's fate — ``OK``
    when the target carries it faithfully, ``DROP`` / ``APPROX`` / ``SYNTH`` when it
    cannot. The verdicts come from a :class:`~app.fidelity_rulepack.FidelityRulePack`:
    an explicit ``rule_pack`` when given, otherwise the profile-derived
    :class:`~app.fidelity_rulepack.CapabilityRulePack` default. Pure and
    deterministic: no I/O, and the returned report is sorted into a stable canonical
    order, so a preview and the report attached to the eventual emit are
    byte-identical for the same inputs.

    Args:
        api: The source canonical model to be exported.
        profile: The target emitter's static :class:`~app.emitter.CapabilityProfile`.
            Ignored when ``rule_pack`` is supplied (the pack carries its own profile).
        target_label: Human label for the target woven into item messages (e.g.
            "OpenAPI 3.1"); cosmetic only, it does not affect verdicts. Ignored when
            ``rule_pack`` is supplied.
        rule_pack: An explicit rule pack to consult. When ``None`` (the default) a
            :class:`~app.fidelity_rulepack.CapabilityRulePack` is built from
            ``profile`` and ``target_label``.

    Returns:
        A :class:`~app.lossiness.LossinessReport` with one or more items per
        top-level construct and one item per lossy field, its summary counts
        derived from those items.
    """
    pack = rule_pack or CapabilityRulePack(profile, target_label)
    return pack.evaluate(api)


def compute_lossiness_for_emitter(
    api: CanonicalApi,
    emitter: Union[Emitter, type[Emitter]],
) -> LossinessReport:
    """Compute the fidelity report for exporting ``api`` through ``emitter``.

    Convenience wrapper over :func:`compute_lossiness` that reads the target's
    capability profile, human label, **and fidelity rule pack** straight from the
    emitter, so callers (the export dispatch in MFX-3.2, the dry-run preview in
    MFX-2.5) need not unpack them. When the emitter declares a
    :class:`~app.fidelity_rulepack.FidelityRulePack` (via
    :meth:`app.emitter.Emitter.fidelity_rule_pack`) that pack's target-specific
    rules are honoured; otherwise the profile-derived default applies. Accepts an
    emitter instance or its class.

    Args:
        api: The source canonical model to be exported.
        emitter: The target :class:`~app.emitter.Emitter` (instance or class).

    Returns:
        The predicted :class:`~app.lossiness.LossinessReport` for the export.
    """
    emitter_cls = emitter if isinstance(emitter, type) else type(emitter)
    profile = emitter_cls.capability_profile()
    label = emitter_cls.label or emitter_cls.key or emitter_cls.format or "the target"
    pack_cls = emitter_cls.fidelity_rule_pack() or CapabilityRulePack
    return compute_lossiness(api, profile, rule_pack=pack_cls(profile, label))
