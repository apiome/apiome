"""Load import document text from local paths, stdin, or HTTP(S) URLs."""

from __future__ import annotations

import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from apiome_cli.import_.yaml_load import safe_load_mapping

_ACCEPTED_SUFFIXES = frozenset({".json", ".yaml", ".yml"})


def is_remote_source(source: str) -> bool:
    """Return whether *source* is an HTTP or HTTPS URL."""
    parsed = urlparse(source)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_local_file_source(source: str) -> bool:
    """Return whether *source* is a local filesystem path (not stdin or URL)."""
    return source != "-" and not is_remote_source(source)


def read_document_bytes(source: str) -> tuple[bytes, str | None]:
    """Read raw document bytes and an optional filename for local paths or stdin."""
    if source == "-":
        return sys.stdin.buffer.read(), None
    if is_remote_source(source):
        msg = "read_document_bytes does not fetch remote URLs"
        raise ValueError(msg)
    path = Path(source)
    return path.read_bytes(), path.name


def load_document_bytes(
    source: str,
    *,
    timeout: float = 30.0,
    verify: bool = True,
) -> tuple[bytes, str | None]:
    """Read raw document bytes from a local path, stdin (``-``), or an HTTP(S) URL.

    Unlike :func:`load_import_document`, this performs **no parsing** and returns the
    bytes verbatim, so format-agnostic adapters (GraphQL SDL, protobuf, Avro, …) can
    be uploaded without being forced through a JSON/YAML reader.

    Args:
        source: Local path, ``-`` for stdin, or an ``http``/``https`` URL.
        timeout: HTTP connect + read timeout when fetching a URL.
        verify: Whether to verify TLS certificates for URL fetches.

    Returns:
        Tuple of raw bytes and an optional filename hint (``None`` for stdin).

    Raises:
        OSError: If a local file cannot be read or a URL fetch fails.
    """
    if is_remote_source(source):
        return _fetch_url_bytes(source, timeout=timeout, verify=verify)
    return read_document_bytes(source)


def _fetch_url_bytes(
    url: str,
    *,
    timeout: float,
    verify: bool,
) -> tuple[bytes, str | None]:
    try:
        with httpx.Client(timeout=timeout, verify=verify) as client:
            response = client.get(url, follow_redirects=True)
    except httpx.RequestError as exc:
        raise OSError(f"Failed to fetch {url!r}: {exc}") from exc
    if response.status_code >= 400:
        raise OSError(f"Failed to fetch {url!r}: HTTP {response.status_code}")
    return response.content, source_basename(url)


def source_basename(source: str) -> str | None:
    """Return a filename hint for *source*, or ``None`` for stdin."""
    if source == "-":
        return None
    if is_remote_source(source):
        path = unquote(urlparse(source).path or "")
        name = PurePosixPath(path).name
        return name or None
    return Path(source).name


def format_import_source_label(source: str) -> str:
    """Return a short human-readable label for an import source path or URL."""
    if source == "-":
        return "stdin"
    basename = source_basename(source)
    if basename:
        return basename
    if is_remote_source(source):
        return source
    return source


def source_byte_size(source: str) -> int | None:
    """Return the on-disk byte length for a local import *source*, when known."""
    if not is_local_file_source(source):
        return None
    return Path(source).stat().st_size


def format_document_import_progress(
    *,
    document_label: str,
    source: str,
    dry_run: bool,
    target_label: str | None = None,
) -> str:
    """Build a one-line stderr message before uploading or fetching a document."""
    source_label = format_import_source_label(source)
    byte_size = source_byte_size(source)
    if byte_size is not None:
        source_label = f"{source_label} ({byte_size} bytes)"
    target_suffix = f" for {target_label}" if target_label else ""

    if dry_run:
        return (
            f"Planning {document_label} import (dry run) of "
            f"{source_label}{target_suffix}…"
        )
    if is_remote_source(source):
        return (
            f"Fetching {document_label} document {source_label}{target_suffix}…"
        )
    return f"Uploading {document_label} document {source_label}{target_suffix}…"


def suffix_from_source(source: str) -> str | None:
    """Return a supported format suffix (``.json``, ``.yaml``, ``.yml``) when known."""
    if source == "-":
        return None
    if is_remote_source(source):
        suffix = PurePosixPath(unquote(urlparse(source).path or "")).suffix.lower()
    else:
        suffix = Path(source).suffix.lower()
    if suffix in _ACCEPTED_SUFFIXES:
        return suffix
    return None


