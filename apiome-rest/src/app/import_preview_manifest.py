"""Import preview manifest — IXH-3.1 (#5103).

The IXH-2.1 pre-flight answers "is this worth importing?" — grade, findings, policy
verdict. What it does **not** answer is *what the import would create*: which services,
operations, types, and channels will exist, under what stable canonical keys, and what
the source carried that the canonical model could not hold. Before this module the only
pre-commit structure the UI had was ``extractFileMetadata`` — a client-side title/version
sniff.

This module extends the pre-flight into a full **import preview manifest**:

* the canonical **entity tree** (services → operations, plus types and channels), every
  entity carrying its stable canonical key and — where the parser captured one — a
  source location;
* per-entity **provenance** back to the source construct (native name / native id /
  source location, read from the same extras keys the export manifest reads);
* a **coverage ledger** classifying source constructs as ``mapped``,
  ``partially-mapped``, ``inferred``, ``unsupported-by-canonical-model``, or
  ``not-parsed-by-adapter`` — unsupported vs not-parsed are *never* conflated: "the
  canonical model cannot hold this" and "our parser does not yet read this" are
  different facts with different owners, and each ``not-parsed-by-adapter`` entry
  names its CLX-2.4 capability-registry reference; ``inferred`` marks constructs
  synthesized from observations (request files / traffic), never presented as declared;
* the **adapter capability reference** (descriptor + the CLX-2.4 per-format capability
  entry + the adapter's declared parser limits); and
* the **routing decision**, carried on the embedded pre-flight report.

**One vocabulary, two directions (CPDO-1.3 / #4800).** The graph reuses the export
projection manifest's node/edge contract verbatim — the same
:class:`~app.export_projection.ProjectionNode` / :class:`~app.export_projection.ProjectionEdge`
models, the same :class:`~app.export_projection.ProjectionNodeKind` /
:class:`~app.export_projection.ProjectionEdgeRelation` enums, and the same
:class:`~app.projection_taxonomy.ProjectionStatus` /
:class:`~app.projection_taxonomy.ProjectionReason` taxonomy — rather than a second
lookalike shape. The lanes read in the import direction: the *source document* is the
origin and the *canonical model* is the destination, so an outcome (``projects``) edge
runs **native → canonical** (where the export manifest's runs canonical → target), and a
dropped source construct has ``target = None`` exactly as a dropped export construct
does. ``derives`` edges carry provenance for mapped entities, mirroring the export
build. A shared contract test asserts the two surfaces agree on every enum, model, id
scheme, and cursor format.

**Coverage classes ↔ shared statuses.** The ledger classes are a documented, bijective
view over the shared taxonomy — they add no second status vocabulary:

========================================  =============  ==========================
Coverage class                            Status         Reason
========================================  =============  ==========================
``mapped``                                ``retained``   —
``partially-mapped``                      ``approximated``  ``destination_unsupported``
``inferred``                              ``synthesized`` ``source_incomplete``
``unsupported-by-canonical-model``        ``dropped``    ``destination_unsupported``
``not-parsed-by-adapter``                 ``dropped``    ``source_parse_limit``
========================================  =============  ==========================

In the import direction the "destination" is the **canonical model**, so
``destination_unsupported`` truthfully means "the canonical fields cannot hold this"
(the attributes ride in the untyped ``extras`` escape hatch), while
``source_parse_limit`` means "apiome's parser does not read this yet" — the same
never-blame-the-wrong-party rule the export taxonomy enforces.

**What populates the ledger.** Only evidence the pipeline actually has:

* every canonical entity → ``mapped`` when its canonical fields hold everything the
  normalizer recovered, ``partially-mapped`` when source attributes ride only in its
  ``extras`` bag (named in the entry's detail);
* document-level ``extras`` on the model root → ``unsupported-by-canonical-model``
  (the source carried document-level constructs no canonical field models);
* the adapter's **declared parser limits** (:data:`KNOWN_PARSER_LIMITS`) →
  ``not-parsed-by-adapter``. These are adapter-level declarations, not per-document
  detections, so each entry is marked ``document_scoped = false`` — the ledger states
  "this adapter does not read X yet" without pretending to have checked whether *this*
  document uses X.

**Determinism.** :func:`build_import_preview_manifest` is pure — no I/O, no clock. The
entity order is the model's declaration order (itself deterministic for a fixed input),
nodes/edges sort exactly as the export manifest sorts them, and the manifest hash folds
the adapter key, adapter/apiome version provenance, and the request options into a
digest over the full graph — so a fixed (input, adapter version, options) triple is
byte-stable, and an adapter upgrade is a different snapshot.

**Bounded output.** The entity tree, graph, and ledger are cursor-paginated over the
entity list (the cursor codec is shared with the export evidence pages). Truncation is
*stated*: ``truncated`` is true whenever a page omits rows, and every ``total_*`` field
reports the full-manifest count, never the page's.

**Re-import delta (IXH-3.4, #5106).** When the wizard's commit would land in an
*existing* catalog item — the commit resolves its target by slug
(:func:`app.import_source_pipeline._resolve_import_project`), so the request carries the
same client-computed ``project_slug`` — the response also carries an
:class:`ImportReimportDelta`: :func:`app.import_source.canonical_diff` between the
current revision's canonical model (re-parsed from its stored source, exactly as the
convert flow does) and the candidate, grouped by entity family, with breaking-change
annotation joined from :func:`app.breaking_change.classify_models` where a classifier
grades the format. An identical re-import is an explicit **no-op** (matching
fingerprints, empty diff) so the client can offer to skip the commit; a first-time
import (no existing item under the slug) has ``reimport = null``. The delta is computed
**per request, never cached** — the current revision can move between requests — from
canonical models, never raw text.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .arrow_normalizer import ARROW_EXTRAS_KEY
from .breaking_change import classify_models, get_breaking_change_classifier
from .canonical_model import CanonicalApi
from .cddl_normalizer import CDDL_EXTRAS_KEY
from .cue_parser import CUE_FORMAT
from .cue_parser import PARTIAL_LIMITS as CUE_PARTIAL_LIMITS
from .dbt_normalizer import DBT_EXTRAS_KEY
from .dhall_parser import DHALL_FORMAT
from .dhall_parser import PARTIAL_LIMITS as DHALL_PARTIAL_LIMITS
from .dtd_normalizer import DTD_EXTRAS_KEY
from .export_projection import (
    NATIVE_ID_EXTRA_KEYS,
    SOURCE_LOCATION_EXTRA_KEYS,
    NativeEvidence,
    ProjectionEdge,
    ProjectionEdgeRelation,
    ProjectionNode,
    ProjectionNodeKind,
    decode_page_cursor,
    encode_page_cursor,
    first_extra,
)
from .format_lint_capabilities import FormatLintCapability, capability_for_format
from .gateway_family import flavor_for
from .hoppscotch_normalizer import HOPPSCOTCH_EXTRAS_KEY
from .hoppscotch_normalizer import PARTIAL_LIMITS as HOPPSCOTCH_PARTIAL_LIMITS
from .import_preflight import run_import_preflight
from .import_source import (
    DiffChangeKind,
    canonical_diff,
    canonical_fingerprint,
    get_import_source,
    load_builtin_import_sources,
)
from .import_source_pipeline import ImportRunArtifacts, _normalize_import_project_slug
from .inference_provenance import (
    INFERRED,
    PROVENANCE_EVIDENCE_KEY,
    PROVENANCE_STAMP_KEYS,
    provenance_of,
)
from .jsonld_normalizer import JSONLD_EXTRAS_KEY
from .jsonld_normalizer import PARTIAL_LIMITS as JSONLD_PARTIAL_LIMITS
from .kafka_connect_normalizer import KAFKA_CONNECT_EXTRAS_KEY
from .lwm2m_normalizer import LWM2M_EXTRAS_KEY
from .lwm2m_normalizer import PARTIAL_LIMITS as LWM2M_PARTIAL_LIMITS
from .mainframe_misc_normalizer import BMS_EXTRAS_KEY, BMS_PARTIAL_LIMITS, VSAM_EXTRAS_KEY, VSAM_PARTIAL_LIMITS
from .matter_normalizer import MATTER_EXTRAS_KEY
from .matter_normalizer import PARTIAL_LIMITS as MATTER_PARTIAL_LIMITS
from .models import ImportPreflightCounts, ImportPreflightReport, ImportPreflightRequest
from .odcs_normalizer import ODCS_EXTRAS_KEY
from .opcua_nodeset_normalizer import OPCUA_EXTRAS_KEY
from .opcua_nodeset_normalizer import PARTIAL_LIMITS as OPCUA_PARTIAL_LIMITS
from .owl_normalizer import OWL_EXTRAS_KEY
from .owl_normalizer import PARTIAL_LIMITS as OWL_PARTIAL_LIMITS
from .pkl_parser import PARTIAL_LIMITS as PKL_PARTIAL_LIMITS
from .pkl_parser import PKL_FORMAT
from .pli_normalizer import PLI_EXTRAS_KEY, PLI_PARTIAL_LIMITS
from .projection_taxonomy import ProjectionReason, ProjectionStatus
from .proto_editions import (
    EDITIONS_PROVENANCE_EXTRA_KEY as PROTO_EDITIONS_EXTRA_KEY,
)
from .pydantic_normalizer import PYDANTIC_EXTRAS_KEY
from .pydantic_parser import PARTIAL_LIMITS as PYDANTIC_PARTIAL_LIMITS
from .relaxng_normalizer import RELAXNG_EXTRAS_KEY
from .ros2_normalizer import PARTIAL_LIMITS as ROS2_PARTIAL_LIMITS
from .ros2_normalizer import ROS2_EXTRAS_KEY
from .shacl_normalizer import PARTIAL_LIMITS as SHACL_PARTIAL_LIMITS
from .shacl_normalizer import SHACL_EXTRAS_KEY
from .soapui_normalizer import PARTIAL_LIMITS as SOAPUI_PARTIAL_LIMITS
from .soapui_normalizer import SOAPUI_EXTRAS_KEY
from .sparkplug_normalizer import PARTIAL_LIMITS as SPARKPLUG_PARTIAL_LIMITS
from .sparkplug_normalizer import SPARKPLUG_EXTRAS_KEY
from .sql_ddl_normalizer import SQL_DDL_EXTRAS_KEY
from .thunder_client_normalizer import PARTIAL_LIMITS as THUNDER_CLIENT_PARTIAL_LIMITS
from .thunder_client_normalizer import THUNDER_CLIENT_EXTRAS_KEY
from .trpc_normalizer import TRPC_EXTRAS_KEY
from .trpc_parser import PARTIAL_LIMITS as TRPC_PARTIAL_LIMITS
from .typescript_types_normalizer import TYPESCRIPT_EXTRAS_KEY
from .zod_normalizer import ZOD_EXTRAS_KEY
from .zod_parser import PARTIAL_LIMITS as ZOD_PARTIAL_LIMITS

logger = logging.getLogger(__name__)

__all__ = [
    "CoverageClass",
    "STATUS_FOR_COVERAGE",
    "coverage_for_outcome",
    "ParserLimit",
    "KNOWN_PARSER_LIMITS",
    "CapabilityReference",
    "ImportAdapterReference",
    "CoverageEntry",
    "ImportPreviewEntity",
    "ImportPreviewManifest",
    "ImportPreviewManifestRequest",
    "ImportPreviewManifestResponse",
    "ReimportDeltaEntry",
    "ImportReimportDelta",
    "build_reimport_delta",
    "build_import_preview_manifest",
    "paginate_import_preview_manifest",
    "run_import_preview_manifest",
    "clear_preview_manifest_cache",
    "preview_manifest_cache_size",
    "DEFAULT_ENTITY_PAGE_SIZE",
    "MAX_ENTITY_PAGE_SIZE",
    "PREVIEW_MANIFEST_CACHE_MAX_ENTRIES",
    "PROVENANCE_EXTRA_KEYS",
]

#: The apiome-rest package version stamped into every manifest's provenance and hash.
APIOME_VERSION = __version__

#: Default and hard-cap entity page sizes for :func:`paginate_import_preview_manifest`.
DEFAULT_ENTITY_PAGE_SIZE = 200
MAX_ENTITY_PAGE_SIZE = 1000

#: Upper bound on cached full manifests held per process (they can be large, so the
#: bound is tighter than the pre-flight report cache's).
PREVIEW_MANIFEST_CACHE_MAX_ENTRIES = 32

#: Extras keys that carry *provenance* (source location / native id / inference
#: bookkeeping) rather than source semantics. An entity whose extras hold only these
#: keys is fully ``mapped`` (or ``inferred`` when ``provenance == "inferred"``) — the
#: bag is our own bookkeeping, not an unmodeled source attribute.
PROVENANCE_EXTRA_KEYS = frozenset(SOURCE_LOCATION_EXTRA_KEYS) | frozenset(NATIVE_ID_EXTRA_KEYS) | frozenset(
    {
        # FMT-8.6: the shared inference-provenance stamp (class + evidence sentence).
        *PROVENANCE_STAMP_KEYS,
        "sample_count",
        "sample_counts",
        "inference_evidence",
        "source_label",
        "source_file",
        "source_files",
        "path_inferences",
        "inferred_auth_schemes",
        "samples",
        "http_status",
        "body_schema",
        "http_file_variables",
        "overlay",
        "gateway",
        "wit",
        # FMT-4.1: the RELAX NG projection record (root type, declared limits, composition
        # hrefs). It is our own bookkeeping about the read, not a construct the grammar names.
        RELAXNG_EXTRAS_KEY,
        # FMT-4.2: the DTD projection record (root type, declared limits, the entity and
        # notation declarations, the modules composed in). Our own bookkeeping about the
        # read — the DTD's own constructs are the elements and attributes it declares.
        DTD_EXTRAS_KEY,
        # FMT-4.4: the CDDL projection record (root rule, declared limits, the sockets,
        # generics and group rules composition resolved). Our own bookkeeping about the
        # read — the grammar's own constructs are the rules it declares.
        CDDL_EXTRAS_KEY,
        # FMT-4.5: the Arrow projection record (root type, declared limits, the schema
        # metadata carried through, the Flight envelope). Our own bookkeeping about the
        # read — the schema's own constructs are the fields it declares.
        ARROW_EXTRAS_KEY,
        # FMT-8.1: the TypeScript projection record (root module, the module set, the export
        # list, declared limits). Our own bookkeeping about the read — the module's own
        # constructs are the declarations it exports.
        TYPESCRIPT_EXTRAS_KEY,
        # FMT-8.2: the Zod projection record (root module, the module set, the export list,
        # declared limits). Our own bookkeeping about the read.
        ZOD_EXTRAS_KEY,
        # FMT-8.3: the tRPC projection record (root module, routers, procedure count, declared
        # limits). Our own bookkeeping about the read.
        TRPC_EXTRAS_KEY,
        # FMT-8.4: the Pydantic projection record (root module, modules, exports, declared
        # limits). Our own bookkeeping about the read.
        PYDANTIC_EXTRAS_KEY,
        # FMT-9.1: the NodeSet projection record (namespaces, models, aliases, reference types,
        # node counts, declared limits). Our own bookkeeping about the read — a type's own
        # references and modelling rules ride under their `opcua_*` keys and read as partial.
        OPCUA_EXTRAS_KEY,
        # FMT-9.2: the Sparkplug projection record (input kind, payloads and their inferred
        # message types, namespace identity, declared limits). Our own bookkeeping about the read
        # — a metric's alias, datatype and properties ride under their `sparkplug_*` keys.
        SPARKPLUG_EXTRAS_KEY,
        # FMT-9.3: the ROS 2 projection record (input kind, interfaces, packages, declared limits).
        # Our own bookkeeping — a field's written type rides under `ros2_type`.
        ROS2_EXTRAS_KEY,
        # FMT-11.3: the VSAM and CICS BMS projection records (clusters, keys, maps, field positions
        # and attributes, declared limits) sit under each sub-format's own key. Our own bookkeeping.
        VSAM_EXTRAS_KEY,
        BMS_EXTRAS_KEY,
        # FMT-11.1: the PL/I projection record (structures, storage map, includes, layout
        # assumptions, declared limits). Our own bookkeeping.
        PLI_EXTRAS_KEY,
        # FMT-10.1: the Hoppscotch projection record (collection versions, environments, folders,
        # variable names, declared limits). Our own bookkeeping — never a credential.
        HOPPSCOTCH_EXTRAS_KEY,
        # FMT-10.2: the Thunder Client projection record (same shape as Hoppscotch's). Our own
        # bookkeeping — never a credential.
        THUNDER_CLIENT_EXTRAS_KEY,
        # FMT-10.3: the SoapUI projection record (interfaces and where each WSDL came from, saved
        # request names, environments, property names, mock services, declared limits). Our own
        # bookkeeping — never a credential.
        SOAPUI_EXTRAS_KEY,
        # FMT-9.5: the LwM2M and Matter projection records (input kind, objects / clusters and
        # device types, declared limits). Our own bookkeeping.
        LWM2M_EXTRAS_KEY,
        MATTER_EXTRAS_KEY,
        # FMT-9.4: the SHACL / OWL / JSON-LD projection records (files, ontologies, shapes, resolved
        # contexts, declared limits). Our own bookkeeping — a construct's IRI rides on `native_id`.
        SHACL_EXTRAS_KEY,
        OWL_EXTRAS_KEY,
        JSONLD_EXTRAS_KEY,
        # FMT-8.5: the CUE / Pkl / Dhall projection records (root file, files, exports, validated
        # instances, declared limits) sit under the format's own key. Our own bookkeeping.
        CUE_FORMAT,
        PKL_FORMAT,
        DHALL_FORMAT,
        # FMT-5.3: the Kafka Connect projection record (root schemas, whether the intake
        # was enveloped, the source files, the declared limits). Our own bookkeeping about
        # the read — the schema's own constructs are the structs and fields it declares,
        # and the ``connect_*`` keys that carry them are deliberately NOT listed here.
        KAFKA_CONNECT_EXTRAS_KEY,
        # FMT-3.6: derived version/provenance labels, not source constructs — the
        # source's own `info.schema` is still reported (as `postman_schema_url`).
        "swagger_1_2",
        "postman_collection_version",
        # FMT-7.1: the AWS API Gateway report (flavor, integration counts, authorizers,
        # validators, every extension site). Rendered by ``_aws_apigateway_capability_rows``;
        # the interpreted constructs themselves ride in ``backend``/``security``/``validation``.
        "aws_apigateway",
        # FMT-7.2: the Azure API Management report (shape, APIs, products, backends, every policy
        # document's sections, mapped counts and the verbatim unmapped policies). Rendered by
        # ``_azure_apim_capability_rows``; the interpreted constructs ride in ``security``,
        # ``rate_limits``, ``backend``, ``rewrite``, ``cors`` and ``access``.
        "azure_apim",
        # FMT-7.3: the Apigee bundle report (proxy and target endpoints, ordered route rules, the
        # declared conditions, fault rules, mapped and verbatim unmapped policies). Rendered by
        # ``_apigee_capability_rows``.
        "apigee",
        # FMT-5.1: the ODCS projection record (declared api version, contract status and
        # identity, the schema objects, declared limits, the composed file set). Our own
        # bookkeeping about the read — the contract's *own* governance blocks live under
        # their own `odcs_*` keys and are deliberately NOT listed here, because they are
        # source constructs the canonical model does not hold and must read as partial.
        ODCS_EXTRAS_KEY,
        # FMT-5.4: the dbt projection record (which of dbt's two descriptions was read, the
        # declared properties/manifest versions, the resource list, the recorded lineage and
        # the references that resolved to nothing, declared limits, the composed file set).
        # Our own bookkeeping about the read — the project's *own* blocks live under their
        # own `dbt_*` keys, and its data tests under the shared `odcs_quality` key, and
        # neither is listed here, because they are source constructs the canonical model does
        # not hold and must read as partial.
        DBT_EXTRAS_KEY,
        # FMT-5.6: the SQL DDL projection record (the resolved dialect and how it was
        # resolved, the relation list, the statement counts, the recorded foreign-key
        # relationships, declared limits, the composed migrations set). Our own reading of
        # the script, not a construct the script names — the script's own blocks live under
        # their own `sql_*` keys and are deliberately NOT listed here, because they are
        # source constructs the canonical model does not hold and must read as partial.
        SQL_DDL_EXTRAS_KEY,
        # FMT-3.7: the resolved Protobuf Editions record (per-file edition, syntax and feature
        # set). It is our own resolution of the document, not a construct the document names.
        # Spelled by its owning module rather than repeated as a literal.
        PROTO_EDITIONS_EXTRA_KEY,
    }
)


# ===========================================================================
# Coverage vocabulary (a view over the shared CPDO-1.3 taxonomy)
# ===========================================================================


class CoverageClass(str, Enum):
    """Coverage classification of one source construct in the import (IXH-3.1).

    The values are the ticket's exact vocabulary. Each class is a documented view over
    the shared :class:`~app.projection_taxonomy.ProjectionStatus` /
    :class:`~app.projection_taxonomy.ProjectionReason` pair (see
    :data:`STATUS_FOR_COVERAGE`) — never a parallel status vocabulary.
    """

    MAPPED = "mapped"
    PARTIALLY_MAPPED = "partially-mapped"
    INFERRED = "inferred"
    UNSUPPORTED_BY_CANONICAL_MODEL = "unsupported-by-canonical-model"
    NOT_PARSED_BY_ADAPTER = "not-parsed-by-adapter"


#: The bijection coverage class → (status, reason) in the shared taxonomy. In the import
#: direction the "destination" is the canonical model, so ``destination_unsupported``
#: means "canonical fields cannot hold this", while ``source_parse_limit`` means "our
#: parser does not read this yet" — the two are never conflated. ``inferred`` means the
#: construct was synthesized from observations (traffic / request files), not declared.
STATUS_FOR_COVERAGE: Dict[CoverageClass, Tuple[ProjectionStatus, Optional[ProjectionReason]]] = {
    CoverageClass.MAPPED: (ProjectionStatus.RETAINED, None),
    CoverageClass.PARTIALLY_MAPPED: (
        ProjectionStatus.APPROXIMATED,
        ProjectionReason.DESTINATION_UNSUPPORTED,
    ),
    CoverageClass.INFERRED: (
        ProjectionStatus.SYNTHESIZED,
        ProjectionReason.SOURCE_INCOMPLETE,
    ),
    CoverageClass.UNSUPPORTED_BY_CANONICAL_MODEL: (
        ProjectionStatus.DROPPED,
        ProjectionReason.DESTINATION_UNSUPPORTED,
    ),
    CoverageClass.NOT_PARSED_BY_ADAPTER: (
        ProjectionStatus.DROPPED,
        ProjectionReason.SOURCE_PARSE_LIMIT,
    ),
}


def coverage_for_outcome(
    status: ProjectionStatus, reason: Optional[ProjectionReason]
) -> Optional[CoverageClass]:
    """Invert :data:`STATUS_FOR_COVERAGE`: the coverage class for a (status, reason) pair.

    Args:
        status: The shared-taxonomy status of an outcome edge.
        reason: Its reason code, or ``None``.

    Returns:
        The coverage class the pair encodes, or ``None`` when the pair is not one the
        import manifest produces (the mapping is a bijection over exactly four pairs).
    """
    for coverage, (mapped_status, mapped_reason) in STATUS_FOR_COVERAGE.items():
        if mapped_status is status and mapped_reason is reason:
            return coverage
    return None


# ===========================================================================
# Adapter capability + parser-limit references (CLX-2.4)
# ===========================================================================


@dataclass(frozen=True)
class ParserLimit:
    """One declared "our parser does not yet read this" limit for an adapter.

    A *declaration*, not a per-document detection: it states a construct class the
    adapter's parser is known not to read today, so the coverage ledger can carry an
    honest ``not-parsed-by-adapter`` entry (``document_scoped = false``) instead of
    silently claiming full coverage.

    Attributes:
        construct: Short name of the source construct class the parser skips.
        detail: One-sentence human description of the limit.
    """

    construct: str
    detail: str


#: Declared parser limits per adapter registry key. Entries are additive and must state
#: only *documented* limits (the corpus manifest's recorded adapter bugs); remove an
#: entry in the same change that fixes its parser. An adapter with no entry simply
#: contributes no ``not-parsed-by-adapter`` rows — absence of a declaration is not a
#: claim of completeness.
KNOWN_PARSER_LIMITS: Dict[str, Tuple[ParserLimit, ...]] = {
    "thrift": (
        ParserLimit(
            construct="single-line method parameters",
            detail="Parameters of a method declared entirely on one line are silently "
            "dropped by the Thrift parser.",
        ),
    ),
    "capnproto": (
        ParserLimit(
            construct="parenthesized method result types",
            detail="Methods whose result type nests parentheses (for example "
            "List(Event)) are dropped by the Cap'n Proto parser.",
        ),
    ),
    "asn1": (
        ParserLimit(
            construct="scalar and alias type assignments",
            detail="Scalar and alias typedefs crash the ASN.1 normalizer and are not "
            "represented in the canonical model.",
        ),
    ),
    "cloudevents": (
        ParserLimit(
            construct="top-level event batch arrays",
            detail="A JSON document whose root is a CloudEvents batch array is rejected "
            "by the parser; only single-event documents are read.",
        ),
    ),
    "kong": (
        ParserLimit(
            construct="expression-based routes",
            detail="Kong 3.x `expression` router rules are preserved verbatim in extras "
            "but not evaluated; a route defined only by an expression imports without "
            "its match conditions.",
        ),
    ),
    "envoy-xds": (
        ParserLimit(
            construct="control-plane state (RDS / LDS / ADS)",
            detail="Routes, listeners and clusters a control plane serves at runtime are not "
            "fetched; only what the supplied files contain is read, and each dynamic source "
            "is declared on the ledger instead.",
        ),
    ),
    "istio": (
        ParserLimit(
            construct="security.istio.io policies and EnvoyFilter patches",
            detail="RequestAuthentication / AuthorizationPolicy resources and EnvoyFilter "
            "patches change what the mesh enforces but are not read; the import reflects the "
            "VirtualService routing alone.",
        ),
    ),
    "traefik": (
        ParserLimit(
            construct="dynamic providers other than the file provider and Kubernetes CRDs",
            detail="Routers that Docker labels, Consul Catalog, etcd or other providers create at "
            "runtime are not part of the input; a reference to one (`name@docker`) is kept as "
            "written and not resolved.",
        ),
    ),
    "nginx": (
        ParserLimit(
            construct="nginx outside the documented directive subset",
            detail="The parser reads a bounded subset of nginx (see the format's capability "
            "entry, directive by directive); `if`, `map`, `geo`, `try_files`, named locations, "
            "scripting modules and every other directive are declared, not interpreted.",
        ),
    ),
    "haproxy": (
        ParserLimit(
            construct="runtime-evaluated conditions and Lua",
            detail="Conditions on the client address, TLS properties, stick-table counters, the "
            "request body or Lua fetches are kept on the route as unmodelled conditions; the "
            "parser never evaluates them.",
        ),
    ),
    "consul": (
        ParserLimit(
            construct="live catalog and mesh state",
            detail="Only the supplied definitions, catalog export and configuration entries are "
            "read; services registered at runtime and intentions or proxy defaults are not "
            "fetched.",
        ),
    ),
    "tyk": (
        ParserLimit(
            construct="custom middleware and plugin code",
            detail="JavaScript, Go and coprocess middleware is named on the API, but what it "
            "does to a request is not knowable from the definition.",
        ),
    ),
    "gateway-api": (
        ParserLimit(
            construct="ExtensionRef filters and policy attachments",
            detail="HTTPRoute ExtensionRef filters and external policy attachments "
            "(for example auth policies) reference resources outside the manifest; "
            "they are preserved verbatim in extras, not resolved.",
        ),
    ),
    "grpc": (
        ParserLimit(
            construct="Editions `enforce_naming_style` / `default_symbol_visibility`",
            detail="These two Edition 2024 features are resolved and reported in provenance "
            "but not modelled: they govern generated-code naming and symbol visibility — "
            "compiler behaviour with no wire or JSON meaning — so no canonical construct "
            "carries them.",
        ),
        ParserLimit(
            construct="custom options and extension declarations",
            detail="A user-defined `option` and an `extend` block are preserved in the "
            "compiled descriptor set and the retained source, but the canonical model has no "
            "vocabulary for them, so they are neither named nor counted.",
        ),
    ),
    "wit": (
        ParserLimit(
            construct="world include expansion",
            detail="A world's `include` statements are recorded but not expanded — "
            "the included world's imports/exports are not merged into the "
            "including world.",
        ),
        ParserLimit(
            construct="secondary nested package blocks",
            detail="A file nesting more than one `package ns:name { … }` block has "
            "only its first block read; the others are counted and reported, not "
            "parsed.",
        ),
    ),
}


class CapabilityReference(BaseModel):
    """A named reference into the CLX-2.4 per-format capability registry.

    The ledger's ``not-parsed-by-adapter`` entries and the manifest's adapter section
    both point here, so "our parser does not yet read this" is always traceable to the
    registry entry that documents the format's coverage state.
    """

    model_config = ConfigDict(extra="forbid")

    format: str = Field(description="Canonical format key of the registry entry (CLX-2.4).")
    mode: str = Field(description="Registry coverage mode: native / adapted / unsupported.")
    importable: bool = Field(description="Whether an import-source adapter ingests this format today.")
    related_issues: List[str] = Field(
        default_factory=list,
        description="GitHub issues tracking planned coverage work for this format.",
    )
    notes: str = Field(default="", description="The registry entry's human rationale.")

    @classmethod
    def from_capability(cls, capability: FormatLintCapability) -> "CapabilityReference":
        """Project a registry :class:`~app.format_lint_capabilities.FormatLintCapability` row."""
        return cls(
            format=capability.format,
            mode=capability.mode,
            importable=capability.importable,
            related_issues=list(capability.related_issues),
            notes=capability.notes,
        )


class ImportAdapterReference(BaseModel):
    """The adapter that produced the manifest, with its capability references (CLX-2.4)."""

    model_config = ConfigDict(extra="forbid")

    adapter_key: str = Field(description="Registry key of the adapter that ran (e.g. ``openapi``).")
    adapter_label: str = Field(description="Human label of the adapter.")
    paradigm: str = Field(description="The canonical paradigm the adapter produces.")
    formats: List[str] = Field(
        default_factory=list, description="Normalizer format keys the adapter can emit."
    )
    apiome_version: str = Field(
        description="The apiome-rest package version that ran the adapter — the adapter "
        "version provenance folded into the manifest hash (adapters version with the package)."
    )
    capability: CapabilityReference = Field(
        description="The CLX-2.4 capability-registry entry for the normalized model's format."
    )
    parser_limits: List[str] = Field(
        default_factory=list,
        description="Construct classes this adapter's parser is declared not to read yet "
        "(see the coverage ledger's not-parsed-by-adapter entries for details).",
    )


# ===========================================================================
# Entity tree + coverage ledger models
# ===========================================================================


class ImportPreviewEntity(BaseModel):
    """One canonical entity the import would create (IXH-3.1).

    A flat row of the entity tree: services, operations (parented to their service),
    channels, and types, in the model's deterministic declaration order. ``order`` is
    the entity's stable index in the *full* tree, so a paginated client can interleave
    pages without re-sorting.
    """

    model_config = ConfigDict(extra="forbid")

    key: str = Field(description="Stable canonical key (``acme.PetService``, ``GET /pets/{id}``, ``User``).")
    name: str = Field(description="Source-visible name of the entity.")
    entity_kind: str = Field(description="service | operation | type | channel.")
    parent_key: Optional[str] = Field(
        default=None,
        description="The owning service's key, on an operation; null elsewhere.",
    )
    order: int = Field(description="Stable 0-based index of this entity in the full tree.")
    description: Optional[str] = Field(default=None, description="Entity description, when the source carried one.")
    deprecated: bool = Field(default=False, description="Whether the source marks the entity deprecated.")
    coverage: CoverageClass = Field(description="This entity's coverage classification.")
    native_name: Optional[str] = Field(
        default=None, description="The construct's name in the source document, when recovered."
    )
    native_id: Optional[str] = Field(
        default=None, description="Source-native stable identifier, when the parser captured one."
    )
    source_location: Optional[str] = Field(
        default=None,
        description="Source location (line/range/pointer) the entity came from, when the parser "
        "captured one; null otherwise — never fabricated.",
    )
    unmodeled_extras: List[str] = Field(
        default_factory=list,
        description="Source attribute names that ride only in the entity's ``extras`` bag "
        "because no canonical field models them; non-empty exactly when coverage is "
        "``partially-mapped``.",
    )


class CoverageEntry(BaseModel):
    """One row of the coverage ledger (IXH-3.1).

    Classifies one source construct. Entity-scoped rows reference their canonical
    entity by key; document-scoped rows (root-level constructs) have no entity. A
    declared parser limit is marked ``document_scoped = false`` — it states an adapter
    fact, not a verified fact about this document.
    """

    model_config = ConfigDict(extra="forbid")

    source_construct: str = Field(
        description="The source construct this row classifies (an entity key, a document-level "
        "attribute, or a construct class). Named ``source_construct`` (not ``construct``) so it "
        "cannot shadow pydantic's legacy ``BaseModel.construct``."
    )
    coverage: CoverageClass = Field(description="The coverage classification.")
    status: ProjectionStatus = Field(
        description="The shared CPDO-1.3 projection status this class encodes."
    )
    reason: Optional[ProjectionReason] = Field(
        default=None,
        description="The shared reason code for a non-mapped class; null for ``mapped``.",
    )
    detail: str = Field(description="Human-readable explanation of the classification.")
    entity_key: Optional[str] = Field(
        default=None,
        description="The canonical entity this row concerns, when entity-scoped.",
    )
    document_scoped: bool = Field(
        default=True,
        description="True when the row states a fact about this document; false for an "
        "adapter-level declaration (a parser limit not evaluated against this document).",
    )
    capability_reference: Optional[CapabilityReference] = Field(
        default=None,
        description="The CLX-2.4 registry entry documenting the coverage gap; present on "
        "every ``not-parsed-by-adapter`` row.",
    )


class ImportPreviewManifest(BaseModel):
    """One page of the import preview manifest (IXH-3.1).

    The identity fields (``manifest_hash``, ``adapter``, counts) always describe the
    **full** manifest; ``entities`` / ``nodes`` / ``edges`` / ``coverage`` carry the
    requested page. ``truncated`` states whether anything was omitted from this
    response — truncation is declared, never silent.
    """

    model_config = ConfigDict(extra="forbid")

    manifest_hash: str = Field(
        description="Stable content hash over the full manifest (adapter + versions + options "
        "+ graph + ledger). Identical for a fixed input, adapter version, and options."
    )
    adapter: ImportAdapterReference = Field(
        description="The adapter that produced the model, with its CLX-2.4 capability references."
    )
    counts: ImportPreflightCounts = Field(
        description="Full-manifest canonical entity counts — the same values the pre-flight "
        "reports and the committed import's summary reports for this document."
    )
    coverage_counts: Dict[str, int] = Field(
        description="Full-manifest ledger row count per coverage class, zero-filled."
    )
    status_counts: Dict[str, int] = Field(
        description="Full-manifest outcome-edge count per shared ProjectionStatus, zero-filled "
        "(parity with the export projection manifest's counts)."
    )
    reason_counts: Dict[str, int] = Field(
        description="Full-manifest outcome-edge count per shared ProjectionReason, zero-filled."
    )
    entities: List[ImportPreviewEntity] = Field(
        default_factory=list, description="This page's entity rows, in stable tree order."
    )
    total_entities: int = Field(description="Entity count in the full manifest.")
    nodes: List[ProjectionNode] = Field(
        default_factory=list,
        description="CPDO-1.3 projection nodes for this page's entities (plus document-scope "
        "nodes on the first page).",
    )
    edges: List[ProjectionEdge] = Field(
        default_factory=list,
        description="CPDO-1.3 projection edges for this page's entities (plus document-scope "
        "edges on the first page). ``projects`` edges run native → canonical: the import "
        "direction's outcome edge.",
    )
    coverage: List[CoverageEntry] = Field(
        default_factory=list,
        description="This page's coverage-ledger rows (entity rows for the page; document-scope "
        "and adapter-declaration rows ride on the first page).",
    )
    total_coverage_entries: int = Field(description="Ledger row count in the full manifest.")
    page_size: int = Field(description="The applied (clamped) entity page size.")
    next_cursor: Optional[str] = Field(
        default=None,
        description="Opaque cursor for the next entity page; null on the last page. The cursor "
        "codec is shared with the export projection evidence pages.",
    )
    truncated: bool = Field(
        description="True when this response omits rows the full manifest has (more pages exist)."
    )


class ImportPreviewManifestRequest(ImportPreflightRequest):
    """The manifest request: the 2.1 pre-flight intake payload plus pagination.

    Everything the pre-flight accepts (document, adapter/source hints, import target,
    archive root) plus a cursor + page size over the entity tree. Repeating a request
    with the next cursor re-submits the same bytes; the manifest itself is served from a
    content-hash cache, so paging does not re-run the pipeline.
    """

    cursor: Optional[str] = Field(
        default=None,
        description="Opaque entity-page cursor from a previous response; null for the first page.",
    )
    page_size: int = Field(
        default=DEFAULT_ENTITY_PAGE_SIZE,
        ge=1,
        description=f"Maximum entities per page; clamped to {MAX_ENTITY_PAGE_SIZE}.",
    )
    project_slug: Optional[str] = Field(
        default=None,
        description="The catalog project slug the commit would target (the wizard computes it "
        "client-side, exactly as it will at commit time). When set and an existing catalog "
        "item lives under it, the response carries the IXH-3.4 re-import delta; omitted or "
        "unmatched, `reimport` is null (a first-time import).",
    )


class ImportPreviewManifestResponse(BaseModel):
    """The preview-manifest endpoint's response (IXH-3.1).

    Embeds the full IXH-2.1 pre-flight report (detection, routing decision, counts,
    lint, policy verdict, taxonomy error) and adds the manifest. ``manifest`` is null
    exactly when the candidate is not importable (``preflight.ok`` false) — there is no
    model to describe, and the pre-flight's ``error`` says why.
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool = Field(description="Mirrors ``preflight.ok``: whether the candidate is importable.")
    preflight: ImportPreflightReport = Field(
        description="The full IXH-2.1 pre-flight report for the same run — detection, routing "
        "decision, entity counts, ranked lint, policy verdict, and the intake-taxonomy error "
        "when the candidate is not importable."
    )
    manifest: Optional[ImportPreviewManifest] = Field(
        default=None,
        description="The requested manifest page; null when the candidate is not importable.",
    )
    reimport: Optional["ImportReimportDelta"] = Field(
        default=None,
        description="The IXH-3.4 re-import delta against the targeted catalog item's current "
        "revision; null for a first-time import (no existing item under the request's "
        "`project_slug`), when no slug was sent, for non-catalog routing, or when the current "
        "revision's source cannot be reconstructed.",
    )


