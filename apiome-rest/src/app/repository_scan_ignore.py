"""Include / exclude rules for the repository scanner (REPO-2.2, #2763).

Most repositories carry vendored, build and test-fixture trees that are noise for spec
discovery. The scanner skips them with:

* :data:`DEFAULT_SCAN_IGNORE_PATTERNS` — always on (mirrored for the UI in
  ``apiome-ui/lib/repositories/scanner/defaults.ts``; a test keeps the two equal);
* the ``ignore:`` array of the repository's optional manifest
  (:data:`SCAN_MANIFEST_PATH`), **added** to the defaults;
* the manifest's ``specs:`` entries, which always win: a file matching a ``specs:`` entry
  is indexed even when an ``ignore:`` pattern (default or manifest) matches it.

Patterns are repository-relative globs matched segment by segment: ``*`` / ``?`` / ``[…]``
stay inside one path segment and ``**`` spans any number of segments (including none), so
``**/node_modules/**`` matches ``node_modules/x.js`` and ``web/node_modules/a/b.js``.

Only ``ignore:`` and ``specs[].path`` are read from the manifest here; the rest of its keys
belong to the manifest feature proper and are ignored by the scanner.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any, Callable, List, Optional, Sequence, Tuple

import yaml

_logger = logging.getLogger(__name__)

#: Ignored on every scan. Keep equal to ``DEFAULT_REPOSITORY_SCAN_IGNORE_PATTERNS`` in
#: ``apiome-ui/lib/repositories/scanner/defaults.ts``.
DEFAULT_SCAN_IGNORE_PATTERNS: Tuple[str, ...] = (
    "**/.git/**",
    "**/node_modules/**",
    "**/vendor/**",
    "**/dist/**",
    "**/build/**",
    "**/coverage/**",
    "**/__pycache__/**",
)

#: Where the scanner looks for per-repository overrides, relative to the repository root.
SCAN_MANIFEST_PATH = ".apiome/repo.yaml"

#: Caps on what a manifest may contribute, so a hostile or broken file cannot make every
#: path test expensive.
MAX_MANIFEST_PATTERNS = 500
MAX_PATTERN_LENGTH = 512
MAX_MANIFEST_BYTES = 256_000


def _split(path_or_pattern: str) -> List[str]:
    """Split a repository-relative path or pattern into its non-empty segments."""
    return [part for part in path_or_pattern.strip().replace("\\", "/").split("/") if part]


def _pattern_parts(pattern: str) -> Tuple[str, ...]:
    """Split a pattern into segments, collapsing runs of ``**`` (they mean the same thing)."""
    parts: List[str] = []
    for part in _split(pattern):
        if part == "**" and parts and parts[-1] == "**":
            continue
        parts.append(part)
    return tuple(parts)


def _match_parts(path: Sequence[str], pattern: Sequence[str]) -> bool:
    """Whether path segments match pattern segments (``**`` spans zero or more segments).

    Args:
        path: The path's segments.
        pattern: The pattern's segments.

    Returns:
        True when the whole path matches the whole pattern.
    """
    if not pattern:
        return not path
    head = pattern[0]
    if head == "**":
        # Collapse runs of ``**`` and try every split point.
        rest = pattern[1:]
        return any(_match_parts(path[i:], rest) for i in range(len(path) + 1))
    if not path:
        return False
    return fnmatchcase(path[0], head) and _match_parts(path[1:], pattern[1:])


def _could_match_below(directory: Sequence[str], pattern: Sequence[str]) -> bool:
    """Whether ``pattern`` could match some file strictly inside ``directory``.

    Conservative by construction: it answers True whenever the directory's segments are a
    possible prefix of a match, which is what pruning needs — a directory is only skipped
    when no ``specs:`` entry could reach into it.

    Args:
        directory: The directory's segments.
        pattern: A ``specs:`` pattern's segments.

    Returns:
        True when a file below the directory might match.
    """
    if not directory:
        # Something must remain to name a file below the directory.
        return bool(pattern)
    if not pattern:
        return False
    head = pattern[0]
    if head == "**":
        return _could_match_below(directory, pattern[1:]) or _could_match_below(directory[1:], pattern)
    return fnmatchcase(directory[0], head) and _could_match_below(directory[1:], pattern[1:])


def _normalize_patterns(raw: Any, *, field_name: str) -> List[str]:
    """Clean a manifest pattern list: strings only, trimmed, deduplicated, capped.

    Args:
        raw: The manifest value (expected: a list of strings).
        field_name: The manifest key, for the log line.

    Returns:
        The usable patterns, in manifest order.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        _logger.warning("repository manifest %s is not a list; ignoring it", field_name)
        return []
    patterns: List[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        pattern = item.strip().replace("\\", "/").lstrip("/")
        if not pattern or len(pattern) > MAX_PATTERN_LENGTH or pattern in patterns:
            continue
        patterns.append(pattern)
        if len(patterns) >= MAX_MANIFEST_PATTERNS:
            _logger.warning(
                "repository manifest %s has more than %s patterns; the rest are dropped",
                field_name,
                MAX_MANIFEST_PATTERNS,
            )
            break
    return patterns


def merge_ignore_patterns(manifest_ignore: Sequence[str]) -> Tuple[str, ...]:
    """Return the defaults followed by any manifest patterns they do not already contain.

    Args:
        manifest_ignore: The manifest's cleaned ``ignore:`` patterns.

    Returns:
        The merged pattern tuple.
    """
    merged = list(DEFAULT_SCAN_IGNORE_PATTERNS)
    for pattern in manifest_ignore:
        if pattern not in merged:
            merged.append(pattern)
    return tuple(merged)


@dataclass(frozen=True)
class ScanIgnoreRules:
    """The effective include / exclude rules for one scan.

    Attributes:
        ignore_patterns: Defaults plus the manifest's ``ignore:`` patterns.
        spec_patterns: The manifest's ``specs:`` paths / patterns; these always win.
    """

    ignore_patterns: Tuple[str, ...] = DEFAULT_SCAN_IGNORE_PATTERNS
    spec_patterns: Tuple[str, ...] = ()
    _ignore_parts: Tuple[Tuple[str, ...], ...] = field(init=False, repr=False, compare=False)
    _spec_parts: Tuple[Tuple[str, ...], ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_ignore_parts", tuple(_pattern_parts(p) for p in self.ignore_patterns))
        object.__setattr__(self, "_spec_parts", tuple(_pattern_parts(p) for p in self.spec_patterns))

    def is_explicit_spec(self, path: str) -> bool:
        """Whether ``path`` matches a manifest ``specs:`` entry."""
        parts = _split(path)
        return any(_match_parts(parts, spec) for spec in self._spec_parts)

    def ignores_file(self, path: str) -> bool:
        """Whether the scanner should skip the file at ``path``.

        Args:
            path: Repository-relative file path.

        Returns:
            True when an ignore pattern matches and no ``specs:`` entry does.
        """
        parts = _split(path)
        if any(_match_parts(parts, spec) for spec in self._spec_parts):
            return False
        return any(_match_parts(parts, pattern) for pattern in self._ignore_parts)

    def prunes_directory(self, path: str) -> bool:
        """Whether the scanner may skip a whole directory without listing it.

        True only when an ignore pattern ending in ``**`` covers everything below the
        directory and no ``specs:`` entry could match a file inside it.

        Args:
            path: Repository-relative directory path.

        Returns:
            True when every file below the directory would be ignored.
        """
        parts = _split(path)
        if not parts:
            return False
        if any(_could_match_below(parts, spec) for spec in self._spec_parts):
            return False
        for pattern in self._ignore_parts:
            if not pattern or pattern[-1] != "**":
                continue
            head = pattern[:-1]
            if any(_match_parts(parts[:k], head) for k in range(1, len(parts) + 1)):
                return True
        return False


def parse_scan_manifest(text: str) -> ScanIgnoreRules:
    """Build the scan rules from a manifest's text.

    A manifest that is not valid YAML, or not a mapping, contributes nothing: the scan
    runs on the defaults rather than failing.

    Args:
        text: The manifest file's contents.

    Returns:
        The effective rules.
    """
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        _logger.warning("repository manifest is not valid YAML; using default ignore rules: %s", exc)
        return ScanIgnoreRules()
    if doc is None:
        return ScanIgnoreRules()
    if not isinstance(doc, dict):
        _logger.warning("repository manifest is not a mapping; using default ignore rules")
        return ScanIgnoreRules()

    raw_specs = doc.get("specs")
    spec_paths: List[Any] = []
    if isinstance(raw_specs, list):
        for entry in raw_specs:
            # REPO-2.4 entries are mappings with a ``path``; a bare string is accepted too.
            spec_paths.append(entry.get("path") if isinstance(entry, dict) else entry)
    elif raw_specs is not None:
        _logger.warning("repository manifest specs is not a list; ignoring it")

    return ScanIgnoreRules(
        ignore_patterns=merge_ignore_patterns(_normalize_patterns(doc.get("ignore"), field_name="ignore")),
        spec_patterns=tuple(_normalize_patterns(spec_paths, field_name="specs")),
    )


def load_scan_ignore_rules(
    fetch_text: Callable[..., Tuple[str, bool]],
    owner: str,
    repo: str,
    ref: str,
    token: Optional[str],
) -> ScanIgnoreRules:
    """Read the repository's manifest at ``ref`` and build the scan rules.

    A missing manifest is the common case and yields the defaults. Any other failure (a
    provider error, an oversized file) is logged and also yields the defaults: ignore rules
    only save work, so they must never stop a scan.

    Args:
        fetch_text: ``fetch_github_repository_file_text`` or a stand-in with its signature.
        owner: GitHub owner.
        repo: GitHub repository name.
        ref: Branch name or commit SHA to read the manifest at.
        token: Access token, if any.

    Returns:
        The effective rules.
    """
    try:
        text, truncated = fetch_text(owner, repo, SCAN_MANIFEST_PATH, ref, token, max_bytes=MAX_MANIFEST_BYTES)
    except ValueError as exc:
        if "not found" in str(exc):
            return ScanIgnoreRules()
        _logger.warning("repository manifest could not be read; using default ignore rules: %s", exc)
        return ScanIgnoreRules()
    except Exception as exc:  # noqa: BLE001 - ignore rules are an optimisation; never fail the scan
        _logger.warning(
            "repository manifest could not be read; using default ignore rules: %s",
            f"{type(exc).__name__}: {exc}"[:300],
        )
        return ScanIgnoreRules()
    if truncated:
        _logger.warning("repository manifest exceeds %s bytes; using default ignore rules", MAX_MANIFEST_BYTES)
        return ScanIgnoreRules()
    return parse_scan_manifest(text)
