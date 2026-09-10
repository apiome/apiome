"""Package versions from a version line and a regen counter — SDK-4.1 (#4495).

A published API has a **version line** (``versions.version_id``: ``1.4``, ``v2``, ``2026-01-01``,
``2.0.0-beta``). A package registry has a *version*, and the two are not the same thing: a version
line can be re-published any number of times — a corrected description, a new example, a
regenerated client — and each of those has to become a *distinct, later* release on npm and PyPI
or the upload is rejected. This module is the rule that maps one onto the other, and it is a pure
function so a dry-run can predict exactly what a publish will claim.

**The rule.** The version line supplies ``major.minor``; the **regen counter** supplies the patch::

    line 1.4      →  1.4.0, then 1.4.1, then 1.4.2 …
    line 2.0.0    →  2.0.0, then 2.0.1 …          (the line's third component is not the patch)
    line v3       →  3.0.0, then 3.0.1 …
    line 2026-01-04 → 2026.1.0, then 2026.1.1 …
    line 1.5-beta →  1.5.0-beta.0, then 1.5.0-beta.1 …

Three consequences are deliberate:

**The counter is allocated per release *series*, not per line.** The series is ``major.minor``
(plus a prerelease tag when the line has one), so lines ``1.4.2`` and ``1.4.3`` — which are the
same ``1.4`` series — draw from one counter and cannot collide on ``1.4.0``. That is what makes
the mapping injective, and it is also the honest reading: within a ``1.4`` series each publish is
the next patch.

**A prerelease line stays a prerelease.** Dropping a ``-beta`` suffix would publish a beta as a
stable release, which npm's ``latest`` tag and pip's default resolver would then hand to everyone.
The tag is preserved and the counter becomes its final component (npm ``1.5.0-beta.3``, PyPI
``1.5.0b3``), which sorts *before* the eventual ``1.5.0`` in both ecosystems.

**A line with no leading number is refused.** ``latest``, ``current`` and ``draft`` carry no
ordering, and inventing one (``0.0.N``) would mean two such lines publishing over each other. The
publish fails with an actionable message instead — this is the one place SDK-4.1 declines to
guess.

Ecosystems here are the two SDK-4.1 publishes to: ``npm`` and ``pypi``. The SDK-3.4 ``gomod``
setting names a *module path*, and a Go module is released by pushing a git tag rather than by
uploading to a registry — that is SDK-4.2's territory, not this module's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

__all__ = [
    "MAX_COMPONENT",
    "NPM_ECOSYSTEM",
    "PUBLISH_ECOSYSTEMS",
    "PYPI_ECOSYSTEM",
    "ReleaseSeries",
    "VersionLineError",
    "package_version",
    "parse_version_line",
    "resolve_package_version",
]

#: The npm ecosystem key, as SDK-3.4 spells it.
NPM_ECOSYSTEM = "npm"

#: The PyPI ecosystem key, as SDK-3.4 spells it.
PYPI_ECOSYSTEM = "pypi"

#: The ecosystems SDK-4.1 can publish to, in a stable order.
PUBLISH_ECOSYSTEMS: Tuple[str, ...] = (NPM_ECOSYSTEM, PYPI_ECOSYSTEM)

#: Largest value a version component may take. Both registries accept far more, but a line like
#: ``20260104120000`` is a timestamp that someone will regret publishing under, and a bounded
#: component keeps the mapping's output predictable.
MAX_COMPONENT = 999_999_999

#: Leading run of digits at the start of what is left of a label.
_DIGITS = re.compile(r"^\d+")

#: The separators a version line may put between its components.
_SEPARATORS = ".-_+"

#: PEP 440 spells the three standard prerelease phases ``a``, ``b`` and ``rc``; these are the
#: spellings that map onto them. Anything else becomes a development release (``.devN``), which is
#: PEP 440's own answer for "a prerelease of a kind I do not recognise".
_PYPI_PHASES: Dict[str, str] = {
    "a": "a",
    "alpha": "a",
    "b": "b",
    "beta": "b",
    "c": "rc",
    "rc": "rc",
    "pre": "rc",
    "preview": "rc",
}


class VersionLineError(ValueError):
    """Raised when a version line cannot be mapped onto a package version.

    Carries a message written for the person who named the version, not for a log: it says what
    the line was and what shape would work.
    """


@dataclass(frozen=True)
class ReleaseSeries:
    """The release series a version line belongs to — the key a regen counter is allocated under.

    Attributes:
        major: First numeric component of the line.
        minor: Second numeric component, or ``0`` when the line has only one.
        prerelease: Normalised prerelease tag (``beta``, ``rc``, ``dev``…), or ``None`` for a
            stable line. Part of the series because a prerelease and a stable release of the same
            ``major.minor`` are separate release streams with separate counters.
    """

    major: int
    minor: int
    prerelease: Optional[str] = None

    @property
    def key(self) -> str:
        """The stored series key: ``"1.4"``, or ``"1.4-beta"`` for a prerelease stream.

        Returns:
            A short, stable string. This is what the run ledger groups by, so it must not change
            shape between releases without a migration of the stored rows.
        """
        base = f"{self.major}.{self.minor}"
        return f"{base}-{self.prerelease}" if self.prerelease else base


def _normalise_prerelease(raw: str) -> Optional[str]:
    """Reduce a line's trailing tag to a single lower-case alphabetic identifier.

    ``-beta.2``, ``-BETA``, ``rc1`` and ``.snapshot-4`` all reduce to their leading word
    (``beta``, ``beta``, ``rc``, ``snapshot``). The numbers that followed it in the *line* are
    dropped deliberately: the published version's prerelease number is the regen counter, and
    keeping both would produce ``1.5.0-beta.2.7``.

    Args:
        raw: Everything after the line's numeric prefix.

    Returns:
        The tag, or ``None`` when nothing alphabetic remains (``1.0.0-`` is just ``1.0``).
    """
    match = re.search(r"[A-Za-z]+", raw)
    if not match:
        return None
    return match.group(0).lower()


def parse_version_line(version_line: Optional[str]) -> ReleaseSeries:
    """Read a version line's release series.

    Leading ``v``/``V`` is stripped, then leading numeric components are consumed across ``.``,
    ``-``, ``_`` and ``+`` separators until a component starts with a letter; that remainder is the
    prerelease tag. ``2026-01-04`` therefore reads as ``(2026, 1)`` rather than as ``2026`` with a
    ``-01-04`` prerelease, which is what makes date-versioned APIs map sensibly.

    Args:
        version_line: The published version's label (``versions.version_id``).

    Returns:
        The :class:`ReleaseSeries`.

    Raises:
        VersionLineError: When the line is empty, has no leading numeric component, or names a
            component larger than :data:`MAX_COMPONENT`.
    """
    label = (version_line or "").strip()
    if not label:
        raise VersionLineError(
            "This version has no version line, so there is no package version to publish under. "
            "Give the version a label such as `1.4` or `2026-01-04` and publish again."
        )

    remainder = label
    if remainder[0] in "vV" and len(remainder) > 1 and remainder[1].isdigit():
        remainder = remainder[1:]

    components: list[int] = []
    while len(components) < 3:
        match = _DIGITS.match(remainder)
        if not match:
            break
        raw = match.group(0)
        value = int(raw)
        if value > MAX_COMPONENT:
            raise VersionLineError(
                f"Version line {label!r} has the component {raw}, which is larger than "
                f"{MAX_COMPONENT:,}. Package versions are bounded; use a shorter version line."
            )
        components.append(value)
        remainder = remainder[match.end() :]
        if not remainder or remainder[0] not in _SEPARATORS:
            break
        remainder = remainder[1:]

    if not components:
        raise VersionLineError(
            f"Version line {label!r} does not start with a number, so it cannot be mapped onto a "
            "package version. Registries order releases numerically — name the version something "
            "like `1.4`, `v2` or `2026-01-04` to publish it."
        )

    major = components[0]
    minor = components[1] if len(components) > 1 else 0
    return ReleaseSeries(
        major=major, minor=minor, prerelease=_normalise_prerelease(remainder)
    )


def package_version(series: ReleaseSeries, ecosystem: str, regen_counter: int) -> str:
    """Render the package version for one series, ecosystem and counter.

    Args:
        series: The release series, from :func:`parse_version_line`.
        ecosystem: ``npm`` or ``pypi``.
        regen_counter: How many releases this series has already had in this ecosystem. ``0`` is
            the first publish.

    Returns:
        The version string to publish under: npm semver, or a PEP 440 version for PyPI.

    Raises:
        ValueError: If the ecosystem is not one SDK-4.1 publishes to, or the counter is negative.
    """
    if ecosystem not in PUBLISH_ECOSYSTEMS:
        raise ValueError(
            f"{ecosystem!r} is not a publishable ecosystem "
            f"({', '.join(PUBLISH_ECOSYSTEMS)})"
        )
    if regen_counter < 0:
        raise ValueError("regen counter cannot be negative")
    if regen_counter > MAX_COMPONENT:
        raise ValueError(
            f"regen counter {regen_counter} exceeds {MAX_COMPONENT:,}; this series is exhausted"
        )

    base = f"{series.major}.{series.minor}"
    if series.prerelease is None:
        # The stable rule, identical in both ecosystems: the counter is the patch.
        return f"{base}.{regen_counter}"

    if ecosystem == NPM_ECOSYSTEM:
        # A semver prerelease: `1.5.0-beta.3`. Numeric identifiers compare numerically, so the
        # counter orders these correctly, and all of them sort before `1.5.0`.
        return f"{base}.0-{series.prerelease}.{regen_counter}"

    phase = _PYPI_PHASES.get(series.prerelease)
    if phase:
        # PEP 440's own prerelease spelling: `1.5.0b3`, `1.5.0rc3`.
        return f"{base}.0{phase}{regen_counter}"
    # An unrecognised tag becomes a development release, which PEP 440 sorts before every
    # prerelease of the same base — the safest place for a version whose phase we cannot name.
    return f"{base}.0.dev{regen_counter}"


def resolve_package_version(
    version_line: Optional[str], ecosystem: str, regen_counter: int
) -> Tuple[ReleaseSeries, str]:
    """Map a version line straight to its package version — the whole rule in one call.

    Args:
        version_line: The published version's label.
        ecosystem: ``npm`` or ``pypi``.
        regen_counter: Releases this series has already had in this ecosystem.

    Returns:
        The ``(series, version)`` pair. The series is returned too because the caller stores it:
        it is the key the next counter is allocated under.

    Raises:
        VersionLineError: When the line cannot be mapped.
        ValueError: When the ecosystem or counter is out of range.
    """
    series = parse_version_line(version_line)
    return series, package_version(series, ecosystem, regen_counter)