# ===========================================================================
# Re-import delta (IXH-3.4, #5106)
# ===========================================================================


class ReimportDeltaEntry(BaseModel):
    """One identity-keyed change a re-import would make, optionally graded.

    The change itself comes from :func:`app.import_source.canonical_diff` (computed over
    canonical models, never raw text). The severity fields are joined from the format's
    breaking-change classifier where one graded the same key; entries the classifier did
    not grade keep them null — absence of a grade is *stated*, never presented as safety.
    """

    model_config = ConfigDict(extra="forbid")

    entity: str = Field(description="Entity family: root/service/operation/type/channel.")
    key: str = Field(description="The entity's stable canonical key (empty for ``root``).")
    change: DiffChangeKind = Field(description="added / removed / changed.")
    severity: Optional[str] = Field(
        default=None,
        description="Breaking-change grade for this change (safe/dangerous/breaking), when the "
        "classifier graded this key; null when unannotated.",
    )
    rule_id: Optional[str] = Field(
        default=None, description="The classifier rule that produced the grade, when graded."
    )
    rationale: Optional[str] = Field(
        default=None, description="One-line justification for the grade, when graded."
    )


class ImportReimportDelta(BaseModel):
    """What re-importing this candidate would change on an existing catalog item.

    Computed **before** the commit, per request (never cached — the item's current
    revision can move between requests), from the two canonical models by stable key. A
    ``noop`` delta (identical fingerprints, empty ``entries``) tells the client the
    commit would create an empty revision, so it can offer to skip it.
    """

    model_config = ConfigDict(extra="forbid")

    target_item_id: str = Field(description="The existing catalog item (project id) the commit would target.")
    target_item_name: Optional[str] = Field(
        default=None, description="The existing item's display name."
    )
    target_item_slug: str = Field(description="The existing item's slug (the resolution key).")
    current_version_record_id: Optional[str] = Field(
        default=None,
        description="The current revision's record id (``versions.id``) the diff was computed against.",
    )
    noop: bool = Field(
        description="True when the candidate's fingerprint equals the current revision's — the "
        "re-import would change nothing."
    )
    candidate_fingerprint: str = Field(
        description="The candidate model's canonical fingerprint (same value as the pre-flight's)."
    )
    current_fingerprint: str = Field(
        description="The current revision's canonical fingerprint, recomputed from its stored source."
    )
    entries: List[ReimportDeltaEntry] = Field(
        default_factory=list,
        description="Every change, sorted (entity, key, change) — empty for a no-op.",
    )
    counts: Dict[str, int] = Field(
        default_factory=dict,
        description="Total changes per kind: added / removed / changed (zero-filled).",
    )
    counts_by_entity: Dict[str, Dict[str, int]] = Field(
        default_factory=dict,
        description="Per entity family, the added/removed/changed tallies (families with changes only).",
    )
    classifier: Optional[str] = Field(
        default=None,
        description="Identifier of the breaking-change classifier that graded the diff "
        "(``builtin`` for the structural baseline, else the format pack's id); null when "
        "grading was unavailable or failed — in which case NO entry carries a severity.",
    )
    classifier_format_pack: bool = Field(
        default=False,
        description="Whether a format-specific classifier pack (not the structural baseline) "
        "graded the diff.",
    )
    overall_severity: Optional[str] = Field(
        default=None,
        description="Worst severity across the graded changes (safe/dangerous/breaking); null "
        "when ungraded.",
    )
    severity_counts: Dict[str, int] = Field(
        default_factory=dict,
        description="Number of graded changes at each severity (non-zero tiers only).",
    )


