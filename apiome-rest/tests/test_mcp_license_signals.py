"""Tests for license & terms signal detection (V2-MCP-34.3 / MCAT-20.3, #4657).

The acceptance criteria drive the layout:

* **Seeded hints are flagged** — SPDX ids, license/terms/restriction phrases, and
  license/terms-pointing URLs planted in ``instructions``/metadata each produce a signal.
* **No false "no license" claim** — an empty result reports status ``not_stated`` and its
  wording never asserts the absence of a license; the statement also distinguishes
  "nothing found in the scanned sources" from "nothing to scan".
* **Pure / unit-tested** — determinism (same input → same signals, order, and ids),
  boundary behaviour (no partial-word matches), and the signal/scan bounds.
"""

import pytest

from app.mcp_license_signals import (
    KIND_LICENSE_MENTION,
    KIND_LICENSE_URL,
    KIND_SPDX_ID,
    KIND_TERMS_MENTION,
    KIND_TERMS_URL,
    KIND_USAGE_RESTRICTION,
    MAX_SCANNED_CHARS,
    MAX_SIGNALS,
    SOURCE_INSTRUCTIONS,
    SOURCE_SERVER_TITLE,
    SOURCE_WEBSITE_URL,
    STATUS_DETECTED,
    STATUS_NOT_STATED,
    detect_license_signals,
)


def _kinds(report):
    return [s.kind for s in report.signals]


def _matches(report):
    return [s.matched for s in report.signals]


# --- Seeded hints are flagged (AC 1) ---------------------------------------------------------


def test_spdx_id_in_instructions_is_flagged():
    report = detect_license_signals(instructions="Licensed under the Apache-2.0 license.")
    assert report.status == STATUS_DETECTED
    spdx = [s for s in report.signals if s.kind == KIND_SPDX_ID]
    assert [s.matched for s in spdx] == ["Apache-2.0"]
    assert spdx[0].source == SOURCE_INSTRUCTIONS


@pytest.mark.parametrize(
    "spdx",
    ["MIT", "Apache-2.0", "GPL-3.0-only", "BSD-3-Clause", "MPL-2.0", "CC-BY-4.0", "0BSD"],
)
def test_common_spdx_ids_are_recognized(spdx):
    report = detect_license_signals(instructions=f"Distributed under {spdx} terms.")
    assert spdx in _matches(report)
    assert KIND_SPDX_ID in _kinds(report)


def test_hyphenated_spdx_ids_match_case_insensitively():
    report = detect_license_signals(instructions="license: apache-2.0")
    assert "Apache-2.0" in _matches(report)


def test_license_and_terms_phrases_are_flagged():
    report = detect_license_signals(
        instructions="By using this server you accept our terms of service."
    )
    terms = [s for s in report.signals if s.kind == KIND_TERMS_MENTION]
    assert [s.matched for s in terms] == ["terms of service"]


def test_usage_restrictions_are_flagged():
    report = detect_license_signals(
        instructions="For internal use only. All rights reserved."
    )
    kinds = _kinds(report)
    assert kinds.count(KIND_USAGE_RESTRICTION) == 2
    assert set(_matches(report)) == {"for internal use only", "all rights reserved"}


def test_license_and_terms_urls_are_classified():
    report = detect_license_signals(
        instructions=(
            "See https://acme.example/LICENSE and https://acme.example/legal/tos "
            "and https://acme.example/docs for details."
        )
    )
    by_kind = {s.kind: s.matched for s in report.signals}
    assert by_kind[KIND_LICENSE_URL] == "https://acme.example/LICENSE"
    assert by_kind[KIND_TERMS_URL] == "https://acme.example/legal/tos"
    # The ordinary docs link is not a signal.
    assert all("docs" not in s.matched for s in report.signals)


def test_branding_website_url_is_classified_not_scanned_as_text():
    report = detect_license_signals(website_url="https://acme.example/terms-of-use")
    assert report.status == STATUS_DETECTED
    assert _kinds(report) == [KIND_TERMS_URL]
    assert report.signals[0].source == SOURCE_WEBSITE_URL
    # An ordinary homepage contributes nothing.
    plain = detect_license_signals(website_url="https://acme.example")
    assert plain.status == STATUS_NOT_STATED
    assert plain.sources_scanned == (SOURCE_WEBSITE_URL,)


def test_server_title_is_scanned():
    report = detect_license_signals(server_title="Acme Search (MIT)")
    assert report.status == STATUS_DETECTED
    assert report.signals[0].source == SOURCE_SERVER_TITLE
    assert report.signals[0].matched == "MIT"


def test_signals_carry_context_excerpts():
    text = "x" * 200 + " licensed under MIT " + "y" * 200
    report = detect_license_signals(instructions=text)
    mention = next(s for s in report.signals if s.kind == KIND_LICENSE_MENTION)
    assert "licensed under" in mention.excerpt
    assert mention.excerpt.startswith("…") and mention.excerpt.endswith("…")
    assert len(mention.excerpt) < 200


# --- No false "no license" claim (AC 2) -------------------------------------------------------


def test_absence_is_reported_as_not_stated():
    report = detect_license_signals(instructions="Use the search tool to find weather data.")
    assert report.status == STATUS_NOT_STATED
    assert report.signals == ()
    assert "not stated" in report.statement.lower()
    assert "not a claim" in report.statement.lower()
    assert SOURCE_INSTRUCTIONS in report.statement  # names what was scanned


