"""The generated Go client's opt-in compatibility beacon — RDG-1.7 / SGD-3.1 (#4736).

:mod:`app.go_client_generator` emits ``telemetry.go`` from :func:`render_telemetry_body`. The file
adds one option, ``WithTelemetry``; **without it the client never reports anything**. With it, the
client counts each call by operation and outcome and, every ``FlushEvery`` calls (and on
``FlushTelemetry``), posts the counts to the tenant's SDK beacon endpoint
(``POST /v1/tenants/{tenant}/usage/sdk-beacon``, :mod:`app.sdk_beacon_routes`).

A report says only what :mod:`app.sdk_beacon` allows — SDK name and version, API version and the
published revision the client was generated from, operation id, outcome category and a count. The
Go type that is marshalled (``beaconEvent``) has exactly those JSON fields; the request carries no
header of the API's own (the beacon uses its own HTTP client and its own ``usage:ingest`` key, never
the caller's credentials or ``WithHeader`` values), no URL, no host, no body, no status code, no
latency. A failed report is dropped: telemetry never fails, retries or slows an API call.

This module is pure: it renders text. The tokens baked in (revision, API version, SDK name) are
normalised here to the patterns the beacon endpoint accepts.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

__all__ = [
    "BEACON_JSON_FIELDS",
    "BEACON_OUTCOMES",
    "TELEMETRY_IDENTIFIERS",
    "beacon_operation_id",
    "beacon_token",
    "render_telemetry_body",
    "telemetry_readme_section",
]

#: The JSON fields of one reported event — the whole payload vocabulary. Mirrors
#: :class:`app.sdk_beacon.SdkBeaconEvent`; a test asserts the generated Go type has exactly these.
BEACON_JSON_FIELDS: Tuple[str, ...] = (
    "sdk_name",
    "sdk_version",
    "api_version",
    "spec_revision_id",
    "operation_id",
    "outcome",
    "count",
)

#: Outcome categories, as the client classifies calls. Mirrors :data:`app.sdk_beacon.OUTCOMES`.
BEACON_OUTCOMES: Tuple[str, ...] = ("ok", "client_error", "server_error", "network", "incompatible")

#: Package-level identifiers ``telemetry.go`` declares (reserved against generated names).
TELEMETRY_IDENTIFIERS = frozenset(
    {
        "ManifestAPIVersion",
        "ManifestRevisionID",
        "SDKName",
        "TelemetryConfig",
        "WithTelemetry",
        "beaconEvent",
        "beaconKey",
        "beaconReport",
        "classifyStatus",
        "telemetry",
    }
)

_UNSAFE_VERSION = re.compile(r"[^0-9A-Za-z._+-]+")
_UNSAFE_NAME = re.compile(r"[^a-z0-9._/-]+")
#: The beacon endpoint's ``operation_id`` pattern (:mod:`app.sdk_beacon`, V380).
_OPERATION = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.:/{} -]{0,254}$")
_UNSAFE_OPERATION = re.compile(r"[^A-Za-z0-9_.:/{} -]+")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def beacon_token(value: Optional[str], *, kind: str, fallback: str) -> str:
    """Normalise a value to the pattern the beacon endpoint accepts for its kind.

    Args:
        value: The raw value (an API version label, an SDK name).
        kind: ``version`` (``^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$``) or ``name``
            (``^[a-z0-9][a-z0-9._/-]{0,63}$``).
        fallback: What to use when nothing usable is left.

    Returns:
        The normalised token, at most 64 characters.
    """
    text = (value or "").strip()
    if kind == "name":
        text = _UNSAFE_NAME.sub("-", text.lower())
    else:
        text = _UNSAFE_VERSION.sub("-", text)
    text = text.lstrip("._+-/")[:64].rstrip("-")
    return text or fallback


def beacon_operation_id(identifier: str, key: str) -> str:
    """The operation id a client reports — the kit manifest's id whenever the endpoint accepts it.

    A report whose ``operation_id`` does not match the endpoint's pattern is refused as a whole, so a
    single unusual ``operationId`` (``get@pet``, non-ASCII) must not silence a client's reports. The
    manifest's id is used when it fits; otherwise the operation's key (``GET /pets/{petId}``, also in
    the manifest); otherwise the id with every disallowed character replaced by ``_``.

    Args:
        identifier: The manifest's ``operation_id``.
        key: The operation's canonical key.

    Returns:
        An id the beacon endpoint accepts.
    """
    for candidate in (identifier, key):
        if candidate and _OPERATION.match(candidate):
            return candidate
    cleaned = _UNSAFE_OPERATION.sub("_", identifier or key or "").lstrip(".:/{} -")[:255]
    return cleaned or "operation"


def normalise_revision(revision_id: Optional[str]) -> str:
    """The revision id to bake in, or ``""`` when there is none (telemetry then stays off).

    Args:
        revision_id: A ``versions.id`` UUID, when the client was built for a published revision.

    Returns:
        The lower-cased UUID, or ``""``.
    """
    value = (revision_id or "").strip()
    return value.lower() if _UUID.match(value) else ""


def render_telemetry_body(
    *, revision_literal: str, api_version_literal: str, sdk_name_literal: str
) -> Tuple[List[str], List[str]]:
    """Render ``telemetry.go``'s imports and declarations.

    Args:
        revision_literal: ``ManifestRevisionID`` as a Go string literal (``""`` disables telemetry).
        api_version_literal: ``ManifestAPIVersion`` as a Go string literal.
        sdk_name_literal: ``SDKName`` as a Go string literal.

    Returns:
        ``(imports, body)`` for :func:`app.go_client_generator._go_file`.
    """
    imports = ["bytes", "context", "encoding/json", "fmt", "net/http", "sort", "sync", "time"]
    body = [
        "",
        "// This file is the opt-in compatibility beacon. It is OFF unless you pass WithTelemetry:",
        "// a client built without it never sends anything anywhere except your own API calls.",
        "//",
        "// With it, the client counts each call by operation and outcome and reports the counts to",
        "// the API owner's Apiome workspace, so they can see which releases SDK users find",
        "// incompatible. A report carries only the fields of beaconEvent — never a request or",
        "// response body, a header, a URL, a host, a status code, a latency or a credential of the",
        "// API you are calling.",
        "",
        "const (",
        "\t// ManifestRevisionID is the published revision this client was generated from — the",
        "\t// revision the Apiome SDK kit manifest names. Empty when the client was generated outside",
        "\t// a kit, in which case WithTelemetry leaves telemetry off.",
        f"\tManifestRevisionID = {revision_literal}",
        "\t// ManifestAPIVersion is the API version this client was generated for.",
        f"\tManifestAPIVersion = {api_version_literal}",
        "\t// SDKName names this client in telemetry reports.",
        f"\tSDKName = {sdk_name_literal}",
        ")",
        "",
        "// TelemetryConfig turns on the opt-in compatibility beacon. Every field but HTTPClient,",
        "// SDKVersion and FlushEvery is required; a config missing one leaves telemetry off.",
        "type TelemetryConfig struct {",
        "\t// Endpoint is the beacon URL the API owner gives you, for example",
        "\t// https://apiome.example.com/v1/tenants/acme/usage/sdk-beacon.",
        "\tEndpoint string",
        "\t// APIKey is the key the API owner gives you for reporting. It carries only the",
        "\t// usage:ingest scope; it is not your key for the API itself.",
        "\tAPIKey string",
        "\t// SourceID names the owner's sdk_beacon usage source.",
        "\tSourceID string",
        "\t// SDKVersion is this SDK's own version. Defaults to ManifestAPIVersion.",
        "\tSDKVersion string",
        "\t// HTTPClient sends the reports. Defaults to an http.Client with a 5-second timeout; it is",
        "\t// never the Doer your API calls use, so none of their headers or credentials can leak.",
        "\tHTTPClient Doer",
        "\t// FlushEvery is how many calls are counted between reports. Defaults to 100.",
        "\tFlushEvery int",
        "}",
        "",
        "// beaconKey groups calls: one count per operation and outcome.",
        "type beaconKey struct {",
        "\toperation string",
        "\toutcome   string",
        "}",
        "",
        "// beaconEvent is one reported count. These seven fields are the whole payload.",
        "type beaconEvent struct {",
        '\tSDKName        string `json:"sdk_name"`',
        '\tSDKVersion     string `json:"sdk_version"`',
        '\tAPIVersion     string `json:"api_version"`',
        '\tSpecRevisionID string `json:"spec_revision_id"`',
        '\tOperationID    string `json:"operation_id"`',
        '\tOutcome        string `json:"outcome"`',
        '\tCount          int    `json:"count"`',
        "}",
        "",
        "// beaconReport is the body posted to the beacon endpoint.",
        "type beaconReport struct {",
        '\tSchema   string        `json:"schema"`',
        '\tSourceID string        `json:"source_id"`',
        '\tEvents   []beaconEvent `json:"events"`',
        "}",
        "",
        "// telemetry holds the counts between reports.",
        "type telemetry struct {",
        "\tcfg     TelemetryConfig",
        "\tmu      sync.Mutex",
        "\tcounts  map[beaconKey]int",
        "\tpending int",
        "}",
        "",
        "// WithTelemetry turns on the opt-in compatibility beacon. Without this option — the",
        "// default — the client reports nothing. A config without Endpoint, APIKey or SourceID, or a",
        "// client generated outside an SDK kit (no ManifestRevisionID), leaves telemetry off.",
        "func WithTelemetry(cfg TelemetryConfig) Option {",
        "\treturn func(c *Client) {",
        '\t\tif cfg.Endpoint == "" || cfg.APIKey == "" || cfg.SourceID == "" || ManifestRevisionID == "" {',
        "\t\t\tc.telemetry = nil",
        "\t\t\treturn",
        "\t\t}",
        '\t\tif cfg.SDKVersion == "" {',
        "\t\t\tcfg.SDKVersion = ManifestAPIVersion",
        "\t\t}",
        "\t\tif cfg.HTTPClient == nil {",
        "\t\t\tcfg.HTTPClient = &http.Client{Timeout: 5 * time.Second}",
        "\t\t}",
        "\t\tif cfg.FlushEvery <= 0 {",
        "\t\t\tcfg.FlushEvery = 100",
        "\t\t}",
        "\t\tc.telemetry = &telemetry{cfg: cfg, counts: map[beaconKey]int{}}",
        "\t}",
        "}",
        "",
        "// FlushTelemetry reports the counts gathered since the last report. It does nothing when",
        "// telemetry is off. Call it before your program exits; otherwise counts are reported every",
        "// FlushEvery calls.",
        "func (c *Client) FlushTelemetry(ctx context.Context) error {",
        "\tif c.telemetry == nil {",
        "\t\treturn nil",
        "\t}",
        "\treturn c.telemetry.flush(ctx)",
        "}",
        "",
        "// observe counts one finished call, when telemetry is on.",
        "func (c *Client) observe(operationID, outcome string) {",
        "\tif c.telemetry != nil {",
        "\t\tc.telemetry.record(operationID, outcome)",
        "\t}",
        "}",
        "",
        "// classifyStatus turns a non-2xx status into an outcome category.",
        "func classifyStatus(status int) string {",
        "\tif status >= 500 {",
        '\t\treturn "server_error"',
        "\t}",
        '\treturn "client_error"',
        "}",
        "",
        "// record counts a call and starts a background report every FlushEvery calls. A report",
        "// runs off the caller's goroutine, so it never slows the API call that triggered it.",
        "func (t *telemetry) record(operationID, outcome string) {",
        "\tt.mu.Lock()",
        "\tt.counts[beaconKey{operation: operationID, outcome: outcome}]++",
        "\tt.pending++",
        "\tdue := t.pending >= t.cfg.FlushEvery",
        "\tt.mu.Unlock()",
        "\tif due {",
        "\t\tgo func() { _ = t.flush(context.Background()) }()",
        "\t}",
        "}",
        "",
        "// take empties the counts into report events, in a stable order.",
        "func (t *telemetry) take() []beaconEvent {",
        "\tt.mu.Lock()",
        "\tdefer t.mu.Unlock()",
        "\tevents := make([]beaconEvent, 0, len(t.counts))",
        "\tfor key, count := range t.counts {",
        "\t\tevents = append(events, beaconEvent{",
        "\t\t\tSDKName:        SDKName,",
        "\t\t\tSDKVersion:     t.cfg.SDKVersion,",
        "\t\t\tAPIVersion:     ManifestAPIVersion,",
        "\t\t\tSpecRevisionID: ManifestRevisionID,",
        "\t\t\tOperationID:    key.operation,",
        "\t\t\tOutcome:        key.outcome,",
        "\t\t\tCount:          count,",
        "\t\t})",
        "\t}",
        "\tt.counts = map[beaconKey]int{}",
        "\tt.pending = 0",
        "\tsort.Slice(events, func(i, j int) bool {",
        "\t\tif events[i].OperationID != events[j].OperationID {",
        "\t\t\treturn events[i].OperationID < events[j].OperationID",
        "\t\t}",
        "\t\treturn events[i].Outcome < events[j].Outcome",
        "\t})",
        "\treturn events",
        "}",
        "",
        "// flush posts the counts. A refused or failed report is dropped, not retried: the counts are",
        "// best-effort evidence, never worth slowing or failing the application.",
        "func (t *telemetry) flush(ctx context.Context) error {",
        "\tevents := t.take()",
        "\tif len(events) == 0 {",
        "\t\treturn nil",
        "\t}",
        '\tpayload, err := json.Marshal(beaconReport{Schema: "apiome.sdk.beacon/v1", SourceID: t.cfg.SourceID, Events: events})',
        "\tif err != nil {",
        "\t\treturn err",
        "\t}",
        "\treq, err := http.NewRequestWithContext(ctx, http.MethodPost, t.cfg.Endpoint, bytes.NewReader(payload))",
        "\tif err != nil {",
        "\t\treturn err",
        "\t}",
        '\treq.Header.Set("Content-Type", "application/json")',
        '\treq.Header.Set("X-API-Key", t.cfg.APIKey)',
        "\tresp, err := t.cfg.HTTPClient.Do(req)",
        "\tif err != nil {",
        "\t\treturn err",
        "\t}",
        "\tdefer resp.Body.Close()",
        "\tif resp.StatusCode < 200 || resp.StatusCode > 299 {",
        '\t\treturn fmt.Errorf("telemetry report refused: HTTP %d", resp.StatusCode)',
        "\t}",
        "\treturn nil",
        "}",
    ]
    return imports, body


def telemetry_readme_section(revision_id: str) -> List[str]:
    """The generated README's **Telemetry (opt-in)** section.

    Args:
        revision_id: The baked-in revision, or ``""`` (then the section says telemetry is unavailable).

    Returns:
        Markdown lines.
    """
    lines = [
        "## Telemetry (opt-in)",
        "",
        "**Off by default.** This client sends nothing to anyone but the API you call unless you pass",
        "`WithTelemetry`. If the API's owner asks you to help them find incompatible releases, they give",
        "you a beacon endpoint, a reporting key and a source id:",
        "",
        "```go",
        "client := NewClient(WithTelemetry(TelemetryConfig{",
        '\tEndpoint: "https://apiome.example.com/v1/tenants/acme/usage/sdk-beacon",',
        '\tAPIKey:   os.Getenv("APIOME_BEACON_KEY"),',
        '\tSourceID: "00000000-0000-0000-0000-000000000000",',
        "}))",
        "defer client.FlushTelemetry(context.Background())",
        "```",
        "",
        "Each report counts calls per operation and outcome and carries **only**: this SDK's name and",
        "version, the API version and published revision it was generated from, the operation id, the",
        "outcome (`ok`, `client_error`, `server_error`, `network`, `incompatible`) and the count. It never",
        "carries request or response bodies, headers, URLs, hosts, status codes, latencies, your",
        "credentials or anything that identifies you. Reports use their own HTTP client and key, are",
        "sent in the background every 100 calls (`FlushEvery`) and on `FlushTelemetry`, and a failed",
        "report is dropped — telemetry never fails or slows a call.",
    ]
    if not revision_id:
        lines += [
            "",
            "This build was generated outside an Apiome SDK kit, so it has no `ManifestRevisionID` and",
            "`WithTelemetry` leaves telemetry off.",
        ]
    return lines