# The response references ImportReimportDelta forward (it is documented after the
# response model); resolve the reference now that both classes exist.
ImportPreviewManifestResponse.model_rebuild()


# ===========================================================================
# Internal full-manifest form (built once, paginated per request)
# ===========================================================================


@dataclass
class _EntityRows:
    """One entity together with its graph and ledger rows (page unit)."""

    entity: ImportPreviewEntity
    nodes: List[ProjectionNode]
    edges: List[ProjectionEdge]
    coverage: CoverageEntry


@dataclass
class _FullManifest:
    """The complete, unpaginated manifest a build produces (cached per content hash).

    Carries the candidate's canonical ``model`` so the per-request re-import delta
    (IXH-3.4) can be computed on cache hits too — the pipeline artifacts are only
    collected on the building request. The cache is bounded
    (:data:`PREVIEW_MANIFEST_CACHE_MAX_ENTRIES`), so the retained models are too.
    """

    model: CanonicalApi
    manifest_hash: str
    adapter: ImportAdapterReference
    counts: ImportPreflightCounts
    coverage_counts: Dict[str, int]
    status_counts: Dict[str, int]
    reason_counts: Dict[str, int]
    entity_rows: List[_EntityRows]
    document_nodes: List[ProjectionNode]
    document_edges: List[ProjectionEdge]
    document_coverage: List[CoverageEntry]

    @property
    def total_entities(self) -> int:
        return len(self.entity_rows)

    @property
    def total_coverage_entries(self) -> int:
        return len(self.entity_rows) + len(self.document_coverage)


