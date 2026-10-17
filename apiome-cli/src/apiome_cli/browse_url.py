"""Browse-app URLs for ``apiome browse open`` (CLI 9.9).

The ``apiome-browse`` app renders published specs at:

* ``/tenant/{tenant}`` — a tenant's public projects;
* ``/tenant/{tenant}/{project}`` — a project and its published versions;
* ``/tenant/{tenant}/{project}/{version}`` — one version;
* ``/tenant/{tenant}/{project}/compare?v1=…&v2=…`` — two versions side by side.

:func:`resolve_browse_base` finds where that app lives, and :func:`build_browse_url` turns the
command's ``PATH`` argument into a URL under it. Both are pure (no HTTP, no typer).

The browse base is, in order:

1. ``APIOME_BROWSE_URL``;
2. ``url`` in the ``[browse]`` section of the user config file (``~/.config/apiome/config.toml``);
3. derived from ``--base-url``: an ``api.`` host becomes ``browse.`` (``https://api.apiome.dev`` →
   ``https://browse.apiome.dev``), and a local API (``localhost``, ``127.0.0.1``, ``::1``) maps to
   the browse dev server on the same host, port 3001.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

#: Environment variable that overrides every other browse-base source.
BROWSE_URL_ENV = "APIOME_BROWSE_URL"
#: Config-file section and key holding the browse base.
BROWSE_SECTION = "browse"
BROWSE_URL_KEY = "url"
#: Port ``apiome-browse`` listens on in development (``apiome-browse/scripts/run.sh``).
LOCAL_BROWSE_PORT = 3001
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
#: Characters kept unescaped inside one path segment (the browse app's slugs and labels).
_SEGMENT_SAFE = "-._~@:+"


class BrowseUrlError(ValueError):
    """The browse base cannot be found, or the PATH argument is not usable."""


def normalize_base(url: str, *, source: str) -> str:
    """Return *url* without a trailing ``/``, after checking it is an absolute http(s) URL.

    Args:
        url: A configured browse base.
        source: Where it came from, for the error message.

    Raises:
        BrowseUrlError: When it is not ``http://`` or ``https://`` with a host.
    """
    text = url.strip()
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise BrowseUrlError(f"{source} must be an http(s) URL, got {url!r}")
    return text.rstrip("/")


def read_browse_section(config_path: Path) -> str | None:
    """Return ``[browse] url`` from the TOML file at *config_path*, or ``None`` if not set.

    A missing file, a missing section or an empty value all return ``None``.

    Raises:
        BrowseUrlError: When the file is not valid UTF-8 TOML, or the value is not a string.
    """
    if not config_path.is_file():
        return None
    try:
        document = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise BrowseUrlError(f"Cannot read {config_path}: {exc}") from exc
    section = document.get(BROWSE_SECTION)
    if not isinstance(section, dict):
        return None
    value = section.get(BROWSE_URL_KEY)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise BrowseUrlError(f"[{BROWSE_SECTION}] {BROWSE_URL_KEY} in {config_path} must be a string")
    return value


def derive_browse_base(api_base_url: str) -> str:
    """Derive the browse base from the REST base URL (the sibling-host rule).

    Args:
        api_base_url: ``--base-url`` / ``APIOME_BASE_URL``, e.g. ``https://api.apiome.dev``.

    Returns:
        ``https://browse.apiome.dev`` for an ``api.`` host, or ``http://localhost:3001`` for a
        local API. Any path on the API URL is dropped (the browse app has its own).

    Raises:
        BrowseUrlError: When neither rule applies; the message says how to configure it.
    """
    parts = urlsplit(api_base_url.strip())
    host = (parts.hostname or "").lower()
    if host.startswith("api.") and len(host) > len("api."):
        netloc = "browse." + parts.netloc.split("@")[-1][len("api."):]
        return urlunsplit((parts.scheme, netloc, "", "", "")).rstrip("/")
    if host in _LOCAL_HOSTS:
        shown = f"[{host}]" if ":" in host else host
        return f"{parts.scheme or 'http'}://{shown}:{LOCAL_BROWSE_PORT}"
    raise BrowseUrlError(
        f"Cannot work out the browse app's address from {api_base_url!r}. Set {BROWSE_URL_ENV}, "
        f'or add [{BROWSE_SECTION}] {BROWSE_URL_KEY} = "https://…" to the config file.'
    )


def resolve_browse_base(*, env_value: str | None, config_path: Path, api_base_url: str) -> str:
    """Pick the browse base: env, then the ``[browse]`` config section, then derivation.

    Args:
        env_value: ``APIOME_BROWSE_URL`` (``None`` or empty when unset).
        config_path: The user config file.
        api_base_url: The effective REST base URL.

    Raises:
        BrowseUrlError: From :func:`normalize_base`, :func:`read_browse_section` or
            :func:`derive_browse_base`.
    """
    if env_value and env_value.strip():
        return normalize_base(env_value, source=BROWSE_URL_ENV)
    configured = read_browse_section(config_path)
    if configured is not None:
        return normalize_base(configured, source=f"[{BROWSE_SECTION}] {BROWSE_URL_KEY}")
    return derive_browse_base(api_base_url)


def build_browse_url(base: str, target: str) -> str:
    """Build the browse URL for the command's PATH argument.

    ``tenant``, ``tenant/project``, ``tenant/project/version`` and any longer path (such as
    ``tenant/project/compare``) go under ``/tenant/``. A PATH that starts with ``/`` is taken from
    the browse root instead (``/mcp/search``). A ``?query`` is kept as typed, so
    ``acme-corp/payments-api/compare?v1=2.0.0&v2=2.1.0`` opens the compare page. Each path segment
    is percent-encoded.

    Args:
        base: From :func:`resolve_browse_base`.
        target: The PATH argument.

    Raises:
        BrowseUrlError: When the path is empty or has an empty segment (``a//b``).
    """
    text = target.strip()
    path, _, query = text.partition("?")
    from_root = path.startswith("/")
    segments = path.strip("/").split("/")
    if not segments or not all(segment.strip() for segment in segments):
        raise BrowseUrlError(f"expected <tenant>[/<project>[/<version>…]] or /<path>, got {target!r}")
    encoded = "/".join(quote(segment.strip(), safe=_SEGMENT_SAFE) for segment in segments)
    url = f"{base}/{encoded}" if from_root else f"{base}/tenant/{encoded}"
    return f"{url}?{query}" if query else url