def read_document_text(
    source: str,
    *,
    timeout: float = 30.0,
    verify: bool = True,
) -> tuple[str, str | None]:
    """Read raw document text and an optional format suffix hint.

    Args:
        source: Local path, ``-`` for stdin, or an ``http``/``https`` URL.
        timeout: HTTP connect + read timeout when fetching a URL.
        verify: Whether to verify TLS certificates for URL fetches.

    Returns:
        Tuple of document text and an optional suffix (``.json``, ``.yaml``,
        ``.yml``). The suffix may come from the path, URL, or ``Content-Type``
        header. ``None`` means callers should try JSON then YAML.

    Raises:
        OSError: If a local file cannot be read or a URL fetch fails.
    """
    if source == "-":
        return sys.stdin.read(), None
    if is_remote_source(source):
        return _fetch_url(source, timeout=timeout, verify=verify)
    text = Path(source).read_text(encoding="utf-8")
    return text, suffix_from_source(source)


def _fetch_url(
    url: str,
    *,
    timeout: float,
    verify: bool,
) -> tuple[str, str | None]:
    try:
        with httpx.Client(timeout=timeout, verify=verify) as client:
            response = client.get(url, follow_redirects=True)
    except httpx.RequestError as exc:
        raise OSError(f"Failed to fetch {url!r}: {exc}") from exc

    if response.status_code >= 400:
        raise OSError(
            f"Failed to fetch {url!r}: HTTP {response.status_code}"
        )

    suffix = suffix_from_source(url)
    if suffix is None:
        suffix = _suffix_from_content_type(
            response.headers.get("content-type", "")
        )
    return response.text, suffix


def _suffix_from_content_type(content_type: str) -> str | None:
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type in {"application/json", "application/schema+json"}:
        return ".json"
    if media_type in {
        "application/yaml",
        "application/x-yaml",
        "text/yaml",
        "text/x-yaml",
    }:
        return ".yaml"
    return None


def load_import_document(
    source: str,
    *,
    timeout: float = 30.0,
    verify: bool = True,
) -> dict[str, Any]:
    """Load and parse any supported import document from *source*.

    Args:
        source: Local path, ``-`` for stdin, or an ``http``/``https`` URL.
        timeout: HTTP connect + read timeout when fetching a URL.
        verify: Whether to verify TLS certificates for URL fetches.

    Returns:
        Parsed top-level mapping.

    Raises:
        ValueError: On unsupported extensions or parse failures.
        OSError: If a local file cannot be read or a URL fetch fails.
    """
    if not is_remote_source(source) and source != "-":
        suffix = suffix_from_source(source)
        if suffix is None:
            raise ValueError(
                f"Unsupported file extension '{Path(source).suffix.lower()}'. "
                "Accepted extensions are: .json, .yaml, .yml"
            )

    text, suffix = read_document_text(source, timeout=timeout, verify=verify)
    return parse_mapping_document(text, source=source, suffix=suffix)


def parse_mapping_document(
    text: str,
    *,
    source: str,
    suffix: str | None,
) -> dict[str, Any]:
    """Parse *text* as JSON or YAML into a top-level mapping.

    When *suffix* is ``None`` (stdin or URL without a format hint), JSON is
    tried first, then YAML.
    """
    if suffix == ".json":
        return _parse_json(text, source=source)
    if suffix in {".yaml", ".yml"}:
        return _parse_yaml(text, source=source)
    return _parse_auto(text, source=source)


def _parse_json(text: str, *, source: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse JSON from {source!r}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(
            f"Expected a JSON object at the top level, got {type(data).__name__}."
        )
    return data


def _parse_yaml(text: str, *, source: str) -> dict[str, Any]:
    try:
        return safe_load_mapping(text)
    except ValueError as exc:
        raise ValueError(f"Failed to parse YAML from {source!r}: {exc}") from exc


def _parse_auto(text: str, *, source: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        pass
    else:
        if not isinstance(data, dict):
            raise ValueError(
                f"Expected a JSON object at the top level, got {type(data).__name__}."
            )
        return data
    try:
        return _parse_yaml(text, source=source)
    except ValueError as exc:
        raise ValueError(
            f"Content from {source!r} could not be parsed as JSON or YAML: {exc}"
        ) from exc