# ===========================================================================
# Build
# ===========================================================================


def _native_evidence_for(extras: Dict[str, Any], name: Optional[str], key: str) -> NativeEvidence:
    """Recover native evidence from an entity's extras, exactly as the export manifest does."""
    return NativeEvidence(
        native_id=first_extra(extras, NATIVE_ID_EXTRA_KEYS),
        native_name=name or key,
        source_location=first_extra(extras, SOURCE_LOCATION_EXTRA_KEYS),
    )


def _unmodeled_extras(extras: Dict[str, Any]) -> List[str]:
    """Source attribute names in ``extras`` that are not our own provenance bookkeeping."""
    return sorted(key for key in extras if key not in PROVENANCE_EXTRA_KEYS)


def _entity_rows(
    *,
    key: str,
    name: str,
    entity_kind: str,
    order: int,
    extras: Dict[str, Any],
    description: Optional[str],
    deprecated: bool,
    parent_key: Optional[str],
) -> _EntityRows:
    """Build one entity's row, nodes, edges, and ledger entry.

    The graph mirrors the export build's shape: one native node, one canonical node, a
    ``derives`` provenance edge (always ``retained``), and exactly one outcome
    (``projects``) edge — here running native → canonical, the import direction's
    destination lane.
    """
    unmodeled = _unmodeled_extras(extras)
    if provenance_of(extras) == INFERRED:
        coverage = CoverageClass.INFERRED
    elif unmodeled:
        coverage = CoverageClass.PARTIALLY_MAPPED
    else:
        coverage = CoverageClass.MAPPED
    status, reason = STATUS_FOR_COVERAGE[coverage]
    evidence = _native_evidence_for(extras, name, key)

    if coverage is CoverageClass.MAPPED:
        detail = "Source construct fully represented by canonical fields."
    elif coverage is CoverageClass.INFERRED:
        sample_count = extras.get("sample_count")
        sample_bit = f" from {sample_count} sample(s)" if sample_count is not None else ""
        path_evidence = extras.get("inference_evidence")
        explicit = extras.get(PROVENANCE_EVIDENCE_KEY)
        if isinstance(explicit, str) and explicit.strip():
            detail = f"Inferred: {explicit.strip()}"
        elif isinstance(path_evidence, dict) and path_evidence.get("template"):
            detail = (
                f"Inferred{sample_bit}: path template {path_evidence['template']!r} "
                f"from samples {path_evidence.get('sample_urls', [])!r}."
            )
        else:
            detail = (
                f"Inferred{sample_bit} from observations; never presented as a "
                "declared source construct."
            )
    else:
        detail = (
            "Source attributes not modeled by canonical fields ride in the entity's "
            f"extras bag: {', '.join(unmodeled)}."
        )

    entity = ImportPreviewEntity(
        key=key,
        name=name,
        entity_kind=entity_kind,
        parent_key=parent_key,
        order=order,
        description=description,
        deprecated=deprecated,
        coverage=coverage,
        native_name=evidence.native_name,
        native_id=evidence.native_id,
        source_location=evidence.source_location,
        unmodeled_extras=unmodeled,
    )

    native_id = f"native:{key}"
    canonical_id = f"canonical:{key}"
    nodes = [
        ProjectionNode(
            id=native_id,
            kind=ProjectionNodeKind.NATIVE,
            label=evidence.native_name or key,
            construct_key=key,
            native=evidence,
        ),
        ProjectionNode(
            id=canonical_id,
            kind=ProjectionNodeKind.CANONICAL,
            label=key,
            construct_key=key,
            canonical_kind=entity_kind,
        ),
    ]
    edges = [
        ProjectionEdge(
            id=f"derives:{key}",
            relation=ProjectionEdgeRelation.DERIVES,
            source=native_id,
            target=canonical_id,
            status=ProjectionStatus.RETAINED,
            detail="source construct normalized into the canonical model",
        ),
        ProjectionEdge(
            id=f"projects:{key}#0",
            relation=ProjectionEdgeRelation.PROJECTS,
            source=native_id,
            target=canonical_id,
            status=status,
            reason=reason,
            detail=detail,
        ),
    ]
    ledger = CoverageEntry(
        source_construct=key,
        coverage=coverage,
        status=status,
        reason=reason,
        detail=detail,
        entity_key=key,
        document_scoped=True,
    )
    return _EntityRows(entity=entity, nodes=nodes, edges=edges, coverage=ledger)


def _document_scope_rows(
    api: CanonicalApi,
    capability: CapabilityReference,
    parser_limits: Tuple[ParserLimit, ...],
) -> Tuple[List[ProjectionNode], List[ProjectionEdge], List[CoverageEntry]]:
    """Build the document-level ledger rows and their graph counterparts.

    * Root-level ``extras`` keys → ``unsupported-by-canonical-model``: the source
      carried a document-level construct no canonical field models. These are facts
      about *this* document, so they get a native node and a ``projects`` edge with
      ``target = None`` — exactly how the export manifest represents a drop.
    * Declared parser limits → ``not-parsed-by-adapter``: adapter-level declarations,
      ledger-only (no graph rows — the graph states only document facts), each naming
      its capability-registry reference.
    * Overlay provenance (IXH-7.7) → ``mapped``: each value an OpenAPI Overlay set,
      replaced, appended, or removed, naming the contributing overlay and action —
      the pre-processor applied the action fully, so the row is a retained fact
      about this document, with the attribution in its detail.
    """
    nodes: List[ProjectionNode] = []
    edges: List[ProjectionEdge] = []
    ledger: List[CoverageEntry] = []

    status, reason = STATUS_FOR_COVERAGE[CoverageClass.UNSUPPORTED_BY_CANONICAL_MODEL]
    for extra_key in _unmodeled_extras(api.extras):
        construct = f"document#{extra_key}"
        detail = (
            f"The source carried document-level construct {extra_key!r}, which no "
            "canonical field models; it is preserved only in the model's extras bag."
        )
        native_id = f"native:{construct}"
        nodes.append(
            ProjectionNode(
                id=native_id,
                kind=ProjectionNodeKind.NATIVE,
                label=extra_key,
                construct_key=construct,
                native=NativeEvidence(native_name=extra_key),
            )
        )
        edges.append(
            ProjectionEdge(
                id=f"projects:{construct}#0",
                relation=ProjectionEdgeRelation.PROJECTS,
                source=native_id,
                target=None,
                status=status,
                reason=reason,
                detail=detail,
            )
        )
        ledger.append(
            CoverageEntry(
                source_construct=construct,
                coverage=CoverageClass.UNSUPPORTED_BY_CANONICAL_MODEL,
                status=status,
                reason=reason,
                detail=detail,
                document_scoped=True,
            )
        )

    limit_status, limit_reason = STATUS_FOR_COVERAGE[CoverageClass.NOT_PARSED_BY_ADAPTER]
    for limit in parser_limits:
        ledger.append(
            CoverageEntry(
                source_construct=limit.construct,
                coverage=CoverageClass.NOT_PARSED_BY_ADAPTER,
                status=limit_status,
                reason=limit_reason,
                detail=(
                    f"{limit.detail} Whether this document uses the construct is not "
                    "evaluated — this is a declared adapter limit."
                ),
                document_scoped=False,
                capability_reference=capability,
            )
        )

    inferred_status, inferred_reason = STATUS_FOR_COVERAGE[CoverageClass.INFERRED]
    path_inferences = api.extras.get("path_inferences") if isinstance(api.extras, dict) else None
    if isinstance(path_inferences, list):
        for index, evidence in enumerate(path_inferences):
            if not isinstance(evidence, dict):
                continue
            method = evidence.get("method") or "?"
            template = evidence.get("template") or "?"
            samples = evidence.get("sample_urls") or []
            construct = f"path-template#{method} {template}"
            detail = (
                f"Inferred path template {method} {template} from "
                f"{len(samples)} sample URL(s): {samples!r}."
            )
            ledger.append(
                CoverageEntry(
                    source_construct=construct,
                    coverage=CoverageClass.INFERRED,
                    status=inferred_status,
                    reason=inferred_reason,
                    detail=detail,
                    document_scoped=True,
                )
            )
            # Keep index referenced so unused-variable linters stay quiet if enumerate changes.
            _ = index

    ledger.extend(_overlay_provenance_rows(api))
    ledger.extend(_gateway_capability_rows(api))
    ledger.extend(_wit_capability_rows(api))
    ledger.extend(_aws_apigateway_capability_rows(api))
    ledger.extend(_azure_apim_capability_rows(api))
    ledger.extend(_apigee_capability_rows(api))
    ledger.extend(_relaxng_capability_rows(api))
    ledger.extend(_dtd_capability_rows(api))
    ledger.extend(_cddl_capability_rows(api))
    ledger.extend(_arrow_capability_rows(api))
    ledger.extend(_typescript_capability_rows(api))
    ledger.extend(_zod_capability_rows(api))
    ledger.extend(_trpc_capability_rows(api))
    ledger.extend(_pydantic_capability_rows(api))
    ledger.extend(_opcua_capability_rows(api))
    ledger.extend(_sparkplug_capability_rows(api))
    ledger.extend(_ros2_capability_rows(api))
    ledger.extend(_mainframe_misc_capability_rows(api))
    ledger.extend(_pli_capability_rows(api))
    ledger.extend(_hoppscotch_capability_rows(api))
    ledger.extend(_thunder_client_capability_rows(api))
    ledger.extend(_soapui_capability_rows(api))
    ledger.extend(_device_model_capability_rows(api))
    ledger.extend(_linked_data_capability_rows(api))
    ledger.extend(_typed_config_capability_rows(api))
    ledger.extend(_odcs_capability_rows(api))
    ledger.extend(_kafka_connect_capability_rows(api))
    ledger.extend(_dbt_capability_rows(api))
    ledger.extend(_sql_ddl_capability_rows(api))

    return nodes, edges, ledger


#: Human verbs for overlay provenance kinds (IXH-7.7).
_OVERLAY_KIND_VERBS = {
    "set": "was added",
    "replaced": "was replaced",
    "appended": "was appended",
    "removed": "was removed",
}


def _overlay_provenance_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the IXH-7.7 overlay application report as document-scoped ledger rows.

    One row per provenance record — the value's JSON Pointer, what happened to it,
    and which overlay's action did it — plus one declared-truncation row when the
    report capped its records, so the ledger never silently claims completeness.
    The rows are ``mapped``: the pre-processor applied the action fully, and the
    attribution (which overlay contributed the value) is the row's detail.
    """
    report = api.extras.get("overlay") if isinstance(api.extras, dict) else None
    if not isinstance(report, dict):
        return []
    status, reason = STATUS_FOR_COVERAGE[CoverageClass.MAPPED]
    rows: List[CoverageEntry] = []
    for record in report.get("provenance") or []:
        if not isinstance(record, dict):
            continue
        pointer = str(record.get("pointer") or "")
        kind = str(record.get("kind") or "")
        verb = _OVERLAY_KIND_VERBS.get(kind, f"was {kind or 'changed'}")
        detail = (
            f"The value at {pointer or 'the document root'} {verb} by overlay "
            f"{record.get('overlay')!r} (action #{record.get('action_index')}, "
            f"target {record.get('target')!r})."
        )
        rows.append(
            CoverageEntry(
                source_construct=f"overlay#{pointer or '/'}",
                coverage=CoverageClass.MAPPED,
                status=status,
                reason=reason,
                detail=detail,
                document_scoped=True,
            )
        )
    if report.get("provenance_truncated"):
        total = report.get("provenance_total")
        rows.append(
            CoverageEntry(
                source_construct="overlay#(truncated)",
                coverage=CoverageClass.MAPPED,
                status=status,
                reason=reason,
                detail=(
                    f"The overlay application recorded {total} change(s) in total; "
                    f"only the first {len(report.get('provenance') or [])} carry "
                    "itemized provenance rows here."
                ),
                document_scoped=True,
            )
        )
    return rows




def _gateway_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the IXH-7.8 gateway-config report as document-scoped ledger rows.

    Gateway configurations declare routes but no request/response schemas. The
    schema absence is stated as ``inferred`` / ``source_incomplete`` — a
    capability limit of the *source format*, **never** a drop — alongside one
    row per inferred auth scheme, one ``partially-mapped`` row per auth plugin
    with no canonical mapping (its config rides in extras), one
    ``unsupported-by-canonical-model`` row per recognized-but-unmodeled source
    construct, one ``partially-mapped`` row per non-auth Kong plugin (CDG-1.2: gateway
    policy the canonical model does not represent, kept in the captured source), and a
    ``mapped`` statement of credential redaction so the scrub is visible, not silent.
    """
    report = api.extras.get("gateway") if isinstance(api.extras, dict) else None
    if not isinstance(report, dict):
        return []
    flavor = str(report.get("flavor") or "")
    # FMT-7.6: the label is part of the flavor's declaration in the gateway family.
    declaration = flavor_for(flavor)
    label = declaration.label if declaration is not None else "This gateway configuration"
    rows: List[CoverageEntry] = []

    inferred_status, inferred_reason = STATUS_FOR_COVERAGE[CoverageClass.INFERRED]
    schemaless = int(report.get("schemaless_operation_count") or 0)
    if schemaless:
        rows.append(
            CoverageEntry(
                source_construct="gateway#request-response-schemas",
                coverage=CoverageClass.INFERRED,
                status=inferred_status,
                reason=inferred_reason,
                detail=(
                    f"{label} declares routes without request/response schemas; "
                    f"{schemaless} operation(s) imported without message payloads. "
                    "This is a capability limit of the source format, not a drop — "
                    "supply schemas and use the convert flow to promote the catalog "
                    "item."
                ),
                document_scoped=True,
            )
        )
    for hint in report.get("auth") or []:
        if not isinstance(hint, dict) or not hint.get("scheme"):
            continue
        rows.append(
            CoverageEntry(
                source_construct=f"gateway#auth.{hint.get('plugin')}",
                coverage=CoverageClass.INFERRED,
                status=inferred_status,
                reason=inferred_reason,
                detail=(
                    f"Auth scheme {hint.get('scheme')!r} inferred from plugin "
                    f"{hint.get('plugin')!r} ({hint.get('scope')} scope) — mapped to "
                    "canonical security, labelled inferred, never presented as "
                    "declared."
                ),
                document_scoped=True,
            )
        )

    partial_status, partial_reason = STATUS_FOR_COVERAGE[CoverageClass.PARTIALLY_MAPPED]
    for plugin in report.get("unmapped_plugins") or []:
        if not isinstance(plugin, dict) or not plugin.get("name"):
            continue
        rows.append(
            CoverageEntry(
                source_construct=f"gateway#plugin.{plugin.get('name')}",
                coverage=CoverageClass.PARTIALLY_MAPPED,
                status=partial_status,
                reason=partial_reason,
                detail=(
                    f"Auth plugin {plugin.get('name')!r} ({plugin.get('scope')} scope) "
                    "has no canonical security mapping; its configuration is preserved "
                    "verbatim in extras."
                ),
                document_scoped=True,
            )
        )

    for plugin in report.get("unmodeled_plugins") or []:
        if not isinstance(plugin, dict) or not plugin.get("name"):
            continue
        rows.append(
            CoverageEntry(
                source_construct=f"gateway#plugin.{plugin.get('name')}.{plugin.get('scope')}",
                coverage=CoverageClass.PARTIALLY_MAPPED,
                status=partial_status,
                reason=partial_reason,
                detail=(
                    f"Plugin {plugin.get('name')!r} ({plugin.get('scope')} scope) is gateway "
                    "policy the canonical model does not represent; its name is kept on the "
                    "operations it applies to and its configuration stays in the captured "
                    "source."
                ),
                document_scoped=True,
            )
        )

    dropped_status, dropped_reason = STATUS_FOR_COVERAGE[
        CoverageClass.UNSUPPORTED_BY_CANONICAL_MODEL
    ]
    for entry in report.get("ignored_constructs") or []:
        if not isinstance(entry, dict) or not entry.get("construct"):
            continue
        rows.append(
            CoverageEntry(
                source_construct=f"gateway#{entry.get('construct')}",
                coverage=CoverageClass.UNSUPPORTED_BY_CANONICAL_MODEL,
                status=dropped_status,
                reason=dropped_reason,
                detail=(
                    f"Source construct {entry.get('construct')!r} "
                    f"({entry.get('count')} entr(y/ies)): {entry.get('reason')}."
                ),
                document_scoped=True,
            )
        )

    redactions = int(report.get("credential_redactions") or 0)
    if redactions:
        mapped_status, mapped_reason = STATUS_FOR_COVERAGE[CoverageClass.MAPPED]
        rows.append(
            CoverageEntry(
                source_construct="gateway#credential-redactions",
                coverage=CoverageClass.MAPPED,
                status=mapped_status,
                reason=mapped_reason,
                detail=(
                    f"{redactions} credential value(s) were redacted at parse time; "
                    "counts are retained, values are never imported."
                ),
                document_scoped=True,
            )
        )
    return rows


