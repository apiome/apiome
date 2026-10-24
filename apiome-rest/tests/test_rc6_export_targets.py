"""The RC6 export target list, verified end to end through the dialog's own routes — RC6-H4 (#6211).

Export studio is held back for RC6, so the in-place **Export** dialog is the only export path for a
catalog item and a version, and its fidelity report the only fidelity surface. This suite pins what
that dialog may promise:

* :data:`RC6_EXPORT_TARGETS` is the release's target list — every registered emitter a reader can use
  (the no-op ``sample`` SPI example is internal and never listed). ``GET …/export/targets`` — what
  the dialog and ``apiome export targets`` draw — must list exactly these, and the *Export a spec*
  guide page must name every one.
* Each target is exercised through the same functions the dialog's three calls run, from two
  sources that reach the dialog by the two RC6 paths:

  - a **catalog item** — a RAML document stored raw (Catalog → item → **Export**);
  - a **version** — an OpenAPI document, as a converted project's published revision carries
    (Versions → row menu → **Export**).

  Both resolve through :func:`app.catalog_conversion.build_conversion_source`, exactly as
  :func:`app.export_source.load_export_source` does for a stored revision. For each pair the target
  must appear in the targets list with a fidelity badge, produce a fidelity report
  (``POST …/export/preview``), and emit a non-empty document (``POST …/export/document``).

No database is touched: the routes' shared bodies are called directly with the reconstructed model.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict

import pytest
from fastapi import HTTPException

from app.canonical_model import CanonicalApi
from app.catalog_conversion import build_conversion_source
from app.emitter import get_emitter, load_builtin_emitters
from app.export_fidelity import build_export_fidelity
from app.export_routes import build_target_fidelity_entries, render_emitted_document
from app.export_service import resolve_emitter
from tests.corpus_loader import EXAMPLES_DIR

load_builtin_emitters()

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXPORT_GUIDE = _REPO_ROOT / "apiome-docs" / "docs" / "ship" / "export-a-spec.md"

#: The RC6 export target list (registry keys). Decided in RC6-H4: every working target ships;
#: only the internal no-op ``sample`` is held out. Adding or removing a target changes the release
#: promise — update this list, the guide page's table and the dialog together.
RC6_EXPORT_TARGETS: tuple[str, ...] = (
    "apiblueprint",
    "apigee",
    "arazzo",
    "asn1",
    "asyncapi",
    "avro",
    "aws-apigateway",
    "azure-apim",
    "capnproto",
    "cddl",
    "cloudevents",
    "cobolcopybook",
    "connectrpc",
    "corbaidl",
    "edix12",
    "envoy-xds",
    "fhir",
    "fix",
    "flatbuffers",
    "gateway-api",
    "graphql",
    "hl7v2",
    "hoppscotch",
    "http-file",
    "idoc",
    "iso20022",
    "iso8583",
    "istio",
    "json-schema",
    "jtd",
    "k8s-crd",
    "kafka-connect",
    "kong",
    "llm-tools",
    "odata",
    "odcs",
    "oncrpc",
    "openapi",
    "openrpc",
    "postman",
    "protobuf",
    "raml",
    "smithy",
    "thrift",
    "thunder-client",
    "traefik",
    "typespec",
    "wadl",
    "wit",
    "wsdl",
    "xmlrpc",
    "xsd",
    "zosconnect",
)


#: Source-bound targets: they write one format's native structure back out, so only a source
#: imported in that format can be exported to them (``Emitter.source_unsupported_reason``). Each
#: maps to the format it is imported from and a corpus fixture of it.
SOURCE_BOUND: Dict[str, tuple[str, str]] = {
    "cobolcopybook": ("cobolcopybook", "cobol-copybook/01-customer-record.cpy"),
    "edix12": ("edix12", "edi-x12/01-850-purchase-order.edi"),
    "fix": ("fix", "fix/01-newordersingle.fix"),
    "hl7v2": ("hl7v2", "hl7v2/01-adt-a01.hl7"),
    "idoc": ("idoc", "idoc/01-minimal-xml-orders05.xml"),
    "iso20022": ("iso20022", "iso20022/01-pain.001-credit-transfer.xml"),
    "iso8583": ("iso8583", "iso8583/01-authorization-0100.json"),
    "xmlrpc": ("xmlrpc", "xml-rpc/01-method-call.xml"),
    "zosconnect": ("zosconnect", "zos-connect/01-api-requester.json"),
}

#: Targets that export from any source.
GENERAL_TARGETS: tuple[str, ...] = tuple(key for key in RC6_EXPORT_TARGETS if key not in SOURCE_BOUND)


def _stored_item(source_format: str, relative_path: str, label: str) -> Dict[str, object]:
    """A stored artifact row as ``load_export_source`` projects it, with its captured source."""
    content = (EXAMPLES_DIR / relative_path).read_text(encoding="utf-8")
    return {
        "id": f"rc6-{source_format}",
        "slug": f"rc6-{source_format}",
        "source_format": source_format,
        "protocol": None,
        "format_metadata": {"sourceContent": content, "sourceLabel": label},
        "tool_versions": {},
        "metadata": {},
    }


@pytest.fixture(scope="module")
def sources() -> Dict[str, CanonicalApi]:
    """The two RC6 export sources: a RAML catalog item and an OpenAPI version."""
    return {
        "catalog-item": build_conversion_source(
            _stored_item("raml", "raml/01-simple-api.raml", "bookstore.raml")
        ).api,
        "version": build_conversion_source(
            _stored_item("openapi", "openapi/31-paths-comprehensive.yaml", "openapi.yaml")
        ).api,
    }


def test_the_targets_list_is_exactly_the_rc6_list(sources: Dict[str, CanonicalApi]) -> None:
    """``GET …/export/targets`` lists the RC6 targets and nothing else — no internal ``sample``."""
    listed = sorted(entry.descriptor.key for entry in build_target_fidelity_entries(sources["version"]))
    assert listed == sorted(RC6_EXPORT_TARGETS)
    assert "sample" not in listed


def test_no_listed_target_needs_a_toolchain(sources: Dict[str, CanonicalApi]) -> None:
    """Nothing the dialog offers is greyed out for a missing toolchain in the RC6 runtime."""
    for entry in build_target_fidelity_entries(sources["version"]):
        assert not entry.descriptor.needs_toolchain, entry.descriptor.key


def _assert_exports(api: CanonicalApi, target: str, source_name: str) -> None:
    """The dialog's three calls succeed for this (source, target): badge, report, document."""
    badge = next(e for e in build_target_fidelity_entries(api) if e.descriptor.key == target)
    assert badge.descriptor.available, f"{target}: offered as unavailable — {badge.descriptor.unavailable_reason}"
    assert badge.fidelity.tier, f"{target}: no fidelity tier on the target card"

    emitter_cls = type(resolve_emitter(target))
    assert get_emitter(badge.descriptor.format) is emitter_cls
    fidelity = build_export_fidelity(api, emitter_cls)
    assert fidelity.report is not None, f"{target}: no fidelity report"
    assert fidelity.summary.total >= 0

    response = render_emitted_document(api, target, None, None)
    assert response.status_code == 200, f"{target} from the {source_name}: {response.status_code}"
    assert response.body, f"{target} from the {source_name}: empty document"


