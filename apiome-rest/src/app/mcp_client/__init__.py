"""Client-side Model Context Protocol (MCP) plumbing for the catalog (V2-MCP-EPIC-16).

This package implements the *client* half of MCP — the code Apiome uses to
reach out to external MCP servers, discover their capabilities, and normalize
them for the catalog. The first building block is the network transport; the
lifecycle handshake (``initialize`` + version negotiation) sits on top of it.

Modules:
    transport_http: JSON-RPC 2.0 over the MCP "Streamable HTTP" transport.
    handshake: The ``initialize`` opening handshake and protocol-version negotiation.
    discovery: Paginated ``*/list`` discovery of the declared capability surface.
    normalize: Canonical, version-tolerant ``DiscoverySurface`` + DB row mapping.
    diff: Structured ``diff_surfaces`` over two surfaces (added/removed/modified).
    resilience: Time-budget and private-address primitives for safe remote runs.
    errors: Stable error taxonomy persisted on ``mcp_discovery_jobs.error``.
"""

from .branding import (
    MAX_BRANDING_URL_LENGTH,
    ServerBranding,
    extract_server_branding,
    safe_branding_url,
)
from .diff import (
    CHANGE_ADDED,
    CHANGE_MODIFIED,
    CHANGE_REMOVED,
    ITEM_TYPE_SERVER,
    FieldChange,
    ItemChange,
    SurfaceDiff,
    diff_surfaces,
)
from .discovery import (
    DEFAULT_PAGE_LIMIT,
    LIST_METHODS,
    DiscoveryListings,
    ListMethod,
    McpDiscoveryError,
    McpPaginationError,
    discover_listings,
    paginate,
)
from .errors import (
    DiscoveryError,
    DiscoveryErrorCode,
    classify_exception,
)
from .handshake import (
    DEFAULT_CLIENT_CAPABILITIES,
    DEFAULT_CLIENT_INFO,
    INVALID_PARAMS_CODE,
    SUPPORTED_PROTOCOL_VERSIONS,
    InitializeResult,
    McpVersionNegotiationError,
    ServerInfo,
    initialize_session,
)
from .normalize import (
    ITEM_TYPE_PROMPT,
    ITEM_TYPE_RESOURCE,
    ITEM_TYPE_RESOURCE_TEMPLATE,
    ITEM_TYPE_TOOL,
    ITEM_TYPES,
    CapabilityItem,
    DiscoverySurface,
)
from .resilience import (
    DEFAULT_PER_CALL_TIMEOUT,
    DEFAULT_TOTAL_BUDGET,
    BudgetExceededError,
    TimeBudget,
    private_address_reason,
)
from .transport_http import (
    DEFAULT_PROTOCOL_VERSION,
    JsonRpcError,
    JsonRpcResponse,
    McpAuthRequiredError,
    McpHttpStatusError,
    McpProtocolError,
    McpRateLimitedError,
    McpSessionExpiredError,
    McpSsrfError,
    McpTransportError,
    StreamableHttpTransport,
    parse_retry_after_seconds,
)
from .transport_meta import (
    NOTABLE_RESPONSE_HEADERS,
    TlsCertificateSummary,
    TransportMetadata,
    capture_transport_metadata,
    summarize_peer_cert,
)

__all__ = [
    "CHANGE_ADDED",
    "CHANGE_MODIFIED",
    "CHANGE_REMOVED",
    "DEFAULT_CLIENT_CAPABILITIES",
    "DEFAULT_CLIENT_INFO",
    "DEFAULT_PAGE_LIMIT",
    "DEFAULT_PER_CALL_TIMEOUT",
    "DEFAULT_PROTOCOL_VERSION",
    "DEFAULT_TOTAL_BUDGET",
    "INVALID_PARAMS_CODE",
    "ITEM_TYPES",
    "ITEM_TYPE_PROMPT",
    "ITEM_TYPE_RESOURCE",
    "ITEM_TYPE_RESOURCE_TEMPLATE",
    "ITEM_TYPE_SERVER",
    "ITEM_TYPE_TOOL",
    "LIST_METHODS",
    "MAX_BRANDING_URL_LENGTH",
    "NOTABLE_RESPONSE_HEADERS",
    "SUPPORTED_PROTOCOL_VERSIONS",
    "BudgetExceededError",
    "CapabilityItem",
    "DiscoveryError",
    "DiscoveryErrorCode",
    "DiscoveryListings",
    "DiscoverySurface",
    "FieldChange",
    "InitializeResult",
    "ItemChange",
    "JsonRpcError",
    "JsonRpcResponse",
    "ListMethod",
    "McpAuthRequiredError",
    "McpDiscoveryError",
    "McpHttpStatusError",
    "McpPaginationError",
    "McpProtocolError",
    "McpRateLimitedError",
    "McpSessionExpiredError",
    "McpSsrfError",
    "McpTransportError",
    "McpVersionNegotiationError",
    "ServerBranding",
    "ServerInfo",
    "StreamableHttpTransport",
    "SurfaceDiff",
    "TimeBudget",
    "TlsCertificateSummary",
    "TransportMetadata",
    "capture_transport_metadata",
    "classify_exception",
    "diff_surfaces",
    "discover_listings",
    "extract_server_branding",
    "initialize_session",
    "safe_branding_url",
    "paginate",
    "parse_retry_after_seconds",
    "private_address_reason",
    "summarize_peer_cert",
]