def _aws_apigateway_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the FMT-7.1 AWS API Gateway report as document-scoped ledger rows.

    The interpreted extensions (integrations, authorizers, request validators, CORS) are
    ``mapped``: each became a canonical backend, security, validation or CORS record labelled
    ``declared``. A documented extension the canonical model has no construct for (resource
    policy, gateway responses, binary media types, …) and an extension nobody has seen before
    are ``partially-mapped``: kept verbatim in extras and listed here by name and location, so
    neither is silently dropped.
    """
    report = api.extras.get("aws_apigateway") if isinstance(api.extras, dict) else None
    if not isinstance(report, dict):
        return []
    mapped_status, mapped_reason = STATUS_FOR_COVERAGE[CoverageClass.MAPPED]
    partial_status, partial_reason = STATUS_FOR_COVERAGE[CoverageClass.PARTIALLY_MAPPED]
    rows: List[CoverageEntry] = []

    def _row(construct: str, coverage: CoverageClass, detail: str) -> None:
        status, reason = (mapped_status, mapped_reason) if coverage is CoverageClass.MAPPED else (
            partial_status,
            partial_reason,
        )
        rows.append(
            CoverageEntry(
                source_construct=construct,
                coverage=coverage,
                status=status,
                reason=reason,
                detail=detail,
                document_scoped=True,
            )
        )

    for kind, count in sorted((report.get("integrations") or {}).items()):
        _row(
            f"aws#integration.{kind}",
            CoverageClass.MAPPED,
            f"{count} operation(s) declare a {kind} integration; recorded as each operation's "
            "backend (declared), with the verbatim integration in extras.",
        )
    for authorizer in report.get("authorizers") or []:
        if isinstance(authorizer, dict) and authorizer.get("name"):
            kind = authorizer.get("type") or authorizer.get("authType") or "authorizer"
            _row(
                f"aws#authorizer.{authorizer['name']}",
                CoverageClass.MAPPED,
                f"Authorizer {authorizer['name']!r} ({kind}) mapped to canonical security on the "
                "operations that require it (declared).",
            )
    for name in sorted(report.get("request_validators") or {}):
        _row(
            f"aws#request-validator.{name}",
            CoverageClass.MAPPED,
            f"Request validator {name!r} recorded as the declared validation posture of the "
            "operations that name it.",
        )
    if isinstance(api.extras.get("cors"), dict):
        _row(
            "aws#cors",
            CoverageClass.MAPPED,
            "x-amazon-apigateway-cors recorded as the API's CORS metadata (declared).",
        )

    by_status: Dict[str, Dict[str, List[str]]] = {"preserved": {}, "unknown": {}}
    for site in report.get("extensions") or []:
        if isinstance(site, dict) and site.get("status") in by_status:
            by_status[site["status"]].setdefault(str(site.get("name")), []).append(str(site.get("pointer")))
    for name, pointers in sorted(by_status["preserved"].items()):
        _row(
            f"aws#extension.{name}",
            CoverageClass.PARTIALLY_MAPPED,
            f"{name} ({len(pointers)} site(s)) has no canonical construct; preserved verbatim in "
            "extras.",
        )
    for name, pointers in sorted(by_status["unknown"].items()):
        shown = ", ".join(pointers[:3]) + (f" and {len(pointers) - 3} more" if len(pointers) > 3 else "")
        _row(
            f"aws#unknown-extension.{name}",
            CoverageClass.PARTIALLY_MAPPED,
            f"Unrecognised extension {name} at {shown} is not interpreted; preserved verbatim in "
            "extras and reported here, never dropped.",
        )
    return rows


#: Where each mapped APIM policy lands in the canonical model (FMT-7.2), for the ledger detail.
_APIM_POLICY_TARGETS = {
    "validate-jwt": "canonical security",
    "validate-azure-ad-token": "canonical security",
    "check-header": "canonical security (header check)",
    "authentication-certificate": "the backend's authentication",
    "authentication-basic": "the backend's authentication",
    "authentication-managed-identity": "the backend's authentication",
    "rate-limit": "rate-limit metadata",
    "rate-limit-by-key": "rate-limit metadata",
    "quota": "rate-limit metadata (quota)",
    "quota-by-key": "rate-limit metadata (quota)",
    "set-backend-service": "the backend (and, at API scope, a server named backend)",
    "rewrite-uri": "the request rewrite (path provenance)",
    "set-method": "the request rewrite",
    "set-query-parameter": "the request rewrite",
    "cors": "CORS metadata",
    "ip-filter": "the access posture",
}


def _azure_apim_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the FMT-7.2 Azure API Management report as document-scoped ledger rows.

    The definition and every mapped policy are ``mapped``: the definition through the OpenAPI
    path, each policy into a canonical security, rate-limit, backend, rewrite, CORS or access
    record labelled ``derivedFrom: "policy"``. A policy the canonical model has no construct for
    (``preserved``: a documented APIM policy; ``unknown``: anything else) is ``partially-mapped``
    — kept verbatim in ``extras.azure_apim.unmapped`` and listed here, so it is never silently
    dropped. An unresolved backend id and a ``<base />`` whose parent scope was not supplied are
    ``partially-mapped`` too: the fact is recorded, its target is not known.
    """
    report = api.extras.get("azure_apim") if isinstance(api.extras, dict) else None
    if not isinstance(report, dict):
        return []
    rows: List[CoverageEntry] = []

    def _row(construct: str, coverage: CoverageClass, detail: str) -> None:
        status, reason = STATUS_FOR_COVERAGE[coverage]
        rows.append(
            CoverageEntry(
                source_construct=construct,
                coverage=coverage,
                status=status,
                reason=reason,
                detail=detail,
                document_scoped=True,
            )
        )

    if report.get("shape") in ("definition", "definition+policy", "arm-template"):
        _row(
            "apim#definition",
            CoverageClass.MAPPED,
            "Paths, parameters and schemas from the API definition, normalized as OpenAPI "
            "(derivedFrom: definition).",
        )
    for name, entry in sorted((report.get("mapped") or {}).items()):
        if not isinstance(entry, dict):
            continue
        scopes = ", ".join(entry.get("scopes") or []) or "unknown"
        _row(
            f"apim#policy.{name}",
            CoverageClass.MAPPED,
            f"{entry.get('count', 0)} {name} element(s) at {scopes} scope; recorded as "
            f"{_APIM_POLICY_TARGETS.get(name, 'canonical metadata')} (declared, derivedFrom: policy).",
        )
    by_name: Dict[Tuple[str, str], List[str]] = {}
    for item in report.get("unmapped") or []:
        if isinstance(item, dict) and item.get("name"):
            where = f"{item.get('scope')}/{item.get('section')}"
            if item.get("operation"):
                where = f"{where} ({item['operation']})"
            by_name.setdefault((str(item.get("status")), str(item["name"])), []).append(where)
    for (status, name), sites in sorted(by_name.items()):
        shown = ", ".join(sites[:3]) + (f" and {len(sites) - 3} more" if len(sites) > 3 else "")
        prefix = "apim#unknown-policy" if status == "unknown" else "apim#policy"
        label = "Unrecognised policy" if status == "unknown" else "Policy"
        _row(
            f"{prefix}.{name}",
            CoverageClass.PARTIALLY_MAPPED,
            f"{label} <{name}> at {shown} has no canonical construct; preserved verbatim in "
            "extras.azure_apim.unmapped and reported here, never dropped.",
        )
    for backend_id in report.get("unresolvedBackends") or []:
        _row(
            f"apim#backend.{backend_id}",
            CoverageClass.PARTIALLY_MAPPED,
            f"set-backend-service names backend {backend_id!r}, which the input does not declare; "
            "the backend id is recorded, its URL is unknown.",
        )
    inherits = (report.get("apiPolicy") or {}).get("inheritsFromParentScope") or []
    if inherits:
        _row(
            "apim#base",
            CoverageClass.PARTIALLY_MAPPED,
            f"<base /> in {', '.join(inherits)} inherits from a parent scope (product or global) the "
            "input does not carry; the local policies are interpreted, the inherited ones are unknown.",
        )
    return rows


def _apigee_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the FMT-7.3 Apigee bundle report as document-scoped ledger rows.

    Mapped policy types (``VerifyAPIKey``, ``OAuthV2``, ``SpikeArrest``, ``Quota``, CORS
    ``AssignMessage``) and the target endpoints are ``mapped``. A **declared condition** — a flow or
    route-rule condition that is not a path and verb, a flow with no condition, a route rule with no
    target — is ``partially-mapped``: kept verbatim in ``extras.apigee.declaredConditions`` and listed
    here, never dropped. So is every policy without a canonical construct, and every step whose
    policy the input does not carry.
    """
    report = api.extras.get("apigee") if isinstance(api.extras, dict) else None
    if not isinstance(report, dict):
        return []
    rows: List[CoverageEntry] = []

    def _row(construct: str, coverage: CoverageClass, detail: str) -> None:
        status, reason = STATUS_FOR_COVERAGE[coverage]
        rows.append(
            CoverageEntry(
                source_construct=construct,
                coverage=coverage,
                status=status,
                reason=reason,
                detail=detail,
                document_scoped=True,
            )
        )

    for policy_type, count in sorted((report.get("mapped") or {}).items()):
        _row(
            f"apigee#policy.{policy_type}",
            CoverageClass.MAPPED,
            f"{count} {policy_type} step(s) recorded as canonical security, rate-limit or CORS metadata (declared).",
        )
    for target in report.get("targetEndpoints") or []:
        if isinstance(target, dict) and (target.get("url") or target.get("loadBalancer")):
            _row(
                f"apigee#target.{target.get('name')}",
                CoverageClass.MAPPED,
                f"Target endpoint {target.get('name')!r} recorded as a server.",
            )
    for index, condition in enumerate(report.get("declaredConditions") or []):
        if not isinstance(condition, dict):
            continue
        where = condition.get("flow") or condition.get("routeRule") or index
        _row(
            f"apigee#declared-condition.{condition.get('kind')}.{where}",
            CoverageClass.PARTIALLY_MAPPED,
            f"{condition.get('meaning')} Expression: {condition.get('expression') or '(none)'}. Kept as a "
            "declared condition, never dropped.",
        )
    for policy in report.get("unmapped") or []:
        if isinstance(policy, dict):
            _row(
                f"apigee#policy.{policy.get('policyType')}.{policy.get('name')}",
                CoverageClass.PARTIALLY_MAPPED,
                f"Policy {policy.get('name')!r} ({policy.get('policyType')}) has no canonical construct; preserved "
                "verbatim in extras.apigee.unmapped.",
            )
    for step, sites in sorted((report.get("unresolvedSteps") or {}).items()):
        _row(
            f"apigee#unresolved-step.{step}",
            CoverageClass.PARTIALLY_MAPPED,
            f"Step {step!r} ({', '.join(sites)}) names a policy the input does not carry; its behaviour is unknown.",
        )
    return rows


def _wit_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the IXH-7.9 WIT capability-limit report as document-scoped ledger rows.

    WIT constructs the canonical model cannot hold — resources with methods,
    ``borrow`` handle semantics, tuples, nested results, stream/future wrappers —
    are stated as ``partially-mapped``: the construct itself was normalized (the
    resource type exists, the referenced type is used) and its inexpressible part
    is preserved verbatim in extras. A **capability limit, never a drop.** A
    ``use`` whose target lives outside the supplied package is ``inferred`` /
    ``source_incomplete``: the reference is kept by name, the definition behind
    it was not supplied.
    """
    report = api.extras.get("wit") if isinstance(api.extras, dict) else None
    if not isinstance(report, dict):
        return []
    rows: List[CoverageEntry] = []

    partial_status, partial_reason = STATUS_FOR_COVERAGE[CoverageClass.PARTIALLY_MAPPED]
    for limit in report.get("capability_limits") or []:
        if not isinstance(limit, dict) or not limit.get("construct"):
            continue
        count = int(limit.get("count") or 1)
        rows.append(
            CoverageEntry(
                source_construct=f"wit#{limit.get('construct')}",
                coverage=CoverageClass.PARTIALLY_MAPPED,
                status=partial_status,
                reason=partial_reason,
                detail=(
                    f"{limit.get('detail')} ({count} occurrence(s); a capability "
                    "limit of the canonical model, not a drop — the WIT construct "
                    "is preserved in extras)."
                ),
                document_scoped=True,
            )
        )

    inferred_status, inferred_reason = STATUS_FOR_COVERAGE[CoverageClass.INFERRED]
    for use in report.get("external_uses") or []:
        rows.append(
            CoverageEntry(
                source_construct=f"wit#use.{use}",
                coverage=CoverageClass.INFERRED,
                status=inferred_status,
                reason=inferred_reason,
                detail=(
                    f"`use {use}` resolves outside the supplied package; the "
                    "imported names are referenced by name only. Supply the "
                    "package's dependencies as a fileset to resolve them."
                ),
                document_scoped=True,
            )
        )
    return rows