@pytest.mark.parametrize("source_name", ["catalog-item", "version"])
@pytest.mark.parametrize("target", GENERAL_TARGETS)
def test_target_exports_with_a_fidelity_report(
    sources: Dict[str, CanonicalApi], source_name: str, target: str
) -> None:
    """A general target exports from a catalog item and from a version, with a fidelity report."""
    _assert_exports(sources[source_name], target, source_name)


@pytest.mark.parametrize("target", sorted(SOURCE_BOUND))
def test_source_bound_target_exports_from_its_own_format(target: str) -> None:
    """A source-bound target exports a catalog item imported in its own format."""
    source_format, path = SOURCE_BOUND[target]
    api = build_conversion_source(_stored_item(source_format, path, Path(path).name)).api
    _assert_exports(api, target, f"{source_format} catalog item")


@pytest.mark.parametrize("source_name", ["catalog-item", "version"])
@pytest.mark.parametrize("target", sorted(SOURCE_BOUND))
def test_source_bound_target_is_unavailable_with_a_reason_elsewhere(
    sources: Dict[str, CanonicalApi], source_name: str, target: str
) -> None:
    """From any other source the card is drawn disabled with the reason, and an export is a 422."""
    api = sources[source_name]
    badge = next(e for e in build_target_fidelity_entries(api) if e.descriptor.key == target)
    assert not badge.descriptor.available
    reason = badge.descriptor.unavailable_reason or ""
    assert reason.strip(), target
    with pytest.raises(HTTPException) as refused:
        render_emitted_document(api, target, None, None)
    assert refused.value.status_code == 422
    assert refused.value.detail == reason


def test_the_export_guide_names_every_rc6_target(sources: Dict[str, CanonicalApi]) -> None:
    """The *Export a spec* page documents the same list the dialog draws (by label)."""
    page = _EXPORT_GUIDE.read_text(encoding="utf-8")
    section = page.split("## Formats the Export dialog offers", 1)
    assert len(section) == 2, "the guide page has no 'Formats the Export dialog offers' section"
    table = section[1].split("\n## ", 1)[0]
    entries = build_target_fidelity_entries(sources["version"])
    labels = {entry.descriptor.key: entry.descriptor.label for entry in entries}
    missing = [label for label in labels.values() if f"| {label} |" not in table]
    assert missing == []
    rows = re.findall(r"^\| (?!Format\b|---)([^|]+?) \|", table, flags=re.MULTILINE)
    assert len(rows) == len(RC6_EXPORT_TARGETS), rows
