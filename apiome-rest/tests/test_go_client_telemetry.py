"""The generated Go client's opt-in compatibility beacon — RDG-1.7 / SGD-3.1 (#4736).

#4736's acceptance criteria, at the template:

* **Disabled by default and documented** — no beacon exists until ``WithTelemetry``; the README has a
  **Telemetry (opt-in)** section that says so.
* **The payload excludes secrets, bodies and identifiers** — the marshalled Go type has exactly the
  seven allowed JSON fields, and ``telemetry.go`` never touches the API request, its headers, URL or
  body, nor the client's own headers (so a credential set with ``WithHeader`` cannot leak).
* **Correlation with the manifest** — the published revision and API version are baked in, and
  each count is keyed by the manifest's operation id.

The first group runs everywhere (text assertions). The last test compiles the module and drives the
beacon over real HTTP with ``go test``; it needs a Go toolchain on ``PATH`` and is skipped without one.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

import pytest

from app.go_client_generator import generate_go_client
from app.go_client_telemetry import (
    beacon_operation_id,
    BEACON_JSON_FIELDS,
    BEACON_OUTCOMES,
    beacon_token,
    normalise_revision,
)
from app.sdk_beacon import OUTCOMES, SdkBeaconEvent
from test_go_client_generator import _compile_gate_api

REVISION = "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0010"


def _package(revision_id=REVISION, api_version="1.2.0"):
    return generate_go_client(
        _compile_gate_api(),
        module_path="example.com/apiome/comments-go",
        package_name="comments",
        user_agent="acme-sdk/1.0.0",
        revision_id=revision_id,
        api_version=api_version,
    )


def _file(package, path: str) -> str:
    return next(item.text for item in package.files if item.path == path)


def _struct(text: str, name: str) -> str:
    start = text.index(f"type {name} struct {{")
    return text[start : text.index("\n}", start)]


# ---------------------------------------------------------------------------------------------
# The payload: exactly the allowed fields
# ---------------------------------------------------------------------------------------------


def test_the_reported_event_has_exactly_the_allowed_json_fields() -> None:
    event = _struct(_file(_package(), "telemetry.go"), "beaconEvent")
    assert tuple(re.findall(r'json:"([a-z_]+)"', event)) == BEACON_JSON_FIELDS


def test_the_go_payload_matches_the_server_contract() -> None:
    """What the client marshals is exactly what the endpoint accepts — no more, no less."""
    assert set(BEACON_JSON_FIELDS) == set(SdkBeaconEvent.model_fields)
    assert BEACON_OUTCOMES == OUTCOMES


def test_the_report_wraps_events_with_only_schema_and_source() -> None:
    report = _struct(_file(_package(), "telemetry.go"), "beaconReport")
    assert re.findall(r'json:"([a-z_]+)"', report) == ["schema", "source_id", "events"]


def _code(text: str) -> str:
    """The Go source with its ``//`` comments removed, so prose cannot trip an assertion."""
    return "\n".join(line.split("//", 1)[0] for line in text.splitlines())


def test_telemetry_never_touches_the_api_request_or_its_credentials() -> None:
    text = _code(_file(_package(), "telemetry.go"))
    # Only its own two headers; never the client's WithHeader values or user agent.
    assert re.findall(r'req\.Header\.Set\("([^"]+)"', text) == ["Content-Type", "X-API-Key"]
    for forbidden in ("c.header", "c.userAgent", "c.httpClient", "req.URL", "resp.Body)", ".Host", "StatusCode,", "latency"):
        assert forbidden not in text, forbidden
    # The beacon's events are built from constants and counter keys alone.
    take = text[text.index("func (t *telemetry) take()") :]
    take = take[: take.index("\n}\n")]
    assert "req" not in take and "resp" not in take


def test_an_outcome_is_counted_only_after_the_call_finished() -> None:
    client = _file(_package(), "client.go")
    do = client[client.index("func (c *Client) do(") :]
    do = do[: do.index("\n}\n")]
    for outcome in ('"network"', "classifyStatus(resp.StatusCode)", '"incompatible"', '"ok"'):
        assert f"c.observe(operationID, {outcome})" in do


def test_every_method_names_its_manifest_operation() -> None:
    package = _package()
    methods = "\n".join(item.text for item in package.files if item.path.endswith(".go"))
    for method in package.methods:
        assert f'c.do(req, ' in methods
        assert f', "{method.operation_id}")' in methods


# ---------------------------------------------------------------------------------------------
# Off by default, documented
# ---------------------------------------------------------------------------------------------


def test_no_option_turns_telemetry_on_except_with_telemetry() -> None:
    package = _package()
    client = _file(package, "client.go")
    assert "telemetry:" not in client[client.index("func NewClient(") :].split("\n}\n")[0]
    text = _file(package, "telemetry.go")
    assert text.count("c.telemetry = &telemetry{") == 1
    assert "func WithTelemetry(cfg TelemetryConfig) Option" in text