def test_statement_never_claims_no_license():
    for report in (
        detect_license_signals(instructions="Just a plain server."),
        detect_license_signals(),
    ):
        lowered = report.statement.lower()
        assert report.status == STATUS_NOT_STATED
        assert lowered.startswith("not stated")
        # Absence talks about missing *signals* and carries an explicit disclaimer — the
        # statement never reads as a verdict that the server is unlicensed.
        assert "this is not a claim" in lowered
        assert "unlicensed" not in lowered


def test_nothing_to_scan_is_distinguished_from_nothing_found():
    empty = detect_license_signals()
    assert empty.status == STATUS_NOT_STATED
    assert empty.sources_scanned == ()
    assert "no instructions or metadata to scan" in empty.statement

    blank = detect_license_signals(instructions="   ", server_title="", website_url=None)
    assert blank.sources_scanned == ()

    scanned = detect_license_signals(instructions="Plain text.")
    assert scanned.sources_scanned == (SOURCE_INSTRUCTIONS,)
    assert "no instructions or metadata" not in scanned.statement


# --- Purity & determinism (AC 3) ---------------------------------------------------------------


def test_detection_is_deterministic_with_stable_ids():
    kwargs = dict(
        instructions="Licensed under MIT. See https://acme.example/terms.",
        server_title="Acme",
        website_url="https://acme.example/license",
    )
    first = detect_license_signals(**kwargs)
    second = detect_license_signals(**kwargs)
    assert first == second
    assert [s.id for s in first.signals] == [s.id for s in second.signals]
    assert all(s.id.startswith("mcp-license-") for s in first.signals)


def test_signals_are_ordered_by_source_then_position():
    report = detect_license_signals(
        instructions="See terms of service. Licensed under Apache-2.0.",
        server_title="MIT tools",
    )
    sources = [s.source for s in report.signals]
    assert sources == sorted(sources, key=(SOURCE_INSTRUCTIONS, SOURCE_SERVER_TITLE).index)
    instruction_signals = [s for s in report.signals if s.source == SOURCE_INSTRUCTIONS]
    assert [s.matched for s in instruction_signals] == [
        "terms of service",
        "licensed under",
        "Apache-2.0",
    ]


# --- Boundary behaviour (no partial-word / collision matches) ----------------------------------


def test_no_partial_word_matches():
    report = detect_license_signals(
        instructions="This permits unlicensed-adjacent words like transmit and admit."
    )
    assert report.status == STATUS_NOT_STATED


def test_short_spdx_ids_are_case_sensitive():
    # Lower-case "mit" (e.g. German for "with") must not read as the MIT license.
    report = detect_license_signals(instructions="Arbeitet mit dem Server zusammen.")
    assert KIND_SPDX_ID not in _kinds(report)
    flagged = detect_license_signals(instructions="Released as MIT.")
    assert "MIT" in _matches(flagged)


def test_spdx_version_continuations_do_not_match():
    report = detect_license_signals(instructions="Requires plugin Apache-2.0.1 to run.")
    assert KIND_SPDX_ID not in _kinds(report)


def test_sentence_ending_matches_are_not_lost():
    report = detect_license_signals(instructions="All rights reserved.")
    assert "all rights reserved" in _matches(report)


def test_longer_phrase_claims_span_over_bare_license():
    report = detect_license_signals(instructions="licensed under something")
    mentions = [s for s in report.signals if s.kind == KIND_LICENSE_MENTION]
    assert [s.matched for s in mentions] == ["licensed under"]


def test_text_inside_urls_is_not_double_reported():
    report = detect_license_signals(instructions="Read https://acme.example/terms first.")
    assert _kinds(report) == [KIND_TERMS_URL]


# --- Bounds -------------------------------------------------------------------------------------


def test_signal_cap_reports_truncation_explicitly():
    # Many distinct license/terms URLs — more than the cap can itemize.
    urls = " ".join(f"https://acme.example/license/{i}" for i in range(MAX_SIGNALS + 10))
    report = detect_license_signals(instructions=urls)
    assert len(report.signals) == MAX_SIGNALS
    assert report.signals_truncated == 10
    assert report.status == STATUS_DETECTED


def test_oversized_instructions_are_bounded_not_rejected():
    text = ("z" * MAX_SCANNED_CHARS) + " licensed under MIT"
    report = detect_license_signals(instructions=text)
    # The hint sits beyond the scan bound: not found, but still a clean "not stated".
    assert report.status == STATUS_NOT_STATED
    in_bounds = detect_license_signals(instructions="licensed under MIT " + "z" * MAX_SCANNED_CHARS)
    assert in_bounds.status == STATUS_DETECTED


# --- Serialization ------------------------------------------------------------------------------


def test_as_dict_is_json_ready_and_stable():
    report = detect_license_signals(instructions="Licensed under MIT.")
    payload = report.as_dict()
    assert payload["status"] == STATUS_DETECTED
    assert payload["sources_scanned"] == [SOURCE_INSTRUCTIONS]
    assert payload["signals_truncated"] == 0
    assert all(
        set(signal) == {"id", "kind", "source", "matched", "excerpt"}
        for signal in payload["signals"]
    )
    assert payload == detect_license_signals(instructions="Licensed under MIT.").as_dict()