def _declared_limit_rows(
    api: CanonicalApi,
    *,
    extras_key: str,
    location_label: str,
    normalized_noun: str,
) -> List[CoverageEntry]:
    """Render one adapter's declared limits as document-scoped ledger rows.

    Every reader that publishes a ``capability_limits`` list in its extras bag renders
    it the same way, and must: a declared limit is always ``partially-mapped``, never a
    drop — the construct *is* normalized and only the part with no canonical analogue is
    lost. Keeping that judgement in one place is what stops the next adapter from
    quietly grading its own limits as something else.

    Args:
        api: The normalized model.
        extras_key: The root extras key holding the reader's projection record.
        location_label: What a recorded location names in this format ("Rule(s)",
            "Field(s)", "Schema object(s)"), used to introduce the location list.
        normalized_noun: What "the … itself is normalized" refers to in this format
            ("rule", "field", "property").

    Returns:
        One ledger row per declared limit, or an empty list for a document that met
        none (or for a model this adapter did not produce).
    """
    report = api.extras.get(extras_key) if isinstance(api.extras, dict) else None
    if not isinstance(report, dict):
        return []
    rows: List[CoverageEntry] = []
    partial_status, partial_reason = STATUS_FOR_COVERAGE[CoverageClass.PARTIALLY_MAPPED]
    for limit in report.get("capability_limits") or []:
        if not isinstance(limit, dict) or not limit.get("construct"):
            continue
        count = int(limit.get("count") or 1)
        locations = [str(name) for name in (limit.get("locations") or [])]
        where = f" {location_label}: {', '.join(locations)}." if locations else ""
        rows.append(
            CoverageEntry(
                source_construct=str(limit.get("construct")),
                coverage=CoverageClass.PARTIALLY_MAPPED,
                status=partial_status,
                reason=partial_reason,
                detail=(
                    f"{limit.get('detail')} ({count} occurrence(s); a capability limit of the "
                    f"canonical model, not a drop — the {normalized_noun} itself is "
                    f"normalized.){where}"
                ),
                document_scoped=True,
            )
        )
    return rows


def _relaxng_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the FMT-4.1 RELAX NG declared limits as document-scoped ledger rows.

    RELAX NG constructs the canonical model cannot fully hold — ``interleave``'s
    order-independence, ``anyName``/``nsName`` wildcards, a ``data`` ``except`` clause,
    ``list`` tokenization, ``mixed`` content, an uninterpreted datatype library, and an
    ``href`` that names a URL import will not fetch — are stated as ``partially-mapped``:
    the construct itself is normalized (the interleaved members exist, the wildcard becomes
    an open-content member, the base datatype survives) and only the part with no canonical
    analogue is lost. A **capability limit, never a silent omission**, which is exactly what
    the ticket's third acceptance criterion asks the registry to carry.

    Args:
        api: The normalized model.

    Returns:
        One ledger row per declared limit, or an empty list for a grammar that met none.
    """
    return _declared_limit_rows(
        api,
        extras_key=RELAXNG_EXTRAS_KEY,
        location_label="Named pattern(s)",
        normalized_noun="pattern",
    )


def _dtd_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the FMT-4.2 DTD declared limits as document-scoped ledger rows.

    DTD constructs the canonical model cannot fully hold — mixed content's interleaving,
    ``ANY``'s open content, an occurrence indicator on a group, the tokenized attribute
    types, ``ID``/``IDREF`` identity, an unparsed entity, an ``<!ATTLIST>`` for an element
    that is never declared, and a system identifier import will not fetch — are stated as
    ``partially-mapped``: the construct itself is normalized (a mixed model keeps its child
    elements and its text, an ``ANY`` element becomes an open-content record, a tokenized
    attribute becomes a list) and only the part with no canonical analogue is lost. A
    **capability limit, never a silent omission**, which is what the ticket's "modelled or
    declared a limit, explicitly" criterion asks the registry to carry.

    Args:
        api: The normalized model.

    Returns:
        One ledger row per declared limit, or an empty list for a DTD that met none.
    """
    return _declared_limit_rows(
        api,
        extras_key=DTD_EXTRAS_KEY,
        location_label="Declaration(s)",
        normalized_noun="declaration",
    )


def _cddl_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the FMT-4.4 CDDL declared limits as document-scoped ledger rows.

    CDDL constructs the canonical model cannot fully hold — a CBOR tag, a major-type
    shorthand, an unwrap, a table entry beside named members, a group choice spliced into a
    larger group, a socket's open-endedness, a parameterised rule, and the control operators
    with no constraint analogue (``.cbor``, ``.cborseq``, ``.bits``, ``.within``, ``.ne``,
    an unmergeable ``.and``) — are stated as ``partially-mapped``: the construct itself is
    normalized (the tagged type exists, the table becomes an open-content member, the plugs
    become union members, the controlled type keeps its type) and only the part with no
    canonical analogue is lost. A **capability limit, never a silent omission**, which is
    what the ticket's "map to canonical constraints where an analogue exists and are
    declared losses where none does" criterion asks the registry to carry.

    Args:
        api: The normalized model.

    Returns:
        One ledger row per declared limit, or an empty list for a grammar that met none.
    """
    return _declared_limit_rows(
        api,
        extras_key=CDDL_EXTRAS_KEY,
        location_label="Rule(s)",
        normalized_noun="rule",
    )


def _arrow_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the FMT-4.5 Arrow declared limits as document-scoped ledger rows.

    Arrow constructs the canonical model cannot fully hold — a dictionary encoding, a
    decimal's precision and scale, an extension type's name, a union's mode and type codes,
    an interval, a half-precision float, the large-offset/view/run-end-encoded layout
    variants, a temporal resolution, and a Flight response's endpoints — are stated as
    ``partially-mapped``: the construct itself is normalized (the dictionary-encoded field
    keeps its value type, the decimal keeps the `decimal` scalar, the union keeps its
    variants) and only the part with no canonical analogue is lost. A **capability limit,
    never a silent omission**, which is what the ticket's "nested, dictionary-encoded and
    decimal types are modelled or declared limits" criterion asks the registry to carry.

    Args:
        api: The normalized model.

    Returns:
        One ledger row per declared limit, or an empty list for a schema that met none.
    """
    return _declared_limit_rows(
        api,
        extras_key=ARROW_EXTRAS_KEY,
        location_label="Field(s)",
        normalized_noun="field",
    )


#: The FMT-8.1 limits whose construct *is* modelled, with only a detail carried in extras —
#: a tuple's per-position types, an index signature beside named properties, an
#: intersection's non-object member. Every other TypeScript limit leaves its declaration or
#: member out of the model, which is a parse limit rather than a partial mapping.
_TYPESCRIPT_PARTIAL_LIMITS = frozenset(
    {"typescript.tuple_positions", "typescript.index_signature", "typescript.intersection"}
)


def _graded_limit_rows(
    api: CanonicalApi, *, format_key: str, extras_key: str, partial: frozenset
) -> List[CoverageEntry]:
    """Render a code-first reader's declared limits, grading each one honestly.

    Unlike the readers that only ever *approximate*, the FMT-8 code-first readers leave things
    out: a construct with no shape (a conditional type, a ``z.function()``) is never widened to
    ``any``, so the declaration or member that needs one is not modelled. Those rows are graded
    ``not-parsed-by-adapter``. The limits whose construct *is* modelled, with only a detail lost
    (``partial``), are ``partially-mapped``, exactly as :func:`_declared_limit_rows` grades every
    other reader's.

    Args:
        api: The normalized model.
        format_key: The canonical format the rows belong to.
        extras_key: The root extras key holding the reader's projection record.
        partial: The limit keys that are partial mappings rather than omissions.

    Returns:
        One ledger row per declared limit, or an empty list for a module that met none.
    """
    report = api.extras.get(extras_key) if isinstance(api.extras, dict) else None
    if not isinstance(report, dict) or api.format != format_key:
        return []
    rows: List[CoverageEntry] = []
    for limit in report.get("capability_limits") or []:
        if not isinstance(limit, dict) or not limit.get("construct"):
            continue
        construct = str(limit.get("construct"))
        coverage = (
            CoverageClass.PARTIALLY_MAPPED
            if construct in partial
            else CoverageClass.NOT_PARSED_BY_ADAPTER
        )
        status, reason = STATUS_FOR_COVERAGE[coverage]
        count = int(limit.get("count") or 1)
        locations = [str(name) for name in (limit.get("locations") or [])]
        where = f" Declaration(s): {', '.join(locations)}." if locations else ""
        consequence = (
            "the declaration itself is normalized"
            if coverage is CoverageClass.PARTIALLY_MAPPED
            else "left out of the model, never widened to `any`"
        )
        rows.append(
            CoverageEntry(
                source_construct=construct,
                coverage=coverage,
                status=status,
                reason=reason,
                detail=f"{limit.get('detail')} ({count} occurrence(s); {consequence}.){where}",
                document_scoped=True,
            )
        )
    return rows


def _typescript_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the FMT-8.1 TypeScript declared limits as document-scoped ledger rows.

    Args:
        api: The normalized model.

    Returns:
        One ledger row per declared limit (see :func:`_graded_limit_rows`).
    """
    return _graded_limit_rows(
        api,
        format_key="typescript-types",
        extras_key=TYPESCRIPT_EXTRAS_KEY,
        partial=_TYPESCRIPT_PARTIAL_LIMITS,
    )


def _zod_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the FMT-8.2 Zod declared limits as document-scoped ledger rows.

    A ``refine``, ``transform``, ``brand``, ``pipe``, ``preprocess`` or coercion keeps the schema
    it wraps, so it is ``partially-mapped``; ``z.custom()``, ``z.function()``, ``z.promise()``
    and the unrepresentable schemas leave their declaration out and are
    ``not-parsed-by-adapter`` — FMT-8.2's "declared limits, not silently dropped".

    Args:
        api: The normalized model.

    Returns:
        One ledger row per declared limit (see :func:`_graded_limit_rows`).
    """
    return _graded_limit_rows(
        api, format_key="zod", extras_key=ZOD_EXTRAS_KEY, partial=ZOD_PARTIAL_LIMITS
    )


def _trpc_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the FMT-8.3 tRPC declared limits as document-scoped ledger rows.

    A hand-written validator keeps its *operation* (only the payload is missing), so it is
    ``partially-mapped``, as are the Zod limits that keep their schema; a lazy router's
    procedures and the shapeless Zod constructs are ``not-parsed-by-adapter``.

    Args:
        api: The normalized model.

    Returns:
        One ledger row per declared limit (see :func:`_graded_limit_rows`).
    """
    return _graded_limit_rows(
        api, format_key="trpc", extras_key=TRPC_EXTRAS_KEY, partial=TRPC_PARTIAL_LIMITS
    )


def _opcua_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the FMT-9.1 OPC UA NodeSet2 declared limits as document-scoped ledger rows.

    Unions, option sets, nested arrays, base structures, data types without a definition and
    unresolved references keep their type or field, so they are ``partially-mapped``; the
    address-space instances the model does not promote are ``not-parsed-by-adapter``.

    Args:
        api: The normalized model.

    Returns:
        One ledger row per declared limit (see :func:`_graded_limit_rows`).
    """
    return _graded_limit_rows(
        api, format_key="opcua-nodeset", extras_key=OPCUA_EXTRAS_KEY, partial=OPCUA_PARTIAL_LIMITS
    )


def _sparkplug_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the FMT-9.2 Sparkplug B declared limits as document-scoped ledger rows.

    An unresolved alias, an inferred or unknown datatype, an unknown message type and an
    unresolved template keep their field or channel, so they are ``partially-mapped``; skipped
    extension fields and a payload's opaque body are ``not-parsed-by-adapter``.

    Args:
        api: The normalized model.

    Returns:
        One ledger row per declared limit (see :func:`_graded_limit_rows`).
    """
    return _graded_limit_rows(
        api, format_key="sparkplug", extras_key=SPARKPLUG_EXTRAS_KEY, partial=SPARKPLUG_PARTIAL_LIMITS
    )


def _ros2_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the FMT-9.3 ROS 2 declared limits as document-scoped ledger rows.

    An unresolved external or sibling reference and a projected ``wstring`` keep their field, so
    every ROS 2 limit is ``partially-mapped``.

    Args:
        api: The normalized model.

    Returns:
        One ledger row per declared limit (see :func:`_graded_limit_rows`).
    """
    return _graded_limit_rows(api, format_key="ros2", extras_key=ROS2_EXTRAS_KEY, partial=ROS2_PARTIAL_LIMITS)