def test_an_incomplete_config_or_a_client_without_a_revision_stays_off() -> None:
    text = _file(_package(), "telemetry.go")
    assert 'cfg.Endpoint == "" || cfg.APIKey == "" || cfg.SourceID == "" || ManifestRevisionID == ""' in text
    standalone = _file(_package(revision_id=None), "telemetry.go")
    assert 'ManifestRevisionID = ""' in standalone


def test_the_readme_documents_telemetry_as_opt_in() -> None:
    readme = _file(_package(), "README.md")
    assert "## Telemetry (opt-in)" in readme
    assert "**Off by default.**" in readme
    assert "never" in readme and "credentials" in readme
    assert "generated outside an Apiome SDK kit" not in readme
    assert "generated outside an Apiome SDK kit" in _file(_package(revision_id=None), "README.md")


# ---------------------------------------------------------------------------------------------
# Correlation: revision and API version baked in, as the endpoint accepts them
# ---------------------------------------------------------------------------------------------


def test_the_revision_api_version_and_sdk_name_are_baked_in() -> None:
    text = _file(_package(api_version="2.0.0-beta.1"), "telemetry.go")
    assert f'ManifestRevisionID = "{REVISION}"' in text
    assert 'ManifestAPIVersion = "2.0.0-beta.1"' in text
    assert 'SDKName = "comments-go"' in text


@pytest.mark.parametrize(
    ("raw", "kind", "expected"),
    [
        ("1.0.0", "version", "1.0.0"),
        ("v1 beta (preview)", "version", "v1-beta-preview"),
        ("", "version", "0"),
        ("Acme Pets-Go", "name", "acme-pets-go"),
        ("...", "name", "apiome-go"),
        ("x" * 100, "version", "x" * 64),
    ],
)
def test_beacon_tokens_fit_the_endpoint_patterns(raw, kind, expected) -> None:
    fallback = "apiome-go" if kind == "name" else "0"
    token = beacon_token(raw, kind=kind, fallback=fallback)
    assert token == expected
    pattern = r"^[a-z0-9][a-z0-9._/-]{0,63}$" if kind == "name" else r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$"
    assert re.match(pattern, token)


@pytest.mark.parametrize(
    ("identifier", "key", "expected"),
    [
        ("getPet", "GET /pets/{petId}", "getPet"),
        ("acme.PetService.GetPet", "acme.PetService.GetPet", "acme.PetService.GetPet"),
        ("get@pet", "GET /pets/{petId}", "GET /pets/{petId}"),
        ("ペット取得", "GET /ペット", "_"),
        ("get@pet", "GET /pets?x=1", "get_pet"),
    ],
)
def test_the_reported_operation_id_is_always_one_the_endpoint_accepts(identifier, key, expected) -> None:
    """The manifest's id when it fits; else its key; else a sanitised id — never one that 422s the report."""
    result = beacon_operation_id(identifier, key)
    assert result == expected
    SdkBeaconEvent(
        sdk_name="x", sdk_version="1", api_version="1", spec_revision_id=REVISION, operation_id=result, outcome="ok"
    )


def test_every_baked_in_operation_id_passes_the_server_contract() -> None:
    package = _package()
    methods = "\n".join(item.text for item in package.files if item.path.endswith(".go"))
    ids = re.findall(r'c\.do\(req, (?:nil|&out), "([^"]*)"\)', methods)
    assert ids
    for operation_id in ids:
        SdkBeaconEvent(
            sdk_name="x", sdk_version="1", api_version="1", spec_revision_id=REVISION,
            operation_id=operation_id, outcome="ok",
        )


def test_only_a_uuid_revision_is_baked_in() -> None:
    assert normalise_revision(REVISION.upper()) == REVISION
    assert normalise_revision("not-a-uuid") == ""
    assert normalise_revision(None) == ""


def test_telemetry_names_are_reserved_against_the_contract() -> None:
    from app.go_client_generator import _RESERVED_FILE_STEMS, _RESERVED_IDENTIFIERS

    assert "telemetry" in _RESERVED_FILE_STEMS
    assert {"WithTelemetry", "TelemetryConfig", "ManifestRevisionID", "SDKName"} <= _RESERVED_IDENTIFIERS


# ---------------------------------------------------------------------------------------------
# Over real HTTP (needs a Go toolchain)
# ---------------------------------------------------------------------------------------------

