"""ACP agent discovery for ``apiome import acp --discover`` (MFI-18.2, #3975).

An ACP server lists the agents it hosts at ``GET /agents`` (under whatever path prefix it is
mounted at) and describes one at ``GET /agents/{name}``. :func:`acp_agents_url` turns a server's
base URL into that listing URL; the listing is then imported through the ordinary
registry-dispatch import, so the server parses, normalizes, versions and lints it exactly as it
would a ``--url`` import. The rules mirror the REST adapter's live discovery
(``app.acp_agent_discovery``).
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def acp_agents_url(base_url: str) -> str:
    """Return the listing URL to import for an ACP server at ``base_url``.

    Args:
        base_url: The server's base URL (``https://acp.example.com`` or a prefix such as
            ``https://example.com/acp``), its ``…/agents`` listing, or one agent's
            ``…/agents/<name>`` URL.

    Returns:
        ``base_url`` itself (query and fragment dropped) when it already names a listing or an
        agent, else ``<base_url>/agents``.

    Raises:
        ValueError: When ``base_url`` is empty, not ``http``/``https``, or has no host.
    """
    cleaned = (base_url or "").strip()
    if not cleaned:
        raise ValueError("ACP server URL is empty")
    parts = urlsplit(cleaned)
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError("ACP server URL must be an http or https URL")
    if not parts.netloc:
        raise ValueError("ACP server URL has no host")
    path = parts.path.rstrip("/")
    segments = path.split("/")
    if segments[-1] != "agents" and not (len(segments) >= 2 and segments[-2] == "agents"):
        path = f"{path}/agents"
    return urlunsplit((parts.scheme.lower(), parts.netloc, path, "", ""))