def _hoppscotch_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the FMT-10.1 Hoppscotch declared limits as document-scoped ledger rows.

    A withheld credential keeps its auth scheme and a secret variable keeps its name, so those
    are ``partially-mapped``; a pre-request or test script is not modelled at all.

    Args:
        api: The normalized model.

    Returns:
        One ledger row per declared limit (see :func:`_graded_limit_rows`).
    """
    return _graded_limit_rows(
        api, format_key="hoppscotch", extras_key=HOPPSCOTCH_EXTRAS_KEY, partial=HOPPSCOTCH_PARTIAL_LIMITS
    )


def _thunder_client_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the FMT-10.2 Thunder Client declared limits as document-scoped ledger rows.

    A withheld credential keeps its auth scheme and a secret variable keeps its name, so those
    are ``partially-mapped``; declarative tests and pre-request steps are not modelled at all.

    Args:
        api: The normalized model.

    Returns:
        One ledger row per declared limit (see :func:`_graded_limit_rows`).
    """
    return _graded_limit_rows(
        api, format_key="thunder-client", extras_key=THUNDER_CLIENT_EXTRAS_KEY, partial=THUNDER_CLIENT_PARTIAL_LIMITS
    )


def _soapui_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the FMT-10.3 SoapUI declared limits as document-scoped ledger rows.

    Test cases (kept as declared test intent), withheld credentials, secret properties, saved
    envelopes and operations behind an unfetched WSDL are modelled with a detail withheld, so they
    are ``partially-mapped``; scripts, matrix parameters, mock dispatch, SOAP mock services and
    unsupported interface kinds are not modelled at all.

    Args:
        api: The normalized model.

    Returns:
        One ledger row per declared limit (see :func:`_graded_limit_rows`).
    """
    return _graded_limit_rows(api, format_key="soapui", extras_key=SOAPUI_EXTRAS_KEY, partial=SOAPUI_PARTIAL_LIMITS)


def _linked_data_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the FMT-9.4 SHACL / OWL / JSON-LD declared limits as document-scoped ledger rows.

    A limit whose construct is still a type or field (a complex path, a class expression, an open
    vocabulary) is ``partially-mapped``; one that is not modelled at all (a SPARQL constraint, OWL's
    inferred consequences, instance data beside a context) is ``not-parsed-by-adapter``.

    Args:
        api: The normalized model.

    Returns:
        One ledger row per declared limit (see :func:`_graded_limit_rows`); empty for any other format.
    """
    for format_key, extras_key, partial in (
        ("shacl", SHACL_EXTRAS_KEY, SHACL_PARTIAL_LIMITS),
        ("owl", OWL_EXTRAS_KEY, OWL_PARTIAL_LIMITS),
        ("jsonld", JSONLD_EXTRAS_KEY, JSONLD_PARTIAL_LIMITS),
    ):
        if api.format == format_key:
            return _graded_limit_rows(api, format_key=format_key, extras_key=extras_key, partial=partial)
    return []