_BEACON_TEST = r'''package comments

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"sort"
	"testing"
)

func TestTelemetryIsOffByDefault(t *testing.T) {
	c := NewClient()
	if c.telemetry != nil {
		t.Fatal("telemetry is on without WithTelemetry")
	}
	c.observe("getThread", "ok")
	if err := c.FlushTelemetry(context.Background()); err != nil {
		t.Fatal(err)
	}
}

func TestAnIncompleteConfigLeavesTelemetryOff(t *testing.T) {
	for _, cfg := range []TelemetryConfig{
		{Endpoint: "http://x", APIKey: "k"},
		{Endpoint: "http://x", SourceID: "s"},
		{APIKey: "k", SourceID: "s"},
	} {
		if NewClient(WithTelemetry(cfg)).telemetry != nil {
			t.Fatalf("telemetry on with %+v", cfg)
		}
	}
}

func TestOutcomesAreClassified(t *testing.T) {
	status := http.StatusOK
	body := `{}`
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(status)
		_, _ = io.WriteString(w, body)
	}))
	defer api.Close()
	c := NewClient(WithBaseURL(api.URL), WithTelemetry(TelemetryConfig{Endpoint: "http://127.0.0.1:1", APIKey: "k", SourceID: "s", FlushEvery: 1000}))
	call := func() {
		req, err := c.newRequest(context.Background(), "GET", "/x", nil, nil, "")
		if err != nil {
			t.Fatal(err)
		}
		var out map[string]any
		_, _ = c.do(req, &out, "op")
	}
	call()
	status, body = http.StatusNotFound, `{}`
	call()
	status, body = http.StatusBadGateway, `{}`
	call()
	status, body = http.StatusOK, `not json`
	call()
	got := map[string]int{}
	for key, count := range c.telemetry.counts {
		got[key.outcome] += count
	}
	want := map[string]int{"ok": 1, "client_error": 1, "server_error": 1, "incompatible": 1}
	for outcome, n := range want {
		if got[outcome] != n {
			t.Fatalf("outcome %s: got %d, want %d (all: %v)", outcome, got[outcome], n, got)
		}
	}
	api.Close()
	call()
	if c.telemetry.counts[beaconKey{operation: "op", outcome: "network"}] != 1 {
		t.Fatalf("network outcome not counted: %v", c.telemetry.counts)
	}
}

func TestTheReportCarriesOnlyTheAllowedFields(t *testing.T) {
	var raw []byte
	var header http.Header
	beacon := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ = io.ReadAll(r.Body)
		header = r.Header.Clone()
		w.WriteHeader(http.StatusAccepted)
	}))
	defer beacon.Close()
	c := NewClient(
		WithHeader("Authorization", "Bearer api-secret"),
		WithUserAgent("my-app/9"),
		WithTelemetry(TelemetryConfig{Endpoint: beacon.URL, APIKey: "beacon-key", SourceID: "src-1", SDKVersion: "3.1.0", FlushEvery: 1000}),
	)
	c.observe("getThread", "ok")
	c.observe("getThread", "ok")
	c.observe("getThread", "incompatible")
	if err := c.FlushTelemetry(context.Background()); err != nil {
		t.Fatal(err)
	}
	if header.Get("Authorization") != "" || header.Get("User-Agent") == "my-app/9" {
		t.Fatal("the API's headers reached the beacon")
	}
	if header.Get("X-API-Key") != "beacon-key" {
		t.Fatal("missing beacon key")
	}
	var report map[string]json.RawMessage
	if err := json.Unmarshal(raw, &report); err != nil {
		t.Fatal(err)
	}
	keys := []string{}
	for key := range report {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	if len(keys) != 3 || keys[0] != "events" || keys[1] != "schema" || keys[2] != "source_id" {
		t.Fatalf("report keys %v", keys)
	}
	var events []map[string]any
	if err := json.Unmarshal(report["events"], &events); err != nil {
		t.Fatal(err)
	}
	if len(events) != 2 {
		t.Fatalf("events %v", events)
	}
	allowed := map[string]bool{"sdk_name": true, "sdk_version": true, "api_version": true, "spec_revision_id": true, "operation_id": true, "outcome": true, "count": true}
	for _, event := range events {
		if len(event) != len(allowed) {
			t.Fatalf("event fields %v", event)
		}
		for key := range event {
			if !allowed[key] {
				t.Fatalf("unexpected field %q", key)
			}
		}
		if event["spec_revision_id"] != ManifestRevisionID || event["sdk_version"] != "3.1.0" {
			t.Fatalf("event %v", event)
		}
	}
	if err := c.FlushTelemetry(context.Background()); err != nil || len(c.telemetry.counts) != 0 {
		t.Fatal("counts were not reset after a report")
	}
}
'''


def _go() -> str | None:
    return shutil.which("go")


@pytest.mark.skipif(_go() is None, reason="no Go toolchain on PATH")
def test_the_beacon_behaves_over_real_http(tmp_path) -> None:
    module = tmp_path / "module"
    for item in _package().files:
        target = module / item.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item.text)
    (module / "beacon_test.go").write_text(_BEACON_TEST)
    environment = {
        **os.environ,
        "GOPATH": str(tmp_path / "gopath"),
        "GOCACHE": str(tmp_path / "gocache"),
        "GOFLAGS": "-mod=mod -p=2",
        "GOTOOLCHAIN": "local",
    }
    result = subprocess.run(
        [_go(), "test", "-run", "Telemetry|Outcomes|Report", "./..."],
        cwd=module,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, result.stdout + result.stderr