def _device_model_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the FMT-9.5 LwM2M and Matter declared limits as document-scoped ledger rows.

    Every limit of both readers keeps its construct (an object link, an unresolved type or cluster,
    a bitmap, a feature's conformance) with only a detail lost, so every row is ``partially-mapped``.

    Args:
        api: The normalized model.

    Returns:
        One ledger row per declared limit (see :func:`_graded_limit_rows`).
    """
    return _graded_limit_rows(
        api, format_key="lwm2m", extras_key=LWM2M_EXTRAS_KEY, partial=LWM2M_PARTIAL_LIMITS
    ) + _graded_limit_rows(api, format_key="matter", extras_key=MATTER_EXTRAS_KEY, partial=MATTER_PARTIAL_LIMITS)


def _mainframe_misc_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the FMT-11.3 VSAM / CICS BMS declared limits as document-scoped ledger rows.

    A record without its field layout, an edited picture, a repeated field and a symbolic-map
    mismatch keep their construct (``partially-mapped``); a LINEAR cluster, a GDG, a utility
    command, a LISTCAT statistics section and a screen literal are not modelled.

    Args:
        api: The normalized model.

    Returns:
        One ledger row per declared limit of whichever sub-format ``api`` is.
    """
    return _graded_limit_rows(
        api, format_key="vsam-idcams", extras_key=VSAM_EXTRAS_KEY, partial=VSAM_PARTIAL_LIMITS
    ) + _graded_limit_rows(api, format_key="cics-bms", extras_key=BMS_EXTRAS_KEY, partial=BMS_PARTIAL_LIMITS)


def _pli_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the FMT-11.1 PL/I declared limits as document-scoped ledger rows.

    An unresolved include, a UNION, a runtime extent, defaulted attributes, an edited picture, a
    locator or program-control item and an unread attribute keep their item (``partially-mapped``);
    a scalar declaration, a non-declaration statement and an unreferenced member are not modelled.

    Args:
        api: The normalized model.

    Returns:
        One ledger row per declared limit (see :func:`_graded_limit_rows`).
    """
    return _graded_limit_rows(api, format_key="pli", extras_key=PLI_EXTRAS_KEY, partial=PLI_PARTIAL_LIMITS)


def _pydantic_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the FMT-8.4 Pydantic declared limits as document-scoped ledger rows.

    Validators, class hooks, decimal precision and tuple positions keep their model or field, so
    they are ``partially-mapped``; dynamically built models, computed fields and annotations the
    static reader cannot resolve are ``not-parsed-by-adapter``.

    Args:
        api: The normalized model.

    Returns:
        One ledger row per declared limit (see :func:`_graded_limit_rows`).
    """
    return _graded_limit_rows(
        api, format_key="pydantic", extras_key=PYDANTIC_EXTRAS_KEY, partial=PYDANTIC_PARTIAL_LIMITS
    )


def _typed_config_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the FMT-8.5 CUE / Pkl / Dhall declared limits as document-scoped ledger rows.

    A constraint, default or detail the language states and JSON Schema cannot keeps its field
    or definition, so it is ``partially-mapped``; a computed field, a function or anything else
    left out of the model is ``not-parsed-by-adapter``.

    Args:
        api: The normalized model.

    Returns:
        One ledger row per declared limit (see :func:`_graded_limit_rows`).
    """
    partial_by_format = {
        CUE_FORMAT: CUE_PARTIAL_LIMITS,
        PKL_FORMAT: PKL_PARTIAL_LIMITS,
        DHALL_FORMAT: DHALL_PARTIAL_LIMITS,
    }
    partial = partial_by_format.get(api.format)
    if partial is None:
        return []
    return _graded_limit_rows(api, format_key=api.format, extras_key=api.format, partial=partial)


def _odcs_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the FMT-5.1 ODCS declared limits as document-scoped ledger rows.

    A data contract's *governance* half — quality rules, ``team``/``roles`` ownership,
    ``slaProperties``, ``servers``, ``support``, ``price``, ``tags``,
    ``customProperties``, ``authoritativeDefinitions`` — plus the per-field declarations
    the canonical model has no facet for (``physicalType``, ``primaryKey``/``unique``,
    ``partitioned``, ``classification``, the transform/lineage block) are stated as
    ``partially-mapped``: every one of them is carried verbatim under the documented
    ``odcs_*`` extras namespace, on the node that declared it, and only the ability of a
    canonical *feature* to read it is lost. A **capability limit, never a silent
    omission**, which is what the ticket's "the capability registry declares what is
    modelled and what is carried-but-not-modelled" criterion asks the registry to carry.

    Args:
        api: The normalized model.

    Returns:
        One ledger row per declared limit, or an empty list for a contract that met none.
    """
    return _declared_limit_rows(
        api,
        extras_key=ODCS_EXTRAS_KEY,
        location_label="Schema object(s)",
        normalized_noun="declaration",
    )


def _dbt_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the FMT-5.4 dbt declared limits as document-scoped ledger rows.

    Everything a dbt project states that the canonical model has no facet for — the data
    tests with no analogue, `unique` identity, `ref()` lineage, build configuration,
    warehouse type parameters, freshness windows, `meta`, `tags`, model versions,
    exposures, metrics, the semantic layer's aggregation vocabulary and a manifest's build
    graph — is stated as ``partially-mapped``: the resource and its columns *are*
    normalized, and only the part with no canonical analogue moves to extras. Data tests
    land in the shared quality namespace FMT-5.1 defined, which is what makes a dbt project
    and an ODCS contract describing the same table comparable on this ledger.

    Args:
        api: The normalized model.

    Returns:
        One ledger row per declared limit, or an empty list for a project that met none.
    """
    return _declared_limit_rows(
        api,
        extras_key=DBT_EXTRAS_KEY,
        location_label="Resource(s)",
        normalized_noun="resource",
    )


def _sql_ddl_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the FMT-5.6 SQL DDL declared limits as document-scoped ledger rows.

    Everything a DDL script states that the canonical model has no facet for — `CHECK`
    predicates, identity declarations, computed columns, indexes, partitioning, storage
    clauses, inheritance links, sequences, collations, type parameters beyond a character
    length, and the statements this reader does not model — is stated as
    ``partially-mapped``: the relation and its columns *are* normalized, and only the part
    with no canonical analogue moves to extras. A foreign key appears here for the same
    reason it does for dbt — the canonical model has no edge vocabulary — even though the
    edge itself is fully resolved and refused when it dangles.

    Args:
        api: The normalized model.

    Returns:
        One ledger row per declared limit, or an empty list for a script that met none.
    """
    return _declared_limit_rows(
        api,
        extras_key=SQL_DDL_EXTRAS_KEY,
        location_label="Relation(s)",
        normalized_noun="relation",
    )


def _kafka_connect_capability_rows(api: CanonicalApi) -> List[CoverageEntry]:
    """Render the FMT-5.3 Kafka Connect declared limits as document-scoped ledger rows.

    A Connect schema's undecoded semantics — a logical type this reader does not know, a
    schema's free-form ``parameters``, the registry ``version``, a ``Decimal``'s digits,
    an anonymous struct's derived identity, an enveloped sample record and a connector
    configuration — are stated as ``partially-mapped``: every one of them is carried
    verbatim under the documented ``connect_*`` extras namespace, on the node that
    declared it, and only the ability of a canonical *feature* to act on it is lost. A
    **capability limit, never a silent omission**, which is what the ticket's "logical
    types map to canonical formats and constraints, not to opaque strings" criterion
    needs the registry to be honest about at the edges of that mapping.

    Args:
        api: The normalized model.

    Returns:
        One ledger row per declared limit, or an empty list for a schema that met none.
    """
    return _declared_limit_rows(
        api,
        extras_key=KAFKA_CONNECT_EXTRAS_KEY,
        location_label="Struct(s)",
        normalized_noun="declaration",
    )


def _sort_graph(
    nodes: List[ProjectionNode], edges: List[ProjectionEdge]
) -> Tuple[List[ProjectionNode], List[ProjectionEdge]]:
    """Order nodes/edges exactly as :class:`~app.export_projection.ProjectionManifest` does."""
    kind_order = {
        ProjectionNodeKind.NATIVE: 0,
        ProjectionNodeKind.CANONICAL: 1,
        ProjectionNodeKind.TARGET: 2,
    }
    return (
        sorted(nodes, key=lambda n: (kind_order[n.kind], n.id)),
        sorted(edges, key=lambda e: e.id),
    )


def _manifest_hash(
    *,
    adapter_key: str,
    options: Dict[str, Any],
    nodes: List[ProjectionNode],
    edges: List[ProjectionEdge],
    coverage: List[CoverageEntry],
) -> str:
    """Stable content hash over the full manifest's identity-bearing content.

    Mirrors the export manifest's hash recipe: adapter + version provenance + normalized
    options folded into a digest over the deterministically ordered graph and ledger, so
    an adapter (package) upgrade or an option change is a different snapshot while a
    fixed input yields an identical hash.
    """
    payload = {
        "adapter_key": adapter_key,
        "apiome_version": APIOME_VERSION,
        "options": options,
        "nodes": [node.model_dump(mode="json") for node in nodes],
        "edges": [edge.model_dump(mode="json") for edge in edges],
        "coverage": [entry.model_dump(mode="json") for entry in coverage],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_import_preview_manifest(
    api: CanonicalApi,
    *,
    adapter_key: str,
    options: Optional[Dict[str, Any]] = None,
) -> _FullManifest:
    """Build the complete (unpaginated) import preview manifest for one model.

    Pure and deterministic: no I/O, no clock. Everything is derived from the canonical
    model (whose declaration order is deterministic for a fixed input), the adapter's
    registry metadata, and the request options, so a fixed (input, adapter version,
    options) triple yields a byte-stable manifest and hash.

    Args:
        api: The normalized canonical model the pre-flight pipeline produced.
        adapter_key: Registry key of the adapter that produced it.
        options: The request options that shaped the run (source kind, import target,
            archive root) — folded into the manifest hash.

    Returns:
        The internal full-manifest form; paginate with
        :func:`paginate_import_preview_manifest`.
    """
    load_builtin_import_sources()
    adapter = get_import_source(adapter_key)
    capability = CapabilityReference.from_capability(capability_for_format(api.format))
    parser_limits = KNOWN_PARSER_LIMITS.get(adapter_key, ())

    adapter_ref = ImportAdapterReference(
        adapter_key=adapter_key,
        adapter_label=adapter.label if adapter is not None else adapter_key,
        paradigm=api.paradigm.value,
        formats=list(adapter.formats) if adapter is not None else [],
        apiome_version=APIOME_VERSION,
        capability=capability,
        parser_limits=[limit.construct for limit in parser_limits],
    )

    entity_rows: List[_EntityRows] = []
    order = 0

    def _add(**kwargs: Any) -> None:
        nonlocal order
        entity_rows.append(_entity_rows(order=order, **kwargs))
        order += 1

    for service in api.services:
        _add(
            key=service.key,
            name=service.name,
            entity_kind="service",
            extras=service.extras,
            description=service.description,
            deprecated=False,
            parent_key=None,
        )
        for operation in service.operations:
            _add(
                key=operation.key,
                name=operation.name,
                entity_kind="operation",
                extras=operation.extras,
                description=operation.description,
                deprecated=operation.deprecated,
                parent_key=service.key,
            )
    for channel in api.channels:
        _add(
            key=channel.key,
            name=channel.name or channel.address,
            entity_kind="channel",
            extras=channel.extras,
            description=channel.description,
            deprecated=False,
            parent_key=None,
        )
    for type_ in api.types:
        _add(
            key=type_.key,
            name=type_.name,
            entity_kind="type",
            extras=type_.extras,
            description=type_.description,
            deprecated=type_.deprecated,
            parent_key=None,
        )

    document_nodes, document_edges, document_coverage = _document_scope_rows(
        api, capability, parser_limits
    )

    counts = ImportPreflightCounts(
        services=len(api.services),
        operations=sum(len(service.operations) for service in api.services),
        types=len(api.types),
        channels=len(api.channels),
    )

    coverage_counts = {coverage.value: 0 for coverage in CoverageClass}
    status_counts = {status.value: 0 for status in ProjectionStatus}
    reason_counts = {reason.value: 0 for reason in ProjectionReason}
    all_ledger = [rows.coverage for rows in entity_rows] + document_coverage
    for entry in all_ledger:
        coverage_counts[entry.coverage.value] += 1
        status_counts[entry.status.value] += 1
        if entry.reason is not None:
            reason_counts[entry.reason.value] += 1

    all_nodes = [node for rows in entity_rows for node in rows.nodes] + document_nodes
    all_edges = [edge for rows in entity_rows for edge in rows.edges] + document_edges
    sorted_nodes, sorted_edges = _sort_graph(all_nodes, all_edges)

    manifest_hash = _manifest_hash(
        adapter_key=adapter_key,
        options=dict(sorted((options or {}).items())),
        nodes=sorted_nodes,
        edges=sorted_edges,
        coverage=all_ledger,
    )

    return _FullManifest(
        model=api,
        manifest_hash=manifest_hash,
        adapter=adapter_ref,
        counts=counts,
        coverage_counts=coverage_counts,
        status_counts=status_counts,
        reason_counts=reason_counts,
        entity_rows=entity_rows,
        document_nodes=document_nodes,
        document_edges=document_edges,
        document_coverage=document_coverage,
    )


def paginate_import_preview_manifest(
    full: _FullManifest,
    *,
    cursor: Optional[str] = None,
    page_size: int = DEFAULT_ENTITY_PAGE_SIZE,
) -> ImportPreviewManifest:
    """Slice one deterministic entity page out of a full manifest.

    Pages over the entity list in tree order; each page carries the graph and ledger
    rows for exactly its entities. Document-scope rows (root-level constructs and the
    adapter's declared parser limits) ride on the **first** page only, so a client that
    walks every page sees every row exactly once.

    Args:
        full: The full manifest from :func:`build_import_preview_manifest`.
        cursor: Opaque cursor from a previous page, or ``None`` for the first page.
        page_size: Maximum entities per page (clamped to ``[1, MAX_ENTITY_PAGE_SIZE]``).

    Returns:
        The page as the wire :class:`ImportPreviewManifest`.

    Raises:
        ValueError: When ``cursor`` is malformed.
    """
    limit = max(1, min(int(page_size), MAX_ENTITY_PAGE_SIZE))
    start = decode_page_cursor(cursor) if cursor else 0
    page_rows = full.entity_rows[start : start + limit]

    nodes = [node for rows in page_rows for node in rows.nodes]
    edges = [edge for rows in page_rows for edge in rows.edges]
    coverage = [rows.coverage for rows in page_rows]
    if start == 0:
        nodes += full.document_nodes
        edges += full.document_edges
        coverage += full.document_coverage
    nodes, edges = _sort_graph(nodes, edges)

    next_start = start + limit
    next_cursor = encode_page_cursor(next_start) if next_start < full.total_entities else None

    return ImportPreviewManifest(
        manifest_hash=full.manifest_hash,
        adapter=full.adapter,
        counts=full.counts,
        coverage_counts=dict(full.coverage_counts),
        status_counts=dict(full.status_counts),
        reason_counts=dict(full.reason_counts),
        entities=[rows.entity for rows in page_rows],
        total_entities=full.total_entities,
        nodes=nodes,
        edges=edges,
        coverage=coverage,
        total_coverage_entries=full.total_coverage_entries,
        page_size=limit,
        next_cursor=next_cursor,
        truncated=next_cursor is not None or start > 0,
    )


# ===========================================================================
# Re-import delta build (IXH-3.4)
# ===========================================================================


def _load_reimport_target(tenant_id: str, project_slug: str) -> Optional[Dict[str, Any]]:
    """Resolve the existing catalog item a commit under ``project_slug`` would reuse.

    Mirrors the commit's own resolution (:func:`app.import_source_pipeline
    ._resolve_import_project`): the slug is normalized the same way and matched against
    the tenant's projects; only a live **non-publishable** row (a catalog item, MFI-23.1)
    counts — a publishable Project under the slug means the commit would allocate a fresh
    item, i.e. a first-time import.

    Module-level and synchronous (the psycopg driver is synchronous, matching the policy
    lookup already on this path) so tests can monkeypatch it with a fabricated item row.

    Args:
        tenant_id: The tenant the lookup is scoped to.
        project_slug: The client-computed slug the commit would use.

    Returns:
        The catalog item row (with its latest revision's ``format_metadata``), or
        ``None`` when no existing catalog item lives under the slug.
    """
    from .database import db

    slug = _normalize_import_project_slug(project_slug, project_slug)
    if not slug:
        return None
    try:
        existing = db.get_project_by_slug(slug, tenant_id)
        if not existing or existing.get("publishable"):
            return None
        item = db.get_catalog_item_by_id(str(existing["id"]), tenant_id)
        if item is None:
            return None
        # Attach the current revision's record id (best-effort provenance) so the delta
        # builder stays free of DB access.
        item = dict(item)
        item.setdefault(
            "version_record_id",
            db.get_latest_revision_id_for_project(str(existing["id"]), tenant_id),
        )
        return item
    except Exception:  # pragma: no cover - degrade on DB faults, never fail the preview
        logger.exception("re-import target lookup failed for slug %r", project_slug)
        return None


def build_reimport_delta(
    candidate: CanonicalApi,
    item: Dict[str, Any],
) -> Optional[ImportReimportDelta]:
    """Compute what re-importing ``candidate`` would change on catalog item ``item``.

    The current revision's canonical model is re-parsed from the item's stored source
    exactly as the convert flow does (:func:`app.catalog_conversion
    .build_conversion_source`), then diffed against the candidate **by stable canonical
    key** (:func:`app.import_source.canonical_diff`) — never from raw text, so a
    re-ordered but structurally identical source is a no-op. Where the format's
    breaking-change classifier grades the same keys
    (:func:`app.breaking_change.classify_models`), the grades are joined onto the
    entries; a failed or unavailable classification leaves every entry ungraded and
    ``classifier`` null — stated, not implied safe.

    Reads nothing but ``item`` and writes nothing.

    Args:
        candidate: The candidate document's normalized canonical model.
        item: The existing catalog item row (from :func:`_load_reimport_target`).

    Returns:
        The delta, or ``None`` when the item's current source cannot be reconstructed
        (nothing honest to diff against — the panel is skipped).
    """
    from .catalog_conversion import ConversionError, build_conversion_source

    try:
        source = build_conversion_source(item, source_version_id=item.get("version_record_id"))
    except ConversionError:
        return None
    current = source.api

    candidate_fp = canonical_fingerprint(candidate)
    current_fp = canonical_fingerprint(current)
    diff_result = canonical_diff(current, candidate)

    # Best-effort breaking-change annotation: join the classifier's per-change grades
    # onto the canonical entries by (change kind, stable key). `modified` is the
    # classifier vocabulary's word for `changed`; unjoined entries stay ungraded.
    classifier_id: Optional[str] = None
    overall_severity: Optional[str] = None
    severity_counts: Dict[str, int] = {}
    grades: Dict[Tuple[str, str], Any] = {}
    try:
        classification = classify_models(current, candidate)
        classifier_id = classification.classifier
        overall_severity = classification.overall_severity.value
        severity_counts = dict(classification.counts_by_severity)
        for grade in classification.classifications:
            kind = "changed" if grade.kind.value == "modified" else grade.kind.value
            grades.setdefault((kind, grade.key), grade)
    except Exception:  # pragma: no cover - a classifier fault must not lose the delta
        logger.exception("breaking-change classification failed for re-import delta")

    entries: List[ReimportDeltaEntry] = []
    counts = {kind.value: 0 for kind in DiffChangeKind}
    counts_by_entity: Dict[str, Dict[str, int]] = {}
    for entry in diff_result.entries:
        counts[entry.change.value] += 1
        family = counts_by_entity.setdefault(entry.entity, {})
        family[entry.change.value] = family.get(entry.change.value, 0) + 1
        grade = grades.get((entry.change.value, entry.key))
        entries.append(
            ReimportDeltaEntry(
                entity=entry.entity,
                key=entry.key,
                change=entry.change,
                severity=grade.severity.value if grade is not None else None,
                rule_id=grade.rule_id if grade is not None else None,
                rationale=grade.rationale if grade is not None else None,
            )
        )

    return ImportReimportDelta(
        target_item_id=str(item.get("id") or ""),
        target_item_name=item.get("name"),
        target_item_slug=str(item.get("slug") or ""),
        current_version_record_id=(
            str(source.source_version_id) if source.source_version_id else None
        ),
        noop=candidate_fp == current_fp,
        candidate_fingerprint=candidate_fp,
        current_fingerprint=current_fp,
        entries=entries,
        counts=counts,
        counts_by_entity=counts_by_entity,
        classifier=classifier_id,
        classifier_format_pack=get_breaking_change_classifier(candidate.format) is not None,
        overall_severity=overall_severity,
        severity_counts=severity_counts,
    )


# ===========================================================================
# Cache + orchestration
# ===========================================================================

#: Per-process cache of full manifests keyed by (tenant, content hash, adapter, target,
#: archive root) — the same identity the pre-flight report cache keys on. A manifest
#: depends only on the model and adapter (not on the tenant's style guide or policy), so
#: no fingerprint re-validation is needed; the bound keeps large graphs from pinning
#: memory. Paging a big document therefore re-runs nothing.
_manifest_cache: "OrderedDict[str, _FullManifest]" = OrderedDict()


def clear_preview_manifest_cache() -> None:
    """Drop every cached full manifest (tests and process-level reloads)."""
    _manifest_cache.clear()


def preview_manifest_cache_size() -> int:
    """Return how many full manifests are currently cached in this process."""
    return len(_manifest_cache)


def _manifest_cache_key(tenant_id: str, content_hash: str, request: ImportPreflightRequest) -> str:
    """The manifest cache key — everything that can change the built manifest."""
    return "|".join(
        (
            tenant_id,
            content_hash,
            (request.source_kind or "").strip().lower() or "auto",
            request.import_target or "",
            (request.archive_root or "").strip(),
        )
    )


def _manifest_cache_store(key: str, full: _FullManifest) -> None:
    """Insert a full manifest, evicting the least recently used when over the bound."""
    _manifest_cache[key] = full
    _manifest_cache.move_to_end(key)
    while len(_manifest_cache) > PREVIEW_MANIFEST_CACHE_MAX_ENTRIES:
        _manifest_cache.popitem(last=False)


def _request_options(request: ImportPreviewManifestRequest) -> Dict[str, Any]:
    """The request options that shape the manifest, normalized for the hash."""
    options: Dict[str, Any] = {}
    if request.source_kind:
        options["source_kind"] = request.source_kind.strip().lower()
    if request.import_target:
        options["import_target"] = request.import_target
    if request.archive_root and request.archive_root.strip():
        options["archive_root"] = request.archive_root.strip()
    return options


async def run_import_preview_manifest(
    request: ImportPreviewManifestRequest,
    *,
    tenant_id: str,
    tenant_slug: str,
    user_id: Optional[str] = None,
) -> ImportPreviewManifestResponse:
    """Produce the preview manifest for one candidate document (IXH-3.1).

    Runs the IXH-2.1 pre-flight (the one import code path, dry-run semantics, nothing
    persisted) with an artifacts collector, builds the full manifest from the collected
    canonical model, caches it per content hash, and returns the requested page
    alongside the full pre-flight report. A repeat request for another page is served
    from the manifest cache without re-running the pipeline.

    Args:
        request: The candidate document, its intake hints, and the page window.
        tenant_id: The tenant the run is scoped to (cache key + style guide + policy).
        tenant_slug: The tenant's slug, recorded on the pipeline payload.
        user_id: The requesting user (provenance only; nothing is written).

    Returns:
        The response; ``manifest`` is null when the candidate is not importable.

    Raises:
        ValueError: When the request's ``cursor`` is malformed.
    """
    content_hash = ""
    try:
        raw = base64.standard_b64decode(request.document_base64)
        content_hash = hashlib.sha256(raw).hexdigest()
    except (binascii.Error, ValueError):
        # Invalid base64 — the pre-flight reports the taxonomy error itself; the manifest
        # simply has nothing to cache under.
        pass

    cache_key = _manifest_cache_key(tenant_id, content_hash, request)
    cached = _manifest_cache.get(cache_key) if content_hash else None

    # The pre-flight request must not carry the pagination or re-import fields (its
    # model forbids extras and its cache key must match a plain pre-flight of the same
    # bytes).
    preflight_request = ImportPreflightRequest(
        **request.model_dump(exclude={"cursor", "page_size", "project_slug"}, exclude_none=True)
    )

    if cached is not None:
        _manifest_cache.move_to_end(cache_key)
        report = await run_import_preflight(
            preflight_request,
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            user_id=user_id,
        )
        full = cached
    else:
        artifacts = ImportRunArtifacts()
        report = await run_import_preflight(
            preflight_request,
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            user_id=user_id,
            artifacts=artifacts,
        )
        if not report.ok or artifacts.model is None or artifacts.adapter_key is None:
            return ImportPreviewManifestResponse(ok=report.ok, preflight=report, manifest=None)
        full = build_import_preview_manifest(
            artifacts.model,
            adapter_key=artifacts.adapter_key,
            options=_request_options(request),
        )
        if content_hash:
            _manifest_cache_store(cache_key, full)

    if not report.ok:
        return ImportPreviewManifestResponse(ok=False, preflight=report, manifest=None)

    page = paginate_import_preview_manifest(
        full, cursor=request.cursor, page_size=request.page_size
    )

    # IXH-3.4: the re-import delta, per request and never cached — the target item's
    # current revision can move between requests, and the manifest hash must stay a
    # function of the candidate alone. Only a commit that would land in an existing
    # catalog item has a delta: the request names the slug the commit will use, and the
    # routing decision must be the non-publishable (catalog) direction.
    reimport: Optional[ImportReimportDelta] = None
    routing = report.routing or {}
    if request.project_slug and routing.get("publishable") is False:
        item = _load_reimport_target(tenant_id, request.project_slug)
        if item is not None:
            reimport = build_reimport_delta(full.model, item)

    return ImportPreviewManifestResponse(
        ok=True, preflight=report, manifest=page, reimport=reimport
    )
