# Changelog

All notable changes to the Apiome REST API will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.413.0] - 2026-10-21

### Added
- **FIX Orchestra import (#5453, FMT-6.9)**: the declared FIX schema, where the `fix` adapter infers one from
  `tag=value` messages.
  - The new **`fix-orchestra`** import source (formats `fix-orchestra` / `orchestra` / `fixr`; `.xml`; file / URL /
    paste / fileset) claims a `repository` root in `http://fixprotocol.io/2020/orchestra/repository` (or the 2016
    FIX Repository draft namespace). `app/fix_orchestra_parser.py` reads `datatypes`, `codeSets`, `fields`,
    `components`, `groups` (with `numInGroup`), `messages` with their `structure`, scenarios and `responses`, and
    `actors` / `flow` / `states` state machines. Entities are keyed by `(id, scenario)`; a ref falls back to the
    `base` scenario.
  - `app/fix_orchestra_normalizer.py`: each message (each scenario) is a record type with its `msgType`, flow and
    responses in `extras`; code sets are enums; components are records; groups are records used as lists with
    `minItems: 1`; a field's datatype resolves through declared `baseType` chains to a primitive (timestamps carry
    `date-time` / `date` / `time`). `presence` maps to optionality and constraints — `required` and `constant`
    non-nullable (`constant` pinned by `enum: [value]` and its default); `conditional`, `forbidden` and `ignored`
    recorded as `constraints.extras.fix_presence`, with every `rule` (`when` / `assign`) in `fix_rules`. A
    `forbidden` field is a declared constraint, never dropped. Actors, flows, state machines and datatypes are in
    the model `extras`; Dublin Core metadata stays in `raw`, outside the fingerprint.
  - **XInclude inside a fileset.** `app/secure_xml.parse_xml` gains `allow_xinclude` (default off, so every other
    adapter still refuses the directive); the Orchestra parser resolves each `xi:include` only against the
    uploaded fileset's members, refusing cycles and text includes. A single file that uses one is
    `INPUT_REFERENCE_UNRESOLVED`.
  - **Linking to `fix` items.** The import records `format_metadata.fixMsgTypes` for both `fix` and `fix-orchestra`
    items (`app/import_source_pipeline.fix_msg_types_metadata`), and
    `GET /v1/identity/{tenant_slug}/projects/{project_id}/suggestions` ranks a shared FIX message type
    (reason `shared FIX message type(s) …`). Suggestions still never auto-link.
  - Refusals: truncated XML `INPUT_TRUNCATED`; ill-formed XML `INPUT_MALFORMED`; no messages, a missing `id` /
    `name`, a duplicate entity in one scenario, or an unknown `presence` `INPUT_SEMANTIC_INVALID`; a ref, a
    `numInGroup` or an include that does not resolve `INPUT_REFERENCE_UNRESOLVED`; a non-Orchestra document
    `FORMAT_MISMATCH`; encoding faults are left code-less.
  - Version coverage for `fix-orchestra`; `fix-orchestra` is a schema-only format. The `fix-orchestra/` corpus is
    activated with goldens and a matrix row (45 known-failing cells recorded); `fix/02-orchestra.xml` now imports
    with this adapter (its known detection and import bugs are retired), and `fix/06-composition-allocation-instruction.fix`
    gives the `fix` adapter its composition rung.
  - The round trip against the Orchestra emitter (#4323) is asserted once that emitter ships.

## [1.412.0] - 2026-10-20

### Added
- **NCPDP SCRIPT and Telecom import (#5452, FMT-6.8)**: US pharmacy messaging — e-prescribing and pharmacy claims.
  - The new **`ncpdp`** import source (formats `ncpdp` / `ncpdp-script` / `ncpdp-telecom`; `.xml` / `.dat` /
    `.ncpdp`; file / URL / paste / fileset) reads two sub-formats, told apart by how they open
    (`app/ncpdp_parser.py`): SCRIPT XML (`app/ncpdp_script.py`) — a `Message` or `Messages` root in the
    `http://www.ncpdp.org/schema/SCRIPT` namespace — and Telecommunication D.0 request transmissions
    (`app/ncpdp_telecom.py`) — the 56-character fixed transaction header and `AM` segments of two-character fields.
  - **Transaction type detected and recorded.** A SCRIPT message's transaction is its `Body`'s one child (`NewRx`,
    `RxFill`, `RxChangeRequest`, `CancelRx`, `Status`, `Error`…), detected per message; an unrecognised name is read
    and stated (`ncpdp.transaction_not_recognized`). A Telecom transmission's transaction code (`B1` billing, `B2`
    reversal…) is read from its header. Both are recorded in `ncpdp_transactions` / `ncpdp_transaction_types`, and
    the sub-format is lifted into provenance as `format_metadata.formatProfile` (`ncpdp-script` / `ncpdp-telecom`).
  - `app/ncpdp_normalizer.py`: SCRIPT imports as one record type per element name inferred across every message
    (attributes, repeats and optionality included); Telecom as `TelecomTransmission` → `Transaction` → one record
    per segment id with a field per field id (described by its data element where a short label table knows it),
    plus a positional `TransactionHeader`. No payload value enters the model.
  - `app/ncpdp_analysis.py` (analyzer `ncpdp@1.0.0`) builds on the shared EDI analysis base: the Telecom header's
    transaction count is recorded as declared versus observed (compared for B1/B2/B3,
    `ncpdp.transaction_count_mismatch` info warning), segments carry byte offsets, values follow the
    value-visibility policy, and `implementation_guide_statement` names the guides not consulted.
  - A SCRIPT fileset is read as one conversation (root plus its SCRIPT siblings); `relatesToResolved` records
    whether a response's `RelatesToMessageID` names a message in the upload.
  - Refusals: XML or Telecom header cut short `INPUT_TRUNCATED`; ill-formed XML, a segment without its `AM` id, a
    field without a two-character id or a line break in a transmission `INPUT_MALFORMED`; an empty `Body`, a `Body`
    with several transactions, a missing `Header`/`Body`, a Telecom version other than `D0`, an unknown transaction
    code or a header with no segments `INPUT_SEMANTIC_INVALID`; anything else `FORMAT_MISMATCH`; encoding faults
    are left code-less.
  - Capability registry `ncpdp` seed (registry version `22`) naming the supported versions (any SCRIPT version,
    recorded; Telecom D.0 only, checked) and stating no implementation guide was consulted; version coverage for
    `ncpdp`; the `ncpdp/` corpus is activated with canonical, analysis and conversion goldens and a matrix row.
    Corpus fixture `ncpdp/05-real-world-telecom-b1-claim.dat` lost a stray field between its header and first
    segment.

## [1.411.0] - 2026-10-20

### Added
- **DICOM SOP class and Structured Report import (#5451, FMT-6.7)**: the imaging half of healthcare, metadata
  layer only.
  - The new **`dicom`** import source (formats `dicom` / `dcm` / `dicom-json`; `.dcm` / `.dicom` / `.dic` / `.json`;
    file / URL / paste / fileset). `app/dicom_part10.py` reads a Part 10 file through the binary intake SPI — the
    preamble and `DICM` magic, the file meta group, then the dataset in implicit or explicit VR little endian,
    explicit VR big endian, deflated explicit VR little endian or any encapsulated transfer syntax; defined- and
    undefined-length sequences and items, and undefined-length `UN` read as an implicit-VR sequence.
    `app/dicom_json.py` reads the DICOM JSON model (PS3.18 Annex F), one dataset or an array; an archive of DICOM
    JSON documents is read root first (`app/dicom_parser.py`).
  - **Pixel data is never read, stored or analysed.** Pixel Data, Float / Double Float Pixel Data and Overlay Data
    values are stepped over by their declared length (or their fragment item headers) without being sliced or
    decoded, and recorded as a skip — tag, VR, length, fragments — on the model (`dicom_pixel_data`), as a
    `pixel-data` analysis node (`read: false`) and as an info warning (`dicom.pixel_data_not_read`). A DICOM JSON
    `BulkDataURI` is not followed and an `InlineBinary` is not decoded. The analysis `sourceHash` is taken over the
    file with every pixel-data value excised.
  - `app/dicom_normalizer.py` models one record type per SOP class (or per query level for a query result), one
    field per attribute keyed by its tag and typed by its VR (aliases over string / integer / number with the VR's
    maximum length; `PN` a record of its component groups), lists where the VM allows several values, one nested
    record type per sequence tag folded across items, and a `FileMetaInformation` type. A Structured Report's
    content tree is recorded as a hierarchy in `dicom_sr_content_trees` (value type, relationship type, concept
    name — never a content value). No attribute value enters the model; fields mark PS3.15 Annex E and private
    attributes `dicom_patient_identifying`.
  - `app/dicom_analysis.py` (analyzer `dicom@1.0.0`) describes every element with its tag, VR, VM and byte offset;
    values follow the value-visibility policy, so the default stores none.
  - `app/dicom_dictionary.py` uses `pydicom` (new dependency, `>=3.0.0`) for the PS3.6 data dictionary and UID
    registry only.
  - Refusals: a file that stops inside an element `INPUT_TRUNCATED`; an unknown VR, a value overrunning its item or
    a broken DICOM JSON attribute `INPUT_MALFORMED`; no `DICM` magic, no Transfer Syntax UID, or a dataset with no
    SOP Class UID that is not a query result `INPUT_SEMANTIC_INVALID`; JSON with no DICOM attribute
    `FORMAT_MISMATCH`; nesting, inflation and element-count bounds `INPUT_DEPTH_LIMIT` / `INPUT_EXPANSION_LIMIT` /
    `INPUT_TOO_LARGE`; JSON syntax and encoding faults are left code-less.
  - Capability registry `dicom` seed (registry version `21`) stating the pixel-data boundary and value policy, and
    version coverage for `dicom`; the `dicom/` corpus is activated with canonical and analysis goldens and a matrix
    row.

### Changed
- **A normalizer can ask for the verbatim upload not to be stored.** Canonical extras
  `source_retention: {"verbatim": false, "reason": ...}` make the import persist `format_metadata.sourceContent` as
  `null` with `sourceWithheld: <reason>` (`import_source_pipeline.source_retention_withheld`). DICOM uses it
  (`dicom-patient-and-pixel-data`). Converting a catalog item whose source was withheld now explains why there is
  nothing to convert instead of asking for a re-import.

## [1.410.0] - 2026-10-20

### Added
- **NACHA ACH and SEPA payment-file import (#5450, FMT-6.6)**: the US and EU payment-batch formats.
  - The new **`nacha`** import source (formats `nacha` / `ach`; `.ach` / `.nacha` / `.txt`; file / URL / paste /
    fileset). `app/nacha_records.py` holds the record-type-driven field maps (file header `1`, batch header `5`,
    entry detail `6`, addenda `7` types 05 / 98 / 99 with a whole-content fallback, batch control `8`, file control
    `9`), positions as the Operating Rules print them. `app/nacha_parser.py` reads one 94-character record per line
    (or an unbroken line cut into records) into file → batch → entry → addenda. Refusals: no ACH file header
    `FORMAT_MISMATCH`, a record that is not 94 characters or has an unknown type `INPUT_MALFORMED` (a short last
    record before the file control, or EOF inside a batch / before the file control, `INPUT_TRUNCATED`), a batch
    with no entries, an orphan addenda, records out of order or content after the file control
    `INPUT_SEMANTIC_INVALID`; encoding faults are left code-less.
  - Declared versus observed control totals (`app/nacha_controls.py`), following the X12 control-total contract:
    entry/addenda count, entry hash (sum of receiving DFI routing prefixes, rightmost ten digits), total debit and
    total credit for every batch control, plus batch count and block count for the file control. A disagreement is
    recorded and warned (`nacha.control_total_mismatch`, info), never rejected.
  - `app/nacha_normalizer.py` models batches and entries as native structure — `AchFile` → `Batch` →
    `EntryDetail`, one record type per layout and per addenda type present, field positions in extras — with no
    payload value; extras `nacha_file`, `nacha_sec_codes`, `nacha_batches`, `nacha_control_totals`.
    `app/nacha_analysis.py` (analyzer `nacha@1.0.0`) describes every record and field with byte positions, entry
    direction / prenote / check-digit validity, and the declared / observed totals on batch and file nodes.
  - **SEPA routes to the ISO 20022 adapter** (`app/iso20022_sepa.py`): `pain.001` / `pain.008` / `pacs.008` are
    recognised from the `<Document>` namespace as the `sepa` profile, recorded under canonical extras
    `format_profile` (lifted to `format_metadata.formatProfile`) with the message id, and named in the detection
    reason. A payment block with no transaction is `INPUT_SEMANTIC_INVALID`; a message-definition version above the
    recognised ceiling (pain.001 ≤ .12, pain.008 ≤ .11, pacs.008 ≤ .13) is `FORMAT_VERSION_UNSUPPORTED`.
  - Capability registry `nacha` seed (registry version `20`) and version coverage for `nacha` and the SEPA families;
    the `nacha/` corpus is activated and the `sepa/` corpus re-pointed at `iso20022`, with canonical, analysis and
    conversion goldens and matrix rows.

### Changed
- The ISO 20022 parser reports XML that stops partway through a tag or value as `INPUT_TRUNCATED` (it was
  code-less, classified `INPUT_MALFORMED`); `Iso20022ParseError` gained a `code`. A document that ends on a complete
  tag and only lacks its closing elements stays `INPUT_MALFORMED`.

## [1.409.0] - 2026-10-20

### Added
- **TRADACOMS, ODETTE/VDA and EANCOM dialect profiles (#5449, FMT-6.5)**: regional EDI dialects as profiles on the
  EDIFACT engine.
  - `app/edi_dialect_profiles.py` — the four profiles (`un-edifact`, `eancom`, `odette`, `tradacoms`): governing
    body, message set, bound code lists, recognition rule and reviewed boundaries; `detect_edifact_profile` /
    `edifact_profile` recognise EANCOM (an `EAN` + three-digit association code) and ODETTE/VDA (an `OD`/`VDA`
    subset designator, or an ODETTE organisation code *and* every message in the ODETTE/VDA set) on a parsed
    interchange, else plain UN/EDIFACT.
  - The **`edifact`** adapter records the profile: canonical extras `format_profile`, interchange attributes
    `profile` / `profileLabel` / `implementationGuideConsulted`, per-message `inProfileMessageSet`, warnings
    `edifact.dialect_profile_applied` and `edifact.message_outside_profile_set`, and the detection reason. Analyzer
    `edifact@1.1.0`.
  - The new **`tradacoms`** import source (format `tradacoms`; `.edi` / `.tra`; file / URL / paste / fileset):
    `app/tradacoms_parser.py` reads segments with the EDIFACT lexical layer (now shared under public names) and
    builds its own transmission (`STX` … `END`) → file (header message carrying `TYP`) → message (`MHD` … `MTR`)
    structure, several transmissions per document. Refusals: mid-segment / mid-message `INPUT_TRUNCATED`, a tag
    without `=` `INPUT_MALFORMED`, no `END`, no message, unnested envelopes or skipping `MHD` references
    `INPUT_SEMANTIC_INVALID`; an EDIFACT interchange is left code-less so the pipeline names it `FORMAT_MISMATCH`.
    `app/tradacoms_normalizer.py` (first detail message, `tradacoms_transmission` / `tradacoms_file` /
    `tradacoms_messages` extras) and `app/tradacoms_analysis.py` (declared-versus-observed `MTR` / `END` counts).
  - Import provenance: `format_metadata.formatProfile` now records the applied dialect profile for any model whose
    canonical extras carry `format_profile`.
  - Reviewed `tradacoms` capability entry and EDIFACT profile notes naming each profile and its boundaries
    (registry contract `19`), version coverage, corpus activation of the 15 `apiome-ui/examples/tradacoms/`
    entries plus the `edifact/negative/07-wrong-format-tradacoms.edi` misroute, goldens and the round-trip matrix
    row (import-only, 45 xfails).

## [1.408.0] - 2026-10-20

### Added
- **HL7 v3 / CDA import (#5448, FMT-6.4)**: the new **`hl7v3`** import source (formats `hl7v3`, `cda`, `c-cda`,
  `hl7-cda`; `.xml` / `.cda`; file / URL / paste / fileset) for CDA R2 documents — CCDs, discharge summaries and
  the other C-CDA document types — completing the HL7 set beside HL7 v2 and FHIR:
  - `app/hl7v3_parser.py` — reads the `ClinicalDocument` through the hardened XML reader: the header, the
    structured body's `component` → `section` → `entry` tree, and every `templateId` as an asserted claim. An HL7
    v3 transmission wrapper (`MCCI_IN000002UV01` …) is read as a fileset root whose payload `reference` names the
    member holding the document. Refusals carry intake codes: truncation `INPUT_TRUNCATED`, ill-formed XML
    `INPUT_MALFORMED`, a non-v3 root `FORMAT_MISMATCH`, a header missing id / code / effectiveTime / recordTarget /
    author / custodian / body `INPUT_SEMANTIC_INVALID`, a dangling narrative `#anchor` or a wrapper without its
    payload `INPUT_REFERENCE_UNRESOLVED`; encoding faults are left for the pipeline to name.
  - `app/hl7v3_datatypes.py` — the stated RIM data-type table (`II`, `CD`, `CE`, `CV`, `CS`, `TS`, `IVL_TS`, `PQ`,
    `IVL_PQ`, `RTO_PQ_PQ`, `INT`, `REAL`, `BL`, `AD`, `PN`, `TEL`, `ED`, `ST`, `SC`, `ON`), the CDA R2 element
    bindings, the C-CDA R2.1 template names and the "not validated" claim statement.
  - `app/hl7v3_normalizer.py` — the document's shape inferred from the instance: one record type per RIM class
    (context-named relationships such as `StructuredBodyComponent` / `OrganizerComponent`), data types as records
    with their declared members, `xsi:type` choices as unions, unmapped data types as declared limits
    (`cda_datatype_limits`). Extras: `cda_sections`, `cda_template_claims` (each `status: "asserted"`,
    `validated: false`), `cda_template_statement`, `cda_document_code`, `cda_type_id`, `cda_transmission`.
  - Reviewed `hl7v3` capability entry stating that template ids are asserted, not validated (registry contract
    `18`), version coverage, corpus activation of the 14 `apiome-ui/examples/hl7v3/` fixtures, goldens and the
    round-trip matrix row (import-only, 45 xfails).

## [1.407.0] - 2026-10-20

### Added
- **SWIFT MT import with MT↔MX projection notes (#5447, FMT-6.3)**: the new **`swift-mt`** import source (formats
  `swift-mt`, `swift`, `mt`; `.fin` / `.mt` / `.txt`; file / URL / paste / fileset) for MT103, MT202 (and COV),
  MT940 and MT942:
  - `app/swift_mt_parser.py` — blocks 1–5 (basic and application headers parsed leniently by position, user header
    and trailer sub-blocks), `:nn[a]:` text-block fields with offsets and lines, several messages per file, MT202 COV
    sequence B (a second `{4:}` block, or the first field 50 of one). Refusals carry intake codes: an unterminated
    text block is `INPUT_TRUNCATED` when its last field is incomplete and `INPUT_MALFORMED` when only the `-}` is
    missing; no field 20, no block 2 or an unsupported type is `INPUT_SEMANTIC_INVALID`.
  - `app/swift_mt_fields.py` — a stated field catalogue: option-letter party shapes (A/B/C/D/F/K), amounts,
    balances, statement lines with supplementary code words, narratives with `/CODE/` qualifiers. Content that does
    not match is kept as lines and flagged, never refused. The MT → MX table (`pacs.008`, `pacs.009`, `pacs.009`
    COV, `camt.053`, `camt.052`) and the disclaimer every note carries.
  - `app/swift_mt_normalizer.py` — the message as the root record type and one record type per field *with its
    option* (`Field50K` ≠ `Field50F`), `CodeWord` / `NumberedLine` records, `StatementLine` groups, a nested
    sequence B; headers in `swift_headers` and the correspondence in `swift_mx_correspondence` (`verified: false`).
  - `app/swift_mt_analysis.py` (`swift-mt@1.0.0`) — message → block → sequence → field → component / code word /
    numbered line / line; tags, options and qualifiers as structure, values under the visibility policy; warnings
    `swift.mx_correspondence_note`, `swift.field_not_well_formed`, `swift.field_not_in_catalogue`,
    `swift.canonical_projection_subset`; a cover's `relatesToMessage`.
  - Reviewed `swift-mt` capability entry (registry contract `17`), version coverage, corpus activation of the 14
    `apiome-ui/examples/swift-mt/` fixtures, goldens and the round-trip matrix row (import-only, 45 xfails).

## [1.406.0] - 2026-10-20

### Added
- **SAP IDoc import and emit (#5446, FMT-6.2)**: the new **`idoc`** import source (formats `idoc`, `sap-idoc`;
  `.idoc` / `.txt` / `.xml`; file / URL / paste / fileset) and **`idoc`** emitter:
  - `app/idoc_parser.py` — both transport forms into one AST: the flat file (the 524-character `EDI_DC40` control
    record cut at its 36 field offsets, then 1063-character `EDI_DD40` data records) and IDoc XML (`<IDOC>` →
    `<EDI_DC40>` + segments, through `secure_xml`). The hierarchy is rebuilt from `SEGNUM`/`PSGNUM` (document order
    in XML), with `HLEVEL` kept as a claim. WE60-style `<IDocSegments>` definitions cut flat `SDATA` into fields;
    without one, `SDATA` stays opaque. Refusals carry intake codes (`INPUT_TRUNCATED`, `INPUT_MALFORMED`,
    `INPUT_SEMANTIC_INVALID` — a short control record among them); encoding faults are left to the pipeline.
    `IDOC_LAYOUT_ASSUMPTIONS` states what every flat offset assumes, mirroring the copybook layout contract.
  - `app/idoc_normalizer.py` — the first IDoc's basic type as the root record type, one record type per segment
    type nested by segment number, lists where a parent carries more than one or the definition allows it,
    descriptions and lengths from the definition. Flat and XML forms read with the same definitions produce the
    same model. Values are never defaults; `idoc_control` (non-empty control fields, layout order) and
    `idoc_segments` (the emitter's template) are extras.
  - `app/idoc_analysis.py` (`idoc@1.0.0`) — IDoc → segment → field, the control record as attributes (never a
    value), flat field offsets / record offsets / lengths, and warnings `idoc.layout_assumptions`,
    `idoc.sdata_without_definition`, `idoc.hierarchy_level_disagrees`, `idoc.definition_mismatch`,
    `idoc.canonical_projection_subset`.
  - `app/idoc_emitter.py` — IDoc XML from the canonical model: the type tree for structure, the imported template
    for values, empty skeletons (recorded as inferred losses) for segment types without one. XML IDocs round-trip
    exactly (`idoc -> idoc` passes in the matrix). Export validation re-reads the output with the parser.
  - Reviewed `idoc` capability entry (registry contract `16`), version coverage, corpus activation of the 14
    `apiome-ui/examples/idoc/` fixtures (fixture `06` rebuilt as the true flat twin of `02`), goldens, and the
    round-trip matrix row and column (110 xfails).

### Changed
- The payload-analysis golden suite reads fileset roots through `parse_fileset` and skips fileset members, as the
  canonical suite does; the EDIFACT `09-interchange-set/contrl.edi` member golden is removed.

## [1.405.0] - 2026-10-20

### Added
- **UN/EDIFACT import (#5445, FMT-6.1)**: the new **`edifact`** import source (formats `edifact`, `un-edifact`;
  `.edi` / `.edifact`; file / URL / paste / fileset) reads a UN/EDIFACT batch interchange (ISO 9735) into the
  Catalog, beside EDI X12:
  - `app/edifact_parser.py` — a hand-written reader of `UNA` service string advice (or the ISO 9735 defaults, or
    the level-B control characters), release characters, syntax-4 repetition, and the `UNB`/`UNZ`, `UNG`/`UNE`,
    `UNH`/`UNT` envelopes. Every segment keeps its exact offset, length, line and column. Refusals carry intake
    codes: `INPUT_TRUNCATED` (ends mid-segment, inside a message, before `UNZ`), `INPUT_MALFORMED` (dropped
    terminator, unreadable tag, bad `UNA`), `INPUT_SEMANTIC_INVALID` (`UNH` without `UNT`, a segment outside any
    message, groups mixed with ungrouped messages, no message); encoding faults are left to the pipeline.
  - `app/edifact_normalizer.py` — the canonical model from the first group's first message, exactly as X12: single
    segments' values become fields (`BGM02`, `DTM01-2`), repeating segments their own record types, the envelope
    and sibling messages `edifact_*` extras.
  - `app/edifact_analysis.py` — the native analysis (analyzer `edifact@1.0.0`): interchange → functional group →
    message → segment → element / composite / component / repetition, with declared-versus-observed `UNT`/`UNE`/`UNZ`
    control counts and control references (warnings `edifact.control_count_mismatch`,
    `edifact.control_reference_mismatch`), present-empty element positions, the value-visibility policy, and
    `edifact.canonical_projection_subset` when the model was derived from one message of several.
  - `app/edi_analysis_base.py` — the **shared EDI analysis base**: locations, control-count statements, the observed
    value node, the envelope budget, the canonical-subset warning and the implementation-guide statement. The X12
    extractor now uses it (its records are unchanged).
  - A reviewed `edifact` capability entry stating that no implementation guide (D.96A, D.01B, EANCOM, ODETTE…) is
    consulted; version coverage for syntax 1–4; corpus activation of the 16 `apiome-ui/examples/edifact/` fixtures
    (four had miscounted `UNT` totals, now corrected), canonical, analysis and conversion goldens, and the round-trip
    matrix row (import-only; the emitter is #4146).

### Changed
- Format capability registry contract `15` (review date 2026-10-20).

## [1.404.0] - 2026-10-20

### Added
- **CNCF xRegistry import (#3980, MFI-19.2)**: the new **`xregistry`** import source (formats `xregistry`,
  `cloudevents-registry`; file / URL / paste / fileset) reads an xRegistry document — `schemagroups`,
  `messagegroups` and `endpoints`, with the earlier draft names `definitiongroups` / `definitions` / `metadata` —
  into the event paradigm:
  - schemas → types: JSON Schema (and its `definitions` / `$defs`) by schema id, Avro / Protobuf / XSD through
    their own adapters, anything else an opaque `SCALAR` type recording its format and reason;
  - messages → operations carrying one `EVENT` message on the channel named by the CloudEvents `type`, with
    the envelope attributes as headers and the referenced or inline schema as payload;
  - endpoints → services (`publish` for a producer, `subscribe` for a consumer / subscriber) and their URIs
    → servers; a message group no endpoint carries is a service of its own.
  Registry bookkeeping (`epoch`, `createdat`, `modifiedat`) never reaches the model; fingerprint, diff and
  lint are the SPI defaults. Fixtures under `apiome-ui/examples/xregistry/` (six valid, five negative), goldens
  and the round-trip matrix row.

### Changed
- The `xregistry` registry crawl now also crawls the **message registry** (`messagegroups/<id>`, one catalog
  item per group) and the **endpoint registry** (`endpoints/<id>`, one item per endpoint, holding the groups it
  references), both imported with the `xregistry` adapter and compared by content digest. A collection the
  registry answers `404` for is treated as absent (a root serving none of them fails the sync). Scope `groups`
  now limits schema and message groups; new scope `include` (`schemas`, `messages`, `endpoints`) picks the
  registries to crawl.

## [1.403.0] - 2026-10-20

### Added
- **Registry-as-source ingestion (#3978, MFI-18.5)**: an import adapter can declare a **registry crawl**
  (`ImportSource.registry_crawl`, exposed as `registry_crawl` on `GET /v1/import/sources`) — list → page → fetch
  each → normalize → version — that runs on the CDG-1.1 connector engine as the new **`registry`** connector kind
  (scope `{"protocol": …}`). Each artifact is one inventory row and one catalog item. A changed artifact is a
  new revision of the same item, with a change report. Re-crawl skips artifacts whose revision is unchanged,
  and those with no revision whose content is unchanged. Every revision records per-artifact provenance
  (`format_metadata.connector_source` gains `registryProtocol`). Cadence, the tenant pull quota, the run
  ledger and audit are the engine's.
- `app.registry_crawl`: the `RegistryCrawl` SPI, a shared `paginate` loop (cursor, `Link: rel="next"`,
  repeated-cursor guard, page limit), and `RegistryHttp`. `RegistryHttp` is the only network surface a
  crawl gets: SSRF-guarded connector client on every hop, a per-host rate limit (`requestsPerSecond`,
  default 5, max 20), a 2,000-request budget per sync, and a 5 MB response cap.
- Three crawls:
  - `a2a-registry` (declared by `a2a`): an agents list or array of card URLs, origins or inline cards, with
    `nextPageToken` paging and the legacy well-known card fallback.
  - `xregistry` (declared by `cloudevents`): CNCF xRegistry `schemagroups` → `schemas`, imported as JSON
    Schema, Avro, Protobuf or XSD by `format`, revision `<version>+e<epoch>`; scope `groups`; unsupported
    formats are reported as findings.
  - `fhir-metadata` (declared by `fhir`): the server's CapabilityStatement, plus each declared profile
    with `includeProfiles`.
- apiome-db **V307** admits the `registry` kind in `catalog_connectors_kind_check`.

### Changed
- The connector engine calls a source's optional `close()` when a sync ends.
- `registry` connectors are left out of Shadow APIs, like the MCP and schema registry kinds.

## [1.402.0] - 2026-10-20

### Added
- **Agent-descriptor paradigm in the canonical model (#3977, MFI-18.4)**: `CanonicalApi.agents` makes agents
  first-class. One `AgentDescriptor` per agent carries identity, provider, version, URL, protocol and protocol
  version, capability flags, typed `AgentSecurityScheme`s (type, scheme, location, parameter name, flows,
  OpenID Connect URL; unmodelled keys in `extras`) and agent-level security requirements. Each `AgentSkill`
  (id, name, description, tags, examples, input/output modes, its own security) is keyed
  `<agent>.<skill id>`, so skill-level diffs are stable. The A2A normalizer fills one descriptor per card,
  and the ACP normalizer one per agent (capability → skill). The existing service / operation projection
  is unchanged; `service_ref` / `operation_ref` link the two.
- `canonical_diff` reports `agent` and `skill` entities. A capability-flag or auth change is a changed
  agent, and a skill is matched by id: a rename is a changed skill, not a remove + add.
- Persistence: apiome-db **V306** adds `api_agent_descriptors` and `api_agent_skills`;
  `canonical_persistence` writes and reloads them losslessly. A2A and ACP imports now land their canonical
  tree in the MFI-2.2 tables, as AsyncAPI imports do.
- Fidelity tests assert skill, capability and auth survival, plus a gap audit for the new entities.

### Fixed
- **Agent-paradigm models can be persisted relationally**: V135's `api_artifacts_paradigm_check` predated
  the `agent` paradigm and rejected every MCP / LLM-tools / A2A / ACP / site-manifest artifact. V306 widens
  it, and a test now pins the check to `ApiParadigm`.

### Notes
- `agents` is additive and omitted from serialization when empty, so no other format's model, fingerprint
  or golden changes. A2A and ACP fingerprints change once, because the descriptor is now part of the model.

## [1.401.0] - 2026-10-20

### Added
- **Agentic-web site manifest import source (#3976, MFI-18.3)**: the `agents-manifest` adapter catalogs a site's
  agentic-web manifest in four dialects — the agents.txt companion `agents.json` (`site`, `mcp` / `a2a` / `skills` /
  `ucp` / `webmcp` endpoint lists, `payments`), the Agent Web Protocol `/.well-known/agent.json` (`protocols`,
  `actions` with `via`, `auth`), `agents.txt` directives (`MCP:`, `A2A:`, `Skills:`, `UCP:`, `WebMCP:`, `X-…`,
  `Protocols:`, `Authorization:`) and `llms.txt` (H1, summary, H2 link sections; each link classified as an Agent
  Card, MCP endpoint, OpenAPI document, nested manifest, skill or docs) — as a file, URL, paste or fileset, or live
  from the site (`AgentsManifestImportSource.introspect` tries `/agents.json`, `/.well-known/agent.json`,
  `/agents.txt`, `/llms.txt` through the SSRF-guarded client, skipping an A2A card or an HTML shell). Normalizes to
  the `agent` paradigm: one service per protocol, one operation per endpoint keyed `<protocol>.<url>` (relative
  references resolved against the site) and per AWP action. Payment layers (x402, AP2, MPP, Skyfire) are
  `extras.payments` metadata only. The A2A, ACP, MCP and nested-manifest endpoints are listed as
  `extras.discovery_seeds` (`{protocol, url, importer}`) for MFI-18.5 or a person to follow. New
  `agents-manifest` lint pack (6 rules: `agents-manifest.broken-endpoint-ref`, `agents-manifest.undeclared-via`,
  `agents-manifest.insecure-endpoint`, `agents-manifest.duplicate-endpoint`, `agents-manifest.duplicate-action-id`,
  `agents-manifest.no-agent-endpoints`); the two blocking rules carry scanner transparency and evidence fixtures.
  The catalog item detail renders **Endpoints**, **Actions**, **Discovery seeds** and **Payments** groups.
- Corpus: six valid and five negative `apiome-ui/examples/agents-manifest/` fixtures covering four sites, with
  goldens; multi-file rung waived.
- apiome-db V305 seeds the `agents-manifest.*` pack into the built-in style guide.

## [1.400.0] - 2026-10-20

### Added
- **ACP agent manifest import source (#3975, MFI-18.2)**: the `acp` adapter catalogs ACP (Agent Communication
  Protocol) agents from a single agent manifest or a server's `GET /agents` listing (`{"agents": [...]}`), as a
  file, URL, paste or fileset, or live from `<server>/agents` through the SSRF-guarded client
  (`AcpImportSource.introspect`; a `…/agents/<name>` URL imports one agent). Normalizes to the `agent` paradigm
  beside A2A: one service per agent (content types, tags, domains, framework, languages, license, author, links,
  dependencies, recommended models on `extras`), one operation per `metadata.capabilities[]` entry keyed
  `<agent>.<capability>` carrying the agent's tags and content types. Runtime `status` and `created_at` /
  `updated_at` are kept in `raw` only, so they never change the fingerprint. A live listing's URL becomes the
  model's server. New `acp` lint pack (9 rules: `acp.duplicate-agent-name`, `acp.invalid-agent-name`,
  `acp.agent-missing-description`, `acp.duplicate-capability-name`, `acp.capability-missing-description`,
  `acp.no-capabilities`, `acp.untyped-content`, `acp.missing-tags`, `acp.missing-license`). The catalog item
  detail renders an ACP document as an **Agents** group.
- Corpus: six valid and five negative `apiome-ui/examples/acp/` fixtures with goldens; multi-file rung waived.

### Changed
- The A2A and ACP adapters share one bounded, SSRF-guarded descriptor fetch (`app.agent_descriptor_fetch`) and
  one duplicate-key helper (`app.agent_paradigm_keys`).

### Fixed
- **Agent rule packs are seeded into the built-in style guide**: the `a2a.*` pack (#3974) shipped without being
  added to "Apiome Recommended", so its findings were dropped for tenants scoring against the seeded guide.
  **apiome-db V304** re-seeds the guide with the `a2a.*` and `acp.*` packs. The two blocking `a2a.*` rules and
  `acp.duplicate-agent-name` now carry scanner transparency (reference, remediation, false-positive guidance,
  evidence fixture), and the lint-rule and axis-score docs list both packs.

## [1.399.0] - 2026-10-20

### Added
- **A2A Agent Card import source (#3974, MFI-18.1)**: the `a2a` adapter catalogs an A2A (Agent2Agent)
  agent from its Agent Card, as a file, URL, paste or fileset, or live from the agent's
  `/.well-known/agent-card.json` (falling back to `/.well-known/agent.json`) through the SSRF-guarded client
  (`A2aImportSource.introspect`). The card normalizes to the `agent` paradigm: one service per agent (its
  `extras` carry `security_schemes` / `security_requirements`), one operation per skill keyed
  `<agent>.<skill id>` with the skill's tags as operation `tags`, input / output modes as request / response
  content types (falling back to the card defaults), and the effective security on `operation.extras.security`.
  Fingerprint and diff are the SPI defaults, so a skill added, removed or edited is an `operation` entry and an
  auth change is a changed `service` entry. New `a2a` lint pack: `a2a.security-undeclared-scheme`,
  `a2a.duplicate-skill-id`, `a2a.no-security`, `a2a.unknown-scheme-type`, `a2a.apikey-in-query`,
  `a2a.insecure-endpoint`, `a2a.missing-required-field`, `a2a.skill-missing-description`,
  `a2a.skill-missing-tags`, `a2a.skill-without-modes`. `GET /v1/import/sources` lists the source with
  `supports_live_discovery: true`.
- The catalog item detail `parsed` model renders an A2A card as a **Skills** group (tags in `meta`; id,
  description, modes, examples and security as rows).
- Corpus: six valid and five negative `apiome-ui/examples/a2a/` fixtures with goldens; the multi-file rung is
  waived (a card is one self-contained document).

## [1.398.0] - 2026-10-19

### Added
- **Multi-repository federation: switch, merge history and per-source conflict diffs (#2806, V2-REPO-8.2)**:
  on top of REPO-5.7's merge engine (deterministic precedence, per-entity provenance), a project can switch
  federation off so each repository import replaces the surface instead of merging, and every import federation
  acts on is recorded with its audit row. apiome-ui's import reports the merge after it commits (and a conflict
  when it fails); a conflict carries the importing file's definition of each collision, and apiome-rest fills the
  contributing file's side from the parent version's rendered spec.
  - **apiome-db V303**: `projects.repository_federation` (default `true`) and `project_federation_merges`
    (`merged` / `conflicted` / `replaced`, snapshot of the imported file, counts, `sources`, `conflicts` with every
    source's definition, bounded at 20 KB each).
  - **`GET` / `PUT /v1/tenants/{tenant_slug}/projects/{project_ref}/repository-federation`** (`projects:view` /
    `projects:edit`; audited `repository.federation_toggled`).
  - **`POST /v1/tenants/{tenant_slug}/projects/{project_ref}/federation-merges`** (`imports:create`, called by the
    import): writes the history row and its audit row — `repository.federation_merged`,
    `repository.federation_conflicted` or `repository.federation_replaced` — in one transaction.
  - **`GET …/projects/{project_ref}/federation-merges`** (`projects:view`) and
    **`GET /v1/tenants/{tenant_slug}/repositories/{repository_id}/federation-merges`** (`imports:view`, the
    repository's sync history). New tag `repository-federation`.

## [1.397.0] - 2026-10-19

### Added
- **PR-back sync: Apiome → repository (#2793, REPO-5.8)**: render a project version and open a pull request into
  the repository files the project was imported from. Each source file gets back only the paths and schemas it
  defines (REPO-5.7 provenance); content no live file defines goes to the precedence-1 file; files are written as
  JSON or YAML to match their extension (other files are skipped and listed). The pull request description is a
  change report per file (base-branch file → rendered file, rendered with the project's change report template).
  One pull request per project and base branch on `apiome/pr-back-<project>-<base>`, rebuilt from the latest base
  and force-updated; re-running refreshes the open pull request (`updated` / `unchanged`) or reports `up_to_date`.
  Pushes reuse the repository's linked-account credential and SDK-4.2's GitHub client (no new credential).
  - **apiome-db V302** `repository_pr_back_settings`: per-repository allow/deny list of projects (no row = no
    project may PR back), target branch, Mustache commit message template, reviewers (logins or `org/team`).
  - **`GET` / `PUT /v1/tenants/{tenant_slug}/repositories/{repository_id}/pr-back-settings`** (`imports:view` /
    `imports:edit`; audited `repository.pr_back_settings.update`).
  - **`GET /v1/tenants/{tenant_slug}/projects/{project_ref}/pr-back/repositories`** (`projects:view`): the
    repositories the project was imported from and whether it may PR back into each (`reasonCode` when not).
  - **`POST /v1/tenants/{tenant_slug}/projects/{project_ref}/pr-back`** (`versions:publish`; `projects:view` with
    `dryRun: true`): `preview` / `opened` / `updated` / `unchanged` / `up_to_date` / `failed`. Every pull request
    opened is audited `repository.pr_back_opened`, every one refreshed `repository.pr_back_updated`. New tag
    `pr-back`.
  - `GitHubGitClient` gained `find_file` (segment-by-segment tree walk) and `request_reviewers`.

## [1.396.0] - 2026-10-19

### Added
- **Multi-repository merge into one API surface (#2792, REPO-5.7)**: a project can source from several
  repository files (one per service). Each import of a repository file into the project builds a version that
  merges every contributing file — the importing file's classes and paths plus everything the other files
  defined, carried forward unchanged; what the importing file no longer defines is dropped. Two files defining
  the same class name or pathname fail the import (dry run included) with a message naming the entity and both
  files, and nothing is written. Precedence (1 = the file that contributed first) orders the sources and keeps
  the first file's project info (a later file only fills in missing metadata); it never resolves a conflict.
  The merge runs in apiome-ui's import (`lib/repository-merge.ts`, `lib/db/repository-merge.ts`).
  - **apiome-db V301**: `project_repository_sources` (the project's contributing files, one row per
    repository / branch / path, with `precedence`) and `version_entity_sources` (per-version provenance of every
    class and path: source, repository / branch / path snapshot, blob, `carried_from_version_id`). A version
    imported from one repository before V301 is attributed to that file on the next merge.
  - **`GET /v1/tenants/{tenant_slug}/projects/{project_ref}/repository-sources`** (`?version=` revision id or
    label; newest when omitted, `projects:view`): the contributing files in precedence order with per-file class
    and path counts, and every class and path of the version with its `source` (null when no repository defined
    it) and `counts`. New tag `project-repository-sources`.

## [1.395.0] - 2026-10-19

### Added
- **Security axis and 0–100 security score for catalog revisions (#5921, ASP-1.3)**: `clx-axis-v1` moves to
  implementation revision `3`. For an API-paradigm revision the `security` axis is now assessed from the newest
  native run's `security`-category findings — before, it was assessed for MCP servers only — under a published,
  deterministic formula: `100 − Σ_rule min(20, Σ_findings penalty(severity) × weight(rule))` with the house
  penalties (`error` 10, `warning` 4, `info` 1), the per-rule cap of 20 and a public per-rule **weight** (default
  `1.0`; `2.0` for `security.write-operation-missing-auth`, `security.credentials-in-server-url`,
  `security.secret-in-document` and `security.pii-exposed-without-auth`). One `error` from a weight-2 rule scores
  exactly 80 and grades B. The axis is assessed only when the report carries the security pack's `security`
  category bar: a revision no security pack evaluated, or whose style guide disables every rule of the pack (the
  guide now withdraws the bar), reads *not assessed* — never 100. Composite weights, the axis set and the
  algorithm id are unchanged; the security axis of an API revision is not comparable across the bump, every other
  axis and every MCP / data-contract subject is byte-identical.
  - **OWASP sub-scores.** The stored axis carries `ruleset`, `skipped_rules` and `owasp`: one entry per OWASP API
    Security Top 10 (2023) category (`API1` … `API10`, new `app.owasp_api` catalog) with `score`,
    `finding_count` and `coverage` — `full` when at least one rule citing the category evaluated, `none` when every
    such rule was skipped for the format or none cites it (rendered *not assessed*, never 100). The axis coverage
    is `partial` when the run skipped registered security rules. Served on `LintAxisOut` as `ruleset`, `owasp[]`
    (`riskId`, `title`, `score`, `findingCount`, `coverage`) and `skippedRules`.
  - **`securityScore` / `securityGrade`** on `GET /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/lint`
    (read from the evaluation the response already carries) and on every row of
    `GET /v1/versions/{tenant_slug}/{project_id}` and `GET …/{version_record_id}`, read stored-first from the
    newest persisted `clx-axis-v1` evaluation (two lateral steps on V168's index: newest evaluation, then its
    security axis) — a 50-revision list issues zero lint requests. Null when the axis is not assessed.
  - **`GET /v1/lint/rules`** publishes `weight` (security rules; null otherwise) and `owasp` (the category ids a
    rule cites, declared through the new `LintRule.owasp_ids` field and validated against the catalog when the
    registry is built) on every entry.
  - **`GET /v1/lint/workspace/summary`** adds `bySubjectType` to every axis rollup — assessed / not-assessed
    counts split by `catalog_revision` and `mcp_endpoint_version`.
  - `record_axis_evaluation` dedupes per `algorithm_version` as well as per fingerprint, so an unchanged report
    re-evaluated under a newer revision records the row a stored-first reader expects.
  - Decision recorded: the ASP-1.1 Spectral OWASP adapter findings do **not** score the axis (parity evidence
    only; scoring them too would count one defect twice).
  - Docs: the weights table and OWASP category table on *Axis score algorithm* are generated from code by
    `scripts/generate_lint_rule_docs.py`; *Lint and check quality* documents the score beside the grade.

## [1.394.0] - 2026-10-19

### Added
- **Project / batch export (#4334, MFX-39.2)**: `POST /v1/export/{tenant_slug}/jobs` accepts `versions` (1–50
  distinct revision ids or version labels) or `all_versions: true` in place of `version`, and one job exports every
  selected version to the target (`target`) or targets (`targets`). Combining `versions`, `all_versions` and
  `version`, blank or repeated `versions` entries, any `acknowledged_snapshot`, or more than 100 version × target items
  in an explicit list is a `422`.
  - **Partial-failure semantics.** Each version × target pair is an item. A version that fails to load, a target that
    does not resolve, a severe conversion without `confirm`, an emit fault, a blocked delivery, or an unexpected crash
    fails only that item; its structured `ExportJobError` is on the item and a `BATCH_ITEM_FAILED` warning is logged.
    The job completes when at least one item completed (with a `BATCH_PARTIAL` warning when some failed) and fails
    with the new `EXPORT_BATCH_FAILED` code, listing every item's error in `error.context.items`, only when all failed.
  - **One archive.** The download is `export-batch.zip`: each completed item's files under `<version>/<target>/`
    (version folder from the label, or the revision id) and a root `manifest.json` (`kind: "batch"`) listing every
    item — files, fidelity and provenance for completed ones, error code and message for failed ones.
  - **Per-item status.** `ExportJobResult.batch` (`ExportBatchSummary`) carries version/target/item/completed/failed
    counts and `items[]` (`ExportBatchItem`: version, revision, target, folder, state, snapshot hash, options, tier,
    preserved percent, guard, validation, delivery, files, error). `fidelity_rollup` covers the completed items,
    labelled `<version>/<target>`. `ExportJobResult.version_record_id` is now nullable and null on a batch result.
  - **`all_versions`** takes every live version, newest first; a project with more than 100 items fails the job with
    the new `EXPORT_BATCH_TOO_LARGE` code before anything runs. A label and its revision id count once
    (`BATCH_VERSION_DUPLICATE` warning). `dry_run` reports each item's fidelity without emitting.
  - **Attestation.** Each completed item is attested against the archive's digest;
    `GET …/jobs/{job_id}/attestation` takes `?version=` (requested version, revision id, or label) with `?target=`.

## [1.393.0] - 2026-10-19

### Added
- **Multi-target export (#4333, MFX-39.1)**: `POST /v1/export/{tenant_slug}/jobs` accepts a `targets` list
  (`[{target, options?, acknowledged_snapshot?}]`, 1–16 entries) in place of `target`, and one job emits the version
  to every listed target. Sending both `target` and `targets`, or top-level `options` / `acknowledged_snapshot` with
  `targets`, is a `422`; two targets resolving to the same format (`openapi` and `openapi-3.1`) are a `400`.
  - **One bundle.** The download is one `application/zip` (`export-multi-target.zip`) with each target's files under a
    subdirectory named after its resolved format key and a root `manifest.json` (`kind: "multi-target"`) listing every
    target's files, fidelity tier, preserved share and snapshot/version provenance, plus the rollup.
  - **Per-target reports + rollup.** `ExportJobResult.targets[]` (`ExportJobTargetResult`) carries each target's
    fidelity envelope, transcode guard, validation report, delivery decision and bundle files;
    `ExportJobResult.fidelity_rollup` (`ExportFidelityRollup`) carries the worst tier, the minimum and mean preserved
    percent, per-tier counts, and the lossy and confirmation-requiring targets. The single-target fields `target`,
    `fidelity` and `guard` are now nullable and are null on a multi-target result.
  - **All-or-nothing.** The source loads once; every target's fidelity, stale-snapshot check and guard run before
    anything is emitted, so a severe target without `confirm` fails the job (`TRANSCODE_CONFIRMATION_REQUIRED`) up
    front. The first target that fails emit, validation or the delivery gate fails the job with `error.context.target`
    naming it, and no bundle is stored. `dry_run` returns every target's report plus the rollup.
  - **Attestation.** Each target's delivery is attested against the combined bundle's digest;
    `GET …/jobs/{job_id}/attestation` takes `?target=<format key>` to pick one (409 without it on a multi-target job).
  - List rows and metrics label a multi-target job with its comma-joined targets.

## [1.392.0] - 2026-10-19

### Added
- **Schema-registry discovery connector (#3784, MFI-12.3)**: `app.schema_registry_connector_source` registers a source
  for the `schema-registry` connector kind on the CDG-1.1 protocol. It crawls a registry that speaks the Confluent
  Schema Registry REST API (Confluent Platform / Cloud, Karapace, Apicurio's `/apis/ccompat/v7`): `GET /subjects`,
  `GET /subjects/{s}/versions` and `GET /config/{s}?defaultToGlobal=true`, falling back to `GET /config` (read once per
  sync) when the subject level answers `404`. A base URL is required and the scope must be `{}`. Optional credentials:
  `{"username", "password"}` (basic) or `{"token"}` (bearer); every request goes through the SSRF-guarded connector
  client. One inventory row per subject; its revision is the latest version plus a digest of the version list and the
  level, so a new or deleted version or a changed level syncs the subject again.
  - **Mirroring.** Each subject is mirrored into the CDG-4.2 subject model: every upstream version not mirrored yet is
    read with `GET /subjects/{s}/versions/{v}` (`GET /schemas/ids/{id}` when the body has no schema text), deduplicated
    by upstream schema id (within the sync and across syncs), fingerprinted by its import source, and — only when the
    workspace does not hold the content yet — imported as a new revision of the subject's catalog item, labelled with
    the upstream version and carrying the connector provenance. The upstream compatibility level is copied onto the
    subject; the naming strategy is inferred from the subject name and the record name when the subject states none.
    Versions the registry no longer lists are soft-deleted on the mirror (their revisions stay). Compatibility checks are
    not run on mirrored versions.
  - **Never overwritten.** A subject of the same name registered in Apiome or mirrored by another connector stays
    `discovered` (`subject-name-taken`); `references-unsupported` and `schema-type-unavailable` are the other
    `discoveredReason` codes. Any other refusal fails that subject for the run, keeping what was already mirrored.
  - **Provenance (apiome-db V300).** `schema_subjects.source_ref` (`registry:<url>`) and `source_connector_id`;
    `schema_subject_versions.upstream_version` and `upstream_schema_id` (unique per subject). Exposed as `sourceRef` /
    `sourceConnectorId` on subjects and `upstreamVersion` / `upstreamSchemaId` on subject versions.
  - **Engine.** `ItemSyncOutcome` gains `project_id` and `pulls`, so a `sync_item` source can link its inventory row to a
    catalog item and count several pulls; each version or schema read counts against the polling quota. Schema registry
    connectors raise no shadow-API notification and are left out of the shadow-API report.

## [1.391.0] - 2026-10-19

### Added
- **Backstage and Compass import (#5983, CDG-5.5)**: everything a Backstage or Atlassian Compass catalog describes
  arrives as a suggestion with its provenance. Nothing becomes a team, a component or a confirmed owner without a click.
  - **Backstage.** Repository scans read every `catalog-info.yaml`. A `kind: API` with `spec.definition` (inline, or a
    `$text` / `$openapi` / `$json` / `$yaml` path beside the file) is imported through the import pipeline as a catalog
    item; an unchanged definition is not imported again. `Component`, `System` and `Domain` entities become component
    suggestions (links, type, lifecycle, parent, owner, `dependsOn` / `consumesApis`). `Group` entities and every
    `spec.owner` become team suggestions.
  - **Compass.** `POST /v1/tenants/{tenant}/catalog-migrations/compass` stages an export (`{components, teams}`, a
    GraphQL `searchComponents` response or a list; at most 5 MB, 413 `migration-too-large`). Components become
    component suggestions with `CHAT_CHANNEL` / `ON_CALL` / `DOCUMENT` / `REPOSITORY` / `DASHBOARD` links and
    `DEPENDS_ON` relationships; `ownerId` becomes a team suggestion.
  - **Reports.** `GET …/catalog-migrations` and `…/catalog-migrations/{id}` return each import report: counts, the
    suggestions and every unmapped field (entity, path, reason; values are never stored).
  - **Decisions.** `POST …/catalog-migration-suggestions/{id}/accept` (`{name, slug, asComponent}`) creates a team
    (or links the live team with its slug), registers a component, or applies a component to the Project or catalog
    item it matches. Imported owners are written only as `entity_owners` suggestions (sources `backstage` /
    `compass`). `…/dismiss` keeps a suggestion out of later runs. 409 `migration-suggestion-decided` /
    `migration-slug-taken`. Audited as `catalog.migration.*`.
  - **Components.** A new `component` entity kind (apiome-db V299 `catalog_components`) in the catalog registry, the
    graph, owners and facts; `GET …/catalog-components/{slug}`. Declared references to a component resolve when it
    is accepted (`app.declared_dependencies.promote_unresolved`).
  - RBAC: `imports:view` to read, `imports:create` to upload and decide, plus `teams:create` to accept a team.
    OpenAPI 1.255.0.

## [1.390.0] - 2026-10-19

### Added
- **Catalog facts for per-kind scorecards (#5982, CDG-5.4)**: `GET /v1/catalog/{tenant}/entities/{kind}/{id}/facts`
  returns the typed facts a catalog entity carries, each with a status (`met`, `unmet`, `not_applicable`,
  `not_assessed`), a value, a detail line and evidence links: `owner.present`, `owner.contactable`,
  `consumers.declared` (count), `dependencies.declared`, `refresh.fresh` (its repository, connector, MCP discovery or
  gateway sync last succeeded within twice its cadence; not applicable when nothing refreshes it), `deployment.known`
  (current `deployed_on` edges), `shadow.none` (the shadow report for the connector or environment; not assessed on a
  stale inventory), `registry.level-set` (catalog items' schema subjects), `mcp.baseline-approved` and
  `agent.readiness` (always `not_assessed` until ATQ-2). Which facts apply depends on the kind (`app.catalog_facts`).
  `score` is always `null` until GVM-1.x maturity ladders consume the facts; a grade is never computed from partial
  facts. Needs `view` on the kind's resource; 422 for an unknown kind, 404 for an unknown entity. OpenAPI 1.254.0.

## [1.389.0] - 2026-10-19

### Added
- **Gateway configs as entities (#5981, CDG-5.3)**: V298 adds `catalog_gateway_configs`, one live row per (connector,
  environment) — a Kong control plane, an AWS stage, an Azure APIM instance, an Apigee environment. Every connector sync
  refreshes them (`gateway_config_store.refresh_gateway_configs`, before the graph): API count, auth and rate-limit
  posture (names and schemes only, read from the served APIs' imported models — Kong's `extras["gateway"]`, the other
  gateways' `extras["security"]` / `extras["rate_limits"]`), and the declared loss "gateway configs carry no
  request/response schemas"; vanished environments are soft-deleted. New routes `GET /v1/tenants/{tenant}/gateway-configs`
  (`?connector=`) and `GET …/gateway-configs/{slug}` (with the APIs served), `imports:view`. `pushBack.target` names the
  export target that writes the gateway's format (`kong` for Kong connectors); AWS API Gateway, Azure APIM and Apigee
  report `pushBack.reason: fmt-7.7` until FMT-7.7 (#5461) ships their emit modes. **Changed:** `deployed_on` graph edges
  now run from a Project or catalog item to the gateway config of the environment serving it (was: to the connector);
  `gateway_config` is a graph node kind, a catalog entity kind and an owner kind. OpenAPI 1.253.0.

## [1.388.0] - 2026-10-19

### Added
- **Agent and model entities (#5980, CDG-5.2)**: V297 adds `catalog_models` (provider, model name and version, hosting
  `api|self_hosted`, data handling, `deprecated_at`), `catalog_agents` (runtime, model, status `active|retired`),
  `catalog_agent_keys` (the AGX-3.1 agent keys an agent uses; a key belongs to one agent) and
  `catalog_agent_consumers`. New routes under `/v1/tenants/{tenant}`: `GET|POST /catalog-agents`,
  `GET|PATCH|DELETE /catalog-agents/{slug}`, `PUT|DELETE /catalog-agents/{slug}/keys/{keyId}`, `GET|POST
  /catalog-models` and `GET|PATCH|DELETE /catalog-models/{slug}` (`consumer_contracts` RBAC; linking a key also needs
  `api_keys:view`; writes audited as `catalog.agent.*` / `catalog.model.*`). An agent is a **consumer**: for each
  project its live keys' enabled, allowlisted toolset tools reach, it gets a consumer (found by its slug, or created)
  and a contract revision with the new source `agent`, so CTG impact, the blast radius and the `consumes` graph edges
  include it. Revoking or unlinking a key, narrowing its allowlist, or retiring the agent records a new revision and
  the dropped edges go stale. An agent shows its model's deprecation date; agent responses carry a key's name, prefix
  and status, never its secret or hash. `agent` and `model` join the catalog entity registry and the owner kinds;
  agent usage (`GET …/agent-usage`) names each key's `agentSlug`. OpenAPI 1.252.0.

## [1.387.0] - 2026-10-19

### Added
- **Entity-kind registry and unified entity list (#5979, CDG-5.1)**: `app.catalog_entities` is one code registry of
  catalog entity kinds — `api` (publishable Projects), `spec` (catalog items), `mcp_server`, `consumer`, `connector`
  and `team` — each declaring its table, live predicate, slug / description columns, owner kind, graph node kind,
  RBAC view resource and UI routes. `GET /v1/catalog/{tenant}/entities?kind=&team=&q=&cursor=&limit=` returns one
  page across kinds in a common envelope (`kind`, `id`, `slug`, `name`, `description`, `owner`, `updatedAt`, `href`,
  `graphNode`), ordered by name, then kind, then id, with a keyset `pagination.nextCursor`; it issues one bounded
  read per kind whatever the page holds. `GET /v1/catalog/{tenant}/entities/summary` counts every kind (one
  statement) and returns the catalog home callouts: `unowned` (no confirmed owner team), `stale` (connectors and MCP
  servers not refreshed within twice their cadence) and `shadow` (the shadow-API report's count). Kinds the caller
  may not view are left out; a `team` filter leaves out kinds without owners; an unknown `kind` is a 422 and a
  malformed `cursor` a 400. The graph labeller (`graph_nodes.label_sql`) now derives its entity queries from the
  registry. OpenAPI 1.251.0.

## [1.386.0] - 2026-10-19

### Added
- **Upstream MCP registry connector (#5976, CDG-4.4)**: `app.mcp_registry_connector_source` registers a source for the
  `mcp-registry` connector kind on the CDG-1.1 protocol. It pages `GET {baseUrl}/v0.1/servers` (`limit`, `cursor`,
  `version=latest`, plus the scope's `search` and `updatedSince` → `updated_since`) from the official registry, Azure
  API Center, a Kong registry or another Apiome tenant (`/registry/mcp/{tenant}`); a trailing `/v0.1[/servers]` on the
  base URL is accepted. Optional credentials: `{"token"}` (bearer) and `{"apiKey"}` (`X-API-Key`). Scope is validated
  (`search`, `updatedSince` only; a base URL is required). One inventory row per server name (the `isLatest` entry;
  `deleted` entries turn the row `missing`); the revision is the version plus a digest of `server.json`. For each new or
  changed entry the source picks the first concrete `streamable-http` / `sse` remote, checks it against the connector
  address rule, creates or refreshes an `mcp_endpoints` row (`added_via = 'registry'`, private, unpublished), links its
  sources as `registry_published` (`registry` identity, `repository.url` as git, npm/PyPI/NuGet/Cargo packages and OCI
  images; links this connector made that the registry dropped are retired) and runs discovery with
  `trigger = 'registry'`, which lints and scores the snapshot. Entries with no usable remote, a refused address, or a
  remote discovery cannot reach stay `discovered` with a `discoveredReason` (`no-remote`, `remote-templated`,
  `remote-refused`, `remote-unreachable`) and are retried every sync.
- `GET …/connectors/{id}/items` rows carry `mcpEndpointId` and `discoveredReason` (apiome-db **V296** adds
  `catalog_connector_items.mcp_endpoint_id` and `discovered_reason`). Run summaries count `discovered` entries and list
  up to 50 under `discoveredItems`.
- The sync engine (`app.catalog_connector_sync`) gains a `sync_item(db, candidate, row, actor_id) -> ItemSyncOutcome`
  source hook for sources that create their own catalog objects, and a `reports_shadow_apis` source flag.

### Changed
- MCP registry connectors are excluded from the shadow-API report and raise no shadow-API notifications.

The OpenAPI version moves to 1.250.0.

## [1.385.0] - 2026-10-19

### Added
- **Confluent-compatible schema registry API (#5975, CDG-4.3)**: `app.schema_registry_confluent_routes` mounts the
  Confluent v1 contract at `/registry/schema/{tenant}` over the CDG-4.2 subject model, answering
  `application/vnd.schemaregistry.v1+json`: `GET /subjects` (`?deleted=true`), `GET|POST /subjects/{s}/versions`
  (register → `{id}`), `POST /subjects/{s}` (lookup), `GET /subjects/{s}/versions/{v|latest|-1}` and `…/schema`,
  `DELETE /subjects/{s}` (soft, `imports:edit`; `?permanent=true` after a soft delete, `imports:delete`),
  `GET /schemas/ids/{id}` (+ `/subjects`, `/versions`), `GET /schemas/types` (`?details=true` labels each type),
  `GET|PUT /config` and `/config/{s}` (`?defaultToGlobal`), `GET|PUT /mode` and `/mode/{s}`,
  `POST /compatibility/subjects/{s}/versions[/{v}]` (`{is_compatible, messages}`). Errors use Confluent's
  `{error_code, message}` body and codes (`40101`, `40301`, `40401`–`40405`, `40408`, `42201`–`42205`). Auth maps onto
  existing workspace API keys — basic auth with the key as password, a bearer key, `X-API-Key`, or a session — through
  `validate_authentication`; new scopes `registry:read` (GETs, lookup, compatibility test) and `registry:write`
  (register, config, mode, delete) in the `app.auth` allowlist (apiome-db V295 widens `api_keys_scopes_vocab_ck`).
  Writes are audited in `registry_audit` (`registry.subject.register|config|delete`). **No silent success**: no XPC-4.x
  rules have shipped (`schema_registry.COMPATIBILITY_RULES_SHIPPED` is empty), so a new version under any level but
  `NONE` — through either API — is refused with `422` `compatibility-rules-unavailable` (Confluent `error_code` 42290);
  a subject's first version and re-registering held content need no verdict. `schema_registry_store` gains
  `list_subject_names` and `hard_delete_subject`; `schema_registry_service` gains `lookup_schema`, `check_compatibility`
  and `effective_level`. `confluent-kafka[avro,json]` joins the dev dependency group: a test runs its
  `SchemaRegistryClient`, `AvroSerializer`/`AvroDeserializer` and `JSONSerializer`/`JSONDeserializer` against the app.

### Changed
- `POST /v1/tenants/{t}/schema-registry/subjects/{s}/versions` (CDG-4.2) applies the same compatibility rule: a new
  version under a level other than `NONE` is refused with `422 compatibility-rules-unavailable`.

The OpenAPI version moves to 1.249.0.

## [1.384.0] - 2026-10-19

### Added
- **Schema subject model (#5974, CDG-4.2)**: apiome-db **V294** adds `schema_registry_config` (per-tenant default
  compatibility level and mode, plus `next_schema_id`, the per-tenant schema id counter), `schema_registry_schemas` (one
  row per distinct schema: `schema_id`, `schema_type` `AVRO|JSON|PROTOBUF`, `fingerprint` + `fingerprint_kind`
  `canonical-model` — `avro-pcf` reserved for MFI-12.1 #3782 — and the catalog revision that first held it; UNIQUE
  (tenant, schema_id) and (tenant, type, kind, fingerprint)), `schema_subjects` (name unique among live subjects,
  `strategy` `topic|record|topic_record`, nullable `compatibility_level` = tenant default, `mode`, backing catalog item,
  soft delete) and `schema_subject_versions` (subject, version, schema_id, the holding `project_id` +
  `version_record_id`, `references`, soft delete; UNIQUE (subject, version) and (subject, schema_id)). Schema ids live
  in their own table so two subjects holding one schema share its id. `app.schema_registry` (rules, strategy mapping to
  the MFX-19.3 `AvroSubjectNamingStrategy`, fingerprint through the Avro / JSON Schema / Protobuf import sources),
  `app.schema_registry_store` (`record_version` creates the subject, finds or allocates the id and inserts the next
  version in one transaction) and `app.schema_registry_service` (register: an existing fingerprint returns its version,
  one held by another subject shares its id and revision, a new one is imported through `run_adapter_import_job` as a
  revision of the subject's catalog item; attach: an existing Avro / JSON Schema / Protobuf catalog item's latest
  revision becomes version 1, history untouched). Routes under `/v1/tenants/{t}/schema-registry` (`schema-registry`
  tag): `GET|PUT /config`, `GET /subjects`, `GET|PUT|DELETE /subjects/{s}`, `GET|POST /subjects/{s}/versions`,
  `GET /subjects/{s}/versions/{n|latest}`, `POST /subjects/{s}/attach`, `GET /schemas/ids/{id}` (resolves after its
  subjects are deleted). Permissions `imports:view|create|edit|delete`. Compatibility verdicts and the
  Confluent-compatible API are CDG-4.3 (#5975).

The OpenAPI version moves to 1.248.0.

## [1.383.0] - 2026-10-19

### Added
- **MCP Registry API over the MCP server catalog (#5973, CDG-4.1)**: the registry routes are also mounted at
  `/registry/mcp/{tenant}/v0.1/…` (`app.mcp_registry_routes.registry_router`) — `GET …/servers`,
  `…/servers/{serverName}/versions` and `…/versions/{version}` — with the same handlers, visibility, cursors and
  ETags as `/v1/tenants/{t}/mcp-registry/v0.1/…`. New `GET …/v0.1/schema` (both mounts) returns the registry API
  version, the `server.json` schema URL and the pinned upstream spec version and commit. Each `server.json` now
  carries `packages[]` from the endpoint's live `mcp_endpoint_sources` (package sources by purl type, identifier and
  — only when pinned to an exact version — `version`; image sources as `oci`; `transport` `stdio`) and `repository`
  from the newest live git source; no source means `packages: []` and no `repository`. `_meta["dev.apiome/catalog"]`
  adds `ownerTeam` (confirmed, else suggested owner), `lintGate` (`verdict` `pass` / `fail` / `not_evaluated` and
  `evaluatedAt` from the snapshot's latest stored `lint_policy_evaluations` row; never run on read) and `sources`
  (`linked` / `none`). `Database.list_mcp_registry_endpoints` joins the owner envelope, the live sources and the
  latest lint gate verdict in the same statement. Names stay `apiome.<tenant-slug>/<endpoint-slug>`: Apiome has no
  tenant-level verified domain yet, so the reverse-DNS naming rule is deferred.

The OpenAPI version moves to 1.247.0.

## [1.382.0] - 2026-10-19

### Added
- **MCP Registry API over the MCP server catalog (#5724, AAU-5.3)**: read-only router `app.mcp_registry_routes`
  serves a tenant's cataloged MCP servers in the official MCP Registry API v0.1 shape —
  `GET /v1/tenants/{t}/mcp-registry/v0.1/servers` (`cursor`, `limit` 1–100 default 30, `search`, `updated_since`,
  `version`), `GET …/servers/{serverName}/versions` and `GET …/servers/{serverName}/versions/{version}` (`latest` or
  exact; `ETag` + `If-None-Match` → `304`). Each entry is a `server.json` built by `app.mcp_registry` from the endpoint
  and its current snapshot: name `apiome.<tenant-slug>/<endpoint-slug>`, version from `serverInfo.version` (else the
  snapshot label), `remotes[]` from the transport and the endpoint URL with userinfo, query and fragment removed
  (`stdio` has none). `_meta` carries `io.modelcontextprotocol.registry/official` (`status`, `publishedAt`,
  `updatedAt`, `isLatest`) and `dev.apiome/catalog` (stored grade and score, the trust posture recomputed offline with
  the vulnerability lookup off, visibility, manifest digest). Anonymous callers get the public gate's slice; a session,
  workspace API key or MCP API key of the tenant (`Database.resolve_mcp_api_key_tenant_id`, read-only) also sees
  private and unpublished endpoints, and a bad or foreign credential is `401` / `403`. Pages are keyset-ordered by slug
  (`Database.list_mcp_registry_endpoints`), so cursors are stable under inserts. The registry response schema is
  vendored at `app/data/mcp_registry_v0_1_schema.json` (server.json 2025-12-11, registry API 2025-12-01 at commit
  `11b7b0e`) and every built page is validated against it in tests. `_build_posture_context` gains
  `scan_vulnerabilities`. The tenant's own agent-runtime entry is left to AAU-5.1 (#5722).

The OpenAPI version moves to 1.246.0.

## [1.381.0] - 2026-10-18

### Added
- **Runtime-derived graph edges (#5970, CDG-3.5)**: `app.runtime_graph` materializes `runtime_calls` edges in
  `catalog_edges` from `usage_daily` rows a RDG-1.8 binding attributed: consumer → project / catalog item, one per
  operation pointer, provenance `runtime`, `source_ref` `usage:30d`, evidence `{calls, errors, last_seen_day,
  window_days, via, consumer_slug}`. Same life cycle as derived edges (upsert, stale when no call in the window, purged
  after 30 days stale), never merged with declared or derived ones. The usage sweep re-derives them after its rollup
  (`UsageSweepResult.runtime_tenants`; a failure there never fails the tick).
- **Suggested consumers (#5970)**: apiome-db **V293** adds `usage_unattributed_client_daily` — per project, day and
  client key, the accepted calls no binding matched: the lower-cased product token of the scrubbed user agent (plain
  names only; credential- or random-looking tokens are dropped) or the `consumer_hint` HMAC — and
  `purge_usage_unattributed()` on the rollup retention, run by the usage sweep (`unattributed_purged`).
  `GET /v1/tenants/{t}/projects/{p}/consumer-suggestions` (`consumer_contracts:view`) lists them busiest first, minus
  keys a live binding already recognises; a hashed client is addressed by an opaque id (truncated SHA-256 of the HMAC)
  and never shows its HMAC. `POST …/consumer-suggestions/{id}/register` (`consumer_contracts:create`) registers a CTG-4.1
  consumer (or binds to an existing one with `consumer`) and creates the binding — `<token>/*` for a user agent, or a
  hashed binding holding the received HMAC (`binding_name` required) — validating everything before the consumer is
  created.
- **Blast radius**: each affected entity carries `provenances`, every provenance that reached it at its depth, so a
  consumer that declares and calls an operation reports `["derived", "runtime"]`; `provenance: ["runtime"]` answers
  with live callers only.

The OpenAPI version moves to 1.245.0.

## [1.380.0] - 2026-10-18

### Added
- **Consumer bindings and runtime edges (#5765, RDG-1.8)**: apiome-db **V292** adds `usage_consumer_binding` (tenant,
  project, consumer, `kind` `header|api_key|jwt_claim|user_agent`, `name` — the header or claim name, or a user-agent
  glob — `value_hmac`, `key_version`, `last_matched_at`, soft `deleted_at`; unique per tenant/kind/name/value among live
  bindings), `consumer.runtime_last_seen_at`, and reserves the consumer handle `anonymous`
  (`409 consumer-slug-reserved`). `GET|POST /v1/tenants/{t}/projects/{p}/consumers/{c}/bindings` and
  `DELETE …/bindings/{id}` (`consumer_contracts:view|create|delete`): the value is accepted once, hashed with
  HMAC-SHA256 under a tenant key derived by HKDF from `APIOME_LINKED_ACCOUNT_TOKEN_ENCRYPTION_KEYS` before the transaction
  opens (`503 consumer-binding-key-unavailable` without one), and never returned — not even as a hash. Responses carry
  `hashed`, never the value. A user-agent glob needs three literal characters (`400 consumer-binding-invalid`); one
  value binds one consumer per tenant (`409 consumer-binding-exists`); 50 live bindings per consumer
  (`409 consumer-binding-limit`). At ingest (`app.usage_ingest`), an accepted event is matched by its `consumer_hint`
  (kind + HMAC), then by its scrubbed user agent (most literal characters first, case-insensitive), and its
  `usage_hourly` grain carries the binding; unmatched traffic keeps no binding and is reported as `anonymous`, never
  dropped. The ingest response gains `attributed`. Bindings are read inside the batch transaction, so a deleted binding
  stops matching on the next batch while history stays attributed (the row is kept). `app.consumer_runtime_edges` (pure)
  compares a consumer's current contract with `usage_daily` and reports `declared_and_used`, `declared_unused` and
  `used_undeclared` operations with calls, errors and last-seen day: `GET …/consumers/{c}/runtime?days=` (1–395, default
  30; `anonymous` reports unattributed traffic) and a `runtime` summary on each `GET …/consumers` row
  (`?runtime_days=`). "Add to contract" goes through the existing `PUT …/contract`.

The OpenAPI version moves to 1.244.0.

## [1.379.0] - 2026-10-18

### Added
- **Usage ingest (#5760, RDG-1.2)**: `POST /v1/tenants/{tenant}/usage/ingest` takes a batch of at most 5,000
  `apiome.usage.event/v1` events and 2 MiB (gzip accepted; the limit applies before and after decompression), naming its
  `usage_source` by `X-Apiome-Usage-Source` or `source_id`. Authenticated with a workspace API key carrying the new
  `usage:ingest` scope (apiome-db V291; the scope admits this route only) or a full-access key; a session is refused
  (`403 usage-ingest-key-required`) and an agent key is never a REST credential. `app.usage_ingest` runs per event, in
  order: the tier cap (`licenses.seats.usage_events_per_day`; over it the batch is `429 usage-quota-exceeded` with
  `retryAt`, `batchId` and `Retry-After`, and ledgered as rejected), deterministic head sampling on
  `(source, observed_at, path, status)` with counts scaled by the inverse rate (`basis: sampled`), the edge scrub (path
  segments flagged by `app.intake_secret_scrub` or shaped like an email or UUID become `{param}` via the new
  `app.inferred_spec.template_path`; query values discarded, names kept as `/parameters/query:<name>` field counters;
  user agents scrubbed then truncated to 256), template matching through `app.consumer_surface.SpecIndex` against the
  project's 20 newest **published** revisions (draft-only operations stay unmatched and count into
  `usage_unmatched_daily` by inferred template), and one `usage_ingest_batch` ledger row per batch echoed in the
  response (`accepted`, `sampledOut`, `unmatched`, `rejected`, `scrubFindings`, up to 100 `rejections` by index and
  reason). Events on a finalized day are rejected (`day-finalized`). A `sample` is refused with
  `422 usage-body-not-accepted` unless the source's body window is open; then it is reduced by the PMR-2.4 capture
  reducer and stored as `usage_sample` only when the credential re-scan is clean and it fits 16 KiB.

### Fixed
- **Secret scrub performance**: the `secret-assignment` pattern of `app.intake_secret_scrub` only starts a match where a
  key-character run starts. Same matches; a long token-shaped string no longer costs quadratic time to scan.

The OpenAPI version moves to 1.243.0.

## [1.378.0] - 2026-10-18

### Added
- **Graph export (#5971, CDG-3.6)**: `GET /v1/graph/{tenant}/export?format=json|dot` (`projects:view`) streams the
  dependency graph as one `apiome.graph.export/v1` JSON document (`filters`, `truncated`, `node_count`, `edge_count`,
  `nodes` with name/slug/owner team, `edges`) or a Graphviz `digraph` (declared edges bold, runtime dotted, stale dashed).
  Filters: `kind`, `team`, `provenance` (repeatable), `stale=false`, or a neighbourhood with `entity=kind:id&depth=1–5`
  (default 2). Bounded at 10,000 edges, current first; the response is a download (`<tenant>-graph.<format>`).
- **Blast radius on the diff gate (#5971)**: `POST /v1/diff/{tenant}/classified` accepts `blastRadius: true`
  (`projects:view`). Each breaking change then carries `blastRadius` — `consumers` (direct and transitive), `teams`
  (their owner teams), `verificationRuns` (invalidated), `truncated` and `line`, e.g. "affects 4 consumers across 2 teams
  (mobile, payments); 2 verification runs invalidated" — computed from the CDG-3.3 blast radius against the base
  project and revision; the response gains `blastRadius: {annotated, skipped, failed, limit}` (at most 50 distinct
  breaking pointers per diff). The markdown changelog gains a `Blast radius:` sub-bullet under each breaking row.
  Without the flag the response is unchanged (no `blastRadius` keys).

The OpenAPI version moves to 1.242.0.

## [1.377.0] - 2026-10-18

### Added
- **Usage event contract (#5759, RDG-1.1)**: `app.usage_events.UsageEvent`, the pure `apiome.usage.event/v1` model every
  usage source will emit: method, path (templated or raw, never a query), status, latency, byte sizes, scheme, host,
  tri-state `auth_present`, `version_hint`, a scrubbed user agent (≤ 256 characters), an HMAC-only `consumer_hint`,
  `spec_revision_id` / `agent_key_id` and the field pointers seen in the bodies. Unknown keys are refused at every level,
  and `to_json()` writes a byte-deterministic canonical form. `latency_bucket()` maps a latency to the shared histogram.
- **Usage index sweep (#5759)**: `app.usage_sweep` rolls `usage_hourly` up into `usage_daily`, finalizes UTC days once
  `APIOME_USAGE_FINALIZE_GRACE_HOURS` (default 6) have passed, and prunes the index per license tier (migration V290).
  It runs from the lifespan every `APIOME_USAGE_SWEEP_INTERVAL_SECONDS` (default 3600; 0 disables it) behind an advisory
  lock, and once from cron with `python -m app.usage_sweep [--grace-hours H] [--batch-size N]`.
  `APIOME_USAGE_SWEEP_BATCH_SIZE` (default 10000) bounds each prune.

No REST endpoint changes: the ingest route that writes the index arrives with RDG-1.2. The OpenAPI version moves to
1.241.0.

## [1.376.0] - 2026-10-18

### Added
- **Graph entity search (#5969, CDG-3.4)**: `GET /v1/graph/{tenant}/entities?q=&kind=&team=&provenance=&limit=&offset=`
  (`projects:view`) lists every entity with at least one edge — name, slug, owner team, `in_count`, `out_count`,
  `stale_count` — most connected first; `limit` 1–2000 (default 200), with `total` and `truncated`.
- **Edge labels (#5969)**: `GET …/entities/{kind}/{id}/edges?labels=true` adds `from_label` / `to_label`
  (`{name, slug, owner}`) to each edge, looked up in batch (`app.graph_nodes`).
- **Blast radius `total_found` (#5969)**: how many entities the walk found, including those past the 2,000 cap or one
  level past `depth` — a lower bound when `truncated`, so a client can say "showing 2,000 of at least N".

The OpenAPI version moves to 1.240.0.

## [1.375.0] - 2026-10-18

### Added
- **Blast radius (#5968, CDG-3.3)**: `POST /v1/graph/{tenant}/blast-radius` (`projects:view`) with `{entity: {kind, id},
  pointers?, depth? (1–5, default 3), provenance?, version?}` returns the `direct` and `transitive` dependents of the change
  along inbound `consumes` / `depends_on` / `runtime_calls` edges (each with its edge `path`, provenance and owner team) and
  `invalidated_evidence`: the latest verification run per target exercising an affected operation, overlapping consumer
  contracts, deploy-gate evaluations citing those runs, SDK regeneration targets, agent-toolset tools, mock fixture packs
  and scenarios, and consumers pinned to deprecated or sunset versions. The direct `consumes` layer reuses the CTG-4.2
  pointer intersection with a segment-wise filter, so it equals the consumer-impact verdict set. Operations match by
  template shape (`{id}` ≡ `{petId}`); schema pointers reach operations through `$ref`s. At most 2,000 entities;
  `truncated` past that or past `depth`; `evidence_checked: true` always.

The OpenAPI version moves to 1.239.0.

## [1.374.0] - 2026-10-18

### Added
- **Declared dependencies (#5967, CDG-3.2)**: `GET|PUT /v1/graph/{tenant}/entities/{kind}/{entity}/dependencies`
  (the kind's own `view` / `edit`; `entity` is an id or a project/catalog-item slug). `PUT` replaces the entity's
  `manual` declarations with `[{to: {kind, id} | {slug}, pointer?, note?}]` (at most 200) as `depends_on` edges with
  provenance `declared`, audited as `graph.dependencies.update`; `GET` returns every declared edge from every source and
  the `unresolved` references.
- **`x-apiome-depends-on` on import (#5967)**: a root list of `<slug>[#<pointer>]` in OpenAPI, AsyncAPI, JSON Schema and
  Avro `.avsc` documents, or an `x-apiome-depends-on:` line in a GraphQL description, is stored as the entity's `spec`
  declarations on every import, in-process or through the OpenAPI worker; the set replaces the previous import's.
- **Backstage `catalog-info.yaml` (#5967)**: each repository scan reads every `catalog-info.yaml` / `.yml` on the branch;
  `consumesApis` become `consumes` and `dependsOn` `depends_on` declared edges (`source_ref: backstage:<path>`) of the
  APIs imported from that branch (`providesApis` picks which). A removed file removes its declarations.
- **Unresolved references (#5967)**: apiome-db V289 `catalog_unresolved_dependencies` keeps references that name no
  entity (`not-found`) or the entity itself (`self`) on the declaring entity, replaced per source.

The OpenAPI version moves to 1.238.0.

## [1.373.0] - 2026-10-18

### Added
- **Catalog graph edge store (#5966, CDG-3.1)**: apiome-db V288 adds `catalog_edges` — `from`/`to` nodes, `edge_kind`,
  an optional JSON `pointer`, `provenance` (`declared`, `derived`, `runtime`), `source_ref`, `first_seen_at`,
  `last_seen_at`, `stale_since` and `evidence`, unique per `(tenant, from, to, edge_kind, pointer, provenance,
  source_ref)` and indexed both ways plus by pointer. `app.catalog_graph.materialize` derives edges idempotently from
  consumer contracts (`consumes`, one per pointer), conversions (`converted_from`), identity groups (`identity_of`),
  MCP sources (`built_from`), connector items (`deployed_on`) and repository imports/bindings (`served_by`). Producers
  re-derive their family inside their own transaction (under a savepoint) or right after it; a nightly sweep repairs
  every family for every tenant. An edge whose source is gone keeps its `last_seen_at`, gains `stale_since` and is
  purged after 30 days.
- **Graph read (#5966)**: `GET /v1/graph/{tenant}/entities/{kind}/{id}/edges?direction=in|out&kind=&provenance=`
  (`projects:view`), paged with `limit` (1–500, default 100) and `offset`, returning `edges` (each with `stale`),
  `total` and `truncated`.

### Changed
- Retiring a consumer (`DELETE …/consumers/{consumer}`) now runs in one transaction with its graph update.

The OpenAPI version moves to 1.237.0.

## [1.372.0] - 2026-10-18

### Added
- **Ownership policy (#5964, CDG-2.5)**: `GET|PUT /v1/tenants/{tenant}/ownership-policy` (`teams:view` / `teams:edit`,
  audited as `ownership_policy.update`) reads and sets `unowned_findings_team` (a catch-all team slug, or `null`) and
  `require_owner_to_publish` (apiome-db V287). With a catch-all team, a finding on an entity with no confirmed owner is
  still recorded in the Unowned findings report and is also delivered to that team (inbox rows marked
  `catch_all: true`, its chat channel, the same throttle); a deleted catch-all team receives nothing.
- **Owner publish gate (#5964)**: with `require_owner_to_publish` on, `POST …/publish` refuses a version of a project with
  no confirmed, live owner team — `422` with `reason: "no-owner"` and an `ownerGate` object — after the COL-2.3 approval
  gate; force-publish still bypasses it. The precheck outcome always carries the verdict (`disabled`, `satisfied`,
  `blocked`). `GET /v1/tenants/{tenant}/ownership-policy/publish-gate?project=<id>` (`versions:view`) previews it for the
  publish dialog.
- **Ownership drift (#5964)**: `GET /v1/tenants/{tenant}/ownership-drift` (`teams:view`) lists entities whose confirmed
  owner team was deleted (`deleted_team`) or has no members (`empty_team`), and suggestions nobody confirmed in 30 days
  (`stale_suggestion`), at most 200 per reason with `counts` totals.
- **Owner facts (#5964)**: `GET /v1/tenants/{tenant}/owners/{kind}/{id}` carries `facts: {"owner.present",
  "owner.contactable"}` for GVM-1.x ladders (CDG-5.4 will read the same `owner_facts()` function).

The OpenAPI version moves to 1.236.0.

## [1.371.0] - 2026-10-18

### Added
- **Owner filter on the lists (#5963, CDG-2.4)**: `GET /v1/catalog/{tenant}`, `GET /v1/projects/{tenant}`,
  `GET /v1/mcp/{tenant}/browse` and `GET /v1/tenants/{tenant}/projects/{project}/consumers` take `?team=<slug>` and
  return only the entities whose owner — confirmed, else suggested, as each row's `owner` shows it — is that team.
  The filter is part of each read's one SQL statement.
- **`owner` on MCP browse (#5963)**: every endpoint in `GET /v1/mcp/{tenant}/browse` carries
  `owner: {team, status, source}`, as the other lists do.
- **Team activity (#5963)**: `GET /v1/tenants/{tenant}/teams/{slug}/activity` (`teams:view`) returns `owned` (confirmed
  ownership: `kind`, `id`, `name`, `source`), `owned_counts` by kind, `suggested_count`, `open_findings` — the caller's
  unread owner-finding notifications routed to the team, the rows their bell counts — and `events`, the findings
  routed to the team in the last 30 days, one per event (`type`, entity, `summary`, `link`, `created_at`,
  `recipients`).

The OpenAPI version moves to 1.235.0.

## [1.370.0] - 2026-10-18

### Added
- **Owner routing of findings (#5962, CDG-2.3)**: findings now reach the entity's **confirmed** owner team (CDG-2.2)
  — one inbox row per team member, minus the actor and anyone the producer already notified, plus one message to the
  team's `chat_url` (a Slack message for a Slack incoming webhook, the structured event otherwise) — written in one
  transaction and throttled to one event per (team, entity, type) per hour. Seven inbox types: `owner_finding`
  (new error-level lint findings from the lint gate, on the project or the MCP endpoint), `owner_breaking_change`
  (`notify_repository_breaking_change`, which also takes `actor_id` / `already_notified`), `owner_verification_drift`
  (scheduled verification drift, on the project its `versionRef` names), `owner_gate_blocked` (a `fail` from
  `GET /v1/projects/{tenant}/{project}/gate`), `owner_trust_drift` (MCP trust drift on `?notify=true`; also the entry
  point for probe failures), `owner_shadow_api` (new shadow APIs, on the connector) and `owner_sync_failed` (a failed
  connector sync, with the redacted error). Payloads carry `entity_kind`, `entity_id`, `entity_name`, `team`,
  `summary`, `finding_id` and a relative `link`. `GET …/notifications?type=` accepts the new types.
- **Unowned findings report (#5962)**: `GET /v1/tenants/{tenant}/unowned-findings` (`teams:view`; `type`, `limit`,
  `offset`) lists findings whose entity has no confirmed owner — one row per entity and type with `occurrences`,
  `first_seen_at`, `last_seen_at` and the latest `payload`. Nothing is dropped; routing clears a row once the entity's
  owner receives that type.

### Changed
- **Webhook deliveries honour `Retry-After` (#5962)**: a `429` or `503` with `Retry-After` (seconds or HTTP date,
  capped at one hour) delays the next attempt at least that long instead of the fixed 10/60/300 s backoff.
- **Direct-URL deliveries (#5962)**: a delivery may target a team's chat URL instead of a subscription; it is sent
  unsigned through the SSRF guard with the same retries and dead-letter handling.

The OpenAPI version moves to 1.234.0.

## [1.369.0] - 2026-10-18

### Added
- **Entity owners (#5961, CDG-2.2)**: `GET|PUT|DELETE /v1/tenants/{tenant}/owners/{kind}/{id}`,
  `POST /v1/tenants/{tenant}/owners/{kind}/{id}/confirm` and bulk `POST /v1/tenants/{tenant}/owners:assign`
  (`{team, entities: [{kind, id}]}`, up to 200, all or nothing). `kind` is `project`, `catalog_item`,
  `mcp_endpoint`, `consumer` or `connector`; reads need the kind's `view` and changes its `edit` (`projects` for
  projects, catalog items and MCP endpoints, `consumer_contracts` for consumers, `imports` for connectors). An
  entity has at most one **confirmed** owner team and any number of **suggested** ones, each with its `source`
  (`manual`, `gateway_tag`, `codeowners`, `spec_extension`) and `source_ref`. Confirming keeps the source and
  records `confirmed_by` / `confirmed_at`; replacing or removing an owner that came from a suggestion turns it back
  into a suggestion. Refusals: `400 owner-invalid`, `404 owner-entity-not-found`, `404 owner-team-not-found`,
  `404 owner-no-suggestion`. Audited as `owner.assign`, `owner.confirm`, `owner.remove`, `owner.bulk_assign` and
  (importer changes) `owner.suggestions`.
- **Suggested owners from importers (#5961)**: connector syncs turn Kong `owner:<slug>` and AWS `apiome:owner`
  tags into `gateway_tag` suggestions on the synced catalog item, and report a tag naming no team as an
  `owner-team-unknown` finding ("unknown team `x` in tag"); imports read an `x-apiome-owner` root extension (or an
  `info.contact.name` that is a team slug) as a `spec_extension` suggestion; repository scans match the branch's
  CODEOWNERS file (`.github/`, root, `docs/`) to spec paths, and an `@org/<team-slug>` owner becomes a `codeowners`
  suggestion on the project imported from that path. Suggestions never notify anyone.
- **`owner` in list envelopes (#5961)**: `GET /v1/catalog/{tenant}`, `GET /v1/projects/{tenant}`,
  `GET /v1/mcp/{tenant}/endpoints` (each endpoint) and the project consumers list (each summary, beside the
  free-text `consumer.owner`) carry `owner: {team: {id, slug, name}, status, source}` — the confirmed owner, else
  the first suggestion — from one SQL join; no list read gains a statement.

The OpenAPI version moves to 1.233.0.

## [1.368.0] - 2026-10-18

### Added
- **Teams (#5960, CDG-2.1)**: `GET|POST /v1/tenants/{tenant}/teams`, `GET|PATCH|DELETE /v1/tenants/{tenant}/teams/{slug}`
  and `PUT /v1/tenants/{tenant}/teams/{slug}/members`. A team has a `slug` (derived from `name` when omitted, not
  editable), `name`, `description`, `contact_email` and `chat_url` / `oncall_url` / `docs_url` (absolute http(s)
  URLs); reads carry `member_count`, and single-team reads and member writes carry `members` (`user_id`, `role`
  `lead|member`, `email`, `name`, `added_at`), leads first. `PUT …/members` replaces the whole membership; every user
  must be a tenant member (`422 team-member-not-in-tenant`, naming them; nothing changes). Deletes are soft and free
  the slug; a team that owns entities is refused with `409 team-owns-entities` and `detail.owned_count` unless
  `?reassign_to=<slug>` names another team, which takes them over in the same transaction. Other refusals:
  `400 team-invalid`, `400 team-reassign-invalid`, `404 team-not-found`, `409 team-slug-taken`. Every write is
  appended to the access audit in its own transaction as `team.create`, `team.update` (changed fields, old and new),
  `team.members.replace` (added / removed / role changed) or `team.delete`.
- **`teams` RBAC resource (#5960)**: apiome-db V284 adds the `teams` and `team_members` tables and the `teams`
  resource — Owner and Admin get view/create/edit/delete, Editor and Viewer get view. Custom roles are not changed;
  grant `teams:*` explicitly. A user removed from a tenant leaves every team of that tenant in the same transaction
  (database trigger), and a team member who is not a tenant member is refused by the database as well as the API.

The OpenAPI version moves to 1.232.0.

## [1.367.0] - 2026-10-18

### Added
- **Connector dry run (#5958, CDG-1.7)**: `POST /v1/tenants/{tenant}/connectors/dry-run` (`imports:create`) takes a
  connector's `kind`, `baseUrl`, `scope` and, optionally, `credentials`, validates them exactly like a create, and
  asks the provider once for its inventory. It returns `itemCount`, a sample of up to 20 `items` (`remoteId`, `name`,
  `environment`, `revision`), `truncated` and the inventory `findings`; nothing is stored. A provider refusal is a
  `422` with `detail.code: "connector-check-failed"`, the error class as `detail.reason`, and the provider's message
  with any credential value redacted. A kind with no source on the deployment is a `409`
  (`connector-kind-unsupported`); a credential for a kind that takes none (`aws-apigateway`) is refused.
- **Refresh-runs ledger (#5958)**: `GET /v1/tenants/{tenant}/refresh-runs` (`imports:view`) lists Git refresh jobs
  and connector runs together, newest first, each with its `source` (`git` | `connector`), status, outcome fields
  (`errorClass`, `httpStatus`, `errorMessage`, `pullCount`, `summary`) and either its connector (`connectorId`,
  `connectorName`, `connectorKind`) or its repository (`repositoryId`, `repositoryName`, `branch`, `path`).
  `?connector=` (404 for an unknown connector), `?source=`, `?limit=` and `?offset=` filter and page it.

The OpenAPI version moves to 1.231.0.

## [1.366.0] - 2026-10-18

### Added
- **Apigee connector (#5956, CDG-1.5)**: connectors of kind `apigee` now sync. Scope `{organization, environments?}`
  (all environments when omitted); the credential goes in `PUT …/credentials` as `{"credentialJson": "…"}` — a
  service-account key (`type: service_account`) or a workload identity federation configuration
  (`type: external_account`), turned into a `cloud-platform` access token by `google-auth`.
  - Inventory: `GET https://apigee.googleapis.com/v1/organizations/{org}/apis`, `…/environments/{env}/deployments`
    and, for a proxy deployed nowhere, `…/apis/{api}/revisions`. Each environment a proxy is deployed to is an
    inventory row (environment, deployed revision as `remote_revision`, deployment start as the update time); all of a
    proxy's rows share **one** catalog item, and a revision two environments run is imported once. A proxy deployed
    nowhere is `discovered` only.
  - Definitions: `…/apis/{api}/revisions/{rev}?format=bundle` is imported by the FMT-7.3 `apigee` adapter through
    archive intake, so a bundle's declared conditions are on the item.
  - Failures name the cause: a refused credential (`invalid_grant` …), a missing IAM permission
    (`Missing permission apigee.deployments.list`) or a token without the `cloud-platform` OAuth scope
    (`ACCESS_TOKEN_SCOPE_INSUFFICIENT`).
- Sync engine: candidates with the same `deployment.catalogKey` share one catalog item, and the default importer links
  a revision label the shared item already has instead of importing it again.
- Dependency: `google-auth`.

The OpenAPI version moves to 1.230.0.

## [1.365.0] - 2026-10-18

### Added
- **Apigee proxy bundle import (#5457, FMT-7.3)**: a new `apigee` import source reads a proxy bundle (the `apiproxy/`
  zip Apigee's `?format=bundle` revision download returns — through archive intake or as raw bytes), a loose
  `ProxyEndpoint` / `TargetEndpoint` / `SharedFlow` file, or a fileset of them.
  - Each `ProxyEndpoint` is a service; each `Flow` whose condition reduces to a path and/or verb is an operation
    (`MatchesPath "/x/*"` → `/x/{segment1}`, `**` → `{path}`, no verb → `ANY`), under the endpoint's base path.
  - Each `TargetEndpoint` is a server (its URL, or a load balancer as `https://{server}<path>` with the balanced
    servers as the variable's enum).
  - `VerifyAPIKey` / `OAuthV2` (VerifyAccessToken) → `operation.extras.security`; `SpikeArrest` / `Quota` →
    `extras.rate_limits`; an `AssignMessage` setting `Access-Control-*` → `extras.cors`. PreFlow/PostFlow steps
    apply to every operation; step conditions are kept; `FlowCallout` expands a shared flow carried in the input.
  - Conditions that cannot be reduced (header/variable tests, `or`, `not`), unconditional flows and route rules
    without a target are **declared conditions** (`extras.apigee.declaredConditions`, or on the operation when part
    of the condition reduced) and coverage-ledger rows (`apigee#declared-condition.*`). Ordered route rules, fault
    rules, unmapped policies (verbatim) and unresolved steps are reported too.
  - A bundle with no ProxyEndpoint is `INPUT_SEMANTIC_INVALID`; a route rule naming a missing target endpoint is
    `INPUT_REFERENCE_UNRESOLVED`; a truncated zip is `INPUT_ARCHIVE_INVALID`.
- Archive intake treats `.xml` members as root candidates, so an uploaded bundle resolves its `APIProxy` manifest.
- The `apigee` corpus (9 valid entries incl. 4 bundle zips, 6 negatives) is now live; the corpus suites read `.zip`
  entries as binary, and the round-trip harness imports binary entries through the shared helpers.

The OpenAPI version moves to 1.229.0.

## [1.364.0] - 2026-10-18

### Added
- **Shadow-API report (#5957, CDG-1.6)**: `GET /v1/tenants/{t}/shadow-report?connector=&environment=` (`imports:view`)
  compares connector inventory with the catalog (`app.shadow_api_report`):
  - **shadow** — gateway APIs with no catalog item and no plausible match;
  - **possibleMatches** — with the best match's `tier` (`remote-id` 1.0, `host` 0.9 with base path / 0.7 host only,
    `title` up to 0.5), `confidence`, `reason` and up to three alternatives; nothing is linked automatically;
  - **undeployed** — catalog items and published Projects with an HTTP server that no connected gateway serves;
  - **drift** — linked APIs whose deployed revision the catalog does not have (RAR-2.2 comparator; a gateway with no
    revision signal is never reported);
  - **ignored** — with their reasons. An ignored item whose hosts or base path change reappears with its reason.
  - A `failing` connector is listed under `stale` with the time of its last successful run.
- Connector item actions (`imports:edit`, audited as `repository.connector.item_*`):
  `POST /v1/tenants/{t}/connectors/{id}/items/{itemId}/link` (`{"catalogItemId"}`), `…/ignore` (`{"reason"}`, kept
  with a snapshot of the hosts and base path), `…/unignore`, and `…/import` (syncs just that item, past the ignore,
  `should_import` and newer-than gates, and returns the run). `ConnectorItemOut` gains `ignoredReason`, `ignoredAt`
  and `linkedAt`.
- `catalog.connector.shadow_api_detected`: a sync that sees an API for the first time that matches nothing in the
  catalog notifies the tenant's push-webhook channels (Slack-shaped for Slack), at most once per connector per hour.
  Owner-team routing follows with CDG-2.3.
- V283: ignore/link columns on `catalog_connector_items` and `catalog_connector_notification_throttle`.

The OpenAPI version moves to 1.228.0.

## [1.363.0] - 2026-10-18

### Added
- **Azure API Management connector (#5955, CDG-1.4)**: connectors of kind `azure-apim` now sync. Scope
  `{tenantId, clientId, subscriptionId, resourceGroup, serviceName, authMethod, includeNonCurrentRevisions}`; the
  Entra ID application signs in with a client secret (`PUT …/credentials` → `{"clientSecret": "…"}`) or, with
  `authMethod: "federated"`, the deployment's workload-identity token (`AZURE_FEDERATED_TOKEN_FILE`) as a client
  assertion. Inventory over ARM (`api-version=2024-05-01`): the service (gateway URL), `/apis` + `/apis/{api}/revisions`,
  `/products` + `/products/{p}/apis`, `/namedValues` (names only) and `/backends`.
  - The current revision of each API is one catalog item (environment: the APIM instance; hosts: the API's gateway
    URL). Non-current revisions are recorded as `discovered` items and imported only with
    `includeNonCurrentRevisions` (`summary.discovered` counts them).
  - Each fetch exports the definition (`?export=true&format=openapi+json-link`, downloaded without the ARM token),
    reads the API policy and every operation policy (`format=rawxml`), and imports them with a `service.json` of
    named-value names and backends as one archive through the FMT-7.2 `azure-apim` adapter — the same input as a
    direct import of those files. The catalog revision label is `rev<n>-<digest>`; unchanged content is re-anchored.
  - Products become tags on the catalog item (the project's tags); a tag the connector added for a product the API
    left is removed.
  - An Entra ID refusal fails the run as `auth` with the `AADSTS` code in the message (`AADSTS7000222` for an
    expired client secret); an ARM refusal names ARM's code (`AuthorizationFailed`). WebSocket, GraphQL and gRPC
    APIs are `api-type-not-exported` findings.
- Sync engine hooks: a source may return `should_import(candidate) = False` (the item stays `discovered`) and may
  finish an imported item with `after_import(db, candidate, project_id)`; a failing hook is counted as
  `summary.postImportFailed` and never fails the import.

### Fixed
- A catalog item imported from an **archive** (`format_metadata.intakeKind: "archive"`) is now rebuilt from its
  captured archive through the adapter's `parse_fileset`, so its parsed model, Format details and conversion work.
  Before, the base64 capture was parsed as text and the rebuild returned nothing.
- Intake secret scrub: a quoted `true`/`false` XML attribute under a secret-named name (`<cors
  allow-credentials="true">`) is no longer redacted. Redacting it withheld every APIM policy archive with CORS.

The OpenAPI version moves to 1.227.0.

## [1.362.0] - 2026-10-18

### Added
- **Azure API Management import (#5456, FMT-7.2)**: a new `azure-apim` import source reads an APIM API from a policy
  document (`<policies>`, or a `<policies-composition>` of scoped documents), an ARM template of
  `Microsoft.ApiManagement/service/…` resources, or an APIM-exported OpenAPI definition with its policy files (a
  fileset; members are scoped by name: `policy.xml`, `operations/{operationId}.xml`, `products/{name}.xml`,
  `global.xml`). The definition is normalized by the OpenAPI path (an ARM template's operations are first written
  as the OpenAPI document APIM exports); the policies are then composed per operation, `<base />` expanding to the
  parent scope at its position, and interpreted:
  - `validate-jwt` / `validate-azure-ad-token` / `check-header` → `operation.extras.security`;
  - `rate-limit` / `rate-limit-by-key` / `quota` / `quota-by-key` → `extras.rate_limits`;
  - `set-backend-service` and the `authentication-*` policies → `extras.backend` (an API-scope backend URL is also
    added as a server named `backend`);
  - `rewrite-uri` / `set-method` / `set-query-parameter` → `extras.rewrite`; `cors` → `extras.cors`;
    `ip-filter` → `extras.access`.

  Every record carries `provenance: "declared"` and `derivedFrom` (`definition` or `policy`, with `policyScope`).
  Unmapped policies are kept verbatim in `extras.azure_apim.unmapped` and reported on the coverage ledger
  (`apim#policy.*`, `apim#unknown-policy.*`). An undeclared `{{named value}}`, or a `backend-id` missing from the
  declared backends, is `INPUT_REFERENCE_UNRESOLVED`; a policy without pipeline sections is
  `INPUT_SEMANTIC_INVALID`. Credentials in policies (`password`, `client-secret`) are never stored.
- Detection: the `openapi` adapter steps down to 0.7 for a definition carrying APIM's `Ocp-Apim-Subscription-Key`
  scheme or an `azure-api.net` server, which `azure-apim` claims at 0.9.
- The `azure-apim` corpus (8 valid entries, 6 negatives) is now live: goldens, round-trip matrix row,
  version-coverage declaration and parity report.

The OpenAPI version moves to 1.226.0.

## [1.361.0] - 2026-10-17

### Added
- **AWS API Gateway connector (#5954, CDG-1.3)**: `aws-apigateway` connectors now sync (`syncableKinds`).
  - Scope `{"roleArn", "externalId", "regions": [...]}`; Apiome calls `sts:AssumeRole` from its own AWS identity and
    never stores keys: `PUT …/credentials` on this kind is a 422 `connector-credentials-refused`, and a base URL is
    refused. Scope is checked on create and update (422 `connector-invalid`).
  - **Dry run on create and on scope change**: assume the role, `GetAccount`, list one REST and one HTTP API per
    region. A refusal is a 422 `connector-check-failed` whose `detail.reason` names the missing permission
    (`sts:AssumeRole on …`, `apigateway:GET on arn:aws:apigateway:<region>::/account`, …).
  - Inventory from `GetRestApis` + `GetStages` and `GetApis` + `GetStages`; **one catalog item per deployed stage**:
    `environment` = stage, invoke URL in `hosts`, `deploymentId` = remote revision. Definitions from `GetExport`
    (`oas30`, `extensions=apigateway`) and `ExportApi` (`OAS30`, `IncludeExtensions`), imported by the FMT-7.1
    `aws-apigateway` adapter unchanged.
  - `deployment` records region, account, API id/type, stage, deploymentId, invoke URL, tags and
    `suggestedOwners` from the `apiome:owner` tag. Findings: `region-empty`, `stage-not-deployed`,
    `websocket-api-not-exported`, `owner-tag-invalid`.
  - Access denials fail the run with `errorClass: "auth"` and the missing permission named; a deployment with no AWS
    identity fails with `invalid-configuration`.
- Connector runs list every skipped candidate with its reason under `summary.unchangedItems`
  (`remoteId`, `revision`, `reasonCode`, `reason`); the AWS source explains it as an unchanged `deploymentId`.
- Connector sources can register a `connection_check` (dry run) and declare `accepts_credentials=False`.

### Fixed
- The intake secret scrub no longer redacts an unquoted `true` / `false` / `null` under a secret-named key
  (`allowCredentials: true` in an HTTP API export's CORS block was turned into a string). A quoted value is still
  redacted.

### Dependencies
- `boto3` (runtime) and `moto` (dev, tests).

The OpenAPI version moves to 1.225.0.

## [1.360.0] - 2026-10-17

### Added
- **AWS API Gateway import (#5455, FMT-7.1)**: a new `aws-apigateway` import source reads an exported REST API
  (`GetExport`, OpenAPI 3.0 or Swagger 2.0 with `extensions=apigateway`) or HTTP API (`ExportApi` with
  `includeExtensions`). The base document is parsed and normalized by the OpenAPI path; the extensions are then
  interpreted, each result labelled `provenance: "declared"`:
  - `x-amazon-apigateway-integration` → `operation.extras.backend` (kind `lambda-proxy` / `aws-proxy` /
    `aws-service` / `http-proxy` / `http` / `mock`, URI, connection, stage variables), with the verbatim
    integration under `extras.aws_apigateway`;
  - `x-amazon-apigateway-authorizer` / `-authtype` / `-auth` / `-api-key-required` → `operation.extras.security`
    (the shape `canonical_security` reads: `authorization`, `bearer`, `awsSigv4`, `apiKey`, …);
  - `x-amazon-apigateway-request-validator(s)` → `operation.extras.validation`;
  - `x-amazon-apigateway-cors` → `api.extras.cors`, and a mock `OPTIONS` integration's `Access-Control-Allow-*`
    headers → that operation's `extras.cors`;
  - `x-amazon-apigateway-any-method` → an `ANY` operation.

  Documented extensions without a canonical construct and unknown extensions are preserved verbatim and reported
  (`extras.aws_apigateway.extensions`, coverage-ledger rows `aws#extension.*` / `aws#unknown-extension.*`). An
  integration with no or an unknown `type` is `INPUT_SEMANTIC_INVALID`. A split export whose schemas live in a
  sibling file imports as one API: cross-file components are hoisted (`openapi_fileset_bundle`).
- Detection is not greedy: only an OpenAPI/Swagger document with an AWS extension at the root, a server, a path
  item, an operation or a security scheme is claimed. The `openapi` adapter steps down to 0.8 for such documents,
  so the two are never reported as ambiguous; a plain OpenAPI document still routes to `openapi`.
- The `aws-apigateway` corpus (7 valid entries, 5 negatives) is now live: goldens, round-trip matrix row,
  version-coverage declaration and parity report.

The OpenAPI version moves to 1.224.0.

## [1.359.0] - 2026-10-17

### Added
- **Kong connector: Konnect control planes and the Admin API (#5953, CDG-1.2)**: `kong-konnect` and `kong-admin`
  connectors now sync (`syncableKinds` lists both).
  - `kong-konnect` reads `GET /v2/control-planes/{cp}/core-entities/services|routes|plugins|consumers`, paged by
    `size` and Kong's `offset` token, with a personal or system access token (`{"token": "kpat_…"}`). Scope
    `{"region": "us"|"eu"|"au"|"me"|"in"|"sg", "controlPlanes": [...]}`; no control planes means every control plane
    the token can read. `kong-admin` reads `GET /services|routes|plugins|consumers` on the connector's base URL, with
    an optional `Kong-Admin-Token` and scope `{"workspace", "environment"}`. Both scopes are checked on create and
    update (422 `connector-invalid`).
  - One catalog item per Kong service. Its document is the declarative file the `kong` adapter already parses
    (the service with its routes and plugins nested, plus global plugins), so a synced service imports exactly
    like that file. Its revision is the document's digest, so changing one route imports one new revision.
  - Inventory items gain `deployment` (V282): control plane id and name (or workspace), tags, enabled, protocols,
    hosts, paths, `updatedAt` and `suggestedOwners` from `owner:<team-slug>` tags. `environment` is the control
    plane's name.
  - Runs record connector-level `summary.findings`: `route-without-service`, `owner-tag-invalid`,
    `consumer-plugins-not-imported`, `consumers-not-imported`.
  - A revoked token fails the run with `errorClass: "auth"`, `httpStatus: 401` and Kong's error message. New error
    classes `invalid-configuration` (missing token or base URL) and `address-refused` (SSRF guard).
- A connector sync that adds a revision to an existing catalog item writes a change report between the two
  revisions (shared change report plus the CTG-1.1 classified diff under `classifiedChanges`), audited as
  `catalog.connector.change_report.generated`.
- The Kong import's coverage ledger lists every non-auth plugin as `partially-mapped`
  (`gateway#plugin.<name>.<scope>`, from `extras.gateway.unmodeled_plugins`) instead of leaving it out.

The OpenAPI version moves to 1.223.0.

## [1.358.0] - 2026-10-17

### Added
- **Catalog connectors and the refresh-source protocol (#5952, CDG-1.1)**: the repository auto-refresh engine now
  syncs two kinds of source through one `app.refresh_source.RefreshSource` protocol (`list_candidates`, `fetch`,
  `freshness_key`, `describe`). Git branches are the first implementation, with no behaviour change (goldens on the
  enqueued job and the RAR-4.1 executor output). Catalog connectors are the second:
  - `GET|POST /v1/tenants/{t}/connectors`, `GET|PATCH|DELETE …/connectors/{id}`, `POST …/connectors/{id}/sync`,
    `GET …/connectors/{id}/items`, `GET …/connectors/{id}/runs`, `PUT …/connectors/{id}/credentials`, on the
    existing `imports` permissions.
  - Kinds `kong-konnect`, `kong-admin`, `aws-apigateway`, `azure-apim`, `apigee`, `url`, `schema-registry`,
    `mcp-registry`. A kind syncs only once a source is registered for it (`syncableKinds`); a sync of any other
    kind is a 409 `connector-kind-unsupported`.
  - Credentials are sealed with the MCP credential envelope, replaced as a whole, and never returned, logged or
    audited (503 `connector-encryption-unconfigured` without `APIOME_MCP_CREDENTIAL_ENCRYPTION_KEYS`).
  - Base URLs pass the SSRF rule: a private-range URL is a 422 `connector-base-url-refused` with
    `reason: "private-address"`, unless `APIOME_CONNECTOR_PRIVATE_NETWORK_ALLOWLIST` (CIDRs) covers it.
  - A sync imports each new remote revision as a **catalog item** revision (OpenAPI included) with the source
    descriptor `{inputKind: "connector", connectorId, remoteId, remoteRevision}` in its format metadata, marks APIs
    gone from the inventory `missing` (never deleted), and records a failed run with `errorClass` and `httpStatus`
    when nothing could be fetched.
  - Runs are rows of `tenant_repository_refresh_jobs` (`refreshSource: "connector"`). Their pulls count against the
    tenant polling quota and the quota telemetry, and they are audited as `repository.connector.*`, which the
    repository audit export includes. Scheduled syncs run in the refresh sweep's tick.
- `GET /v1/catalog/{t}/{id}`: `source.kind` can be `connector`, and `source.connector` carries the connector,
  remote API and remote revision.

The OpenAPI version moves to 1.222.0.

## [1.357.0] - 2026-10-17

### Added
- **Class summary in the version list (#3229, CLI 7.1)**: `GET /v1/classes/{tenant}?version_id=…` now returns, on
  every class, `property_count` (its top-level properties) and `tags` (`{id, project_id, name, color, description}`,
  sorted by name), in the same query — so a list view needs no per-class calls. The unfiltered list and the other
  class responses leave `property_count` `null`. Used by `apiome classes list`.

The OpenAPI version moves to 1.221.0.

## [1.356.0] - 2026-10-17

### Added
- **Force-delete a property (#3227, CLI 6.5)**: `DELETE /v1/properties/{tenant}/{project}/{property_id}?force=true`
  removes every class attribute that uses the property (with its nested attributes) in live, unpublished versions and
  soft-deletes the property, in one transaction; the response adds `detached` (how many class attributes were
  removed). If any use is in a published version, nothing changes and the request fails with 409
  `{code: "property_in_published_version", uses: [{class_name, attribute_name, version}]}`. Without `force` the
  delete is unchanged. Used by `apiome properties delete --force`.

The OpenAPI version moves to 1.220.0.

## [1.355.0] - 2026-10-17

### Added
- **Conditional property updates (#3226, CLI 6.4)**: `PUT /v1/properties/{tenant}/{project}/{property_id}` accepts
  `expectedUpdatedAt` (or `expected_updated_at`), the property's `updated_at` as last read. When the property changed
  since, nothing is written and the request fails with 409 `{code: "update_conflict", current_updated_at}`; the check
  and the write are one statement. Used by `apiome properties update --from-file`.
- **Required everywhere (#3226)**: the same PUT accepts `requiredEverywhere: true|false`, which sets `required` on every
  class attribute that uses the property in an unpublished version, in the same transaction as the property update.
  Published versions are left alone. The response carries `required_everywhere_result`
  `{changed, unchanged, skipped_published}`. Used by `apiome properties update --required-everywhere`.

The OpenAPI version moves to 1.219.0.

## [1.354.0] - 2026-10-17

### Added
- **Which class attributes use a property (#3224, CLI 6.2)**: `GET /v1/properties/{tenant}/{project}/{property_id}`
  returns `usage`, one `{class_name, attribute_name, required}` entry per distinct class attribute that references the
  property across the project's live versions, sorted by class then attribute. `required` is true when the class
  property's data has `"required": true`. Soft-deleted classes and versions do not count. The list, create and update
  responses leave `usage` `null`. Used by `apiome properties show`.

The OpenAPI version moves to 1.218.0.

## [1.353.0] - 2026-10-17

### Added
- **Where each property is used (#3223, CLI 6.1)**: `GET /v1/properties/{tenant}/{project}` returns, on every
  property, `used_by` (the distinct names of the classes that use it, across the project's live versions, sorted)
  and `used_by_count` (how many class properties reference it). Soft-deleted classes and versions do not count.
  The single-property, create and update responses leave both `null`. Used by `apiome properties list --unused`.

The OpenAPI version moves to 1.217.0.

## [1.352.0] - 2026-10-17

### Added
- **Change a version tag's message (#3265, CLI 11.6)**: `PATCH /v1/version-tags/{tenant}/{project}/{tag_id}`
  accepts `message` (up to 2000 characters). Omit it to keep the current message; `null` or `""` clears it.
  A message-only PATCH is now a valid update. Used by `apiome tags update --description`.

The OpenAPI version moves to 1.216.0.

## [1.351.0] - 2026-10-17

### Added
- **Version tag creator email (#3263, CLI 11.4)**: `GET /v1/version-tags/{tenant}/{project}` now returns
  `created_by_email` on each tag (joined from `apiome.users`; `null` when the creator is unknown or deleted),
  so `apiome tags list` can show who created each tag. Other tag responses leave it `null`. Tags still record
  no updater and no move history.

The OpenAPI version moves to 1.215.0.

## [1.350.0] - 2026-10-16

### Added
- **Frozen OpenAPI snapshots (#3214, CLI 4.7)**: freezing a published version stores the exact bytes
  `GET /v1/schema/{tenant}/{project}/{version}` serves (V279 `apiome.version_spec_snapshots`). While
  frozen, that route returns the stored bytes verbatim — with an `X-Apiome-Snapshot-Sha256` header — and
  counts each download, so later class / property / path edits no longer change the document.
  - `POST /v1/versions/{tenant}/{project}/{version_record_id}/freeze-schema` takes an optional
    `{ dryRun }` and returns `{ frozen, sha256, sizeBytes, snapshotUrl, classCount, propertyCount,
    pathCount, downloadCount, … }`. `409 version_not_published` for a draft; `409 already_frozen`.
  - `GET …/freeze-schema` reports the snapshot (or `frozen: false`).
  - `DELETE …/freeze-schema` unfreezes; `409 snapshot_downloaded` once the snapshot was fetched,
    unless `?force=true` from a tenant administrator (`403 force_unfreeze_requires_admin` otherwise).

### Changed
- `POST …/freeze-schema` used to only capture class schemas into `apiome.class_schema` (and returned
  `400` when they already existed — true of every published version). It now freezes the OpenAPI
  document, still captures the class schemas when they are missing, and returns the snapshot instead of
  the version.

The OpenAPI version moves to 1.214.0.

## [1.349.0] - 2026-10-16

### Added
- **Unpublish with a reason, tag moves and a webhook (#3213, CLI 4.6)**: `POST /v1/versions/{tenant}/{project}/{version_record_id}/unpublish`
  takes an optional body `{ reason, keepTags, silent, dryRun }`.
  - `reason` (up to 2000 characters) is stored with `unpublishedAt` / `unpublishedBy` (V278) and
    returned on the version (`unpublishReason`, `unpublishedAt`, `unpublishedBy`; `publish` pull section).
  - Unless `keepTags`, the version tags on the revision move to the project's next-most-recent
    published revision in the same transaction. Immutable tags, protected tags (for a non-administrator)
    and tags with nowhere to go stay; the response lists `tagsMoved` and `tagsKept`.
  - A `version.unpublished` push-webhook event goes to every active subscription unless `silent`, which
    only a tenant administrator may ask for (`403` `silent_requires_admin`).
  - `dryRun: true` returns the plan (`tagsMoved`, `tagsKept`, `previousPublishedVersionLabel`,
    `publishedVersionsRemaining`, `webhookSubscribers`) without writing anything.
  - An empty body still works; it now also moves the tags and sends the webhook.

The OpenAPI version moves to 1.213.0.

## [1.348.1] - 2026-10-16

### Fixed
- **Fork into a project that already has the version (#3211, CLI 4.4)**: `POST /v1/versions/{tenant}/{project}/fork`
  with a `versionId` the target project already has now returns `409` with `detail` `{ "code":
  "version_exists", "message", "version_id" }`, instead of a `400` carrying the database's
  unique-constraint text. `apiome versions fork` maps it to exit 6.

The OpenAPI version moves to 1.212.1.

## [1.348.0] - 2026-10-16

### Added
- **All migration plans of a project (#3207, CLI 3.6)**: `GET /v1/migration-plans/{tenant}/projects/{project_id}`
  returns `{ "plans": [{ id, from_version_id, to_version_id, created_at, updated_at, rules: [{ class_name,
  source_property, rule }] }] }` in one call — plans ordered by version pair, rules by class and source
  property, each rule as stored. Requires `projects:view`; `404` for an unknown project. Used by
  `apiome projects export`, which previously would have had to probe every version pair.

The OpenAPI version moves to 1.212.0.

## [1.347.0] - 2026-10-16

### Added
- **Permanent project delete and deletion impact (#3206, CLI 3.5)**:
  - `DELETE /v1/projects/{tenant}/{project}?permanent=true` deletes the project and everything under
    it — revisions, classes and their properties, project properties, paths, branches and merge
    sessions — irreversibly, in one transaction (the same cascade the web app's "Permanently delete"
    ran). It also accepts an already soft-deleted project. Audit history is never deleted: when a
    revision is referenced by audit records the request is refused with `409` `detail.code`
    `delete_blocked` (naming the table) and nothing is removed. Without `permanent` the route is the
    unchanged soft delete; both responses now carry `permanent`.
  - `GET /v1/projects/{tenant}/{project}/deletion-impact` counts what a permanent delete would remove:
    `versions` (all, soft-deleted included), `published_versions` (live and published),
    `unpublished_versions`, `classes`, `properties`, `paths`, plus `slug`, `name` and `deleted`.
    Requires `projects:view`; works for soft-deleted projects.

The OpenAPI version moves to 1.211.0.

## [1.346.0] - 2026-10-16

### Added
- **Optimistic concurrency on project updates (#3205, CLI 3.4)**: `PUT
  /v1/projects/{tenant}/{project}` accepts an optional `expectedUpdatedAt` — the project's
  `updated_at` as the caller last read it. When set, the update applies only if the project is
  unchanged since; the check is part of the `UPDATE` statement, so a concurrent edit cannot slip in
  between. Otherwise nothing is written and the response is `409` with `detail` `{ "code":
  "update_conflict", "message", "current_updated_at" }`. Requests without the field behave as
  before. Used by `apiome projects update` (exit 6 on a conflict).

The OpenAPI version moves to 1.210.0.

## [1.345.0] - 2026-10-16

### Added
- **Catalog categorization (#3755, MFI-6.3)**: catalog items are categorized by **paradigm**
  (auto-derived — the latest revision's protocol), **domain** (manual — the project
  `metadata.domainCategory` allow-list) and free-form **tags** (manual — new V277
  `apiome.artifact_tags`, generic over artifact kind so MCP endpoints can use it for MCAT-9.3).
  - `GET /v1/catalog/{tenant}` items carry `paradigm`, `domain` and `tags`, and the list takes
    repeatable `protocol`, `format`, `domain` and `tag` filters: values within a facet OR, facets
    AND, an unknown value narrows to nothing, and `uncategorized` selects items with no value.
    The detail (`GET …/{item}`) carries the same three fields.
  - `GET /v1/catalog/{tenant}/facets` returns `{ total, matched, facets: { protocols, formats,
    domains, tags } }`, each bucket `{ value, label, count, selected }` counted over the items
    the *other* facets leave.
  - `PUT /v1/catalog/{tenant}/{item}/categories` with `{ "domain", "tags" }` replaces the item's
    domain (null/`"none"` clears it) and tag set (lower-cased, de-duplicated, at most 20 of 1–64
    characters; `uncategorized` is reserved). Requires `projects:edit`; `422` for an unknown
    domain or an invalid tag, `404` for an id that is not a live catalog item.

The OpenAPI version moves to 1.209.0.

## [1.344.0] - 2026-10-16

### Added
- **Per-format conversion packs (#4009, MFI-22.8)**: catalog → OpenAPI conversion now runs each
  source format through its own pack (`app.conversion_packs`) — OData, Smithy, gRPC/Protobuf,
  GraphQL, AsyncAPI, CloudEvents, WSDL, Avro, RAML, API Blueprint and WADL. The RAML (MFI-15.5),
  API Blueprint (MFI-16.4) and WADL (§9.3) migrate-to-OpenAPI notes resolve to their packs.
  - **gRPC/Protobuf** honors `option (google.api.http)`: an annotated method converts to its
    declared method and path (`body`, custom verbs; `additional_bindings` reported) instead of a
    synthesized `POST /{Service}/{Method}`. A service with methods but no annotation is now
    capped at the **low** tier, with the loss `grpc-no-http-annotations`.
  - **Smithy** honors `@http(method, uri)`; `@endpoint` and `@hostLabel` are charged as
    losses (`smithy-endpoint-trait`, `smithy-hostLabel-trait`).
  - **AsyncAPI** and **CloudEvents** are capped at the **low** tier (they previously reported
    medium), with the loss `event-schemas-only`.
  - **Every pack** renames schema names OpenAPI forbids (WSDL/WADL XML-qualified names, Avro
    map names) together with every reference, so those conversions are now valid OpenAPI 3.1.
  - Each pack names its authoritative converter (`odata-openapi`, `smithy-openapi`,
    `protoc-gen-openapiv2`, `sofa-openapi`) and uses it through the toolchain runner when one is
    registered (source on stdin, OpenAPI JSON on stdout), falling back natively otherwise. None
    ships in the image, so all conversions are native today.
  - `POST /v1/catalog/{tenant}/{item}/convert?dryRun=true` adds `conversionPack` (key, label,
    `native`/`external` strategy, refinements, documented losses, expected tiers, converter
    status); null for OpenAPI/Swagger/TypeSpec and formats without a pack.
- **Protobuf import with `google.api.http`**: `google/api/annotations.proto` and
  `google/api/http.proto` are vendored (Apache-2.0) and supplied to `buf build` when a source
  imports them and does not carry its own copy, so annotated `.proto` files import and convert.

The OpenAPI version moves to 1.208.0.

## [1.343.0] - 2026-10-16

### Added
- **Catalog provenance: fingerprint and routing reason (#4093, MFI-25.8)**: a non-dry-run adapter
  import now records two more keys on the created revision's `format_metadata`, which the catalog
  item detail (`GET /v1/catalog/{tenant}/{item}`) already returns under `formatMetadata`:
  - `fingerprint` — the adapter's revision fingerprint (the `VERSION_FINGERPRINT` phase), omitted
    when none was computed;
  - `routingReason` — the `routing_decision.reason` the import recorded when it routed the source
    to the catalog rather than a Project.

  The catalog item's **Provenance** tab shows both. Items imported earlier carry neither: the tab
  shows the fingerprint as not recorded and derives the routing sentence from the format. No
  schema change (the bag is free-form); the OpenAPI version moves to 1.207.0.

## [1.342.0] - 2026-10-12

### Added
- **Admin reset of a user's two-factor (#5656, TFA-1.2)**: a user who has lost their authenticator
  and their backup codes can now be let back in.
  - `POST /v1/admin/users/{user_id}/two-factor/reset` — the installation's super-admin, for any
    user (`401` without a super-admin session, `403` with a bad one, `404` for an unknown user).
  - `POST /v1/access/{tenant_slug}/members/{user_id}/two-factor/reset` — a workspace **owner**, for
    an active member who belongs to **no other workspace**. `403 owner_required` for anyone else
    and `403 session_required` for an API key; `404 member_not_found` for a user who is not an
    active member; `409 multi_tenant_member` when the member also belongs elsewhere (two-factor
    protects the whole account, so that case is the super-admin's); `409 self_reset` for the
    caller's own account.

  Both take `{ "reason", "confirm" }`: a reason of 10–500 characters, and the target's email
  address typed out (`422 invalid_reason` / `confirmation_mismatch`). The reset deletes the user's
  `two_factor` row, clears `"twoFactorEnabled"`, removes their trusted-device records and any
  second-factor challenge in flight, and deletes every one of their sessions — and appends the
  audit rows **in the same transaction**: an `auth_events` row of the new type `two_factor_reset`
  (actor, target, reason), plus `member.two_factor_reset` on the workspace's access audit when an
  owner did it. The response says what was cleared; emailing the user is done by the web app.
  Migration V276 adds `users.two_factor_reset_at`, which the app reads to prompt the user to enrol
  again. The OpenAPI version moves to 1.206.0.

### Changed
- `Database.write_auth_event` and `Database.write_access_audit` now share their chain-and-insert
  step with cursor-level helpers (`_append_auth_event`, `_append_access_audit`), so a caller can
  append an audit row inside its own transaction. Their behaviour is unchanged.

## [1.341.0] - 2026-10-11

### Security
- **Linked-account tokens are encrypted at rest (#4960, OLO-7.3 follow-up)**: the OAuth access and
  refresh tokens and the personal access tokens stored for linked accounts
  (`apiome.external_auth_providers`) were plaintext, so a database read — a leaked backup, a
  replica, an injection — yielded live credentials to users' repositories. They are now sealed with
  AES-256-GCM envelope encryption (`app.linked_account_token_crypto`, the same scheme as the MCP,
  SDK-registry and upstream-credential vaults, under its own magic) and stored as
  `enc:v1:<key_version>:<base64>`. apiome-ui seals a token when it writes it; apiome-rest opens it
  in one place (`Database.get_external_auth_provider_for_user`), so repository scans, imports,
  webhook rotation and SDK delivery are unchanged. The staged OAuth sign-up token set
  (`oauth_signup_pending.account_json`) is sealed the same way, and Better Auth now seals its own
  copies in `apiome.account`. Migration V275 clears the plaintext copies nothing reads and
  corrects the column comments.

  **Operators must act.** Set `APIOME_LINKED_ACCOUNT_TOKEN_ENCRYPTION_KEYS` — a JSON map of
  key-version to base64 32-byte key — to the **same value in apiome-rest and apiome-ui**, then seal
  the rows written before the upgrade with `python -m app.seal_linked_account_tokens`
  (`--dry-run` previews; it prints counts only and is safe to re-run). Until the key is set,
  existing plaintext rows still read, sign-in and account linking still work, but no new provider
  token is stored and saving a personal access token is refused — a token is never written in
  plaintext. Rotate by adding a higher key-version to the map in both services and running the
  command again. No endpoint changed shape; the OpenAPI version moves to 1.205.1.

## [1.340.0] - 2026-10-11

### Added
- **Installation sign-up policy (#5653, SGN-1.4)**: who may create an account is now a
  database-stored setting with `AUTH_SIGNUP_DISABLED` as the fallback, replacing the env flag as the
  only control. `GET /v1/admin/signup-policy` returns the effective policy — `mode` (`open`,
  `invite_only` or `closed`), `allowed_email_domains`, `source` (`db` or `env`) and `env_mode` —
  and `PUT /v1/admin/signup-policy` stores it, or clears it with `"mode": null` so the installation
  reverts to env. Both need the super-admin session (`401` without one, `403` with a bad one); an
  unknown mode or a malformed domain is a structured `422` (`invalid_mode`,
  `invalid_email_domain`). Every change writes an `apiome.signup_policy_audit` row in the same
  transaction (migration V274). The policy is enforced by one gate
  (`app.signup_policy.signup_rejection_code`) for the email form and every OAuth provider, and is
  cached for `SIGNUP_POLICY_CACHE_TTL_SECONDS` (default 30), so a change needs no restart. Two auth
  error codes join the contract: `signup-invite-only` and `signup-domain-not-allowed`. With no
  stored policy, behaviour is unchanged. The OpenAPI version moves to 1.205.0.

## [1.339.1] - 2026-10-07

### Added
- **Generated REST reference on the documentation site (#5628, DOCS-1.11)**:
  `scripts/generate_rest_reference_docs.py` renders `openapi.yaml` into
  `apiome-docs/docs/reference/rest/` — one page per tag (plus `untagged`) with every operation's
  parameters, request body, responses and the schemas it uses. The index records the document's
  SHA-256 (`openapi_sha256`), and `yarn docs:check` fails when `openapi.yaml` changes without
  regenerating; `--check` and `tests/test_rest_reference_docs.py` fail on stale pages. Rendering
  lives in `app.rest_reference_doc`. No API change; the OpenAPI version moves to 1.204.1.

## [1.339.0] - 2026-10-07

### Changed
- **Guide pages moved to the documentation site (#5619, DOCS-1.2)**: every `docsPage` the API
  returns now names a page of the Docusaurus site instead of the retired `docs/guide/` folder —
  e.g. `GET /v1/lint/rules` → `"docsPage": "apiome-docs/docs/build/lint-rules.md"`. The value is
  still a monorepo-relative source path; `apiome-ui` resolves it to
  `https://apiome.github.io/apiome/build/lint-rules`. Affected fields: lint-rule catalog and
  style-guide `docsPage`, blocking-rule `docs_page` (schema → `build/lint-rules`, MCP →
  `govern/mcp-*-rules`), axis `algorithmDocsPage` (`build/axis-score`) and import-preflight rule
  links. Blocking schema-rule `reference` URLs now point at the site
  (`https://apiome.github.io/apiome/build/lint-rules#<rule>`).
  - New `app.docs_site` builds those paths, the site URLs and the pages' front matter.
  - `scripts/generate_lint_rule_docs.py`, `generate_supported_formats_doc.py` and
    `generate_format_counts.py` write into `apiome-docs/docs/**`; generated pages open with front
    matter and mark rule / format anchors as heading ids (`### `rule.id` {#rule-id}`).
  - OpenAPI `info.version` 1.204.0 (description text only).

## [1.336.0] - 2026-10-06

### Added
- **Agent toolset description enrichment (#4531, AGX-1.3)**: flags tools an agent will struggle
  with, and lets the copilot propose better descriptions that a person reviews before any agent
  sees them.

  ```bash
  curl -sX POST "$APIOME/v1/tenants/acme/agent-toolsets/$TOOLSET/enrichment" -H "Authorization: Bearer $JWT"
  curl -sX PATCH "$APIOME/v1/tenants/acme/agent-toolsets/$TOOLSET/enrichment/$PROPOSAL" \
       -H "Authorization: Bearer $JWT" -H 'Content-Type: application/json' -d '{"decision": "accept"}'
  curl -s "$APIOME/v1/tenants/acme/agent-toolsets/$TOOLSET/compiled" -H "Authorization: Bearer $JWT"
  ```

  - **Agent-hostile flags** with machine-readable reasons: `missing-description`,
    `thin-description`, `missing-examples`, `undocumented-errors`,
    `missing-parameter-description`, `thin-parameter-description`. They feed AGX-4.4.
  - **Copilot proposals** from an Ollama chat model (`APIOME_AGENT_ENRICHMENT_MODEL`; unset means
    flag-only), written only from the spec's own documentation. The pass is idempotent and asks
    about at most 20 operations per run.
  - **Human review.** `accept` (optionally edited) or `reject`. Only accepted text is compiled, and
    only while the toolset's new `descriptionEnrichment` setting is on (the default). V273 adds
    `agent_toolset_enrichments`; its CHECK makes accepted text without a review unrepresentable.
  - **`GET …/compiled`** returns the toolset as agents are served it.
  - Audited as `agent.toolset.enrichment.run` / `agent.toolset.enrichment.review` (metadata only).
  - New `app.ollama_chat`: the stdlib Ollama chat client for REST-side copilot features.
  - Docs: `docs/agent_toolset_enrichment.md`.

## [1.333.0] - 2026-10-05

### Added
- **Agent toolsets: tool selection & curation (#4530, AGX-1.2)**: a tenant decides which
  operations of a published version its AI agents may call as MCP tools. **Safe by default:**
  reads on, write operations opt-in, each with an explicit confirmation.

  ```bash
  curl -sX POST "$APIOME/v1/tenants/acme/agent-toolsets" \
       -H "Authorization: Bearer $JWT" -H 'Content-Type: application/json' \
       -d '{"versionId": "'"$VERSION"'"}'
  curl -sX PATCH "$APIOME/v1/tenants/acme/agent-toolsets/$TOOLSET/tools/$TOOL" \
       -H "Authorization: Bearer $JWT" -H 'Content-Type: application/json' \
       -d '{"enabled": true, "confirmWriteOp": true}'
  ```

  - **Two tables (V270).** `agent_toolsets`: one per published version, with `enabled` and
    `target` (`prod` | `mock`, consumed by AGX-2.4). `agent_toolset_tools`: one row per callable
    operation, holding the canonical operation key, the AGX-1.1 compiled tool name, `write_op`,
    `enabled`, and who confirmed an enabled write op and when.
  - **Seeding.** Creating a toolset enables `GET`/`HEAD` operations and GraphQL queries
    (deprecated ones excepted). Every other operation is a write op and starts disabled. Enabling
    one without `confirmWriteOp: true` is a `422 agent-toolset-write-op-unconfirmed`, and a
    database CHECK makes an enabled but unconfirmed write op unrepresentable.
  - **Seven routes** under `/v1/tenants/{t}/agent-toolsets`: list (`?versionId`), create, get
    (with tools), `PATCH` (`enabled` / `target`), `DELETE`, `GET …/{id}/tools`, and
    `PATCH …/{id}/tools/{toolId}`. Guarded by the existing `api_keys` permissions; no new RBAC
    resource.
  - **Audited.** `agent.toolset.create`, `agent.toolset.update` (before/after),
    `agent.toolset.delete` and `agent.toolset.tool.update` (operation, write-op flag, enabled
    before/after, confirmation time), with metadata only.
  - Docs: `docs/agent_toolsets.md`.

### Changed
- **AGX-2.2 / AGX-3.1 handoffs closed.** V270 deletes upstream credentials and agent keys whose
  toolset does not exist, then gives both `toolset_id` columns a `(tenant_id, toolset_id)` foreign
  key to `agent_toolsets` with `ON DELETE CASCADE`. Deleting a toolset now deletes its upstream
  credentials and agent keys. `POST /agent-keys` and the upstream-credential list/create routes
  answer `404 agent-toolset-not-found` for a toolset that is not in the caller's tenant.
- apiome-mcp's agent-access middleware now reads a key's enabled tools from the toolset by
  default (`toolset_enabled_tools`), instead of failing closed on every request.

## [1.332.0] - 2026-09-17

### Added
- **Agent keys (#4537, AGX-3.1)**: a new kind of API key for AI agents. Each one is bound to one
  agent toolset, limited to an explicit tool allowlist, and can expire. It is the credential an
  agent presents to the MCP agent runtime, and the identity that quotas (AGX-3.2) and usage
  analytics (AGX-3.3 / 3.4) will attach to.

  ```bash
  curl -sX POST "$APIOME/v1/tenants/acme/agent-keys" \
       -H "Authorization: Bearer $JWT" -H 'Content-Type: application/json' \
       -d '{"name": "claude-desktop", "toolsetId": "'"$TOOLSET"'",
            "toolAllowlist": ["listPets", "getPetById"], "expiresAt": "2026-12-31T00:00:00Z"}'
  ```

  - **`api_keys` extended (V269).** `kind` (`workspace` | `agent`; existing rows are
    `workspace`), `toolset_id` and `tool_allowlist` (a JSON array of AGX-1.1 tool names, at most
    1024, no wildcard). `expires_at` is reused. CHECKs keep the two kinds exclusive and pin agent
    keys to the scope `agent:invoke`.
  - **Five routes** under `/v1/tenants/{t}/agent-keys`: list (`?toolsetId`, `?includeRevoked`),
    create, get, `PUT …/{id}/allowlist`, and `DELETE …/{id}` (revoke, idempotent). Guarded by the
    existing `api_keys` view / create / edit / delete permissions; no new RBAC resource.
  - **Secret shown once.** The secret is `ak_` + 64 hex characters, returned only by create. Rows
    store a bcrypt hash and the usual lookup prefix; no response carries the hash.
  - **Audited.** `agent.key.create`, `agent.key.allowlist_update` (the list before and after) and
    `agent.key.revoke` go to the access audit, with metadata only.
  - **Enforced in apiome-mcp.** `apiome_mcp.agent_access.AgentAccessMiddleware` narrows
    `tools/list` and `tools/call` to the toolset's enabled tools ∩ the allowlist. A revoke,
    expiry or allowlist edit applies to the agent's next request. Until AGX-1.2 (#4530) supplies
    toolset curation, it fails closed.
  - `toolset_id` has no foreign key yet (`agent_toolsets` is AGX-1.2). Docs:
    `docs/agent_keys.md`.

### Security
- **An agent key never authenticates a REST call.** `validate_api_key` now selects
  `kind = 'workspace'` keys only, and falls back to the older queries on a pre-V269 database.
  Separately, no REST scope-allowlist entry accepts `agent:invoke`, so an agent key would get a
  `403` on every route even if the kind filter were bypassed.

## [1.331.0] - 2026-09-17

### Added
- **Upstream auth vault (#4534, AGX-2.2)** — agents must never hold real API credentials. A
  tenant now stores the upstream credential a managed MCP toolset presents to its real API, and
  the AGX-2.1 invocation proxy injects it server-side; the agent only ever holds its Apiome key.

  ```bash
  curl -sX POST "$APIOME/v1/tenants/acme/agent-toolsets/$TOOLSET/upstream-credentials" \
       -H "X-API-Key: $APIOME_KEY" -H 'Content-Type: application/json' \
       -d '{"serverUrl": "https://api.example.com/v1", "kind": "apiKey",
            "in": "header", "name": "X-Api-Key", "secret": {"value": "sk_live_…"}}'
  ```

  - **Encrypted at rest.** `apiome.upstream_credentials` (V268) holds ciphertext only, sealed by
    the shared envelope cipher under its own key map (`APIOME_UPSTREAM_CREDENTIAL_ENCRYPTION_KEYS`)
    and vault magic. No key configured ⇒ storing is a `503` and nothing is written in the clear.
  - **Write-only.** `GET` lists metadata (binding, kind, placement, key version, whether it still
    opens, created / rotated / last-used); create, rotate (`POST …/{id}/rotate`) and delete accept
    a secret and never return one. A test sweeps every `GET` route in the app for any rendering of
    a stored secret or its ciphertext. The router's `422`s no longer echo a submitted body
    (`app.redacted_validation_route`).
  - **Bound to a toolset and a server URL.** `https://` origin plus base path, stored normalized;
    a secret is only opened for a request with the same scheme, host and port whose path sits
    under the base path — never for a look-alike host, a downgrade, userinfo or an encoded
    traversal. Kinds: `apiKey` (header or query, configurable name), `bearer`, `basic`.
  - **Rotation without downtime.** One in-place `UPDATE`; concurrent resolves see the old secret or
    the new one, never neither, and in-flight invocations keep the secret they opened.
  - **Use is audited as metadata only** in the write-once `upstream_credential_uses` ledger (which
    credential, which toolset, when, `injected` / `unavailable`); create / rotate / delete land in
    the access audit as `agent.upstream_credential.*`. A bound credential that won't open fails
    the call closed.
  - Guarded by the existing `api_keys` permission (view / create / edit / delete); no new RBAC
    resource. `toolset_id` gains its foreign key in AGX-1.2 (#4530). See
    `docs/upstream_credential_vault.md`.

## [1.329.0] - 2026-09-17

### Added
- **API change check suite (#4740, GNC-3.1)** — a pull request that changed an API used to collect
  a wall of checks (lint, diff, breaking-change gate, contract test, SDK build), each with its own
  log, and a reviewer who read none of them. The platform already knew every answer; the suite
  turns them into **one** verdict — `pending`, `pass`, `fail` or `skipped` — recorded as an
  evaluation, reported on the pull request as the `apiome/api-change` check (replacing the pending
  check GNC-2.2's webhook seeded), and optionally required before publish.

  ```bash
  curl -sX POST "$APIOME/v1/tenants/acme/projects/pets/versions/2.0.0/check-suite" \
       -H "X-API-Key: $APIOME_KEY" -H 'Content-Type: application/json' \
       -d "{\"commit_sha\": \"$GITHUB_SHA\", \"pr_number\": 42}"
  ```

  - **Five components, all existing evidence.** `lint` (the stored-first lint report;
    error-severity violations fail it, as they fail publish), `breaking` and `consumers` (the CTG
    classification against the previous published revision and CTG-4.2's per-consumer verdicts for
    that same diff), `contract` (the newest ECA contract run of this revision, counted only while
    recompiling its own reference still yields the digest it executed) and `sdk` (the SDK kit
    manifest built from the draft). The three CTG-4.5 components are judged by the deploy gate's
    own evaluators and thresholds, so the pull request and the deploy gate cannot disagree.
  - **Deterministic.** A tenant (or project) policy marks each component `required`, `advisory`
    or `off`; the required ones reduce with GNC-2.2's precedence (a failure fails, an unfinished
    component holds, a set of skips is a skip). Missing evidence holds a required component
    `pending` and skips an advisory one; unreadable evidence is `pending`, never green; a version
    with no captured source skips contract and sdk rather than waiting forever.
  - **The suite judges the draft.** Its verdict is reported against the commit the binding is
    synchronized with. A newer commit gets a placeholder: `skipped` (`spec-unchanged`) when it does
    not touch the bound specification, otherwise `pending` (`draft-not-synchronized`).
  - **Idempotent re-runs.** An evaluation is keyed by the draft digest, commit, requirements,
    thresholds, and every component's verdict and evidence; unchanged inputs are a `200` replay of
    the same evaluation with the same evidence ids, and the provider is not called again.
  - **Drill-down.** `GET …/check-suite/runs/{id}` names every component's evidence (ids,
    digests, counts), a link to it, and the rule behind it, plus snapshots of both policies. The
    pull-request summary is the same thing as markdown. Consumer names are redacted for readers
    without `consumer_contracts:view`.
  - **Required before publish.** `requiredForPublish` on the suite policy refuses (`422`,
    `apiCheckSuiteGate`) a version whose current content has no passing evaluation under the
    component requirements and thresholds in force; force-publish stays the escape, and every
    judged publish is audited as `version.api_check_suite_gate`.
  - Endpoints: `POST`/`GET …/projects/{project}/versions/{version}/check-suite`, `GET …/runs`,
    `GET …/projects/{project}/check-suite/runs/{run_id}`, and `GET`/`PUT`/`DELETE` of
    `…/governance/check-suite-policy` and `…/projects/{project}/check-suite-policy` (tenant
    administrators only for changes). The latest-evaluation read is allowlisted for `diff:read` /
    `lint:read` CI keys. CLI: `apiome checks run|show`.
  - apiome-db **V267**: `apiome.api_check_suite_policy` (one row per scope, mutable — every
    evaluation snapshots the policy it was judged under) and `apiome.api_check_suite_runs`
    (append-only except the `ON DELETE SET NULL` of its author; a placeholder can never pass or
    fail), plus an index on ECA-1.3 runs by `source->>'revision_id'`.

### Fixed
- **A retried provider check publish that succeeded was never recorded (GNC-2.2).** The publish
  ledger was unique on `(check_run_id, request_fingerprint)`, so a verdict's failed attempt took
  the slot its successful retry needed: the retry reached the provider, collided in the ledger,
  and never wrote the provider's check-run id back — so every later publish POSTed a *new* check
  run onto the pull request. V267 re-keys the ledger per outcome and the lookup reads a verdict's
  dispatch first; a verdict is still dispatched at most once.

## [1.328.0] - 2026-09-16

### Added
- **Three-way spec synchronization (#4739, GNC-2.3)** — a bound draft has three descriptions of the
  same API — the repository at the commit it is synchronized with (the **base**), the repository at
  the commit its branch has moved to (**Git**), and the version as this platform has it (the
  **draft**) — and they drift apart independently. Copying either repository side over the draft
  destroys whatever somebody was editing and invalidates whatever reviewers already decided. A
  **semantic three-way merge** now measures both sides against the base, applies the incoming
  changes that touch nothing the draft touched, and hands back every overlap as an explicit
  conflict.

  ```bash
  # The branch moved. What would land, and what collides?
  curl -sX POST "$APIOME/v1/tenants/acme/projects/pets/versions/2.0.0/binding/sync" \
       -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{}'

  # Decide one collision. `git` takes the repository's value; `draft` keeps the version's.
  curl -sX POST "$APIOME/v1/tenants/acme/projects/pets/sync-plans/$PLAN/conflicts/$CONFLICT" \
       -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
       -d '{"resolution":"git","note":"the rename was agreed in review"}'
  ```

  - **A merge result is a reading, never a write.** There is no code path from this surface to the
    canonical model, to `versions`, or to a review — not in the store, not in the accessors, and not
    in the schema. Computing a merge writes one row; settling a conflict records which side a person
    chose. Both leave the draft exactly where it was, which is what makes it safe for a webhook to
    raise a candidate and for anyone at all to merge it.
  - apiome-db **V266**: `apiome.draft_sync_plans` (one merge per binding and trio of documents,
    recording the base, Git and draft digests it was computed from, what merged and how much did
    not, with the identity frozen by a trigger and a CHECK that keeps the status and the two counts
    from disagreeing) and `apiome.draft_sync_conflicts` (one row per overlap, carrying all three
    values with the repository file and line it lives at, settled once towards `git` or `draft`).
  - apiome-rest `app.spec_sync` (vocabulary, models, the merge engine, the plan fingerprint and the
    YAML/JSON line locator — all pure), `app.spec_sync_store` (the rules), `app.spec_sync_routes`
    (four endpoints), and the accessors at the end of `database.py`, whose `sync.planned` /
    `sync.conflict_resolved` audit rows are written **inside** each write's transaction.
  - **Conflicts are located, not just named.** Each carries its RFC 6901 pointer, the shared
    `document`/`path`/`operation`/`component`/`schema` grouping every other change list in the
    product uses, what each side did to the base, all three values, and the repository file, 1-based
    line and link at the commit. Lines come from *composing* the incoming document rather than
    loading it, and a mapping entry reports its key's line — in block YAML the value of `summary:`
    starts on the next line, which is not where anybody would look. A value too large to send to a
    browser is replaced by its size, and a merge that collides in more places than one result holds
    says so on the row — a result that quietly dropped findings would read as *less* conflicted than
    it is.
  - **Three proven reads, never a payload.** Both commits are fetched through the same
    credential-resolving read binding uses, so a repository the tenant cannot reach is answered
    `403 binding-repository-forbidden` rather than merged from a guess. And the base is re-read and
    re-hashed first: if it no longer matches the digest the binding recorded, history was rewritten
    underneath the merge base and the request refuses with `sync-base-drifted` instead of guessing
    which side changed what.
  - **Reruns are free, not just idempotent.** The rerun key is taken over the binding and the three
    documents' digests — all known before any network call — so re-merging an unchanged trio returns
    the stored result without fetching two commits to prove it would be the same. The draft is
    identified by its content digest rather than its revision id, because an edited revision is a
    different document; a stored result whose draft has moved on reads as `stale`.
  - **Work that already exists is reported, not trampled.** A result carries a `guard` — `none`,
    `review_decided` (an open review's current round already holds a decision) or
    `version_published`. A guard never refuses the merge: knowing exactly what would collide is
    precisely what such a reader needs.
  - Documented in `apiome-rest/docs/spec_sync.md`. This ticket deliberately **writes nothing back to
    Git** and **applies nothing to a draft**; the merged document is computed and proven
    deterministic, but turning it into an edit is a separate, explicit act with no storage here.

## [1.327.0] - 2026-09-16

### Added
- **Provider webhook and status adapter (#4738, GNC-2.2)** — GNC-2.1 gave a draft a durable
  relationship to a repository ref, but nothing could answer the provider: a pull request that
  changed an API showed no verdict from this platform, because there was nowhere to record one and
  nothing to send it with. Both halves now exist — a **normalized check model** that belongs to the
  platform rather than to any provider, and one **status adapter** interface with GitHub, GitLab
  and Bitbucket behind it.

  ```bash
  # Record a verdict about the commit this draft is bound to, and put it on the pull request.
  # (binding, commit, name) identifies the check, so the same call twice is one verdict.
  curl -sX POST "$APIOME/v1/tenants/acme/projects/pets/versions/2.0.0/binding/checks" \
       -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
       -d '{"name":"apiome/api-change","state":"fail","title":"2 breaking changes",
            "summary":"`GET /pets` lost a required field.","details_url":"https://…"}'

  # What did the provider actually do with it?
  curl -s "$APIOME/v1/tenants/acme/projects/pets/checks/$CHECK_ID" \
       -H "Authorization: Bearer $TOKEN"
  ```

  - **Four words, provider-independent**: `pending` / `pass` / `fail` / `skipped`. The three
    providers disagree about what a status even is — GitHub splits it into `status` and
    `conclusion`, GitLab has one commit `state`, Bitbucket has build states in capitals and no
    `skipped` at all — so storing any one of them would make the other two lossy translations.
    Only `pass` ever maps to a provider's passing status: a skip is "we did not look", which is not
    "we looked and it is fine".
  - apiome-db **V265**: `apiome.provider_check_runs` (one verdict per binding, commit and check
    name, backed by a unique index — the re-run idempotency — with `completed_at` tied to the state
    by a CHECK and the identity frozen by a trigger) and `apiome.provider_check_deliveries` (an
    append-only publish ledger, one row per distinct verdict sent, which may not claim a reach it
    did not have).
  - apiome-rest `app.provider_checks` (vocabulary, models, codes, the provider spelling tables and
    the fingerprint — all pure), `app.provider_status_adapter` (one `StatusAdapter` contract;
    GitHub check runs, GitLab commit statuses, Bitbucket build statuses), `app.provider_check_store`
    (the rules), `app.provider_check_routes` (four endpoints), and the accessors at the end of
    `database.py`, whose `check.recorded` / `check.published` audit rows are written **inside** each
    write's transaction.
  - **Recording comes before publishing, always.** A verdict is written first and only then offered
    to the provider, so a refusal appends a `failed` row to the publish ledger and the verdict
    stands. A check recorded and not published is evidence; a check published and not recorded is a
    green tick with nothing behind it.
  - **Idempotent twice over.** Re-recording the same verdict moves one row rather than fanning out a
    second, and each publish carries a fingerprint of the *verdict* — not of the HTTP call, which
    changes once a provider hands back an id — consulted **before** the adapter runs. A redelivered
    webhook therefore costs the provider nothing, not just us.
  - **A delivery resolves to an authorized binding, or to nothing.** A verified push or PR on a
    bound ref now seeds a `pending` check beside GNC-2.1's sync candidate, through the *existing*
    REPO-4.3 endpoint and deliberately outside its tracked-branch gate. Authorized means the binding
    is active *and* its repository registration still exists — that registration is the credential a
    verdict is published with. Both halves are best-effort: neither can turn a verified delivery
    into a 500 the provider would retry forever. The acceptance audit carries `checksSeeded`.
  - **Browser clients never receive repository tokens, and cannot supply one.** The token is
    resolved in server memory from the binding's registration (the same vault lookup an import
    uses); V265 has no token column on either table, not an encrypted one; the request and response
    models forbid extras; and a provider's refusal is redacted before it is stored.
  - New settings: `APIOME_PROVIDER_CHECKS_ENABLED` (publish kill switch — recording is never
    gated), `APIOME_PROVIDER_CHECKS_WEBHOOK_SEED`, `APIOME_PROVIDER_CHECKS_DETAILS_BASE_URL`.
  - Documented in `apiome-rest/docs/provider_checks.md`. This ticket **produces** no verdicts — it
    carries them; the check suite that decides one is GNC-3.1. Making a check *required* stays a
    provider-side branch protection setting, which is the repository owner's to make.

## [1.326.0] - 2026-09-16

### Added
- **Branch-to-draft binding (#4737, GNC-2.1)** — repository import creates a snapshot; it does not
  create a durable review unit. A **binding** now pins one draft version to one provider,
  repository, ref and source path, together with the digest of the source it is synchronized with,
  and every observed movement of that ref becomes an explicit, auditable **sync candidate** instead
  of quietly rewriting the draft.

  ```bash
  # Bind a draft to a branch. The ref is resolved and the selection read through a STORED
  # credential first: that read is the authorization check, and it produces the commit and digest.
  curl -sX POST "$APIOME/v1/tenants/acme/projects/pets/versions/2.0.0/binding" \
       -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
       -d '{"repository_id":"…","ref":"main","path":"spec/openapi.yaml"}'

  # Has the branch moved? A moved ref records a candidate; nothing about the draft changes.
  curl -sX POST "$APIOME/v1/tenants/acme/projects/pets/versions/2.0.0/binding/check" \
       -H "Authorization: Bearer $TOKEN"

  # Decide: `applied` re-reads the source at that commit and advances the binding's base;
  # `dismissed` leaves it exactly where it is. A candidate settles once.
  curl -sX POST "$APIOME/v1/tenants/acme/projects/pets/versions/2.0.0/binding/candidates/$ID" \
       -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
       -d '{"status":"dismissed","note":"not ours to take"}'
  ```

  - apiome-db **V264**: `apiome.draft_repository_bindings` (one active binding per draft, backed by
    a partial unique index; released rows kept as history and frozen by a trigger) and
    `apiome.draft_binding_sync_candidates` (idempotent per target commit *and* per provider
    delivery, settling exactly once). What a binding names never changes — only the synchronized
    pair (`commit_sha`, `source_digest`) moves, and only while it is active.
  - apiome-rest `app.draft_bindings` (vocabulary, models, codes, the digest — all pure),
    `app.draft_binding_store` (the rules), `app.draft_binding_routes` (seven endpoints), and the
    accessors at the end of `database.py`, whose `binding.*` audit rows are written **inside** each
    write's transaction.
  - **Authorization is a proven read, not a claim.** Binding, checking, and applying each resolve a
    stored linked-account credential and actually read the ref and the selection through the
    provider before anything is written. No token is ever accepted from a request body.
  - **A ref update never rewrites a draft.** A verified provider delivery on a bound ref raises a
    candidate through the *existing* REPO-4.3 webhook endpoint — deliberately outside its
    tracked-branch gate, because a bound branch need never have been imported from. A push moves the
    branch it names; a pull request moves its head branch, never its base.
  - De-registering a repository releases every binding it authorized, in the same transaction as the
    soft delete, reason `repository_removed`.
  - `Database._insert_review_audit` was generalized to `_insert_workflow_audit_tx`; COL-2.1's five
    call sites are unchanged in behaviour.
  - Documented in `apiome-rest/docs/draft_bindings.md`. Writing back to the provider (check runs, PR
    status) is GNC-2.2; merging repository changes into a draft is GNC-2.3, which will settle the
    same candidates once it can reconcile without silent overwrite.

## [1.325.0] - 2026-09-15

### Added
- **Notification model & fan-out (#4521, COL-3.1)** — the collaboration roadmap stops depending on
  people polling pages. Every mention, review request, decision, thread resolution and publish now
  writes one inbox row per person it concerns, **in the same transaction as the event itself**, and
  three endpoints read that inbox.

  ```bash
  # The bell badge
  curl -s "$APIOME/v1/tenants/acme/notifications/unread-count" -H "Authorization: Bearer $TOKEN"
  # {"total":3,"by_type":{"mention":2,"review_requested":1,"review_decision":0,…}}

  # The list behind the notification centre
  curl -s "$APIOME/v1/tenants/acme/notifications?unread=true&limit=20" -H "Authorization: Bearer $TOKEN"

  # Clearing it
  curl -sX POST "$APIOME/v1/tenants/acme/notifications/read" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"all": true}'
  ```

  - **Storage** (apiome-db **V263**): `notifications` — recipient, tenant, `type`, `payload jsonb`,
    `read_at`, plus the actor and the project/version the row points at, so a deleted destination
    takes its dead links with it while "somebody mentioned you" survives that somebody leaving.
  - **Five event types**: `mention` (an edit notifies only the members it *newly* names),
    `review_requested` (every round's reviewers), `review_decision` (the member who asked for the
    review), `thread_resolved` (everyone who took part), `version_published` (the version's
    collaborators — its review and thread participants). Nobody is ever notified of their own
    action, and a recipient set is bounded at 200.
  - **Transactional fan-out**: each write accessor takes a `notify` callable and runs it inside its
    own transaction, so a committed event always has its rows and a refused one leaves none. The
    insert joins `users`, so a recipient deleted mid-flight is skipped rather than rolling the
    event back.
  - **Retention**: a statement-level trigger keeps each inbox to its newest 500 rows, so the bound
    holds for every writer rather than depending on each one to remember.
  - **API**: `GET /v1/tenants/{tenantSlug}/notifications` (filters `unread`, `type`, paged),
    `GET …/notifications/unread-count` (total and per type, zeroes included), and
    `POST …/notifications/read` (`ids` or `all`, idempotent, answering with the new count). All
    three need only authentication — an inbox is the caller's own, which no `resource:action` can
    express — and listing never marks anything read.
  - Documented in `docs/notifications.md`. Per-type delivery preferences are **not** stored yet;
    COL-3.2 needs them and should filter on read, not at write time.

## [1.324.0] - 2026-09-15

### Added
- **Approval policy & publish gate (#4519, COL-2.3)** — review outcomes become binding at publish
  time. A tenant can require *n* approvals (optionally from a named role) before a draft version
  may be published; publishing without them is refused, and the force-publish escape is audited.

  ```bash
  # Arm the gate on the governing style guide
  curl -sX PUT "$APIOME/v1/style-guides/acme/$GUIDE_ID/policy" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d '{"requiredApprovals": 2, "requiredReviewerRole": "release-manager"}'

  # A publish that has not collected them is refused with 422 + the verdict
  curl -sX POST "$APIOME/v1/versions/acme/pets/$REVISION/publish" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d '{"shortMessage": "Ship it"}'
  ```

  - **Policy** (apiome-db **V262**): `style_guides.required_approvals` (`0` = off, the default,
    capped at the 20-reviewer limit) and `style_guides.required_reviewer_role` (a `roles.slug`,
    nullable). Both resolve through the GOV-1.4 guide chain — project assignment → tenant
    assignment → tenant default — beside the CTG-3.4 breaking-publish level, and both are frozen
    into each `style_guide_revisions` snapshot. Read/written at
    `GET`/`PUT /v1/style-guides/{tenantSlug}/{guideId}/policy`, where `requiredReviewerRole` is
    the one field for which *omitted* (leave alone) and *null* (clear) differ.
  - **Gate**: only the version's **open** review and only its **current round** count. Blocked
    with a stable `reason` for `no-review`, `changes-requested`, `spec-changed` (the content moved
    since the round was requested, so its approvals are stale — COL-2.1's `spec_changed`),
    `insufficient-approvals`, and `missing-required-role`. A reviewer's role is their effective
    RBAC slug, so a tenant administrator resolves to `owner`.
  - **422 contract**: `{"detail": {"message": …, "approvalGate": {…}}}`, the same shape the
    breaking-publish guardrail and the verification policy use. Force-publishing
    (`skipPublishChecks` + `forcePublishReason`) gets past it, exactly as it does for them.
  - **Audit**: every publish an armed policy judged appends a `version.approval_policy_gate`
    `workflow_audit` row with `action` of `satisfied`, `forced`, or `unavailable` — passing
    verdicts included, so the trail can answer "who signed off on this release?".
  - Faults degrade to `unavailable` and never block a publish; the degradation is audited rather
    than silent.
  - Documented in `docs/approval_publish_gate.md`; 46 tests in
    `tests/test_approval_publish_gate.py`.

## [1.322.0] - 2026-09-14

### Added
- **Comment anchor resilience (#4516, COL-1.4)** — a comment thread no longer silently disappears
  when its element is deleted, and renames and moves are proven to keep it in place.

  ```bash
  # Threads whose element was deleted, with the element's last-known label
  curl -s "$APIOME/v1/tenants/acme/projects/pets/comment-threads?version=1.0.0&status=orphaned" \
    -H "Authorization: Bearer $TOKEN"

  # Re-attach one to another element of the same version
  curl -sX POST "$APIOME/v1/tenants/acme/projects/pets/comment-threads/<thread id>/relink" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d '{"anchor_type": "property", "anchor_id": "<class property id>"}'
  ```

  - **Orphaning** (apiome-db **V260**): `status` gains `orphaned`, with `anchor_label` (the element's
    name when it was deleted — `Customer`, `Customer.email`, `/customers/{id}`, `GET /customers/{id}`)
    and `orphaned_at`. Database triggers orphan threads on every delete path: the class, property,
    path, and operation DELETE routes, a whole-version source-change rewrite, and foreign-key cascades
    (a class takes its properties' threads, a path its operations'). A resolved thread keeps its
    resolution while orphaned.
  - **Relink**: `POST …/comment-threads/{thread_id}/relink` `{anchor_type, anchor_id}` re-attaches an
    orphaned thread to an element of its own version (or to the version). It comes back `resolved`
    if it was, `open` otherwise. `404 comment-anchor-not-found` for a target outside the version,
    `409 comment-thread-not-orphaned` for a thread that is not orphaned. Requires `projects:view`.
  - Resolving or reopening an orphaned thread is `409 comment-thread-orphaned`. Replies still work.
  - Renames and moves (class, property, path, operation, canvas position) are pinned by tests as
    in-place updates keyed by the element id, and no orphan trigger watches a name column.
  - Documented in `docs/comments.md`.

## [1.321.0] - 2026-09-14

### Added
- **Comment threads (#4513, COL-1.1)** — discussion now lives next to the specification instead of in
  Slack screenshots. Open a thread on a class, property, path, operation, or a whole version; reply
  in Markdown; mention teammates; resolve and reopen.

  ```bash
  # Ask about a class on version 1.0.0 and mention a teammate
  curl -sX POST "$APIOME/v1/tenants/acme/projects/pets/comment-threads" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d '{"version": "1.0.0", "anchor_type": "class", "anchor_id": "<class id>", "body": "Nullable, @bob.brown?"}'

  # Everything open on that version that mentions me
  curl -s "$APIOME/v1/tenants/acme/projects/pets/comment-threads?version=1.0.0&status=open&mentions_me=true" \
    -H "Authorization: Bearer $TOKEN"
  ```

  - **Storage** (apiome-db **V259**): `comment_threads` (tenant, project, version, `anchor_type` +
    `anchor_id`, `status`, resolution stamps, `last_activity_at`) and `comments` (`thread_id`,
    `author_id`, Markdown `body`, `mentions uuid[]`, `edited_at`). A thread is anchored by the
    element's **primary key**, never canvas coordinates, and the element must exist in the named
    version when the thread is opened.
  - **Endpoints** under `…/projects/{project_ref}/comment-threads`: list (filters `version`, `status`,
    `anchor_type`, `anchor_id`, `mentions_me`; paged with a `total`; each row carries its opening
    comment), open, read, delete, `resolve`, `reopen`, and `…/comments` to reply, edit, and delete.
    Deleting a thread's last comment deletes the thread.
  - **Permissions**: no new RBAC resource. `projects:view` is enough to read, comment, resolve, and
    reopen. Editing or deleting a comment is limited to its author or a tenant administrator, and
    deleting a thread to whoever opened it or a tenant administrator (`403 comment-forbidden`).
  - **Mentions** are resolved on the server against active and pending members, by full email, email
    local part, or display name without spaces. A handle shared by several members resolves to
    nobody. Code, escapes, addresses, and URLs are never mentions, and an edit re-resolves them.
  - **Rate limit**: opening and replying share a per-user budget,
    `APIOME_COMMENT_CREATE_RATE_LIMIT_PER_MINUTE` (default 30); over it returns
    `429 comment-rate-limited`. Documented in `docs/comments.md`.

## [1.320.0] - 2026-09-10

### Added
- **Auto-regen on publish (#4497, SDK-4.3)** — watch mode for SDKs. Subscribe a project's SDK once,
  and every published version regenerates it and ships it: an SDK-4.1 registry publish, an SDK-4.2
  pull request, or both. Nobody has to remember.

  ```bash
  # Every publish of widgets: publish the npm SDK, then open a PR carrying that same version
  curl -sX PUT "$APIOME/v1/projects/acme/widgets/sdk-regen-subscriptions/npm" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d '{"deliveryMode": "registry_and_git"}'

  # What each publish did — and the dead letter
  curl -s "$APIOME/v1/projects/acme/widgets/sdk-regen-runs?status=dead_letter" -H "Authorization: Bearer $TOKEN"
  ```

  - **Subscriptions** (apiome-db **V258** `sdk_regen_subscriptions`) — one per project per ecosystem,
    with a `deliveryMode` of `registry`, `git` or `registry_and_git`, `options` and `active`.
    `deliveryMode` has **no default**, because publishing to a public registry is irreversible.
    `options` is a closed vocabulary: `dryRun` (registry modes only, default `false`) rehearses every
    release, and an unknown option is refused, so a misspelt one can never silently publish. Listing
    is `projects:view`. Subscribing or re-enabling needs `projects:edit` **and** `versions:publish`,
    because a subscription publishes on the tenant's behalf on every later publish. Disabling or
    unsubscribing needs only `projects:edit`.
  - **The trigger** — the publish route queues a run (`sdk_regen_runs`) and one pending job per active
    subscription (`sdk_regen_jobs`) in one statement, as a background task that never fails the
    publish. A project with no active subscription gains no rows.
  - **The worker** (`app.sdk_regen_worker`, ticking every `APIOME_SDK_REGEN_INTERVAL`) calls SDK-4.1's
    `publish()` and SDK-4.2's `deliver()` **unchanged**, so an automatic release and a manual one are
    identical. In `registry_and_git` mode the pull request is pinned to the version the publish just
    claimed. Jobs are claimed with `FOR UPDATE SKIP LOCKED`, so replicas share the queue. A
    subscription's publishes run in order, and one subscription's failure never blocks another's.
  - **Failures go to a dead letter, like webhooks.** Transient failures (a registry 5xx, a GitHub
    outage or rate limit) retry with backoff (4 attempts: 60s/5min/30min). Permanent ones (a missing
    credential, no delivery target, a registry refusal) are dead-lettered at once with a message that
    names the fix. A dead letter fans out an `sdk.regen.dead_lettered` push-webhook event and is
    retried with `POST …/sdk-regen-jobs/{jobId}/retry` (`versions:publish`). **A step that succeeded
    is never repeated**: a retry after a publish only delivers, and the registry result is written
    to the job before the git step starts, so this holds even if the worker dies. A job still running
    past `APIOME_SDK_REGEN_LEASE_SECONDS` is dead-lettered (`sdk-regen-worker-lost`), never retried
    automatically, since it may already have published. A fresh claim token per attempt stops a stale
    worker from overwriting a job that was retried since.
  - **History links publish event → jobs → artifacts → deliveries.** Each run lists its jobs, and
    each job gives the SDK-4.1 publish run (package, version, archive digest) and the SDK-4.2 delivery
    run (pull request), with links to both ledgers and to the published version. Every attempt is
    recorded against the runs it wrote.
  - **Unsubscribing stops future runs without touching past artifacts.** Queued jobs for a disabled or
    removed subscription are `cancelled`, and a removed subscription's dead letters can no longer be
    retried. Runs, jobs, packages and pull requests already produced are kept (`ON DELETE SET NULL`).
  - `PublishOutcome.retryable` (SDK-4.1, in-process only) now carries the registry's own
    `RegistryUploadError.retryable`, mirroring SDK-4.2's `DeliveryOutcome.retryable`.
  - Settings: `APIOME_SDK_REGEN_ENABLED` (kill switch), `APIOME_SDK_REGEN_INTERVAL`,
    `APIOME_SDK_REGEN_BATCH_SIZE`, `APIOME_SDK_REGEN_LEASE_SECONDS`. No new RBAC resource and no new
    credential. Documented in `docs/sdk_regen_on_publish.md`.

## [1.319.0] - 2026-09-10

### Added
- **Git delivery, PR mode (#4496, SDK-4.2)** — registry publishing serves an SDK's consumers; git
  delivery serves its owners. A regenerated SDK now arrives as a **pull request** against the
  tenant's own repository, where their normal review and CI apply.

  ```bash
  # Point the project's npm SDK at a repository already registered with Apiome
  curl -sX PUT "$APIOME/v1/projects/acme/widgets/sdk-git-delivery-targets/npm" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d '{"repositoryId": "5f0c…", "baseBranch": "main", "targetPath": "sdks/typescript"}'

  # Deliver version 1.4.2 — opens (or updates) apiome/sdk-regen-1.4.2-widgets-npm
  curl -sX POST "$APIOME/v1/projects/acme/widgets/sdk-git-delivery" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d '{"ecosystem": "npm", "version": "1.4.2"}'
  ```

  - **No new credential type.** A delivery target (apiome-db V257 `sdk_git_delivery_targets`: one
    per project per ecosystem — repository, base branch, target path) names a repository registered
    through a linked GitHub account, and a delivery pushes with that repository's existing
    linked-account token. There is no token column in V257. A repository registered from a public
    URL, or hosted outside GitHub, is refused with the reason.
  - **The SDK-4.1 package, committed.** The delivery builds the same file list a publish would
    upload (`app.sdk_publish_pipeline` now exposes `resolve_release_branding`,
    `resolve_release_series` and `build_release_distribution`), carrying the version the next
    registry publish of the series would claim, and commits it under the target path through
    GitHub's Git Database API — no clone, no git binary, no token on disk.
  - **A pull request with provenance.** Its body carries the spec version and revision id, the
    generator version, a changed-files overview and the provenance table; the commit carries
    `Apiome-Revision` / `Apiome-Version-Line` / `Apiome-Package` / `Apiome-Generator` trailers.
  - **Idempotent per (version, target, options).** The branch is
    `apiome/sdk-regen-<version>-<project>-<ecosystem>` — the ticket's `apiome/sdk-regen-<version>`
    plus the project and ecosystem, so several SDKs can share a repository without overwriting each
    other's pull requests. Every delivery is rebuilt on the latest base branch and force-updates the
    branch; re-running updates the open pull request (`updated`), writes nothing when it already
    carries this SDK (`unchanged`) or when the base already contains it (`up_to_date`), and only
    opens one when none is open (`opened`).
  - **Only generated files are ever removed.** A `.apiome/sdk-delivery.json` manifest beside the SDK
    lists what Apiome generated; the next delivery removes files that list named and the new one
    does not, and never touches anything else under the target path.
  - **Failures are runs with actionable logs.** Every attempt is a row in
    `sdk_git_delivery_runs`; a missing or revoked credential, a read-only token, a rejected push, a
    refused pull request or a package that cannot be built is a `failed` run with a stable
    `errorCode`, a message naming the fix, and a step log redacted of the repository token.
    `POST …/sdk-git-delivery` answers `200` with the run either way.
  - **Shared run log.** SDK-4.1's redacting event log moved to `app.sdk_run_log.RunLog` (with a
    per-pipeline redaction marker) so both release pipelines redact through one implementation.
  - Listing targets is `projects:view`; saving one is `projects:edit` **and** `imports:edit` (a
    target decides what Apiome pushes into a repository with that repository's credential);
    delivering is `versions:publish`; history is `versions:view`. No new RBAC resource. Documented
    in `docs/sdk_git_delivery.md`.

## [1.318.0] - 2026-09-09

### Added
- **Package publishing pipelines (#4495, SDK-4.1)** — downloading a zip is not how SDKs are
  consumed at scale, so a published version can now be released as a package a consumer installs:
  `npm install @acme/widgets-sdk`, `pip install acme-widgets`.

  ```bash
  # Store the workspace's token once (write-only; never returned by any route)
  curl -sX PUT "$APIOME/v1/tenants/acme/governance/sdk-registry-credentials/npm" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d '{"token": "npm_..."}'

  # Validate a release without publishing anything (the default)
  curl -sX POST "$APIOME/v1/projects/acme/widgets/sdk-publish" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d '{"ecosystem": "npm", "version": "1.4.2"}'
  ```

  - **Encrypted tenant registry credentials.** npm / PyPI tokens are stored in apiome-db V256
    `sdk_registry_credentials` as **ciphertext only**, sealed with AES-256-GCM envelope encryption
    under `APIOME_SDK_REGISTRY_CREDENTIAL_ENCRYPTION_KEYS`. The scheme MCAT-6.2 already used was
    extracted to `app.envelope_crypto` rather than copied, and the SDK vault seals under its own
    magic so a blob cannot be moved between the two even on a shared key. A credential is
    **write-only** — every read returns the ecosystem, the registry, the token's *public* scheme
    prefix, its length and a truncated digest, and no route returns a token. A project credential
    replaces the workspace one whole (unlike SDK-3.4's settings, a token is atomic), and both
    scopes are managed at `…/sdk-registry-credentials`.
  - **Publish with a dry run.** `POST /v1/projects/{t}/{project}/sdk-publish` defaults to
    `dryRun: true`: it resolves the branding, resolves *and decrypts* the credential, computes the
    version the next real publish would claim, builds the exact archive that publish would upload
    and reports its SHA-256 — and uploads nothing. Because the build is byte-deterministic, the
    digest a dry run reports is the digest a publish uploads. Sending `dryRun: false` is the
    deliberate act; a default that published would make a mis-typed request a public release.
  - **Semver from the version line and a regen counter.** The published version is
    `major.minor.<counter>`, where `major.minor` come from the revision's version line and the
    counter is how many releases that line's *release series* has already had: `1.4` → `1.4.0`,
    `1.4.1`, `1.4.2`…; `v3` → `3.0.0`; `2026-01-04` → `2026.1.0`. The counter is allocated per
    series rather than per line, so `1.4.2` and `1.4.3` cannot both claim `1.4.0`. A prerelease
    line stays a prerelease (npm `1.5.0-beta.2`, PyPI `1.5.0b2`), and a line with no leading
    number (`latest`, `draft`) is refused rather than given an invented ordering. The counter is
    **derived from the run ledger**, never stored on a project row, and a partial unique index
    makes that safe under concurrency — a run is inserted `in_progress` holding its version before
    the upload, and a publish that loses the race takes the next number.
  - **Provenance in the package's own metadata.** `package.json` carries an `apiome` object and
    PyPI's core metadata carries `Project-URL` entries naming the **revision id** (not merely the
    label — a label can be re-published, a revision cannot), the version line, the release series,
    the regen counter, the renderer and the SDK-3.4 settings fingerprint. An installed package
    therefore traces back to its spec with nothing but the package manager.
  - **What is in the package.** SDK-4.1's stated dependencies — the two MVP client generators
    (#4485/#4486), the generator SPI (#4482) and the SDK-1.1 job service and artifact store
    (#4481) this was to be a step on — were all closed **not-planned**, so, following the
    SDK-2.3/2.4/2.5/3.3/3.4 precedent, the pipeline publishes what did ship, read straight from
    the persisted canonical model: the published contract verbatim, a README, one runnable snippet
    per operation, and an importable module exposing the provenance and the spec. A distribution is
    assembled from a list of files plus metadata, so a future client generator becomes another
    contributor to that list rather than a second pipeline. `gomod` is deliberately not
    publishable — it names a module path, and a Go module is released by pushing a tag (SDK-4.2).
  - **Secrets never reach a log.** The token is read into memory, handed to the transport and
    never touched again; every run-log line — including anything the registry said — passes
    through exact-substring redaction over the token in play, so even a registry that quotes the
    credential it rejected cannot put one in the ledger. Uploads go through the SSRF-guarded
    client, so a tenant cannot point a registry URL at an internal address and be handed a token.
  - **History.** `GET …/sdk-publish-runs[/{run_id}]` lists every attempt, dry runs included, with
    the version it claimed, the digest it uploaded and its redacted event log.
  - Credential management is `projects:view` / `projects:edit`; publishing — including a dry run —
    is `versions:publish`. No new RBAC resource, for the reason CTG-4.4, CTG-4.5 and SDK-3.4 all
    gave. Documented in `docs/sdk_package_publishing.md`.

## [1.316.0] - 2026-09-08

### Added
- **Go client generator (#4488, SDK-2.4)** — Go was the most-requested third language for infra
  buyers, and the client kit now carries one: a complete, **dependency-free** Go module generated
  from the published contract, sitting in the kit's `go/` directory beside the snippets.

  ```bash
  curl -sO -J "$APIOME/v1/browse/tenants/$TENANT/projects/$PROJECT/versions/1.0.0/sdk/download"
  unzip -q petstore-1.0.0-sdk.zip && cd go && go build ./... && go vet ./...
  ```

  - **What it generates.** `go.mod` (standard library only — a generated SDK that pulls in a
    dependency tree is a liability), a `net/http` transport behind an injectable `Doer` with
    `WithHTTPClient` / `WithBaseURL` / `WithUserAgent` / `WithHeader` / `WithRequestEditor`,
    exported types for every schema the contract declares, one `context.Context`-first method per
    HTTP operation, auth options derived from the model's security schemes, a typed error per
    declared error response, a `README.md`, and a runnable `examples/<group>/main.go` per operation
    group. The tenant's SDK-3.4 licence header is commented onto every `.go` file and its
    user-agent is baked in as `DefaultUserAgent`.
  - **Why it generates from the canonical model.** SDK-2.4's stated dependencies — the generator
    SPI (#4482) and the codegen preprocessing pass (#4483) — were both closed **not-planned**, as
    were the artifact store (#4481), the two MVP language generators (#4485/#4486) and the
    dashboard/CLI surfaces (#4491/#4492). Following the precedent SDK-2.3/3.3/3.4 set,
    `app.go_client_generator` is a pure function of the persisted canonical model and its output
    rides the existing client kit rather than an artifact store — so the download stays
    byte-deterministic and keeps its content-addressed `ETag`.
  - **`gomod`, a third SDK-3.4 package ecosystem.** A tenant configures the `go.mod` module path
    their consumers `go get`, with the same tenant → project merge and `{tenant}`/`{project}`
    tokens as the npm and PyPI patterns. Unconfigured, it falls back to
    `example.com/<tenant>/<project>-go` — `example.com` is IANA-reserved, so a default module path
    can never point at somebody's real repository.
  - **It never takes a download down.** An operation with no HTTP binding gets no method and is
    recorded with a reason, exactly as the snippets record theirs; a generator failure degrades the
    kit to its snippets and says so in the README and the manifest.
  - **The manifest gained a `go_client` block** (module path, package name, Go version, method and
    type counts, auth options, example groups, per-method coordinates and skips), and the public
    SDK info route gained a `go_client` object so the browse panel can name the module without
    paying to generate it.
  - **The compile gate is real.** `tests/test_go_client_generator.py` runs `go build ./...`,
    `go vet ./...`, `gofmt -l` and a `go test` that drives the generated client against a live
    `httptest` server — path, query, cookie, auth header, user-agent, JSON decoding and the typed
    404 over an actual HTTP round trip — whenever a Go toolchain is on `PATH`, and skips otherwise.

### Changed
- **Reading a model's auth moved to `app.canonical_security` (#4488).** The canonical model has no
  first-class security field, so importers record auth in two `extras` shapes that mean different
  things: `operation.extras["security"]` is a per-operation *requirement*, while
  `api.extras["inferred_auth_schemes"]` is only an *observation* that the API was seen using a
  scheme. Three emitters now need that distinction, so `AUTH_SCHEME_HEADERS` and both readers live
  in one module; `app.http_file_emitter` and `app.llm_tools_emitter` delegate to it. Behaviour is
  unchanged.
- **Three `app.snippet_render` helpers became public** — `upper_snake_token`, `request_message` and
  `pick_content_type` — so the Go generator asks the same questions the snippets do rather than
  keeping a second copy of the answers. `license_comment_block` learned the `go` comment prefix.

## [1.315.0] - 2026-09-08

### Added
- **Public "Get SDK" surface (#4493, SDK-3.3)** — the browse portal is where API *consumers*
  land, and until now a published spec page offered them no path to a working client. It now
  offers two, both behind one per-project switch that is **off by default**.

  ```bash
  # Opt a project in, then take the kit.
  curl -sX PUT -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
    "$APIOME/v1/projects/$TENANT/$PROJECT/sdk-settings" \
    -d '{"settings":{"publicSdkEnabled":true}}' > /dev/null
  curl -sO -J "$APIOME/v1/browse/tenants/$TENANT/projects/$PROJECT/versions/1.0.0/sdk/download"
  ```

  - Two anonymous routes:
    `GET /v1/browse/tenants/{t}/projects/{p}/versions/{v}/sdk` describes what is on offer (the
    resolved package names and their install commands, the languages, the operation counts, the
    settings fingerprint), and `…/sdk/download` serves the archive itself as `application/zip`.
    Both share the MFX-7.3 public-export rate limit; the download reuses its size cap.
  - **What the download is.** The original scope served a generated client library from the
    SDK-1.1 artifact store. SDK-1.1 (#4481), the generator SPI (#4482), both language generators
    (#4485/#4486) and the dashboard/CLI surfaces (#4491/#4492) were closed **not-planned**, so
    there is no artifact to serve and no generator to make one. The download is instead an
    `sdk.client-kit.v1` archive built from what *did* ship — the SDK-2.3 renderer — carrying a
    README, the published contract verbatim, and one runnable snippet per operation in
    ts/python/curl. It is built **per request**, so there is no artifact lifecycle to retain or
    expire.
  - **`publicSdkEnabled`, a new key on the SDK-3.4 `sdk.generation-settings.v1` body.** It merges
    tenant → project key by key like every other setting, so a workspace can open every project at
    once and one project can override either way. It is the only setting that is an access control
    rather than branding, so it defaults to `false` rather than `null` — for a permission, "not
    configured" and "not allowed" are the same answer — and an unreadable settings row also reads
    as `false`: **the gate fails closed**. Only a real boolean is accepted; `1` is refused.
  - **A project that has not opted in gets a 404**, identical to the one an unpublished, private or
    unknown version gets. A `403` would confirm that the project exists and merely declined.
  - **Provenance and determinism.** The archive's `manifest.json` records the version record id,
    version label, source format, renderer, API version and merged settings fingerprint, and
    digests every entry. Building twice from the same inputs yields byte-identical archives, which
    is what lets an unstored download carry a strong content-addressed `ETag` (with `If-None-Match`
    → 304) and a `Digest` over its exact bytes.
  - Operations with no HTTP binding (gRPC, GraphQL, events) are recorded in the manifest's
    `skipped` list rather than failing the kit, and the work is capped at 250 renderable operations
    with `truncated` reported.

### Changed
- **The anonymous snippet route is now gated (#4493).**
  `GET /v1/browse/tenants/{t}/projects/{p}/versions/{v}/snippets/{operation_id}` is part of the
  same consumer-facing SDK surface as the Get SDK download, so it now answers **404** for a project
  whose `publicSdkEnabled` is not set. Since the setting defaults to off, **public snippet URLs
  that worked in 1.314.0 return 404 until a workspace or project owner opts in.** The
  **authenticated** snippet route is unchanged — it is tenant-scoped, not public exposure.
- **Every settings fingerprint changed value.** The canonical settings body carries every key,
  including unset ones, so that a fingerprint keeps meaning the same thing across releases; adding
  `publicSdkEnabled` therefore changes the digest the same settings produce. Stored row
  fingerprints are untouched until their row is next saved; the ones responses report changed
  immediately.
- `ExportSource` now carries the revision's captured `source_text` and `source_format`, so a bundle
  can ship the contract alongside what was derived from it. Additive; existing callers are
  unaffected.
- The deterministic zip-entry writer moved from `app.export_job_engine` to a shared
  `app.zip_bundle`, so the export bundle and the client kit cannot drift apart on the pinned
  timestamp their reproducibility depends on.

## [1.314.0] - 2026-09-07

### Added
- **SDK generation settings & branding (#4494, SDK-3.4)** — an organisation wants the code Apiome
  hands its consumers to carry the organisation's identity: packages under its own npm scope /
  PyPI naming pattern, its licence header on the source, its own user-agent on the traffic those
  clients generate. None of that is a property of any version, project row or generated file, so
  it now has one durable home and one set of rules.

  ```bash
  curl -sX PUT -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
    "$APIOME/v1/tenants/$TENANT/governance/sdk-generation-settings" \
    -d '{"settings":{"packageNamePatterns":{"npm":"@acme/{project}-sdk"},
         "userAgent":"acme-sdk/{version}"}}' | jq -r .resolved.packageNames
  ```

  - Six endpoints, three per scope:
    `GET|PUT|DELETE /v1/tenants/{t}/governance/sdk-generation-settings` and
    `GET|PUT|DELETE /v1/projects/{t}/{project}/sdk-settings`. A `GET` never materialises a row —
    a scope with nothing saved answers `source: "default"` — and a `DELETE` returns the settings
    **now** in force rather than a bare `204`.
  - **The merge is per key, not per row.** A project that overrides only its user-agent still
    inherits its tenant's package pattern, and `packageNamePatterns` merges one ecosystem at a
    time. This is the one place SDK-3.4 departs from CTG-4.5's whole-body override, and the reason
    a stored body carries only the keys its author named: an **absent** key inherits the next scope
    up, an explicit **`null`** is deliberately none and blocks that inheritance.
  - **A pattern is validated by being resolved.** `@acme/{project}-sdk` is not itself a legal npm
    name, so patterns are checked by substituting probe values and validating the result. At read
    time a package pattern whose tokens the scope cannot fill is *omitted* rather than resolved
    approximately — a package name is an exact identifier, and a nearly-right one is worse than
    none. Tokens: `{tenant}`, `{project}`, `{version}`, `{year}`.
  - **The snippet service applies them.** SDK-2.3's authenticated and anonymous surfaces now stamp
    the tenant's user-agent onto the example request and its licence header above the code (as
    line comments — a block comment could be terminated from inside by a licence containing `*/`),
    and report both back in a new `branding` field alongside the resolved package names.
    Rendering with no branding is byte-identical to before, which is what keeps FMT-2.4's bulk
    request-file emitter — which shares `synthesize_request` and `render_curl` — unchanged.
  - `projects:view` to read, `projects:edit` to change: no new RBAC resource and no new API-key
    scope. Both writes are audited as `governance.sdk_generation_settings.update` / `.clear`,
    with the licence header recorded by length rather than verbatim.
  - Schema: apiome-db **V255** (`sdk_generation_settings`, two partial unique indexes, one JSONB
    body). Docs: `apiome-rest/docs/sdk_generation_settings.md`.

## [1.313.0] - 2026-09-07

### Added
- **Deploy-gating status API (#4502, CTG-4.5)** — a CD pipeline asks one question, *can I promote
  this API version?*, and the answer lived in five places: the GOV lint grade on the revision,
  CTG-3.1's breaking classification, CTG-4.2's per-consumer verdicts, CTG-4.3's conformance report
  and CTG-4.4's freshness. Every team that wanted a gate scripted its own multi-call version, and
  every one of them decided the combination rules differently.

  ```bash
  curl -sH "X-API-Key: $KEY" "$APIOME/v1/projects/$TENANT/$PROJECT/gate" | jq -r .status
  ```

  `GET /v1/projects/{tenant_slug}/{project_ref}/gate` returns `pass` / `warn` / `fail` plus a
  per-signal breakdown, each signal carrying a stable reason code, a human sentence, a link to its
  evidence, and the facts the judgment was made from. **No analysis was added**: every signal is a
  read of something an earlier ticket already stored — the gate never re-lints (#5259's stored
  reports) and never re-diffs (the stored `ctg.changelog.v1` payload is rehydrated into the
  classified diff CTG-4.2's `consumer_impact_for_diff` already takes, because a changelog entry and
  a classified change carry the same fields).

  **Partial inputs are the normal case, so there are five per-signal statuses rather than three.**
  A signal with nothing behind it reports `not_configured`; one that exists but could not be read
  reports `unknown`. Both are excluded from the verdict — the endpoint has to ship before all four
  sources exist everywhere — and both are counted apart, because "nobody has registered a consumer",
  "I could not read the registry" and "no consumer is broken" are three different facts.
  `evaluatedSignals` is how a strict pipeline tells an empty gate from a real pass.

  **The status is always 200.** A `409` on a failing build would make a network fault and a breaking
  change look identical to a pipeline's error handling; the verdict is in the body and the caller
  owns the exit code, exactly as the CLX-4.2 lint gate does.

  **Thresholds are two-rung and tenant- or project-scoped.** Each signal carries a warn threshold
  and a fail threshold, either of which may be `null` to disable that rung, which is what lets one
  vocabulary come out of four very different measurements without a per-signal "action" dial:
  *warn below B, fail below D* says the whole lint policy in five words. A rung that could never
  fire is refused with a `422` listing every problem at once.
  `GET|PUT|DELETE /v1/tenants/{tenant}/governance/deploy-gate-policy` and the per-project
  `…/gate/policy` configure it, resolving project → tenant → documented default, with `policy.source`
  on every response saying which one applied. Unlike the other policy surfaces these rows are
  mutable rather than append-only — the gate stores no verdict, so there is no past judgment for a
  version history to explain; attribution lives in `access_audit`.

  Unlike every other policy default in the platform, **this one has teeth**: it fails on a breaking
  change and on a broken consumer, and warns on a lint grade below B or a verification older than a
  day. The advisory defaults elsewhere exist because those gates hang off flows that already existed
  and a blocking default would break people who never asked for one; nothing hangs off this one.

  **Every signal fails soft, on its own.** A store that is unreachable or a payload this release
  cannot parse costs that signal — `unknown`, reason `signal-unavailable` — and nothing else. A gate
  that returned `500` because one of four inputs was briefly unavailable would stop every pipeline in
  the tenant. The policy read degrades the same way, flagging `policy.degraded` so "nothing is
  configured" stays distinguishable from "I could not read what is".

  A schedule is matched to the gated revision however its reference was spelled (`…/1.2.0`,
  `…/<uuid>`, `…/latest`); across several, freshness is the most recent clean run and the status is
  the worst, so a failing staging check is never averaged away by a passing production one. When
  nothing schedules the version, the signal falls back to a manual CTG-4.3 report, read by resolved
  artifact coordinates — and a failing report never becomes the freshness anchor.

  **No new RBAC resource and no new API-key scope.** Reading a gate is `versions:view` (what a CI
  runner resolves to); moving the bar is `verification_targets:edit`, the same class of decision
  V211 already keeps out of an Editor's hands. The consumer signal is gated inside the response on
  `consumer_contracts:view`, reported `unknown` rather than leaked or silently passed. The gate is
  allowlisted for *either* CTG-2.3 CI read scope (`diff:read` or `lint:read`), since it aggregates
  inputs both of those already grant.

  apiome-db **V254** adds `deploy_gate_policy` (one row per scope, two partial unique indexes) plus
  the artifact index the report fallback reads. See `docs/deploy_gate.md`.

## [1.311.0] - 2026-09-07

### Added
- **Consumer-aware breaking analysis (#4480, CTG-4.2)** — "breaking" is a claim about somebody.
  A whole-spec verdict ("47 breaking changes") forces a provider to treat every change as an
  incident and tells a consumer nothing. `POST /v1/diff/{tenant}/classified` with
  `consumers: true` now intersects the CTG-1.1 classified changes with what each registered
  consumer declared it uses (CTG-4.1) and answers the question that actually gates a release:

  ```
  breaks 2 of 7 consumers: billing-service, mobile-app
  ```

  Nothing was added to the database. A verdict is derived from a stored contract and a diff, and
  both already existed; what was missing was the join. `app.consumer_impact` is pure (pointer
  algebra, attribution rules, markdown), `app.consumer_impact_service` is the one place the
  registry is read for an analysis, and CTG-4.5's deploy gate calls the same seam.

  **The exclusion is the point.** A change inside a body schema, on an operation whose consumer
  declared which fields it reads, attributes only when one of those fields is met — removing a
  field nobody reads breaks nobody. Two exceptions keep that from under-reporting: an operation
  declared with no fields is operation-wide throughout (nothing finer was declared, so nothing
  finer is claimed), and a `/parameters/…` change is always operation-wide, because a newly
  required query parameter breaks every caller whether or not they declared it. Root `security`,
  `servers` and `securitySchemes` changes reach every declared consumer.

  Pointer overlap is **segment-aware**, unlike the `starts_with` narrowing query behind
  `db.find_consumer_contracts_by_pointers`: `/components/schemas/Pet` no longer "touches"
  `/components/schemas/PetFood`. The SQL only narrows the candidate set; this renders the verdict.

  **The denominator is honest.** A consumer registered without a current contract cannot be
  counted as safe, so it is reported beside the fraction (`2 registered consumers have declared
  no surface`) with verdict `undeclared`, never inside it. Each verdict also carries
  `contractMatchesBase`, so a surface resolved against a different revision is flagged rather
  than silently equated.

  Changes touching nobody stay globally classified and are flagged: each change gains a
  `consumers` array (`[]` = no registered consumer affected, `null` = not analysed), and the
  report's `attribution` list is exact even when a consumer's `impacts` enumeration is capped.

  Markdown responses gain a **Consumer impact** section, and `apiome diff --consumers` prints
  `breaks billing-service` lines in text, JSON and markdown. The CI **exit code is unchanged** —
  `--fail-on` still grades the whole specification, so a build never passes merely because nobody
  has registered as a consumer yet.

  See `apiome-rest/docs/consumer_impact.md`.

## [1.310.0] - 2026-09-07

### Added
- **Provider verification against a live deployment (#4489, CTG-4.3)** — a published specification
  can be perfectly versioned and still lie. `POST /v1/tenants/{tenant}/contracts/{version_ref}/
  verify-provider` executes the version's compiled contract suite against a registered deployment
  and returns a **conformance report**: per-operation verdicts, every schema violation located by
  its JSON Pointer into the response body, and coverage measured against every operation the
  specification declares.

  Nothing here re-implements execution. ECA-1.1 compiles the requests, ECA-1.2 holds the target and
  its credential *reference*, ECA-2.1 sends them and validates responses, ECA-1.3 stores the run.
  What was missing was the judgment: coverage had no denominator (a run recorded the cases it
  executed, never the operations it did not reach), drift had no location (the validator's JSON
  Pointers were computed and then discarded), mutation was an all-or-nothing target flag, and there
  was no report object a deploy gate could fetch.

  **Safe by default.** Only `GET`/`HEAD`/`OPTIONS` are sent. A mutating case runs only when the
  target policy permits mutation, *and* the run opts in, *and* a tenant-supplied fixture names the
  operation — because "you may write" and "here is the row you may write to" are different
  permissions. A run can narrow what the registry permits and never widen it; a fixture supplies the
  request but never the expectation, so it cannot make a failing case pass; a fixture carrying a
  credential header is refused; and a fixture never overwrites a negative case's body or restores
  the parameter that case exists to omit. A fixture that matches nothing is reported, not dropped.

  **Coverage is honest.** The denominator counts operations the suite compiler could not compile,
  so a coverage number cannot be inflated by a document half of which was skipped, and every
  operation the report does not vouch for is named with its reason.

  Reports are persisted write-once beside their evidence (apiome-db **V252**,
  `provider_verification_report`) with the coverage numbers and verdict as indexed columns, so
  CTG-4.4 (scheduled verification) and CTG-4.5 (deploy gating) can ask "is the newest report for
  this version passing?" without parsing a report body. No new RBAC resource: a conformance report
  *is* verification evidence. See `docs/provider_verification.md`.

### Changed
- `app/contract_runner.py` (ECA-2.1) now records **one assertion per located schema violation**
  alongside the existing headline verdict, with the instance JSON Pointer as the assertion subject,
  and accepts an optional per-case `decisions` map so a caller can hold a case back or substitute a
  request without reimplementing the runner. Both are additive: omitting `decisions` is exactly the
  previous behaviour, and the headline assertion's shape is unchanged.

## [1.308.0] - 2026-08-31

### Changed
- **There is now one mock engine (#5532, MSC-2.2)** — the mock implementation that lived inside
  apiome-rest is deleted, and every mock request is resolved by apiome-mock.

  There were two. This one served `/v1/mock/{id}/…` — the short-lived sandbox instances the hosted
  Mock Server (#3615) and the Export Studio's test drive (MFX-44.5) provision — from
  `mock_instances.config`, a *list* of scenarios with `rules`. apiome-mock served
  `/{tenant}/{project}/{version}/…` and portable bundles from `versions.mock_settings`, a *dict
  keyed by scenario name*. They shared three routing symbols and reimplemented everything
  downstream, so a feature built in one was invisible in the other: sandboxes had no templates, no
  match predicates, no stateful CRUD, no fixture packs and no chaos, and every future mock feature
  would have had to be written twice.

  A sandbox request now takes one internal hop. apiome-rest keeps what a *sandbox* is — does the
  instance exist, has it expired, is the caller inside its rate limit, what goes in the request
  log — builds the instance's portable mock bundle, and asks apiome-mock's new `/__sandbox__`
  endpoint to serve it through `serve_compiled_request`, the same function the hosted data plane
  and the portable runtime call. Sandboxes gain every feature they lacked as a side effect.

  There is deliberately **no local fallback**: a deployment that has not configured
  `APIOME_MOCK_INTERNAL_BASE_URL` / `APIOME_MOCK_INTERNAL_TOKEN` answers `503` on the data plane
  and says which switch is missing, rather than inventing an answer from a second engine.

- **The built-in scenarios still resolve, everywhere (#5532)** — `happy-path`, `server-error`,
  `not-found` and `slow` are written into client code by name, so all four are now defined on
  *every* version, supplied by the runtime and merged into whatever the version stores. A stored
  scenario of the same name wins outright, exactly as the retired engine's `normalize_scenarios`
  resolved the same collision.

### Added
- **Two additions to the scenario schema (#5532)** — both needed to express the built-ins and the
  migrated rules, and both available to any authored scenario:
  - the operation key `"*"`, which applies to every operation a scenario does not name explicitly
    (an exact key always wins). Its canned bodies are not checked against the spec at save time,
    because a wildcard covers operations with different response schemas; status, media type,
    headers and template syntax still are;
  - an override's `status`, which pins the response status but leaves the **body to the spec**,
    resolved as a request sending `?__status=` resolves it. A canned response with no body would
    serve an empty one, and freezing a synthesized body into settings would stop it tracking the
    spec.

- **`migrationNotes` on a mock instance (#5532)** — every rule in a pre-fold `config` that could
  not be translated is reported on the instance and stored in `mock_instances.migration_notes`:
  one that matched no operation in the frozen spec, one an earlier rule had already made
  unreachable, one that set nothing, or one whose latency was clamped to the 30 s ceiling. The
  acceptance criterion is that untranslatable rules are reported, never silently dropped.

### Migration
- **`V250__mock_instance_engine_fold_5532.sql`** adds `mock_instances.settings` (the
  apiome-mock-shaped configuration an instance is served from) and `migration_notes`. `settings` is
  NULL until an instance is folded; either plane folds a row the first time it reads one, so no
  maintenance window is required. `apiome-rest/scripts/fold_mock_instance_configs.py` folds the
  whole estate at once and prints the report (`--dry-run` translates without writing).

  The translation (`app.mock_instance_config`) is spec-aware, because three legacy behaviours
  cannot be reproduced from the stored shapes alone: a body-only rule served the operation's *own*
  default success status; precedence was first-matching-rule-wins per operation, which inverts in
  the keyed shape where an exact key beats the wildcard; and a rule matching nothing in the frozen
  spec did nothing. `active_scenario` lands on `activeScenario`, the key #5531 introduced — the two
  spellings of one concept are now one. The legacy `config` column is kept, unread, as the pre-fold
  record a migrated instance is diffed against.

### Removed
- **`app.mock_engine` and `app.mock_data_generator` (#5532)** — the retired engine's resolver
  (`resolve_response`, `normalize_scenarios`, `resolve_active_scenario_name`, `BUILTIN_SCENARIOS`)
  and its data generator, superseded by `apiome_mock`'s resolver and its format-aware
  `schema_synthesizer`. What both packages genuinely shared — `MockOperation`,
  `extract_operations`, `match_operation` and the path-template compiler — moved to
  `app.mock_routing`, whose name says that it is routing and not an engine. The one piece of
  `mock_data_generator` with no runtime counterpart, `validate_value`, moved to
  `app.mock_schema_validation`.

## [1.307.0] - 2026-08-31

### Added
- **The version's active scenario is now a mock setting the hosted runtime honours (#5531,
  MSC-2.1)** — `GET`/`PUT .../mock/scenarios` carry `activeScenario`, the scenario the mock serves
  when a request sends no `X-Mock-Scenario` header. It is stored in `versions.mock_settings`
  alongside the scenarios it names, travels inside a portable mock bundle, and is a section of the
  MSC-1.4 configuration document.

  Until now the control plane could store and switch an active scenario that nothing in the hosted
  data plane read: `grep -rn "active_scenario" apiome-mock/src` returned nothing, and the runtime
  selected a scenario from the request header alone. Switching a mock to `server-error` and then
  calling the hosted URL returned happy-path responses, with nothing to indicate why. A shipped
  control that changes nothing is a correctness problem, not a nicety.

  The precedence is explicit: **request header → stored `activeScenario` → no scenario**. The
  header stays an outright override, and a version with no stored value behaves byte-identically
  to before. Every response served while a scenario is in effect now names it in the
  `X-Mock-Scenario` response header — including responses for operations the scenario does not
  override, because a caller who sent no header cannot otherwise tell what answered them.

  `activeScenario` must name one of the scenarios saved with it, so a version can never store a
  default that means nothing; the runtime, by contrast, is lenient with a stored name that stops
  resolving (a renamed or deleted scenario) — it logs `mock_active_scenario_unknown` and serves the
  default flow, because an unresolvable default must never take a serving mock down.

  Unlike `scenarios` and `chaos`, the field is *preserved* when a `PUT` omits it and cleared only
  when it is sent as `null`, so an editor written before the field existed cannot silently switch a
  version's mock back to its default flow.

### Changed
- **Mock bundles carry `activeScenario` (#5531)** — a bundle exported from a version defaults to
  the same scenario the hosted mock does, asserted response-by-response by the PMR-3.1 parity
  harness.
- **The MSC-1.2 preview trace reports `scenarioSource`** — `"header"` or `"config"` — so a preview
  says *why* a scenario applied, not merely that one did.

## [1.306.0] - 2026-08-29

### Added
- **`?dryRun=true` on the version mock-settings write routes (#5530, MSC-1.4)** — `PUT
  .../mock/scenarios`, `PUT .../mock/correlation` and `PUT .../mock/fixture-packs` accept
  `?dryRun=true`: the same validation runs, the response describes what *would* be stored, and
  nothing is written.

  It exists so that a mock configuration held as a file — `apiome mock config push --dry-run` —
  can be checked in CI against the *authoritative* validators rather than a second copy of them,
  and so that a real push can validate every section before any of them is stored. Without it a
  document whose scenarios are valid and whose correlation block is not would leave a version
  half-configured, and would report only the first problem rather than all of them.

  The dry-run response is built by the very readers the write path reports with, so it cannot
  describe an outcome the write would not produce — operation keys normalize the same way, fixture
  packs gain the same format defaults, and a cleared correlation block reports as `null`. It
  reports validation, not ownership: the creator/administrator gate lives in the write itself and
  cannot be exercised without writing.

  The parameter defaults to off, so every existing caller is unaffected.

## [1.305.0] - 2026-08-28

### Added
- **Mock authoring catalogue endpoint (#5529, MSC-1.3)** — `GET
  /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/mock/operations` describes a version
  the way a mock editor needs it: every operation it has, with its path, query and header
  parameters (each carrying the ready-to-insert `{{request.*}}` expression), the JSON Pointers the
  success response body actually has, the top-level request-body field names, and the fixture names
  `{{fixture.<name>}}` can read on this version.

  The part that makes response correlation trustworthy is `bindings`: **which response properties
  the `path-params` and `inferred` passes would bind, and to what**, projected before anything is
  saved. Those are not a second implementation of inference — the name-matching rules moved into
  the new `app.mock_correlation_rules`, which `apiome_mock.correlation` now imports, the same call
  `app.mock_match` and `app.mock_template` already made. So the editor's preview cannot promise a
  binding the runtime declines to make.

  Two limits follow from projecting over a response *schema* rather than a rendered body, and are
  reported rather than hidden: a pointer inside an array names member `0` and is flagged
  `repeated` (the runtime binds every member), and a `oneOf`/`anyOf` schema is projected through
  its first branch. The walk is bounded — depth 6, 200 pointers per operation, and a `$ref` cycle
  guard — so a recursive schema terminates.

  Read-only and cheap: it generates the version's OpenAPI document and walks it, needs only
  `versions:view`, writes nothing, and answers for a version whose mock is switched **off** —
  which is when correlation is usually configured for the first time.

## [1.304.0] - 2026-08-28

### Added
- **Mock response preview endpoint (#5528, MSC-1.2)** — `POST
  /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/mock/preview` answers the question a
  mock author actually has: *given this request, what does the mock return?* Send a synthetic
  request (`method`, `path`, `headers`, `query`, `body`, plus `scenario`/`seed` shorthands) and get
  back the status, headers, media type and body the mock would serve — with no mock enabled, no
  instance provisioned, and no live request.

  Every response carries a **decision trace** naming which layer produced the body: `scenario`
  (with the matched rule's zero-based index), `stateful`, `correlation` (with the mode and the
  JSON Pointers it bound), `example` or `synthesis` — plus `forced-status`, `request-invalid`,
  `no-operation`, `method-not-allowed`, `unknown-scenario`, `not-acceptable` and `template-limit`
  for the paths that produce no ordinary body. Without it an author can see *that* a value
  appeared but not *why*, which is most of the value of a preview.

  The render is **not** re-implemented here. REST authenticates and authorizes the caller, builds
  the version's portable mock bundle, and asks apiome-mock's internal `/__preview__` endpoint to
  render it through `serve_compiled_request` — the same function its data plane and the portable
  runtime call. A preview therefore cannot disagree with the served response, and apiome-mock's
  suite asserts exactly that by rendering one correlated request both ways.

  An optional `settings` override previews an **unsaved draft**: it overlays the stored settings
  per key (scenarios, chaos, fixture packs, callbacks, correlation), is canonicalized and validated
  with the same rules its save route applies — so a draft that could never be saved is a 422 rather
  than a silently ignored no-op — and persists nothing. It requires `versions:edit`; previewing the
  stored settings needs only `versions:view`.

  Preview never writes: session state lives and dies inside the render, no callback is delivered,
  and no usage, audit or provisioning row is touched. Chaos is *reported* rather than applied, so a
  preview never sleeps for a configured latency or randomly answers 500. Renders are rate limited
  per version (`APIOME_MOCK_PREVIEW_RATE_LIMIT_PER_MINUTE`, default 120) and the synthetic body is
  capped (`APIOME_MOCK_PREVIEW_MAX_BODY_BYTES`, default 256 KiB).

  Configuration: `APIOME_MOCK_INTERNAL_BASE_URL` (the mock service's **internal** address) and
  `APIOME_MOCK_INTERNAL_TOKEN` (shared with apiome-mock). Both are required — with either unset the
  endpoint fails closed with 503. The token is deliberately not `INTERNAL_SERVICE_TOKEN`:
  rendering a preview should not carry the secret that unseals auth-provider credentials. See
  [docs/guide/mock-response-preview.md](../docs/guide/mock-response-preview.md).

## [1.303.0] - 2026-08-28

### Added
- **Request-correlated mock responses (#5527, MSC-1.1)** — `GET`/`PUT
  /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/mock/correlation` read and write a
  `responseCorrelation` block in `versions.mock_settings`, alongside the existing `scenarios`,
  `chaos`, `fixturePacks` and `callbacks` keys. The block makes the mock's **default** response
  path answer with the request's own values — with no request header, so a generated SDK or a
  browser app gets it too, where scenario overrides (`X-Mock-Scenario`) and stateful CRUD
  (`X-Mock-Session`) could never reach.

  Four modes: `off` (the default — byte-identical to today), `path-params` (a response property
  named after a path parameter takes the request's value, at every depth and inside array
  members), `inferred` (that plus echoing request-body fields back on `POST`/`PUT`/`PATCH`, while
  `id`/`createdAt`/`updatedAt` and anything absent from the request stay synthesized), and
  `explicit` (only a per-operation map of response JSON Pointer to template expression). The
  pointer map applies in every mode except `off` and always wins for the pointer it names.

  Expressions are the existing bounded `{{ … }}` language, validated on save with
  `validate_template_value`, so a bad expression is a 422 rather than a serve-time surprise;
  operation keys must name a real operation in the version's generated OpenAPI document; bindings
  saved with `mode: "off"` are refused rather than silently ignored. Limits: 200 operations, 50
  pointers each, 64 KiB. `responseCorrelation` is a bundled settings key, so a portable bundle
  correlates identically offline (the PMR-3.1 parity harness asserts it). See
  [docs/guide/mock-response-correlation.md](../docs/guide/mock-response-correlation.md).

### Removed
- **The dead `mock_settings.fixtures` reader (#5527)** — `apiome_mock.fixture_data.parse_fixtures`
  read a flat fixtures map that nothing in apiome-rest ever wrote; only fixture *packs* are wired.
  A configuration surface that silently did nothing was dropped rather than given a writer.
  Hosted template fixture data comes from `fixturePacks` alone; the bundle path is unchanged.

## [1.263.0] - 2026-08-17

### Added
- **Re-issue an outstanding member invitation (#5305)** — `POST /v1/access/{tenant_slug}/members/{user_id}/resend-invite`.
  Apiome does not mail invitations: an invitee already holds an account and their `pending`
  membership flips to `active` the next time they sign in. Re-issuing therefore *renews* the
  invitation rather than re-sending a message — the membership row is re-stamped
  (`touch_pending_membership`, scoped to `status = 'pending'` in SQL so an invitation accepted
  in between cannot be un-accepted) and the renewal is written to the access ledger as
  `member.invite_resent`, which the existing `?filter=member` audit tab already covers.
  Gated on `members:create`; consumes no seat, because the pending membership already holds
  one. Answers 404 when the user has no membership in the tenant and 409 when their
  membership is not pending.

### Changed
- **`GET /v1/access/{tenant_slug}/members` carries three more facts per member (#5305)** —
  `joined_at` (`tenant_users.created_at`, when the membership was first written, as distinct
  from the existing `member_since` = `updated_at`, which moves with every status change),
  `last_active` (`users.last_login_at`, V070) and `two_factor_enabled` (the Better Auth
  `users."twoFactorEnabled"` flag, V201). All three read columns that already existed; the
  response is additive, so existing clients are unaffected.

## [1.262.0] - 2026-08-15

### Fixed
- **Project versions were re-linted when listed (#5259)** — the Versions screen rendered a
  lint badge per row that called `GET .../{version}/lint` for every revision, and for any
  revision without a stored report (hand-authored, forked, pushed, pre-V160) that endpoint
  rebuilt the OpenAPI document, ran the linter **and** the external validation pack — on
  every list render, N times over. Fifty revisions meant fifty concurrent lints.

  **The report now lives on the version record and is served from there.**
  `GET /v1/versions/{tenant_slug}/{project_id}` carries each row's stored `qualityScore` /
  `qualityGrade` (`VersionSchema`; `get_versions_for_project` / `get_version_by_id` select the
  V124 columns), so the list renders from the record and issues no lint requests.
  `GET .../lint` serves the stored `quality_report` whenever it is current; the persisted
  report now carries a `source_fingerprint` (sha256 of the reconstructed OpenAPI document,
  `app.version_quality_capture.openapi_source_fingerprint`), and freshness is decided by
  rebuilding the document and comparing — never by re-linting. A revision with no stored
  report, or whose content changed since capture, is linted once and the result **persisted**
  (`persist_version_lint_report`), so the next read is a plain read; a `baseRevisionId`
  comparison is computed live and never stored. Reports without a fingerprint (pre-#5259,
  canonical-model imports) are served as-is; a legacy native import re-linted from its
  canonical model is stored on first open too.

  **Linting runs on version changes and imports only.** Push (`POST /v1/versions/{t}/{p}`)
  and fork schedule the shared capture (`capture_version_quality_score`, moved out of
  `spec_import_engine`) as a background task; the publish precheck stores the report it
  already computed; import/conversion captures gained the fingerprint + guide context
  (`persistable_lint_report`). Stored reports echo the guide they were scored under
  (`guideId` / `guideName` / `guideSource`) so the read path has the same context as a live run.

## [1.261.0] - 2026-08-07

### Added
- **Bounded primitives search (DWX-3.1, private-suite#2683)** — `GET
  /v1/primitives/{tenant_slug}` has always answered with *every* primitive a tenant
  can see. A tenant that has imported a standard library has thousands of rows, and
  the unified workspace's type picker — a 320px rail — cannot be built on a read like
  that. The endpoint now takes `q`, `scope`, `namespace`, `limit` and `cursor`, and
  answers those with at most `limit` rows plus the four type-picker tab counts
  (`app.primitives_search_store`, `PrimitiveSearchPage`).

  **Both shapes, one path.** A caller that asks none of the five bounded parameters
  gets the classic JSON array, from the same `get_primitives_for_tenant` read, with
  `category` working exactly as before — the classic property dialogs are unaffected
  and keep working until private-suite's DWX-8.3 retires their callers. Asking any one
  of the five switches the response to the paged envelope. The two shapes list the
  same catalog: the same visibility scope (`is_system` ∪ the caller's own rows) and
  the same `(namespace, name)` deduplication, so a primitive is never reachable
  through one and not the other.

  **The scope classification is the client's rule, in three places that must agree.**
  The four tabs — Standard, Core, Tenant, Custom — are derived in the designer today
  by `classifyPrimitive`. A server that filtered by scope while the client grouped by
  its own rule would silently hide types, so the rule is now written three times over
  one shared fixture (`tests/fixtures/primitive_scope_cases.json`): the TypeScript
  original, `classify_scope` in Python, and `SCOPE_EXPRESSION` in SQL. `pytest` checks
  Python against the fixture and SQL against Python over real rows; the designer's jest
  suite checks the TypeScript half against its copy of the same cases.

  **The cursor is keyset, not an offset.** It carries the sort key of the last row
  handed out, so a primitive created mid-scroll cannot shift a page boundary and make
  a row repeat or vanish; a live-DB test walks 5,000 rows and asserts each is visited
  exactly once. It is opaque, and a token this endpoint did not mint is a 400 rather
  than a silently ignored parameter that would restart a paging client at page one
  forever. An unknown `scope` is likewise a 400 — a misspelling that quietly listed
  every tab would make an unbounded read look like a bounded one.

  Tenancy is unchanged and enforced by construction: another tenant's private types
  are not filtered out of the result, they are never in the visibility CTE, so no
  query, namespace, cursor or `$ref` reaches one.

  `apiome-db/scripts/V244__primitives_bounded_search_indexes_2683.sql` adds the
  read-path indexes: a `(namespace, name, tenant_id)` b-tree for the dedupe and the
  cursor ordering, an `(is_system, source, namespace)` b-tree for the scope
  classification, and `pg_trgm` GIN indexes so a leading-wildcard `ILIKE` is not a
  sequential scan of the registry. Nothing there changes a column, a constraint or a
  value, and — as in V230 — the trigram block degrades to a `NOTICE` where the
  migration role cannot install contrib extensions.

## [1.260.0] - 2026-08-05

### Added
- **Programmable custom palette actions (DUW-5.5, private-suite#2592)** — The ⌘K
  palette's `Actions` band has been a fixed registry of five built-ins since DUW-5.4;
  "programmable" means a tenant defining its own rows — `Open runbook for {subject}`
  against every class whose name contains `Invoice` — and that needs the definitions
  stored somewhere durable and tenant-scoped. `apiome.workspace_custom_actions` (V243)
  and the CRUD surface under `/v1/workspace/{tenant_slug}/custom-actions` are that
  storage.

  A definition is a *declaration*, never a script. Its matcher is a subject kind
  (`class`, `path`, `property`, `any`) plus an optional case-insensitive label
  substring; its effects are an ordered list drawn from a closed vocabulary —
  `hydrate-set`, `lens-switch`, `open-inspector-tab`, `run-consumption-query`,
  `open-url` — each element validated down to exactly the fields its type declares
  (`workspace_custom_action_rules`). Unknown keys are rejected rather than ignored, so
  a typo cannot become an effect that silently does less than its author meant;
  `open-url` accepts absolute `https://` URLs only, with no embedded credentials,
  because `javascript:` and `data:` are not effects, they are payloads. Anything
  resembling SDK-script execution stays out of scope by design and defers to the
  DUW-7.4 sandbox. The database independently pins the outer shape — a JSON array of
  1–5 elements under 16KB — so no write path can park a script here even if it skipped
  the service schema.

  Tenancy comes from the token, never the URL: every statement is scoped by the
  caller's tenant, so another tenant's action is a 404 — whether it exists is not
  something this API confirms. Reads are open to any authenticated member (the palette
  performs one for everyone); writes require an attributable user holding
  VERSIONS/EDIT, the same gate the domain folders use for reorganizing what everyone
  sees. Deletes are soft, and a live action's name is unique per tenant
  case-insensitively — two rows both drawn as `Open runbook…` in one band would be
  indistinguishable to the reader. The management page that will wrap this API is
  DUW-8.2 (private-suite#2602); until it lands, these routes are the management
  surface, which is why every 422 names the offending field as a pointer
  (`effects[1].lens`).

## [1.258.0] - 2026-08-05

### Added
- **Response status codes on the scoped path read (DUW-4.3, private-suite#2583)** —
  The unified workspace's paths lens draws every operation as a lane, and a lane ends
  in the codes it answers with (`200·400·401`), coloured by method. Those codes were
  the one thing on the lane the scoped read did not carry: `GET
  /v1/workspace/{tenant}/version/{version_id}/paths` shipped each operation's
  `operation_id`, `summary` and `deprecated` flag and left everything about a response
  with the per-path `/full` endpoint. That is right for a response *body* — schemas,
  content types and examples are inspector-sized data for one selected operation — but
  a status code is a label the canvas prints on every lane it draws, and there is no
  number of round trips between "one" and "one per operation" that answers it.

  Each operation now carries `response_codes`: the status codes it declares, as
  strings, ascending (`default` sorts after the numbers), empty when it declares none.
  They come from a lateral aggregate over `path_operation_response_link` →
  `shared_path_response` on the statement that was already reading the operations, so
  a page of paths costs the same two statements it did before, whatever its size. The
  codes are per *operation*, not per path: responses are shared per path in this schema
  and linked per operation, so a read that rolled up by path would give every verb on
  `/customers` the same list. Response bodies stay exactly where they were.

## [1.257.0] - 2026-08-04

### Added
- **Schema↔path consumption index (DUW-1.4, private-suite#2571)** — Five surfaces
  of the unified workspace need to know which operations consume which classes and
  *how*: the combined lens's edges (solid amber for a schema named directly by a
  request or response, dashed rose for one reached through a parent class), the
  tree's per-path `Schemas` rows (`Customer 200`, `Address nested`), the palette's
  "find every path that consumes X" action, the inspector's `Consumes` list, and
  the status bar's `N schema↔path links` chip. Today's derivation is the designer's
  `createAllEdges` — O(classes×properties) over a full-catalog fetch, and
  schema↔schema only; it has never known that an *operation* consumes anything.
  `GET /v1/workspace/{tenant}/version/{version_id}/consumption` answers it from
  the server, in seven statements.

  Every edge names both members, how the consumption arrives (`request`,
  `parameter`, `response.<status>`) and — for a nested one — the chain of classes
  it hangs off, so one response drives all five surfaces. The facts arrive twice:
  flat in `edges`, the shape the canvas draws, and rolled up per path in `paths`,
  the shape the tree nests under a path with the badge each row prints.
  `link_count` counts operation↔class edges, `path_link_count` distinct path↔class
  pairs.

  Five decisions are load-bearing:

  - **A reference is a `$ref` anywhere in a payload.** The catalog stores an
    operation's schemas as a `class_id` column, an inline schema or a legacy `data`
    blob, and a class's own references as `$ref`, `items.$ref`,
    `allOf`/`anyOf`/`oneOf`, or any of those nested inside another. Enumerating the
    shapes would mean re-deriving the emitter's rules in reverse and losing an edge
    whenever they gained a case, so the resolver walks the JSON and collects every
    `$ref` — exactly the set of names the emitted document carries. Only the tables
    the emitter reads are indexed (`shared_path_response`(`_content`),
    `shared_path_request_body_content`, `shared_path_parameter`); the V028-era
    tables V031–V034 superseded are read by nothing, and indexing them would invent
    edges no exported document contains.

  - **Nesting is resolved per class, not per operation, and breadth-first.** Two
    operations returning `Customer` reach the same descendants through the same
    edges, so the walk runs once per class and is memoized — walking per operation
    would be the client-side derivation moved to the server and multiplied by the
    operation count. Breadth-first makes `via` the *shortest* parent chain, and
    ties break on class name, so "nested via X" is a property of the catalog rather
    than of row order. Cycles terminate by construction: the visited set includes
    the root, so a self-referencing class and a mutual pair are each walked once
    and the root is never nested under itself. Depth is capped at 6 hops
    (`depth_cap`) and a graph continuing past it says so through `depth_capped`.

  - **A directly named class is never also nested.** The canvas draws one line
    between two nodes, and the solid one is the truthful description.

  - **The scope narrows paths; the graph is always whole.** `domain_id` and
    `path_ids` are mutually exclusive path selectors; `class_ids` narrows the class
    side and composes with either, because "which of these classes does
    `customers/` consume" is a real question. The class filter is applied *after*
    the walk — filtering the graph first would drop the very parents a nested edge
    is reached through, so "every path that consumes `Address`" would miss every
    path that reaches it through `Customer`, which is most of them. A
    domain-scoped answer therefore still names classes outside the domain, which is
    what "nested via parent" means.

  - **Caching is content-addressed.** The index is computed on read and never
    persisted (no table in v1); the response carries a strong `ETag` digested from
    the body, which keys it on version content by construction *and* on the scope —
    something a stored version-content hash would not do — so a repeat read is a
    `304` until the index actually changes. Same convention as the APX-3.4 agent
    outputs.

  Bounded and honest about it: `edge_limit` caps the edge list at 5000 with
  `truncated` set, and there is no cursor, because an edge means nothing without
  both members it connects. Unresolvable path or class ids come back in
  `missing_ids` rather than being silently absent, and the two id selectors share
  the DUW-1.2 cap of 200 per request. Verified against a seeded 218-path /
  250-class catalog under `pg_virtualenv`: the mockup's
  Customer/Address/ContactMethod × 4 operations reproduced edge for edge including
  `nested via parent` and the status bar's six path↔class pairs, a self-referencing
  class and a mutual pair terminating on stored rows, seven statements whatever the
  scope, and p95 ≈ 5.3 ms against the epic's 300 ms budget. No migration: V242's
  `domain_id` indexes and the existing `version_id` indexes cover the reads. The
  BFF routes and typed client are DUW-1.5.

## [1.256.0] - 2026-08-04

### Added
- **Domain summary & counts API (DUW-1.3, private-suite#2570)** — The workspace
  tree draws a badge on every domain folder before anything is hydrated —
  `customers/ 3·4`, `billing/ 5·9`, `shared/ 8` — and each lens badges the same
  folder with a different number (`3 classes` in the schemas lens, `4 ops` in the
  paths lens). Deriving any of that in the browser would mean fetching the whole
  catalog first, which is the read DUW-1.2 exists to eliminate.
  `GET /v1/workspace/{tenant}/version/{version_id}/summary` answers it in one
  round trip: every folder with `class_count`, `path_count`, `op_count` and
  `enum_count`, plus shallow member lists — class rows (id, name, kind, version
  badge) and path rows carrying their operations (verb, `operation_id`,
  `summary`, `deprecated`) — which is every field the three tree lens panels
  draw.

  Counts are exhaustive; member lists are not. A badge that is only right for the
  first page is not a badge, so each count covers the folder's whole membership,
  while the rows beside it are capped per folder by `member_limit` (default 50,
  clamped to 200, `0` for badges alone) and a folder that was cut reports
  `classes_truncated` / `paths_truncated`, continuing through DUW-1.2's paged
  reads. `class_count` and `enum_count` *partition* a folder's classes rather
  than overlapping, matching the mockup's `customers/ 3 classes` above three
  objects and one enum; each row carries a `kind` of `object`/`enum`/`union` read
  from the stored schema column, so the `Schemas` and `Enums & unions` groups
  need no second pass, and objects sort first so a truncated list is cut from the
  enum group upward. The `v2.1` badge is the version's own label repeated per
  class row — a class has no version of its own — so a tree row renders without
  consulting the envelope.

  The cost is four statements whatever the version holds: a window function
  carries each domain's totals onto its own member rows, so a 40-folder catalog
  costs what a one-folder catalog does. A per-domain count query would be exactly
  the N+1 this endpoint exists to prevent, and would pass every functional test.
  The `shared/` bucket is joined with `IS NOT DISTINCT FROM`, because `NULL =
  NULL` would silently drop the largest folder in most catalogs, and empty
  folders are listed with zeroes so a newly created one cannot look like a failed
  write. Reads commit, matching the scoped reads: psycopg2 opens a transaction
  for a bare SELECT too. Verified against a seeded 218-path / 250-class catalog
  under `pg_virtualenv` — every badge checked against its own `SELECT COUNT(*)`,
  the mockup's numbers reproduced, and p95 ≈ 3.5 ms against the ticket's 300 ms
  budget. No migration: V242's `domain_id` indexes and the existing `version_id`
  indexes cover the aggregates. The per-path schema rows the combined lens nests
  under an operation remain DUW-1.4.

## [1.255.0] - 2026-08-04

### Added
- **Selection-scoped class and path reads (DUW-1.2, private-suite#2569)** — The
  only way to read a version's classes with their properties and tags was
  `GET /v1/classes/{tenant}/version/{version_id}/with-properties-tags`, three
  queries with no LIMIT that return the whole catalog. Twelve designer call
  sites use it, `/editor` fires it twice on mount and again after every
  single-class edit, and that is the direct cause of the browser choking on a
  large catalog. `/v1/workspace/{tenant}/version/{version_id}/classes` and
  `…/paths` answer the question the canvas actually asks: *these items*, or
  *this folder*, never *this version*. A selection is mandatory — omitting both
  `class_ids` and `domain_id` is a 400 rather than a convenience default,
  because that default would be the very read this endpoint exists to replace,
  and supplying both is a 400 too rather than a guess about which one wins. The
  server cap is enforced two different ways for one reason: a page size over 200
  is clamped, since a domain listing hands back a cursor and the client has a
  working continuation, while an id list over 200 is refused, since there is no
  cursor for an arbitrary id set and quietly answering a different question than
  the one asked would be undetectable. Both bounds are echoed in every response
  and documented in the OpenAPI parameter descriptions, so a client never has to
  trigger a 400 to discover them. A bounded read is still a bulk read: three
  statements hydrate a page of classes and two hydrate a page of paths, whatever
  the page size, so cost tracks the selection rather than the catalog. Ids that
  no longer resolve — a class deleted since the selection was made, one
  belonging to another version, one that is not a UUID at all — come back in
  `missing_ids` rather than as a silently short response that would leave an
  unexplained hole on the canvas. Every query is scoped by `version_id` even in
  id mode, which is the tenancy boundary: the version is resolved against the
  caller's tenant first, so an id from another tenant's catalog matches nothing.
  `total` is the size of the whole selection rather than of the page, which is
  what the workspace sizes its node budget against, and pagination reuses the
  same opaque cursor format the export and import manifest surfaces already
  speak. Paths carry their operations with each operation's `operation_id`,
  `summary` and `deprecated` flag, because the mockup's paths lens draws the
  operationId beside every verb; parameters, request bodies and responses stay
  with the per-path `/full` endpoint, which is inspector-sized data for one
  selected operation. The legacy full-version read is deliberately unchanged —
  exports, scoring and readiness sweeps really do want every class — but now
  carries a deprecation note pointing here. No migration: V242's `domain_id`
  indexes were added for exactly these reads.

## [1.254.0] - 2026-08-04

### Added
- **Domain folders for schemas and paths (DUW-1.1, private-suite#2568)** — The
  unified workspace organizes a catalog into domain folders and scopes the canvas
  to one of them, but classes and paths had no hierarchy at all: two flat lists
  read with `ORDER BY name ASC`. Tags and canvas groups are not that hierarchy —
  tags are project-scoped, many-to-many and for filtering; canvas groups are
  per-layout visual furniture. A folder that scopes a *fetch* has to be exactly
  one per item, version-scoped, and stored beside the item it groups, so V242
  (`apiome-db`) adds `apiome.domains` plus a nullable `domain_id` on
  `apiome.classes` and `apiome.version_path`. `/v1/domains` lists, creates,
  renames and deletes them, and moves a class or a path between them.
  `shared/` is deliberately **not** a row: a member with `domain_id IS NULL` *is*
  in it, so the bucket always exists, cannot be renamed or deleted, and is
  synthesized into the list response with `id: null` and `virtual: true`. The
  slug `shared` is reserved by a CHECK so no stored domain can draw the same
  folder. Deleting a domain never deletes its contents — the delete is a soft
  delete, and V242's `trg_domains_soft_delete_release` releases every member to
  `shared/` in the same statement, with `ON DELETE SET NULL` covering a hard
  delete too; the response reports how many classes and paths moved. A database
  trigger, not a service-layer check, rejects a domain assignment that crosses
  versions or targets a deleted domain, because a foreign key can constrain
  `domain_id` but knows nothing about `version_id` on either side. Existing
  catalogs are backfilled: paths seed domains from their first *meaningful* path
  segment — skipping templated segments (`/{customerId}` names an instance) and
  API version prefixes (`/v1/` is on every path, so it partitions nothing) — and
  classes follow a project tag whose name slugifies to a seeded domain. Anything
  unmatched stays in `shared/`, which is the honest outcome for a catalog with no
  path structure and no tags. Per-domain counts for the tree badges are DUW-1.2 /
  DUW-1.3, not this release.

## [1.253.0] - 2026-08-03

### Added
- **Slate custom domains + DNS/TLS (Slate 10.1, private-suite#119)** — The
  editing half of the domain inventory APX-3.1 could only report, under
  `/v1/slate`: attach a hostname to a lane and get back the exact DNS rows to
  publish, verify ownership against the tenant's live records, probe the host to
  see what certificate it is actually serving, make a host canonical, park
  renewal, and detach. A subdomain is delegated with one CNAME; an apex is
  proven with a TXT record and pointed with ALIAS/ANAME, because RFC 1034
  forbids a CNAME beside the SOA and NS records every apex carries. A failed
  check reports what the resolver found, not merely that it failed.
  `app.slate_dns` is a dependency-free DNS client (the stdlib resolver discards
  the CNAME chain and every TXT record — the two things verification needs);
  `app.slate_tls_probe` completes a verified TLS handshake and reads the peer
  certificate, so every certificate field is an observation of the live host at
  a stated instant and a renewal is *detected* (the serial changes) rather than
  assumed. Nothing here issues, stores or renews a certificate: the edge does
  (`deploy/Caddyfile`, Caddy on-demand TLS against Let's Encrypt), and
  `GET /v1/slate/tls/authorize?domain=` is the gate it asks first — a single
  conjunction (row exists, ownership verified, renewal on), unauthenticated
  because the caller is a TLS handshake with no session to present. Requires
  V241 (`apiome-db`), which adds the verification/certificate lifecycle columns
  and CHECKs that make "verified with no timestamp" and "active with no expiry"
  unrepresentable. New settings: `APIOME_SLATE_DOMAIN_DNS_TARGET`,
  `APIOME_SLATE_DOMAIN_RESERVED_ZONE`,
  `APIOME_SLATE_DOMAIN_VERIFICATION_SECRET` (fails closed in production).

## [1.252.0] - 2026-08-03

### Added
- **Snippet service (SDK-2.3, #4487)** — Per-operation usage snippets
  (install + call code) rendered server-side from the persisted canonical
  model, as the single source of truth for the browse operation pages
  (SDK-3.3) and the Try It copy-as-code feature (SIM-3.5). Two surfaces share
  one pure renderer (`app.snippet_render`):
  `GET /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/snippets/{operation_id}?lang=`
  (authenticated, published revisions only) and
  `GET /v1/browse/tenants/{t}/projects/{p}/versions/{v}/snippets/{operation_id}?lang=`
  (anonymous, published+public with uniform 404s, sharing the public-export
  rate limit). Languages: `ts` (built-in `fetch`), `python` (`httpx`, with a
  `pip install httpx` install line), and `curl`, plus browse-vocabulary
  aliases `fetch`/`httpx`. Output shape, escaping, and `$API_KEY`-style
  secret placeholders mirror the client-side Try It generators; request
  bodies are minimal valid instances synthesized deterministically from the
  payload schema, so responses are content-addressed (`ETag` / 304). The
  structured response carries the resolved operation, the synthesized
  request, and a placeholder inventory so consumers need no post-processing.
  Snippets derive from the canonical spec directly — the original SDK-2.1/2.2
  template dependency was dropped when those tickets were cancelled.

## [1.251.0] - 2026-08-02

### Added
- **WIT (WebAssembly Component Model) import (IXH-7.9, #5134)** — A new `wit`
  `ImportSource` adapter makes WIT packages importable (file, URL, paste, or a
  multi-file package fileset). Worlds and interfaces normalize to canonical
  services on the RPC paradigm, functions to operations (a top-of-return
  `result<ok, err>` becomes the RESPONSE/ERROR message pair; `option<t>` maps to
  canonical nullability, `list<t>` to list nesting), and the WIT type system to
  canonical types: `record` → RECORD, `enum` → ENUM, `variant` → UNION with case
  payloads preserved, `flags` → ENUM with bitset semantics flagged, `type`
  aliases → ALIAS, `resource` → RECORD carrying its constructor and methods in
  extras.
- **Cross-file `use` resolution** — Archive/git filesets merge every `.wit`
  member into one package, so `use iface.{type}` statements resolve against
  sibling files; a `use` naming another package is recorded as an external
  reference (`inferred` / `source_incomplete` ledger row), never fabricated or
  dropped.
- **Capability limits, never silent drops** — Constructs the canonical model
  cannot hold (resources with methods, `borrow<…>` handle semantics, tuples,
  nested results, `stream`/`future` wrappers) are preserved in extras and
  reported on the import preview coverage ledger as `partially-mapped`
  capability limits; declared parser limits (`include` expansion, secondary
  nested package blocks) carry `not-parsed-by-adapter` registry entries.
- **Corpus ladder** — Full six-rung WIT corpus (minimal, typical calculator,
  world composition, type-system stress, WASI-style key-value real-world, and a
  multi-file package set), a five-class negative tier, golden snapshots,
  round-trip matrix rows, and the lint capability matrix / catalog format
  registry entries.

## [1.250.0] - 2026-08-02

### Added
- **Gateway configuration import (IXH-7.8, #5133)** — Two new `ImportSource`
  adapters make gateway configs importable: `kong` (Kong declarative / deck
  YAML-JSON, single file or split fileset) and `gateway-api` (Kubernetes Gateway
  API `HTTPRoute` manifests, single document, multi-document stream, or manifest
  directory). Routes normalize to canonical REST operations — hosts, path
  patterns (regex paths become inferred `{param}` templates with the original
  pattern preserved as evidence), methods, header/query matches, and backends.
  Kong auth plugins map to canonical security where a mapping exists
  (`key-auth` → apiKey, `jwt` → bearer, `oauth2`, `basic-auth`, `mtls-auth`,
  `openid-connect`) and are preserved as unmapped hints otherwise; Gateway API
  filters are preserved verbatim in extras.
- **Schema absence as a capability limit** — Gateway configs carry no
  request/response schemas, so both formats route to the catalog as
  non-publishable with the reason stated (supply schemas and convert to
  promote), and the import preview coverage ledger reports the missing schemas
  as `inferred` / `source_incomplete` — a capability limit of the source
  format, never a drop.
- **Credential hygiene** — Kong consumer credentials (key-auth keys, basic-auth
  passwords, JWT secrets) and secret-shaped plugin config values are redacted at
  parse time (counts retained, values never imported); `kong` joins the
  always-enforced intake secret-scrub formats, and a `secrets-kong.yaml`
  adversarial fixture guards the pipeline end to end.
- **Corpus ladder** — Full six-rung corpus for both formats (single-service,
  multi-service, and plugin-heavy Kong configs; single-route, multi-document,
  and filter-heavy HTTPRoute manifests, plus split-file/manifest-directory
  filesets), five-class negative tiers, golden snapshots, and round-trip matrix
  rows.

## [1.249.0] - 2026-08-02

### Added
- **OpenAPI Overlay 1.0 pre-processor (IXH-7.7, #5132)** — The OpenAPI adapter now
  resolves a base document plus one or more Overlay Specification 1.0 documents at
  import time, with per-value provenance (`app/openapi_overlay.py`).
  - **Action semantics**: `update` deep-merges into object targets (nested objects
    merge recursively; primitives and arrays replace), **appends** to array targets,
    and replaces primitive targets in place; `remove: true` deletes the selected
    nodes (list indices deleted highest-first so survivors never shift under the
    removal). Targets are JSONPath, evaluated through the custom-rule DSL's hardened
    Spectral-compatible parser (`parse_jsonpath_expression`, now public).
  - **Fileset intake**: the adapter accepts multi-document filesets
    (`InputKind.FILESET`) — members classified by version marker (exactly one
    `openapi`/`swagger` base; every `overlay: 1.x` member applied in member-path
    order, each seeing the previous one's result, so a chain's last writer wins);
    unclassified members (e.g. `$ref` targets) ride along untouched and are listed
    as ignored.
  - **Per-value provenance**: each set/replaced/appended/removed value is recorded
    (JSON Pointer, kind, contributing overlay, action index, target expression) on
    the canonical model's `extras["overlay"]`, rendered by the import preview
    coverage ledger as document-scoped `mapped` rows — capped at 500 records with a
    declared-truncation row, never a silent cut.
  - **Bare overlay prompt**: a lone overlay document is *detected* (claimed at 0.9,
    no format pinned) and rejected with new taxonomy code
    `INPUT_OVERLAY_BASE_MISSING`, whose remediation prompts for the base document —
    instead of an obscure parse error. A fileset with overlays but no base gets the
    same code.
  - **Findings, not silence**: actions whose target matches nothing, or that are
    structurally unusable (no target, neither `update` nor `remove`, invalid
    JSONPath, type-mismatched update, root removal), surface as new registered
    warning rules `intake.overlay-unmatched-target` / `intake.overlay-action-invalid`
    merged into the import lint report (tenant-governable like any registered rule).
  - **Corpus ladder**: `openapi/34-overlay-basic-set/` (add + update + remove in one
    overlay), `openapi/35-overlay-chain-set/` (two-overlay chain with a last-writer
    override), and negative `openapi/negative/06-bare-overlay.yaml`
    (`INPUT_OVERLAY_BASE_MISSING`), with canonical goldens; the openapi `multi-file`
    rung waiver is retired.

## [1.248.0] - 2026-08-02

### Added
- **GraphQL Federation supergraph and subgraph import (IXH-7.6, #5131)** — The GraphQL
  adapter is now composition-aware: a supergraph SDL and a multi-file subgraph set both
  import with per-type / per-field subgraph ownership carried through the canonical model
  (`app/graphql_federation.py`, docs in `docs/graphql_federation.md`).
  - **Ownership**: supergraph ownership is read off the Apollo `join`-spec directives
    (`@join__type` / `@join__field`, `external: true` references excluded); a subgraph
    set derives ownership from file boundaries (`@external` stubs excluded). Recorded as
    `extras["federation"]` on the artifact and `extras["subgraphs"]` on every owned
    type/field/service/operation, so ownership participates in the fingerprint.
  - **Subgraph SDL builds bare**: real-world subgraph files apply `@key`/`@shareable`/
    `@link` without defining them; the parser injects exactly the missing Federation v2
    definitions before `validate_sdl` (author definitions never overridden).
  - **Diff attribution**: `GraphQlDiffLabeler` — the first provider on the MFI-3.x
    `DiffLabeler` SPI — labels every change with its owning subgraph(s)
    (`owned by subgraph 'reviews'`, `subgraph ownership: products → reviews`).
  - **Composition lint dimension**: new `composition` category in the GraphQL rule pack —
    `graphql.composition-invalid-key`, `graphql.composition-non-shareable-field`,
    `graphql.composition-unresolvable-selection` (pure checks over the subgraph set), and
    `graphql.composition-error` surfacing the bundled `rover supergraph compose` verdict
    captured at import time (worker-loop bridge; degrades to "no verdict" when the tool
    or its composition plugin is unavailable). Every finding names the offending
    subgraph. Federation spec-machinery names (`join__Graph`, …) are exempt from the
    GraphQL naming rules.
  - **Directive preservation**: applied directives are no longer stripped —
    `print_schema_with_directives` restores them on the parser's canonical SDL and the
    normalizer's `raw["sdl"]`, and the emitter rebuilds custom directive definitions
    (`extras["directive_definitions"]`) as real `GraphQLDirective`s and re-attaches the
    per-entity `extras["directives"]` applications onto the printed SDL with validation
    fallback. A GraphQL→GraphQL supergraph round-trip is canonical-diff clean.
  - **Corpus ladder**: `graphql/13-federation-set/` (products/reviews/inventory,
    `multi-file` rung) and `graphql/14-federation-supergraph.graphql` (`composition`
    rung), with canonical goldens.

## [1.247.0] - 2026-08-02

### Added
- **Protobuf descriptor set / buf image binary intake (IXH-7.5, #5130)** — Real gRPC
  deployments distribute a serialized `FileDescriptorSet` (or a buf image), not a `.proto`
  source tree; the gRPC adapter now imports that artifact directly.
  - **Binary parse seam** (`ImportSource.accepts_bytes` / `parse_bytes`): the import
    pipeline consults the adapter before decoding an upload to text and routes claimed
    binary payloads to `parse_bytes` under the same IXH-6.5 size/time/memory stage guards
    (the raw-bytes ceiling applies before the parse ever runs). Text-only adapters are
    unaffected (default declines).
  - **gRPC adapter**: `parse_bytes` decodes a `FileDescriptorSet` / buf image with the
    pure MFI-9.1 read layer — dependencies resolve from within the set, with no
    filesystem, network, or `buf` toolchain access — and feeds the existing Protobuf
    normalizer. Payloads are claimed by content sniff (`sniff_file_descriptor_set`) or by
    conventional suffix (`.binpb`/`.desc`/`.protoset`), so malformed descriptor uploads
    fail with descriptor-specific taxonomy codes (`INPUT_MALFORMED`, or `INPUT_TRUNCATED`
    when the wire stream is cut off mid-element via a top-level wire walk) instead of
    `INPUT_ENCODING_INVALID`. The Connect-RPC adapter delegates the same seam.
  - **Detection**: `DetectionInput` gains optional undecoded `data` bytes; the gRPC
    adapter and the registry sniffer claim descriptor-set bytes at 0.9 confidence, so
    binary uploads auto-detect and pre-flight routes them to the `grpc` importer.
  - **Paired corpus contract**: `protobuf/07-inventory-source.proto` and the descriptor
    set / buf image compiled from it (`08`/`09-*.binpb`) must import to the same
    canonical model and fingerprint; binary negatives assert the truncated/malformed
    codes through the real pipeline. The corpus harness reads binary entries as bytes and
    drives `parse_bytes`.
  - gRPC server reflection discovery through the SSRF-guarded fetcher already shipped in
    MFI-9.3 and is unchanged; `parse_bytes` completes the pairing by importing the same
    descriptor bytes reflection returns.

## [1.246.0] - 2026-08-02

### Added
- **Import/export observability — stage timings, failure reasons, metrics (IXH-6.6, #5125)** —
  Diagnosing "imports are slow for one tenant" meant reading logs; now the two job pipelines
  emit aggregate metrics and a correlation id that survives from the request to every log line.
  - **Metrics** (`app/import_export_metrics.py`, in-process/per-replica like the rest of the
    `/v1/ops/metrics` plane): per-stage duration histograms + byte totals, terminal job totals
    keyed adapter/target × format × outcome, and failure counters keyed by the IXH-6.4
    taxonomy code. Every tag comes from a closed vocabulary (registered adapters/targets, the
    engine stage names, the two taxonomies) with out-of-vocabulary values clamped to `other` —
    **no per-tenant or per-job tags exist**. Each record also emits one structured log line
    (`import_export.stage|job|failure`).
  - **Stage timings**: the in-process import pipeline now emits `PHASE_TIMING` events (the
    exact shape the tsx worker always emitted, including a `failed` outcome for interrupted
    stages), ingested into the metrics at the engine's event-dedupe seam so both paths feed
    the same aggregates; the export engine times its five stages at the `_publish` funnel.
    Timing events persist per job inside `async_job.status`, so durable evidence survives
    restarts even though the aggregates are per-replica.
  - **Correlation id (additive `correlation_id` fields)**: captured from the middleware's
    `X-Request-ID` at schedule time, stamped onto every stored import/export job status and —
    structurally — onto `SpecImportJobError`/`ExportJobError`, bound into every job log line
    (explicitly on the export engine's thread loop), and therefore returned to the caller on
    failure: the 202's `X-Request-ID` equals every subsequent poll's `correlation_id`.
  - **Operator view**: new `GET /v1/ops/import-export` (platform-admin) rendering the
    aggregates plus the complete documented tag set; `/v1/ops/metrics`/`status` carry the
    snapshot under `import_export`; the ops dashboard gains *Import/Export jobs* and
    *Import/Export failures* cards. Documented in `docs/import_export_observability.md`.

## [1.245.0] - 2026-08-02

### Added
- **Saved schema test suites and regression tracking (IXH-5.7, #5119)** —
  A payload validated once is worth keeping. `/v1/tenants/{tenant}/schema-suites` persists
  named, tenant-scoped suites — payloads plus expected verdicts in the IXH-1.1
  `validity_class` vocabulary — attached to a stable schema reference that survives
  revisions (`{kind}/{artifact}[/{type}]`; a 5.1-shaped reference's version segment is
  discarded; `registry/…` is rejected because it has no revisions to regress across).
  - **Runs** (`POST …/{id}/runs`) execute every payload through the IXH-5.1 validator
    against one revision — resolved once and pinned, so a moving `latest` cannot split a
    run — judge each verdict exactly like the CLI (`passed`/`failed`/`error`), and record
    the run plus per-payload results (apiome-db V240). An unresolvable reference records a
    `status: error` run: that history is the product, not an exception.
  - **Regression tracking**: each result is diffed by payload name against the suite's
    previous completed run, whatever revision it targeted. `passed → failed` flags the
    result and the run; `passed → error` deliberately does not (no verdict was produced),
    staying visible via `previous_status`. Listings carry each suite's newest run summary
    so the catalog and version detail surfaces can badge regressions from one query.
  - **Corpus round trip**: `GET …/{id}/export` produces an IXH-1.1 corpus manifest plus
    payload files, directly consumable by `apiome schema test --suite` once materialized;
    `POST …/schema-suites/import` reads the same envelope back losslessly.
  - **Bounded and documented** (`docs/schema_test_suites.md`): payloads per suite
    (`APIOME_SCHEMA_SUITE_MAX_PAYLOADS`, 50), 256 KiB per payload (V240 CHECK), findings
    per result (`APIOME_SCHEMA_SUITE_RESULT_FINDINGS_CAP`, 20); run history pruned on
    write beyond `APIOME_SCHEMA_SUITE_RUN_MAX_PER_SUITE` (200) and by age on the IXH-6.3
    retention tick (`APIOME_SCHEMA_SUITE_RUN_RETENTION_DAYS`, 180) — always keeping each
    suite's newest `APIOME_SCHEMA_SUITE_RUN_KEEP_MIN` (20) so a rarely-run suite never
    loses its regression baseline.

## [1.244.0] - 2026-08-02

### Added
- **Cross-format schema conformance, canonical → target (IXH-5.6, #5118)** —
  Fidelity reporting describes *structural* loss; it never answered the question that
  actually breaks a consumer at runtime: does a payload that is valid against the source
  schema remain valid against the emitted target schema? `app/cross_format_conformance.py`
  answers it empirically, per emit target and per entity.
  - For every target with a validatable schema language — JSON Schema
    (`validate_json_instance`), Avro (`fastavro`), protobuf (`buf` compile +
    `json_format.ParseDict`), GraphQL input types (`graphql-core` input coercion), and XSD
    (`xmllint`) — the IXH-5.2 source-valid instances (minimal, full, branch; never mutants)
    are validated against the **actually emitted** schema. Failures are reported per entity
    with the target-side constraint that rejected the instance.
  - **Wire-format transcoding is explicit** (`app/conformance_transcoding.py`): base64 →
    Avro binary, canonical-model-driven JSON → XML documents mirroring the emitted XSD
    grammar, and the proto3 canonical JSON mapping. Transcode failures are a separate
    failure kind — they never masquerade as a pass or a conformance verdict.
  - Targets without a validatable schema language are reported **not applicable, never
    passing**; a missing toolchain (`buf`, `xmllint`) reports *not validated* with the
    reason, mirroring the `export_validation` honesty contract.
  - **Feeds the IXH-2.4 readiness rank**: `POST …/export/preflight` accepts
    `include_conformance`, attaches each target's verdict beside its structural fidelity
    envelope, demotes a `ready` target to `caution` when its emitted schema rejected
    source-valid instances, re-ranks, and refreshes the ranking fingerprint.
  - Covered across the IXH-1.7 grid: every corpus source-format representative × every
    production emit target asserts the applicability split and that no target ever reads
    as passing without instances actually judged.

## [1.243.0] - 2026-08-02

### Added
- **On-demand export round-trip comparison (IXH-4.4, #5112)** —
  The strongest possible answer to "is this export honest?" is empirical: emit the artifact,
  re-import it through the matching import adapter, and diff the re-imported canonical model
  against the source. The IXH-1.7 conformance matrix proves this in CI over the corpus; the
  user had no way to see it for their own document.
  - `POST /v1/export/{tenant}/roundtrip` runs the same loop, on demand, for one
    (source revision, target, options): a read-only emit via the dispatch primitive (so the
    verdict and the Studio's fidelity surfaces describe one snapshot), re-import through the
    matrix's own adapter join, `canonical_diff` against the source, and the matrix's
    `reconcile` against the fidelity report. Nothing is persisted — no artifact, no job row,
    no field-identity rows.
  - Differences come back **grouped**: `matched` (each explained difference paired with the
    fidelity finding covering it — expected loss), `unexplained`, and `overclaims` (`ok`
    findings reality contradicts) — the latter two flagging a fidelity bug worth reporting,
    with reproduction provenance (model fingerprints + emitter/apiome/registry versions,
    never source content) inline.
  - A target with no import adapter is **skipped with the matrix's own explanation**
    (`status: unsupported`), never silently; a re-import failure is reported as a `fail`
    verdict rather than a 500. `app/export_roundtrip.py` holds the composition; the verdict
    vocabulary is the 1.7 matrix's, so Studio results reconcile with the published grid for
    corpus entries.

## [1.242.0] - 2026-08-02

### Added
- **Multi-file and archive intake explorer (IXH-3.5, #5107)** —
  MFI-29.1/29.2 made a single import dozens of files, but the preview still showed one grade and
  one entity tree for all of them: which file failed, which was never read, which import could not
  be resolved, and whether the detected entry point was even right were all unanswerable. That is
  the failure mode that makes multi-file gRPC imports frustrating.
  - `POST /v1/tenants/{tenant}/import/bundle-inventory` unpacks the candidate through the *same*
    MFI-29.1 archive intake the commit uses and runs the *same* IXH-2.1 pre-flight the quality step
    already ran (so it rides that cached run rather than parsing the bundle twice), then returns per
    file: its **role** (entry-point / dependency / unreferenced / ignored — always with the reason —
    / unreadable), its **verdict** plus the parse diagnostic naming it, its resolved
    **import/include edges** and incoming references, and the **canonical entities it appears to
    contribute**.
  - Every **unresolved** reference lists *the search paths that were tried, in order*. Imports the
    format's own toolchain supplies (protobuf well-known types, Cap'n Proto builtins) resolve as
    `provided` instead of being reported missing.
  - `app/intake_bundle_graph.py` holds the pure half: a per-suffix directive table (proto, Thrift,
    FlatBuffers, Cap'n Proto, TypeSpec, GraphQL, RAML, Avro IDL, JSON/YAML `$ref`, XSD/WSDL/EDMX),
    include-root resolution, role classification, and the declaration-scan attribution — whose
    method is carried on the response (`attribution`) so its evidence quality is never overstated
    as parser provenance.
  - Ranked **entry-point candidates** come from the same ranking `resolve_fileset_root` decides
    with; overriding is a plain re-run against `archive_root`. An ambiguous root and a failed parse
    both still return the complete file list.
  - Archive unpack can now report *what it skipped and why* (`unpack_archive_members(ignored=…)`),
    and its skip normalisation is fixed: `lstrip("./")` stripped characters, so `.git/` internals
    and a top-level `.DS_Store` were never actually being skipped despite both rules existing.
  - Bounded: files are cursor-paginated, unresolved references ride the first page with the full
    total stated, and a per-process LRU keeps the built inventory so paging never re-unpacks.
  - UI: a **Bundle files** tab in the import wizard's quality step (mounted only for a bundle
    candidate) with a windowed ARIA file tree, role legend, per-file detail, unresolved-imports
    list, and an entry-point picker that re-runs the whole pre-flight.

## [1.241.0] - 2026-08-02

### Added
- **Quality-rank telemetry and grade drift over revisions (IXH-2.7, #5102)** —
  scores were captured per revision but never aggregated across intake, so nobody could see that
  a team's imports were trending downward, or that one format consistently graded low — which is
  as likely to be an *adapter gap* as a spec problem, and a per-revision score cannot tell the
  two apart.
  - **An append-only observation series.** `apiome.quality_rank_observations` (V239) records one
    row every time a grade is produced — an import pre-flight, a committed import, an export
    pre-flight ranking, a delivery gate decision — keyed by tenant, format, adapter and
    **style-guide version** (the guide's content fingerprint, which is what actually moves a
    score), plus the policy version, the gate outcome, and the severity tally.
  - **Attribution, not just grades.** Every observation carries the finding split that separates
    what apiome's intake is answerable for from what the specification is: `intake.*` findings
    (an external `$ref` never resolved or refused) are adapter-attributable, everything else is
    spec-attributable and classed by the rule id's namespace. An unrecognised rule is
    spec-attributable by construction — the opposite default would blame the adapter for every
    new rule anybody adds. The adapter's *declared* parser limits
    (`import_preview_manifest.KNOWN_PARSER_LIMITS`) ride alongside as a separate count and are
    never folded into the finding tallies.
  - **Export readiness in the same series.** An export pre-flight records the readiness composite,
    band and rank of its top-ranked targets, so a target whose readiness is sliding shows up
    beside the specs feeding it rather than in a second, parallel view.
  - **One read.** `GET /v1/lint/workspace/quality-ranks` groups the window by `(scope, format)`
    and returns each group's grade distribution, average score, drift (`scoreDelta`), outcome
    tally, attribution split, style-guide versions, and a per-day point series. A day with no
    observation is a **gap** (`averageScore: null`), never a zero. Rendered in the lint workspace
    as a new **Quality ranks** tab with a selectable 7/30/90/180-day window.
  - **Bounded by construction.** Recording is best-effort everywhere (telemetry never fails an
    import, an export, or a pre-flight); an export pre-flight records only the head of its
    ranking rather than all 30-odd targets; the read caps its window at 180 days and its format
    count at 24, stating `truncated` rather than dropping rows silently; and the series is pruned
    by `APIOME_QUALITY_RANK_RETENTION_DAYS` (default 180) on the IXH-6.3 retention sweep tick,
    which is already the deployment's retention worker.

## [1.239.0] - 2026-08-02

### Added
- **Corpus provenance, licensing and contributor guide (IXH-1.9, #5095)** —
  real-world examples are the corpus's most valuable tier and the easiest to add carelessly:
  a third-party spec carries a license the repository must honor, and a payload captured from
  a running system carries personal data that must never reach git history. Neither was tracked.
  - **Declared origin.** Manifest entries gained `origin`
    (`hand-authored` | `derived` | `captured`, absent means hand-authored), `source_url` (the
    upstream document a derived entry came from) and `anonymization` (how a captured payload was
    scrubbed before commit). Both loaders expose them — `corpus_loader.CorpusEntry.effective_origin`
    plus a `load_corpus(origin=…)` filter, and the same in `apiome-ui/lib/corpus/corpus.ts`.
  - **An enforced gate.** `scripts/check_corpus_provenance.py` is a stdlib-only CI check: every
    entry with a non-empty `source` must declare a `license`, that license must be on a reviewed
    SPDX allowlist (copyleft, share-alike and non-commercial terms fail), `origin` and `source`
    must agree, derived entries must link their upstream, and captured entries must carry an
    anonymization statement under a license the contributor can actually grant. It runs as its own
    lightweight workflow (`.github/workflows/corpus-provenance.yml`) so a manifest-only pull
    request is gated even though the corpus lives under `apiome-ui/`.
  - **The guide.** `docs/CORPUS_CONTRIBUTOR_GUIDE.md` documents the tiers and the six-rung ladder,
    every manifest field, the licensing rules (including what to do when the upstream license is
    not acceptable — reconstruct, do not vendor), the anonymization rule for captured payloads,
    the end-to-end add-an-example workflow, and the reviewer checklist. The generated examples
    README links it and now publishes the corpus's licensing bill of materials by origin.
  - **Tests.** `tests/test_corpus_provenance.py` fires every rule against a purpose-built bad
    entry, asserts the committed corpus is clean, and pins the guide/README linkage.

## [1.238.0] - 2026-08-02

### Added
- **Scale corpus and import/export performance budgets (IXH-1.5, #5091)** —
  nothing in the corpus approached the size of the specs teams actually hold, so import and
  export timings were unmeasured and a regression in normalization or fidelity analysis would
  have shipped unnoticed. There is now a measured, gated scale tier.
  - **The corpus.** `scripts/generate_scale_corpus.py` is a committed spec of six large,
    deterministic, *valid* documents — one per paradigm and one for the mainframe half: a
    550-path OpenAPI 3.1 spec, a 1500-method OpenRPC service, a CloudEvents envelope with a
    15000-attribute payload, a 900-type Avro snapshot, a 1500-transaction-set X12 interchange,
    and a 7500-item COBOL copybook. The bytes are built at test time, so repository size stays
    flat (the IXH-1.4 rule). Every fixture stays under the 10 MiB intake ceiling and uses an
    adapter with no external toolchain, so none of them can silently skip.
  - **Ten measured stages.** `tests/scale_benchmark.py` drives each fixture through
    `parse → normalize → fingerprint → lint → persist` and
    `load-source → analyze-fidelity → emit → validate → package`, calling the same functions
    the running pipelines call, and records per-stage wall-clock plus peak allocation
    (`tracemalloc`, which is attributable per stage) alongside the process peak RSS. The two
    database-straddling stages are measured up to the row write — `persist` is the source
    capture and secret scrub, `load-source` the full re-parse/re-normalize — because a
    Postgres round-trip's cost cannot be attributed to a code change.
  - **Budgets with a margin, not a threshold.** `tests/scale/scale_budgets.json` is the one
    committed baseline, carrying the margins, the noise floors, and the machine it was measured
    on. A stage fails only when it is both over `baseline × margin` *and* over an absolute
    floor, so a 2 ms stage tripling is ignored while a 30 % slowdown of a two-second stage
    fails. `SCALE_REGRESSION_MARGIN` / `SCALE_MEMORY_MARGIN` override per run, and absolute
    ceilings (180 s, 1 GiB per stage) fail regardless of any baseline. Refresh with
    `pytest tests/test_scale_corpus.py --update-scale-budgets`.
  - **Opt-in locally, scheduled in CI.** `tests/test_scale_corpus.py` runs only under
    `--scale` / `RUN_SCALE_SUITE=1`; `.github/workflows/apiome-rest-scale.yml` runs it weekly
    and on dispatch, uploading `reports/scale-benchmark.json` — a machine-readable per-stage
    report with each budget, ratio, and the environment measured in. `tests/test_scale_harness.py`
    runs on every PR and keeps the spec, the baseline, and the comparison rules honest between
    scheduled runs.
  - **First findings, for IXH-6.5.** Fidelity analysis is the memory hot spot at roughly
    300 KiB per canonical type (~265 MiB for the 900-type Avro snapshot); OpenAPI export
    validation dominates wall-clock at ~15 s for a 1.5 MiB spec; exporting a revision costs
    about what importing it did, because the canonical model is rebuilt from the captured
    source. See `docs/scale_benchmarks.md`.

## [1.237.0] - 2026-08-01

### Added
- **Breaking-publish guardrail (CTG-3.4, #4478)** —
  CTG-3.1 made breaking changes visible *after* publish, but nothing stopped a publisher from
  shipping one as a minor or patch bump — the semver violation that destroys consumer trust,
  committed with the platform already knowing the change was breaking. Publish now says so
  first.
  - **The check.** At publish time the head is classified against the previous **published**
    revision (the CTG-1.1 taxonomy through the CTG-1.3 changelog builder, so the guardrail lists
    exactly what the published changelog will list) and the two version labels are compared for
    a semver major bump. Breaking **and** no major bump is the only combination that triggers.
    The baseline is resolved independently of the request's change-report baseline mode, so
    selecting `initial` cannot dodge the guardrail, and the check runs *after* the
    `allowBreaking` gate — a publisher who opted into shipping breaking changes is exactly the
    one it exists for.
  - **Tenant policy, on the guide.** `style_guides.breaking_publish_policy` (migration V237) is
    `off` / `warn` (default) / `block`, resolved through the GOV-1.4 chain (project → tenant →
    default) and editable at `PUT …/style-guides/{tenantSlug}/{guideId}/policy` beside the
    CLX-1.3 gates. Under `block`, publish is refused with `422` carrying the full assessment;
    force-publish (`skipPublishChecks` + reason) gets past it exactly as it does for style-guide
    errors, per GOV-2.5. The level is frozen into each GOV-1.6 guide revision, so escalating to
    `block` is auditable history.
  - **Preflight for the dialog.** `GET /v1/versions/{tenantSlug}/{projectId}/{versionRecordId}/breaking-publish-guardrail`
    returns the same payload read-only: status, the breaking changes (capped at 50, with
    `truncated` and a true `breakingCount`), `majorBumped`, and the `recommendedVersion` a
    compliant bump would use.
  - **Never fails closed.** Version labels are free-form, so "was the major bumped?" has three
    answers — a non-semver label yields `null`, which warns but never blocks, since that tenant
    has not committed a semver violation. Every fault (unbuildable spec, missing baseline, DB
    error, unknown policy value) degrades to `status: unavailable` or the `warn` default: a
    guardrail that failed closed on its own bugs would be worse than the violation it guards
    against.
  - **Audited.** Every flagged publish appends a `version.breaking_publish_guardrail` workflow
    audit row with `action: warned | forced`, the force reason, and the full assessment. The
    forced case is assessed after publish, since `skipPublishChecks` skips the prechecks
    wholesale — precisely the case where the trail matters most.
  - Documented in `docs/breaking_publish_guardrail.md`; 50 tests in
    `test_breaking_publish_guardrail.py` plus guide-policy and revision-snapshot coverage.

## [1.236.0] - 2026-08-01

### Added
- **Guide versioning & audit (GOV-1.6, #4432)** —
  style guides were edited in place, so a lint score recorded last month named the guide that
  produced it but not *what that guide contained*: once the guide changed, the result could no
  longer be explained or defended. Guides now keep an immutable history, lint results pin the
  revision they ran against, and governance changes land in the tenant's audit ledger.
  - **A revision per edit, and only per edit.** `apiome.style_guide_revisions` (migration V236)
    is append-only and write-once (the shared V128 UPDATE-forbid trigger). Creating a guide,
    renaming it, saving the rule catalog, saving the custom-rules YAML, or changing policy gates
    each append one row carrying the guide's whole state — name, description, external lint
    profile, every rule row (enable flag, severity, custom definition) and the draft gates —
    plus a `changeKind` and the actor. A save that changed nothing appends nothing: the two
    fingerprints on each revision separate "the rules moved" (`contentFingerprint`) from
    "anything moved" (`snapshotFingerprint`). Assigning a guide changes no content and is
    therefore an audit event, not a revision.
  - **Lint results pin their ruleset.** `GET …/{versionRecordId}/lint` now returns
    `guideRevisionId` alongside `guideId` / `guideName`, and every immutable lint evidence row
    (`lint_evidence_runs.guide_revision_id`) records the same pin at capture time, so
    import-time scores are as explainable as live recomputes. The pin is exact rather than
    heuristic: a revision's `contentFingerprint` is produced by the *same* function that stamps
    the compiled guide's fingerprint, so matching content is provably the same ruleset.
  - **History is readable, and self-heals.** `GET /v1/style-guides/{tenantSlug}/{guideId}/revisions`
    lists the history newest-first with rule rollups; `GET …/revisions/{revisionId}` returns the
    frozen rules and gates behind any past score. Both are readable by any tenant member —
    compliance review is not an admin-only activity. Guides that predate this feature are
    captured on first read/edit/lint, and every edit path captures the **pre-edit** state first,
    so what an edit replaced is preserved rather than lost.
  - **Audit events on create / edit / assign.** `style_guide.created`, `.updated`, `.deleted`,
    `.rules_updated`, `.custom_rules_updated`, `.policy_updated`, `.assigned` and `.unassigned`
    append to the existing hash-chained `apiome.access_audit` ledger — one ledger for a
    reviewer to read — filterable with `GET /v1/access/{tenantSlug}/audit?filter=styleGuide`.
    Only changes that actually happened are recorded, and history/audit capture is best-effort
    by contract: a ledger or capture failure can never fail the guide change it describes.
  - Documented in `docs/guide/style-guide-revisions.md`; 48 tests across
    `test_style_guide_revisions.py` and `test_style_guide_routes.py`.

## [1.235.0] - 2026-08-01

### Added
- **Spectral ruleset importer (GOV-1.5, #4431)** —
  teams migrating from Stoplight/Redocly arrive with a `.spectral.yaml` holding years of org
  standards. Re-authoring every rule by hand was a real switching cost, so
  `POST /v1/lint/custom-rules/import` now reads that file — pasted/uploaded via `content`, or
  fetched from a `url` through the existing SSRF-guarded ingestion boundary (256 KiB cap,
  redirects re-validated) — and translates it into Apiome governance state. Nothing is
  persisted: the response is a review-then-store payload whose `yaml` is exactly what
  `PUT /v1/style-guides/{tenantSlug}/{guideId}/custom-rules` accepts and whose `builtinRules`
  are exactly what `PUT …/rules` accepts.
  - **Three outcomes, no silent loss.** Every `rules.<id>` entry of the source lands in exactly
    one outcome, so the report accounts for the whole document: `builtin` (resolved onto the
    GOV-1.2 rule catalog via the `extends: spectral:oas` map — `info-description`,
    `operation-description`, and the four `valid-*-example` rules), `custom` (translated into
    the GOV-1.3 DSL and validated *by* that module, so anything emitted is guaranteed storable
    and evaluable), or `unsupported`.
  - **Unsupported rules say why.** Ten stable reason codes — `js_function`,
    `unsupported_function` (Spectral's `schema` / `alphabetical` / `xor` / `falsy` /
    `unreferencedReusableObject`), `unsupported_extends`, `unmapped_builtin`, `unknown_rule`,
    `unsupported_severity`, `invalid_definition`, `malformed_rule`, `unknown_alias`,
    `rule_limit` — each with a human `detail` and, for DSL rejections, the `pointer` to the
    offending node (`rules.my-rule.then.functionOptions.separator`).
  - **Lossy translations are declared, not hidden.** A rule that imports while losing something
    carries `notes`: a dropped `message` template or `formats` restriction, `resolved: false`,
    `severity: hint` folded to `info`, a normalized rule id (an id that would shadow a built-in
    becomes `imported.<id>`). Rules the source turned **off** (`off` / `false` /
    `recommended: false`) are reported with `enabled: false` and deliberately left out of the
    emitted YAML, so applying an import never silently switches a rule on. Document-level
    `notes` cover ignored `overrides`, `parserOptions`, and unknown top-level keys.
  - **Spectral dialect handling.** Severity tokens (`error`/`warn`/`info`/`hint`/`off`,
    booleans, numeric `DiagnosticSeverity` including YAML 1.1 resolving bare `off` to `false`),
    `extends` as a scalar/list/`[target, modifier]` pair (`off` inherits everything disabled),
    and simple `aliases` (including `#Alias.suffix` expansion) all resolve.
  - **Acceptance criterion pinned by fixture.** `tests/fixtures/spectral/zalando-style.spectral.yaml`
    — a 27-rule Zalando-style ruleset — imports at **81.5%** coverage, above the ≥70% bar, and
    its output round-trips through `POST /v1/lint/custom-rules/validate`. Documented in
    `docs/guide/spectral-import.md`; 84 tests across `test_spectral_import.py` and
    `test_spectral_import_routes.py`.

## [1.234.0] - 2026-08-01

### Added
- **Protocol / format facets on public browse (MFI-6.1, #3753)** —
  the directory now spans many API description formats, so browsing it needs more than a name
  search: a visitor has to be able to ask for "the event-driven ones" or "everything published as
  gRPC". Both facet axes read the columns MFI-7.1 put on `apiome.versions` (`protocol`,
  `source_format`), backed by that migration's partial facet indexes.
  - **Two filters, one vocabulary.** `GET /v1/browse/tenants` and
    `GET /v1/browse/tenants/{slug}/projects` accept `protocol` (the canonical `ApiParadigm`:
    `rest`, `rpc`, `event`, `graph`, `data_schema`, `agent`) and `format` (the specific source
    format key an adapter recorded at import: `openapi-3.1`, `protobuf`, `graphql`, …). Matching is
    case- and punctuation-insensitive — `data-schema`, `event-driven` and `graphql` all resolve —
    and an unrecognised value *narrows to nothing* rather than erroring, the same contract the
    existing `search`/`domain` filters have. The two axes compose with AND, and an entry matches
    when **any** of its listed versions carries the value.
  - **Counts per facet.** Both responses gained a `facets` block — `{protocols, formats}`, each a
    list of `{value, label, count}`. Counts honour the listing's *other* filters (`search`,
    `domain`) but deliberately ignore the facet selection itself, so a chip row always answers
    "what else could I pick" instead of collapsing to what is already selected. Protocols come
    back in canonical paradigm order; formats by descending count, ties broken by key.
  - **Rows say what they are.** Every tenant and project row now carries `protocols` / `formats`
    (the distinct values across its listed versions) and every version row carries its own
    `protocol` / `source_format`, so a listing stays readable once a facet has narrowed it.
  - **Labels reuse the registries.** `app/browse_facets.py` owns the normalization and the
    labelling; format labels come from the import-source registry (so a newly registered adapter
    labels its own chips) with a versioned-key rule that keeps `openapi-3.0`, `openapi-3.1` and
    `swagger-2.0` distinguishable. An unknown key still renders — as itself.
  - **Note.** Revisions imported before MFI-7.1 carry no protocol/format and so contribute no
    chip; the MFI-7.3 backfill (#3758) is what lights the facets up for pre-existing specs.

## [1.233.0] - 2026-08-01

### Added
- **Per-repository / per-file refresh conflict policy (RAR-4.5, #3531)** —
  the RAR-4.4 divergence guard gave auto-refresh one answer when it meets a version that was
  hand-edited after the original import: hold, do not clobber. That is the right default and
  it is only one of the three answers teams want. This makes the answer configurable, at the
  two scopes the work actually needs.
  - **Three policies, stored as their wire tokens.** `overwrite` lets the refresh supersede
    the hand edit — the divergence is still *detected and reported*, it just does not stop the
    refresh; `hold-for-review` (the default) skips the refresh and flags the file `diverged`;
    `new-branch` leaves the current version untouched and lands the refresh on a side branch
    so neither the edit nor the upstream change is lost.
  - **The default does not move.** `tenant_repositories.refresh_conflict_policy` is
    `NOT NULL DEFAULT 'hold-for-review'`, so every existing repository keeps the behaviour it
    has today. Opting into a policy that can lose work not held in the repository is an
    explicit act, never a migration side-effect — and every degradation path (an unrecognised
    token, a missing row, a blank value) falls back toward that same safe default rather than
    failing a refresh.
  - **Per-file overrides are exceptions, not enrolments.**
    `apiome.repository_conflict_policy_override` holds one row per file that deviates, keyed on
    the same `(repository_id, branch, path)` lineage tuple as RAR-1.1's `repository_import_spec`.
    A file with no row inherits its repository's policy, so the table stays tiny and clearing an
    override is a *delete* — the file then follows whatever the repository says next, not a
    frozen copy of today's setting. The table is separate from `tenant_repository_files`
    deliberately: that one is rewritten by every scan, and policy must outlive the scan index.
  - **One decision site.** `app/repository_conflict_policy.py` resolves
    `per-file → repository → default`, runs the RAR-4.4 guard under the resolved policy, and
    returns a `ConflictOutcome` carrying the action (`apply` / `hold` / `new-branch`), whether
    a manual edit was detected, the reason code, the policy and where it came from. Branch
    names for the `new-branch` policy are deterministic
    (`apiome-refresh/<branch>/<file stem>-<short sha>`), so a refresh that runs twice for one
    commit targets one branch rather than accumulating near-duplicates. Like RAR-4.1–4.4 the
    module is pure and DB-free; acting on the outcome remains the EPIC-4 dispatcher's job.
  - **API.** `GET/PUT /v1/tenants/{slug}/repositories/{id}/conflict-policy` reads and sets the
    repository policy; `PUT …/conflict-policy/file` sets an override, or clears it with
    `"policy": null`. Both the read and every mutation return the same projection — policy,
    default, accepted tokens and overrides — so a settings panel cannot drift from stored
    state. An unrecognised token is a `400` that lists what is accepted, not a `500` from the
    column's CHECK. The repository policy is also patchable through the existing dashboard
    `PATCH /v1/tenants/{slug}/repositories/{id}` as `refreshConflictPolicy`.
  - See `docs/repository_conflict_policy.md`.

## [1.232.0] - 2026-08-01

### Added
- **Source-IP allowlist for webhook ingestion (REPO-7.6, #2804)** —
  `POST /v1/repositories/webhook/{provider}` is the one repository route with no bearer token,
  so the HMAC signature is its only authentication. That check is sound and it is reached by
  anyone who can open a socket: every unsigned POST on the internet buys a subscription
  lookup, a constant-time comparison against a real secret, and a ledger row. The allowlist
  filters on the source address **before** any of that runs.
  - **A blocked delivery is a `403` and is never verified.** The guard runs in the route,
    ahead of `ingest_webhook_delivery`, so a refused source never reaches `verify_signature`
    at all — the ticket's defense-in-depth requirement, and the reason this is not a branch
    inside the dispatcher. The response body says only that the source was refused; naming the
    allowlist, the tenant or the matched range would turn the endpoint into a probe for the
    deployment's network policy.
  - **Provider ranges are fetched daily, not hard-coded.** GitHub's `hooks` array from
    `api.github.com/meta` and Bitbucket's entries from `ip-ranges.atlassian.com` are refreshed
    on a daily cadence into `apiome.webhook_provider_ip_range`, shared across replicas so
    every process filters on the same list. Due-ness is measured from the last *success*, so a
    provider whose endpoint is failing is retried on the next hourly tick rather than
    tomorrow. GitLab.com publishes no machine-readable list; its ranges come from
    `APIOME_REPOSITORY_WEBHOOK_IP_RANGES_GITLAB`, and the same setting exists for the other
    two providers for self-hosted instances.
  - **Per-tenant additional ranges, scoped to the tenant that owns the repository.** A
    self-hosted runner or an egress gateway is added per workspace and consulted only for the
    tenants that registered the repository the payload names — resolved by parsing, which
    reaches no secret. A union across tenants would let one workspace widen the filter
    protecting all the others.
  - **The bypass is an administrator's act, with a reason.** `enforcement_enabled = false` on
    `apiome.tenant_webhook_ip_policy` turns the filter off for one tenant's repositories;
    setting it, and adding a range, both require a signed-in tenant administrator (API keys
    are refused) and both write to `apiome.workflow_audit`. Disabling without a stated reason
    is a 400.
  - **Failure modes are chosen.** Enforcement is off by default
    (`APIOME_REPOSITORY_WEBHOOK_IP_ALLOWLIST`), so an upgrade changes nothing. A provider with
    no cached ranges allows and logs rather than rejecting everything;
    `..._IP_ALLOWLIST_STRICT` flips that to fail-closed. An empty provider fetch is treated as
    a failure and leaves the previous cache standing. An unidentifiable client address blocks
    — unless the owning tenant has bypassed enforcement, which is exactly the escape hatch
    that case calls for.
  - **`X-Forwarded-For` is worth what the deployment says it is.**
    `APIOME_REPOSITORY_WEBHOOK_TRUSTED_PROXY_HOPS` (default 0) decides how many hops in to
    read; at 0 the header is ignored entirely, since honouring it unverified would let any
    caller name its own source address. A header shorter than the configured chain is refused
    rather than guessed at.
  - `GET|POST|PATCH|DELETE|PUT /v1/tenants/{slug}/repository-webhook-ip-allowlist[...]` back
    the admin panel. The read needs only import-view permission — seeing the filter is how
    anyone diagnoses "our webhooks stopped" — while every mutation needs the admin role. Every
    mutation answers with the whole allowlist, so a panel can never drift from what was
    stored.
  - Blocked deliveries land in the existing `apiome.repository_webhook_event` ledger with the
    `rejected` outcome and an `ip-not-allowed` reason, and are audited per owning tenant as
    `repository.webhook.ip_blocked` — which carries the `repository.` prefix, so it appears in
    the REPO-7.5 compliance export with no further wiring.
  - V234 adds the four tables (provider range cache, per-provider refresh state, per-tenant
    entries, per-tenant policy). Tables and indexes only; no existing data is touched.

## [1.231.0] - 2026-07-31

### Added
- **SOC 2 / ISO 27001 audit export (REPO-7.5, #2803)** — compliance reviews need a structured,
  dateable artifact of everything the repository subsystem wrote to the audit ledger, not a
  paginated API a reviewer has to page through by hand.
  - `GET /v1/tenants/{slug}/repository-audit-export?from=&to=&format=csv|json` streams every
    `repository.*` row of `apiome.workflow_audit` (refresh cycles, webhook registrations /
    deliveries / secret rotations, external-ref fetches, …) in the inclusive `created_at`
    range, oldest first, served as an attachment with a range-stamped filename
    (`repository-audit-export_20260101-20260731.csv`).
  - **Admin-only.** The ledger names every repository and actor in the workspace, so the
    export requires a signed-in tenant administrator; API keys are refused outright rather
    than resolved to their creating user.
  - **Streamed at any size.** Rows are read oldest-first with a `(created_at, id)` keyset
    cursor in 1,000-row batches, so an export far beyond 10k rows holds one batch in memory
    and every batch costs the same — no OFFSET cliff, and rows appended mid-export cannot
    shift between batches.
  - **CSV or JSON.** CSV is a header plus one RFC-4180 row per entry with `detail`
    JSON-encoded in its cell; JSON is a single document — an `export` metadata envelope, the
    `entries` array streamed element by element, and a trailing `rowCount` — that only parses
    when the download ran to completion, so a truncated artifact is detectably incomplete
    instead of silently short.
  - **The export is itself evidence.** Every attempt appends a
    `repository.audit_exported` row to the same ledger: `success` with the exact row count on
    completion, `failure` with the partial count when the stream errors or the client
    disconnects mid-download. Because the action carries the `repository.` prefix, each
    export shows up in the next one. Recording is best-effort, so audit bookkeeping can never
    break the download it describes.
  - Ledger and endpoint only; no migration — `apiome.workflow_audit` is reused unchanged.

## [1.230.0] - 2026-07-31

### Added
- **Quota & rate-limit telemetry (REPO-7.3, #2801)** — the REPO-4.6 polling quota and the
  REPO-2.5 scan budget both work silently. The only record of a deferral was a log line and a
  per-replica in-memory counter that died with the process, so "is this workspace permanently
  parked against its ceiling, or was that one bad afternoon?" had no answer anyone could give.
  There is now a durable per-tenant counter behind it.
  - **Five metrics in a rolling-window table** (`apiome.repository_quota_window`, V233):
    `polls`, `polls_deferred` and `files_deferred` bucket hourly (matching the REPO-4.6 quota
    window); `scans` and `bytes_scanned` bucket daily. Aggregates, not events — a workspace
    polling 600 times an hour costs one row an hour, not 600.
  - **A window boundary is the reset.** Nothing zeroes a counter: an increment lands on the
    bucket its timestamp falls in, so crossing a boundary writes to a different row and the new
    window starts at zero. That holds across restarts, across replicas, and across a sweep tick
    that straddles the boundary — none of which a "reset the counter" job would survive.
  - **Deferrals are counted apart from work.** `polls` says how much refreshing happened;
    `polls_deferred` / `files_deferred` say how much the quota pushed into a later window.
    Folding them together would erase the one signal the dashboard exists to show.
  - **Increments are a single atomic upsert** on `(tenant_id, metric, window_start)`, so two
    replicas sweeping the same tenant in the same window converge on one row rather than each
    creating their own and halving every subsequent read.
  - **Recording can never fail a caller.** Every counter write is best-effort and swallowed:
    telemetry that can raise would turn an observability problem into a refresh outage. A scan
    pass that *raised* records nothing at all — reporting it as scan volume would make a broken
    repository look like a busy one.
  - `GET /v1/tenants/{slug}/repository-quota-telemetry?days=7` returns the trailing series
    alongside the tenant's current quota position, so a dashboard renders "42 of 600 used this
    hour" and "here is the last week" from one request. Every metric is present and zero-filled
    across the whole range, so a workspace that has never been deferred sees a flat line rather
    than a missing panel. A counter read that fails comes back `available: false` with zeros —
    the flag is what stops "we could not read this" being shown as "nothing happened".
  - Counter rows are pruned by the existing async-job retention sweep after
    `APIOME_REPOSITORY_QUOTA_WINDOW_RETENTION_DAYS` (default 120, comfortably longer than the
    90-day maximum range the API serves). `0` keeps them forever.
  - V233 adds the counter table. Table and indexes only; no existing data is touched.

## [1.229.0] - 2026-07-31

### Added
- **Notifications on scan / sync events (REPO-7.2, #2800)** — RAR-5.4 gave the auto-refresh loop
  a voice, but no off switch and no volume control: a repository stuck in a failure loop could
  page the same on-call every sweep tick, and nobody could ask it to stop. Repository
  notifications now go through a policy layer before a single channel is resolved.
  - **Three operator-facing events**, all inside the `repository.refresh.*` namespace subscribers
    already route on: `auto_paused` (scheduled refresh has stopped and must be resumed by hand),
    `breaking_change` (a sync produced a version whose change report classifies as breaking), and
    `repeated_failures` (the warning shot — failing repeatedly but not paused yet).
  - **Per-repository, per-event-type opt-out.** `apiome.repository_notification_preference` holds
    exceptions, not enrolments: a repository with no rows is subscribed to everything, and only an
    explicit `enabled = FALSE` mutes an event, so a partial preference set fails *open*. A
    preference read that errors mutes nothing — failing closed would silence a repository during
    the incident that broke the read.
  - **At most one notification per repository per event type per hour.** The slot claim is a
    single conditional upsert on `apiome.repository_notification_throttle`, so the decision and
    the timestamp write are the same statement and two sweep workers racing on one repository
    cannot both win. A losing claim bumps `suppressed_count` instead, which is how "quiet because
    nothing happened" is later told apart from "quiet because we muffled 400 of them". A tenant
    with no channels does not burn its hourly slot.
  - **Channels are resolved per tenant** from the existing push-webhook subscriptions, with their
    retry and dead-letter semantics unchanged, and each is shaped for its destination: a Slack
    incoming webhook receives a Slack `text`/`blocks` message (Slack rejects a body without
    `text`), every other endpoint receives the structured JSON. One dead channel never takes the
    rest of the fan-out down with it.
  - **Wired into the refresh sweep.** An auto-pause transition sends the auto-pause event; an
    unpaused repository past three consecutive failures sends the repeated-failures warning on
    every tick, which the hourly throttle makes safe. A newly paused repository sends only the
    pause — pairing it with a warning about the same failures is just noise.
  - `GET`/`PUT /v1/tenants/{slug}/repositories/{id}/notification-preferences` report and set the
    opt-outs. The read always lists every event type, with a one-sentence description of what
    muting it would cost and the throttle state for that pair. The write is partial (events it
    does not mention keep their state) and rejects unknown or repeated event types with a 400
    rather than returning 200 for an opt-out that mutes nothing.
  - V232 adds the two policy tables. Indexes and tables only; no existing data is touched.

## [1.228.0] - 2026-07-31

### Added
- **Per-repository health badge (REPO-6.5, #2798)** — the repository surface exposed plenty of
  individual signals (scan job outcomes, per-spec quality attempts, the linked account a private
  repository authenticates with) but nothing that answered an operator's first question at a
  glance: *is this repository fine?* Every repository now carries one three-valued badge, on the
  repositories list rows (REPO-6.1) and the repository detail header (REPO-6.2).
  - **Three inputs, three levels.** `healthy` / `warnings` / `error` is rolled up from the scan
    success rate over the last 30 days, the count of discovered specs on the default branch whose
    REPO-2.8 quality attempt errored or could not parse, and the health of the linked account's
    access token (REPO-7.4). Below 50% of scans succeeding is an `error`, below 90% a `warnings`;
    parse errors are a `warnings` until ten of them, at which point the repository is not usable
    as an import source; a disconnected account, a missing token or an expired one is an `error`,
    and a token expiring within seven days is a `warnings`.
  - **Token issues always demote to at least `warnings`.** A repository Apiome can no longer
    authenticate to never reads as healthy, however spotless its scan history. Every token factor
    is emitted at warnings-or-worse and the roll-up clamps as well, so the guarantee survives a
    future factor being added at the wrong level.
  - **A tooltip that says what changed.** Each contributing factor carries a stable machine code,
    a level, a one-sentence operator-facing summary and — where an event lies behind it — when it
    was last observed. `primary_factor` is the *most recently observed* factor, which is what the
    badge tooltip leads with; the full list is ordered most severe first. A standing condition
    with no event behind it ("this token expires soon") never displaces something that actually
    happened.
  - **No signal is not a problem.** A repository registered a minute ago has no scans, no scored
    files and (for a public clone URL) no token to expire; it reads as `healthy` rather than
    manufacturing an alarm out of missing data. Public-URL repositories are read anonymously and
    so always have perfect token health.
  - **One query per page, not one per row.** `Database.get_repository_health_signals` answers the
    whole batch with two correlated laterals, and V231 indexes both: `(repository_id, created_at
    DESC) INCLUDE (status, finished_at)` on the scan queue turns the trailing window into a
    bounded range scan, and a partial index on the file table holding only rows that actually
    failed to parse — empty on a healthy monorepo. The migration adds indexes only.
  - **Decoration, never a point of failure.** The badge is computed by a pure, side-effect-free
    module that cannot raise; if the signal query itself fails, the affected rows carry no badge
    and the listing is unaffected. The access token's *value* is never selected — only whether
    one exists — so a credential cannot leak through a listing response.
  - `GET /v1/tenants/{slug}/repositories` and `GET /v1/tenants/{slug}/repositories/{id}` (and the
    PATCH / refresh-resume reads that return the same record) gain a `health` object.

## [1.227.0] - 2026-07-31

### Added
- **Cross-repository discovered-specs catalog (REPO-6.4, #2797)** — the repository surface could
  only answer "what specs are in *this* repo on *this* branch" (REPO-6.2). An operator running
  more than a handful of repositories had no way to ask "where does this spec live", short of
  opening each repository in turn.
  - **`GET /v1/tenants/{slug}/repository-files`.** One tenant-wide, server-paginated listing of
    every discovered spec across every registered repository. Free-text `q` matches the file
    path, its detected kind, the repository's full name and the mapped project's name; `format`,
    `repository_id`, `project_id` and `status` narrow it further; `sort` orders by repository,
    path, format, status or recent activity. Search, filtering, ordering and pagination all
    evaluate in SQL, so the response carries only the requested page.
  - **Derived per-spec status.** Each row resolves to exactly one of `needs_attention` (quality
    scoring errored, or the last scan left external `$ref`s unresolved), `imported`, `mapped`
    (bound to a project, no import yet) or `discovered`, in that precedence. The status is
    projected and filtered by the same SQL expression, so a row can never be listed under a
    value it cannot be filtered by.
  - **Project and version context per row.** Each spec carries the project it is mapped to (or
    was last imported into) and the version its most recent import produced, resolved through a
    lateral join so a file imported fifty times still contributes one catalog row.
  - **Opt-in facets.** `include_facets=true` returns the filter dropdown options — formats,
    statuses, repositories and projects, each with a catalog-wide count. Facets are computed
    over the whole catalog rather than the filtered page, so picking one filter never hides the
    others. The catalog page requests them once on mount.
  - **Scoped for signal, not volume.** Vendored trees (`node_modules`, `vendor`, `.git`) and
    dot-directories are always excluded; only each repository's default branch is listed unless
    `all_branches=true`; only classified spec types unless `importable_only=false`.
  - **Indexes for the 10k-file bar (V230).** A `pg_trgm` GIN index makes the substring search
    indexable, and a `(repository_id, branch, path, created_at DESC)` index answers the
    latest-import lookup with one backwards scan. The trigram block degrades to a notice where
    the migration role cannot install contrib extensions — the catalog stays correct, just
    sequential.

## [1.222.0] - 2026-07-31

### Added
- **Arazzo 1.x workflow importer (REPO-3.4, #2773)** — Arazzo describes orchestrated multi-step
  API workflows and is a sibling specification to OpenAPI, but Apiome could only *read* one
  (detect → parse → normalize → lint → emit → diff, MFI-30.2). An imported Arazzo document landed
  as a store-raw catalog item and its orchestration was invisible. It is now a first-class entity.
  - **Workflow + WorkflowStep entities (V225).** `apiome.api_workflows` and
    `apiome.api_workflow_steps` hang off the version's `api_artifacts` row like every other
    canonical child, so a re-import replaces the previous orchestration instead of accumulating
    duplicates. Each `workflows[]` entry becomes one workflow row (`workflowId`, `summary`,
    `description`, `inputs`, `outputs`) plus N step rows in source order.
  - **`operationRef` resolution.** A step that points at an OpenAPI operation imported in the same
    scan resolves to that internal `path_operation` id. "The same scan" is concrete: with git
    provenance it is every project `repository_import_spec` links to the same repository and
    branch; otherwise it is the importing project. Every reference spelling in the wild is
    handled — `operationId`, `$sourceDescriptions.<name>.<operationId>`, an `operationRef`
    JSON-pointer (`…#/paths/~1pets~1{petId}/get`), and Arazzo 1.0.0's `operationPath` route
    pointer, which resolves only when the route carries exactly one operation.
  - **A miss is not a failure.** An unresolved reference keeps its raw string verbatim, leaves the
    FK NULL, and records a stable `resolution_reason` (`unknown-operation`, `ambiguous-operation`,
    `no-operation-target`, …) plus a human-readable warning. A step that calls a sibling workflow
    is `not_applicable` rather than "unknown"; a step that cannot be read at all is isolated as
    `parse_error` and its siblings still import. Workflow persistence is an enrichment over the
    catalog item, so a failure there never fails an import whose source bytes are already stored.
  - **Verbatim step payloads.** `parameters`, `successCriteria`, `onFailure`, `outputs` and
    `dependsOn` are stored exactly as written — Arazzo's runtime-expression grammar
    (`$response.body#/id`, `$steps.foo.outputs.bar`) is never re-parsed, which keeps round-trip
    honest.
  - **Verified against the official bundles.** `tests/fixtures/arazzo` carries the OAI example
    documents verbatim (`pet-coupons`, `LoginAndRetrievePets`, `oauth`); they round-trip
    normalize → map → persist → load with identical workflows and steps.

## [1.218.0] - 2026-07-31

### Added
- **Quality scoring per discovered spec (REPO-2.8, #2769)** — the repository scanner classified
  a discovered file by filename but said nothing about whether it was any good, so triaging a
  repository's specs meant opening each candidate by hand. Every *classified* spec now carries a
  rough 0–100 quality score.
  - **Reuses the existing engines, not new scoring.** A discovered spec is scored through its
    import-source adapter — `parse` → `normalize` → `lint` — which for OpenAPI is the native
    path/schema linter (`schema_lint.lint_openapi_spec`: the PATH-QUALITY and SCHEMA-QUALITY rule
    groups) and for every other format the canonical-model rule packs behind `ImportSource.lint`.
    A repository file and an imported revision therefore land on one comparable scale, and a rule
    added to either engine shows up here for free.
  - **Only classified specs.** `unknown_spec` files — no `detected_kind`, or a generic container
    kind like `json-candidate` on a `package.json` — are never scored, selected by the same
    importable predicate the Files browser filters on. A classified format with no adapter yet
    (Prisma, SQL DDL, DBML) is skipped for its own distinct, labelled reason.
  - **Persisted on the file row.** `apiome.tenant_repository_files` gains `quality_score`,
    `quality_grade`, `quality_status` (`scored` | `skipped` | `error`), `quality_reason`,
    `quality_scored_at` and `quality_scored_blob_sha` (V222). All nullable, so every
    already-indexed repository reads as "not scored yet" and no re-scan is required.
  - **Bounded background pass.** Scoring runs in its own sweep
    (`repository_quality_sweep.process_repository_spec_quality_batch`), not inside the REPO-2.5
    tree walk, so a monorepo scan keeps its current cost. Each tick claims at most
    `APIOME_REPOSITORY_QUALITY_BATCH_SIZE` (default 10) due files every
    `APIOME_REPOSITORY_QUALITY_INTERVAL` seconds (default 30); set
    `APIOME_REPOSITORY_QUALITY_SCORING=false` to disable it entirely.
  - **One download per revision.** Every attempt stamps the blob sha it read, success or not, so
    an unscorable file settles instead of being re-fetched each tick, and editing the file makes
    it due again. Private repositories are read only with their linked-account token, and files
    above the 900 KB content cap are skipped without being downloaded.
  - **Informational only.** No scoring path can raise: an unparseable document, a missing
    toolchain, a provider failure, or an adapter bug is recorded on the row as a stable machine
    reason. Nothing gates a scan, a refresh, or an import on the score — spec promotion gating
    remains REPO-5.6's job.
  - `GET /v1/tenants/{slug}/repositories/{id}/files` returns `quality_score`, `quality_grade`,
    `quality_status` and `quality_reason` per row, and the Repository detail Files tab renders
    them in a new **Quality** column (REPO-6.2).

## [1.217.0] - 2026-07-30

### Added
- **Large-monorepo support: sparse / paged repository walk (REPO-2.5, #2766)** — a repository
  with more than ~25k entries could not be indexed at all: the walker pulled the whole branch
  tree in one `recursive=1` GitHub Trees call, buffered every blob in memory, and turned
  GitHub's own `truncated: true` size signal into the hard failure "repository too large for
  this scan pass". The walk is now bounded and resumable.
  - **Streams in chunks.** `walk_github_tree_in_chunks` hands entries to its sink in batches of
    at most 1000 (`repository_scan_budget.MAX_WALK_CHUNK_SIZE`, capped regardless of
    `APIOME_REPOSITORY_SCAN_CHUNK_SIZE`), written through the new upserting
    `Database.append_tenant_repository_files` instead of one whole-branch statement.
  - **Provider-side sparse primitive.** A `truncated` recursive response now switches the walk
    to a breadth-first per-directory descent over the non-recursive Trees API, so only a queue
    of unvisited *directories* is ever held in memory.
  - **Per-tenant wall-clock budget.** `tenants.repository_scan_budget_seconds` (default 300 =
    5 min) bounds one scan pass, clamped at read time into
    `[APIOME_REPOSITORY_SCAN_BUDGET_MIN, APIOME_REPOSITORY_SCAN_BUDGET_MAX]`. A pass that spends
    its budget stores its position and comes back incomplete rather than being killed.
  - **Resume via stored cursor.** `apiome.tenant_repository_scan_cursors` holds one cursor per
    (repository, branch) — the pinned tree SHA, the RAR-2.1 branch-tip anchors, the walk mode and
    the pending sub-tree queue. A paused pass, or one interrupted by a transient provider failure
    (network error, 429, 5xx), re-queues its scan job instead of failing it, and the next sweep
    tick continues from the cursor. The tree SHA is pinned so a resumed pass keeps indexing the
    same snapshot even if the branch moves.
  - **Fair queueing.** A resumed job is claimed on `COALESCE(requeued_at, created_at)`, so a
    monorepo needing twenty passes yields to other repositories between them instead of owning
    the scan worker for the whole walk.
  - Safeguards: a cursor older than 24h is discarded and the branch rewalked; a walk that indexes
    nothing new for too many consecutive passes is abandoned with an error (progress resets that
    counter, so a long walk is never penalized for being long); a transient failure with no stored
    position still fails the job; and a completed scan re-reads its counts from the persisted rows
    so a re-emitted chunk cannot inflate them.

## [1.216.0] - 2026-07-29

### Fixed
- **Dependents of a registry type (#3477)** — opening `number` from `decimal`'s base chain
  showed "No types reference this primitive yet" while `decimal` plainly referenced it.
  `apiome.primitives.refs` records only a type's *outgoing* edges, so nothing ever answered
  the reverse question; the field was declared on the detail page and never populated.
  `GET /v1/primitives/{tenant}/{id}` now returns `dependents`, the reverse index built by
  scanning the visible types' edge lists for the viewed type's `$id`
  (`Database.get_dependent_primitives`).
  - Matching is on the stored absolute `resolved_target` (the form V218 normalized to), so a
    dependent is found however its relative `$ref` was written, and an edge still flagged
    `unresolved` by a stale resolver run is still listed — the target exists, so the
    dependency is real.
  - One entry per referencing *edge*, each labelled with the property carrying it
    (`ref_location_label` over the new `iter_ref_locations` walk): `money` shows up under
    `decimal` as `amount`, while `decimal` under `number` carries no property because the
    `$ref` is the whole type. Read scope is unchanged — system-core ∪ the caller's own
    (#3453) — and per-tenant seeded copies of a core dependent collapse to one row.
  - OpenAPI 1.80.1 → 1.81.0 (`PrimitiveSchema.dependents` added; existing fields unchanged).

## [1.215.1] - 2026-07-28

### Added
- **CPDO user guide and format-detail documentation (#4806, CPDO-4.3)** — the user-facing
  guides `docs/guide/catalog-format-details.md` (Format details tab: status vocabulary,
  value-visibility/redaction, analysis bounds, X12 and copybook inspector boundaries, the
  absence-category table) and `docs/guide/convert-to-openapi.md` (conversion walkthrough:
  projection-graph legend, status and reason-code vocabulary with remediations, safe
  defaults, acknowledgement gating, historical-vs-fresh evidence, CLI/REST surfaces), with
  authoritative X12 and IBM COBOL references.
  - **`tests/test_cpdo_docs_guide.py`** couples the prose to the code registries: every
    analysis status/reason, value-visibility level, conversion status, projection reason
    code, and absence-category label must appear in the guides, the required primary
    references must stay linked, and every external link must be `https`. The UI-side twin
    (`apiome-ui/tests/cpdo-guide-terminology.test.ts`) holds the guides to the exact labels
    and symbols the UI renders.
  - OpenAPI 1.80.0 → 1.80.1 (no contract shape changes).

## [1.212.0] - 2026-07-28

### Added
- **COBOL copybook layout inspection (#4799, CPDO-2.3)** — a copybook is a *positional*
  description, and the position is the half a normalized field list cannot hold. `PIC S9(9)V99
  COMP-3` says six bytes, packed, and the field after it starts six bytes further into the record.
  - **`app/cobolcopybook_layout.py`** computes it: every item's byte offset, the bytes one
    occurrence takes, the bytes every occurrence takes, and the record's own length — as a **range**
    when a variable table makes it one. `05-ach-entry-detail.cpy` computes to 94 bytes, which is
    what the public NACHA file format fixes that record at.
  - **It computes nothing it cannot know.** A PICTURE the calculator does not read sizes to
    *unknown* with a stated reason, and the unknown propagates — the group containing it has no
    length, and nothing after it has an offset. An item after a variable-length table carries
    `offsetVariable` and **no** offset, because a minimum presented as *the* offset is the single
    most misleading number it could emit. A length and a reason are never both present.
  - **REDEFINES is parsed** (`CobolField.redefines`) and laid out as what it is: the same storage
    described a second time. A redefining item starts at its target's offset and does not advance
    the record; each item records what it redefines and what redefines it.
  - **A clause continued onto a second source line is read as one clause.** A COBOL entry ends at a
    period, not at a line break — before this, the `DEPENDING ON` of any table that declared it on a
    following line was silently lost, including in the shipped `01-customer-record.cpy`. Fixed-size
    `OCCURS n TIMES` is read too.
  - **The assumptions ride on every record** as an `info` warning: a single-byte encoding, packed
    decimal at two digits per byte plus a sign nibble, the common binary width table, an overpunched
    rather than separate sign, no `SYNCHRONIZED` slack. A computed length is conditional, and the
    conditions ship with it.
  - **Only an unsized item makes a record `partial`** — that is a boundary of the analyzer. A
    variable-length record, an unresolved ODO controller and a REDEFINES that does not fit are facts
    about the *copybook*, recorded as `info` rather than graded, exactly as an X12 control-total
    mismatch is (CPDO-2.2).
  - Analyzer version `1.1.0`, parser `1.1.0`. See
    [docs/payload_analyzers.md](./docs/payload_analyzers.md).

### Changed
- **Format capability registry to version `3` (#4799)** — the `cobolcopybook` entry moves
  `copybook.redefines`, `copybook.computed_storage_length`, `copybook.storage_offsets`,
  `copybook.variable_length_records` and `copybook.multi_line_clauses` to supported, adds
  `copybook.character_encoding_detection` to unsupported (an encoding is assumed, never detected),
  and states the assumptions in its notes. Mirrored in
  `scripts/format_capabilities/vocabulary.json`.
- **Copybook corpus goldens regenerated** — the round-trip extras gained `redefines`, and
  `01-customer-record.cpy` now carries the `depending_on` controller its continuation line declared.
  The canonical type/field structure is otherwise unchanged; representing a REDEFINES overlay as a
  union remains #3991's.

## [1.211.0] - 2026-07-28

### Added
- **X12 interchange and transaction-set inspection (#4798, CPDO-2.2)** — `pyx12` answers
  questions about *values*, so three facts an inspector needs were never in the record: where a
  segment sits in the file, which element positions were written and left **empty**, and how a
  repeated value divides. All three are in the interchange text, which the analysis already holds
  in order to hash it.
  - **`app/edix12_segment_scan.py`** is a second, independent reading of those bytes — a
    delimiter-aware scan with no `pyx12` import and no AST. It reads each interchange's *own* four
    delimiters out of its ISA header by counting element separators, and honours `ISA11` as a
    repetition separator only from version `00501` (at `00401` that position is an ordinary code,
    and splitting on it would invent occurrences from any value containing a `U`).
  - **The two readings are aligned segment by segment.** Both are in source order, so alignment is
    a match on segment ids; a single unmatched id abandons the scan **whole** and the record falls
    back to CPDO-1.2's path-and-ordinal locations. A record therefore carries positions that were
    checked against the parse, or carries none — half-aligned positions would put a reader in front
    of the wrong bytes.
  - **What the tree gained**: exact `offset`/`length`/`line` on every envelope and segment; element
    nodes for positions written and left empty (`valuePresent` true, `valueLength` zero) beside the
    parser's own count; `repetition` children under a split element; `repeatIndex`/`repeatCount`
    per segment within its transaction set; the component and repetition separators; `ISA09`,
    `ISA10`, `ISA14` and `ISA15` (with the usage indicator's word — `T` and `P` is the difference
    between a test file and real claims); `GS04`, `GS05`, `GS07`; `ST03`; and the `IEA01`/`GE01`/
    `SE01` control totals beside the counts actually observed.
  - **A control-total mismatch is recorded, never reconciled**, and never makes a record `partial`:
    the analysis is complete, and the status vocabulary means "what the analyzer could not do", not
    "what the interchange got wrong". A missing declaration is likewise not agreement.
  - **`x12.canonical_projection_subset`** (`info`) names the transaction set the canonical model was
    derived from and how many it was not, so an OpenAPI derived from a sixth of an interchange says
    so instead of leaving the reader to compare two screens.
  - **Capabilities narrow per record.** `x12.byte_offsets`, `x12.empty_elements`,
    `x12.repeating_elements` and `x12.envelope_control_totals` are declared supported only where the
    scan aligned; the adapter's format-wide `analysis_capabilities()` declares all four, which is
    what the CPDO-2.4 registry publishes ahead of an import.
  - Analyzer version `1.1.0`. See [docs/payload_analyzers.md](./docs/payload_analyzers.md).

### Changed
- **Format capability registry to version `2` (#4798)** — the `edix12` entry's source-location
  quality moves from `path_only` to `byte_offsets`, its notes are rewritten around what the second
  reading can now state, and `x12.empty_elements`, `x12.repeating_elements`,
  `x12.envelope_control_totals` and `x12.segment_repeat_counts` join its dropped-by-projection list.
  Mirrored in `scripts/format_capabilities/vocabulary.json`.
- **`structural` visibility no longer flags a zero-length observed value as redacted** — there was
  nothing in it to withhold, and marking it would make a present-and-empty X12 element
  indistinguishable from one whose real value was suppressed. `none` still counts it, because
  stripping the presence fact does withhold something. The same reasoning already governed a value
  observed absent.

## [1.210.0] - 2026-07-28

### Added
- **Format capability & parsing-limit registry (#4796, CPDO-2.4)** — the versioned answer to
  "why is there no detail here?", so an unsupported format, an uncaptured source, a parser
  limit, a redaction and a genuinely absent construct stop sharing one sentence. See
  [docs/format_capabilities.md](./docs/format_capabilities.md).
  - **`GET /v1/import/format-capabilities`** returns the whole registry; **`GET
    …/{format_key}`** returns one entry. Both are authenticated, tenant-independent registry
    metadata, deterministic and cacheable by `version`.
  - **One entry per registered import source**, each stating native hierarchy,
    source-location quality, value-visibility ceiling, unsupported grammar,
    canonical-projection coverage and conversion-graph support — stamped with the analyzer
    key/version and underlying tool versions backing the claim.
  - **Safe fallback for every format:** a reviewed seed where one exists, otherwise an entry
    derived from the live adapter with pessimistic defaults, and an `unknown_format` entry for
    a key whose adapter was retired (200, not 404 — a 404 there is the "no details" dead end).
  - **X12 and copybook boundaries are explicit** — X12 keeps the whole envelope the canonical
    model drops; the copybook value ceiling is `none`, because a layout has no runtime values
    to withhold.
  - **`source_missing` is true for exactly one absence category**, reachable only from
    `no_source_captured`. Enforced in the registry, on the wire, and in the UI panel.
  - Cross-language contract via `scripts/format_capabilities/vocabulary.json`, asserted from
    both the Python and TypeScript suites.
  - OpenAPI version **1.75.0**.

## [1.206.0] - 2026-07-27

### Added
- **Evidence-backed policy evaluator (#4734, ECA-3.1)** — publish/deploy policy over ECA-1.3
  evidence and CTG-3.1 whole-spec breaking severity. See
  [docs/verification_policy.md](./docs/verification_policy.md).
  - **Postgres** `verification_policies` + `verification_policy_evaluations` (apiome-db V213),
    append-only with immutable UPDATE triggers.
  - **`GET/PUT …/governance/verification-policy`**, versions history, **`POST …/evaluate`**,
    and evaluations list. Decisions cite exact `evidenceRunIds` and are audited.
  - **Gates:** required suite digests, maximum evidence age, whole-spec breaking
    (`ignore`/`warn`/`block`). Not consumer-aware yet (#4479 follow-up).
  - **Publish precheck** evaluates `purpose=publish`; `enforcement=block` + failed decision
    refuses publish with the same decision payload the dashboard renders.
  - OpenAPI version **1.71.0**.

## [1.205.0] - 2026-07-27

### Added
- **HTTP contract runner (#4732, ECA-2.1)** — execute a compiled ECA-1.1 suite against an
  ECA-1.2 verification target with bounded concurrency, per-case timeouts, transport-only
  retries (never masking a status/schema failure), response-schema validation (IXH-5.1), and
  immutable ECA-1.3 evidence on every execution. See
  [docs/contract_runner.md](./docs/contract_runner.md).
  - **`POST /v1/tenants/{tenant}/contracts/{version_ref}/run`** — compile → resolve → run →
    `record_run`. Requires `versions:view` and `verification_evidence:create`. Answers **201**
    for new evidence, **200** for idempotent replay or `ok: false` taxonomy refusals.
  - **Runner name** `apiome-contract-runner` matches the evidence fixtures and JUnit properties.
  - **Private-network SSRF exception** — `build_guarded_client(allow_private=True)` for approved
    `network_class: private` targets (localhost Apiome mock) while still rejecting `file:` /
    credentialed URLs on every hop.
  - Stable failure codes: `status-mismatch`, `response-schema-mismatch`, `transport-error`,
    `timeout`, `auth-unavailable`, `mutating-method-blocked`.

## [1.204.0] - 2026-07-27

### Added
- **Verification evidence schema (#4731, ECA-1.3)** — a contract run used to end as runner output:
  a log, a scrollback, maybe a JUnit file in a CI artifact bucket. None of that can be queried,
  compared across runs, or pointed at by a gate, and it disappears when the CI job's retention
  window closes. A run is now four immutable, tenant-scoped records plus two exports. See
  [docs/verification_evidence.md](./docs/verification_evidence.md).
  - **Evidence is immutable and written whole.** `verification_run`, `verification_run_operation`,
    `verification_run_assertion`, and `verification_run_artifact` (apiome-db V212) each carry the
    shared `BEFORE UPDATE` guard that rejects any in-place edit. That is livable because a run is
    recorded in **one transaction** — there is no open-append-close path, so partial evidence is
    never stored. The REST surface says the same by omission: no `PATCH`, `PUT`, or `DELETE` on a
    run. The only removal is `apiome.purge_verification_evidence(days)`.
  - **Tenant-scoped all the way down.** `tenant_id` is on all four tables, and each child
    references its parent on `(id, tenant_id)` — a composite foreign key, so a cross-tenant child
    is structurally impossible rather than merely unlikely.
  - **The verdict is derived, never asserted.** Counts and outcome are computed from the case
    records; a declared `outcome` that disagrees is refused (`evidence-outcome-mismatch`), and V212
    refuses the row a second time. `errored` outranks `failed` — a gate must tell "incompatible"
    from "we never found out". Only `cancelled`, which no record can imply, is taken on the
    runner's word.
  - **A failure always says why.** A case recorded `failed`/`errored` needs a `failure_code`, a
    failed assertion needs a `code`, and a case recorded `passed` may carry neither a failure code
    nor a failed assertion.
  - **Artifacts are linked, redacted, and verifiable.** There is no column and no model field for
    content; a `data:` URI is refused (that is embedding), as is a URI carrying `user:pass@`;
    `redacted` admits only `TRUE`; `content_sha256` lets a reader verify what they fetched; and
    every free-text field goes through `app.intake_secret_scrub.scrub_message` before truncation,
    so a token a runner quoted never reaches storage.
  - **A run names the target it used.** The ECA-1.2 identity is snapshotted (id, slug, environment,
    network class, base URL) from a *read* rather than a resolve — recording history must not fail
    because the target has since been disabled, nor claim a fresh selection happened. The
    credential reference is deliberately not part of the snapshot.
  - **JUnit and JSON exports reproduce stored outcomes.** `GET .../{run_id}/export?format=json`
    returns the stored record with sorted keys (two exports of a run are byte-identical);
    `format=junit` returns JUnit XML whose counters come from the **stored counts**, one
    `<testcase>` per stored case in stored order, `failed` → `<failure>` and `errored` →
    `<error>`, with the suite digest and target identity as `<properties>`.
  - **Recording is idempotent.** A repeated upload with the same `idempotency_key` returns the
    original run with `200` instead of minting a duplicate, including when a concurrent upload
    loses the unique-index race.
  - **`verification_evidence` RBAC resource** (apiome-db V212) — Owner/Admin manage; **Editor may
    view and create**, because recording a run is what verification is and a CI runner's API key
    resolves to that grid; Viewer may view.
  - **Endpoints** — `POST|GET /v1/tenants/{tenant}/verification-runs`, `GET .../{run_id}`, and
    `GET .../{run_id}/export`. Every refusal carries a stable `{code, message}`.

## [1.203.0] - 2026-07-27

### Added
- **Environment and target registry (#4730, ECA-1.2)** — a compiled contract suite carries no URL
  and no credential, so until now everything about *where* a run points lived outside the platform:
  a CI variable here, a shell export there. Nothing recorded which target a run used, nothing
  stopped one from pointing at an internal address, and credentials travelled next to the
  configuration that named them. Targets are now tenant-scoped, secret-free records with an
  append-only ledger of every change and every selection. See
  [docs/verification_targets.md](./docs/verification_targets.md).
  - **A target never holds a secret.** `auth.kind` says where the credential lives — `env` (an
    environment-variable **name** the runner reads from its own environment, `^[A-Z_][A-Z0-9_]*$`)
    or `stored` (a UUID in the existing encrypted credential vault) — and both shapes are enforced
    in the Pydantic contract *and* as V211 CHECK constraints. A bearer token, an API key, a base64
    blob, and a JWT all fail the env grammar, so a paste cannot become a stored credential.
  - **URL validation blocks private-network SSRF by default.** Every base URL goes through
    `app.ssrf_guard`: `http`/`https` only, no `user:pass@` authority, and — for the default
    `network_class: public` — every resolved address must be globally routable (loopback, RFC1918,
    link-local incl. `169.254.169.254`, CGNAT, and IPv4-mapped IPv6 forms all refused). An internal
    target requires `network_class: private` plus an `approval_reason`, and records the caller as
    its approver. The address check runs **again at resolve time**, because DNS moves while a
    definition looks unchanged.
  - **Target selection is audited.** `POST .../{ref}/resolve` writes a `target.resolve` entry
    whether it succeeds or not, with the actor and whether they were an interactive user or a CI
    runner (`actor_kind: api_key`). An update records which *field names* changed and never their
    values; a resolve records the credential reference *kind* and never the reference itself.
  - **`verification_targets` RBAC resource** (apiome-db V211) — Owner/Admin manage; Editor, Viewer,
    and any member with no explicit role may view, which is what a resolve requires.
  - **Endpoints** — `GET|POST /v1/tenants/{tenant}/verification-targets`,
    `GET|PATCH|DELETE .../{ref}`, `POST .../{ref}/resolve`, and
    `GET /v1/tenants/{tenant}/verification-targets-audit`. `{ref}` is a slug **or** an id, so CI
    names a stable handle while an evidence record names an immutable one. Every refusal carries a
    stable `{code, message}`.
  - **Run records carry a target identity, never credentials** — `target_identity()` is the
    ECA-1.3 seam (id, slug, environment, network class, base URL). Retired targets are
    soft-deleted so an evidence reference keeps resolving; the slug is freed for reuse.
  - **Policy is set by the registry, not the runner** — timeout, concurrency, retries (transport
    only), mutating methods off by default, redirects off, TLS verification only disableable on an
    approved private target, and a failing run blocking the gate by default.

## [1.202.0] - 2026-07-27

### Added
- **Version contract-suite compiler (#4729, ECA-1.1)** — a published specification is passive: until
  somebody hand-writes verification cases, "the API matches its contract" is an opinion, and the
  cases that do get written differ between teams and cannot be reproduced later. One canonical
  version plus one set of compiler options now produce one versioned manifest of executable request
  cases. See [docs/contract_suite.md](./docs/contract_suite.md).
  - **`app/contract_suite.py`** — the pure compiler. Declared examples first, then schema-valid
    generated bodies (required-only, every-property, one per polymorphic branch), then the negative
    cases a contract needs to be worth running (a required body omitted, a required query parameter
    dropped, a wrong-typed parameter, and bodies that each violate exactly one schema constraint).
    Every case carries its operation, its source, its provenance pointer, and the outcome the
    contract promises.
  - **Deterministic by construction.** The same model and options produce byte-identical output:
    `canonical_manifest_bytes()` is that artifact (sorted keys, tight separators, trailing newline)
    and `digest` is its SHA-256 with the digest field blanked. Nothing reads the clock, the network,
    or an unseeded PRNG; generated values are seeded from `(suite seed, operation key)`, operations
    compile in canonical-key order, and options are normalized before they are hashed. This is what
    makes "verified against suite `sha256:…`" a checkable claim — and why `compiler_version` exists.
  - **Honest about what it cannot express.** Streaming operations, non-HTTP paradigms, XML-only
    bodies, structured parameters, cookie parameters, undeclared route placeholders, undeclared
    status codes, unmapped scalars, truncated schemas, and capped coverage each become a
    `SuiteFinding` with a stable code and level. A declared example that does not satisfy its own
    schema is reported with its pointer and **not** compiled: it would fail a correct implementation.
  - **`app/contract_suite_examples.py`** — attributes a source document's examples to
    `(path, method, request body | parameter | response)` by pointer, across OpenAPI 3.x and
    Swagger 2, reusing the IXH-5.4 example table rather than restating where examples live.
    Anything belonging to no operation is counted, never dropped silently.
  - **`POST /v1/tenants/{tenant}/contracts/{version_ref}/suite`** — gated on `versions:view`,
    addressed with the schema-reference grammar minus the type segment
    (`project/{slug}/{version}`, `catalog/{item}/{version}`). Nothing is persisted. A version that
    yields no suite is a 200 with `ok: false` and an intake-taxonomy code; only addressing faults
    are HTTP errors. The manifest records whether the resolved revision is published — looked up,
    never assumed.
  - **A suite carries no target and no credentials.** Paths are relative and security requirements
    are reported for the runner to satisfy; targets are ECA-1.2 and run evidence is ECA-1.3.
  - **`canonical_json_schema.build_ref_json_schema`** — projects a *use-site* `TypeRef` (a
    parameter, a list-wrapped body) with its own constraints, sharing the `$defs` walk with the
    named-type projection instead of duplicating it.

## [1.201.0] - 2026-07-27

### Added
- **Native-analysis extractors and import integration (#4795, CPDO-1.2)** — CPDO-1.1 defined what a
  payload analysis is and left every revision reading back as a declared `unavailable` record,
  because nothing produced one. This produces them. An import parses its source into the format's
  own AST, normalizes that AST into the canonical model, and drops it; everything the canonical
  model has no word for existed only for the duration of one function call. The AST is now analysed
  **while it is still in hand** — after parse, before persistence.
  - **New analyzer SPI on `ImportSource`** — `analyzer_key` / `analyzer_version`,
    `analyzer_tool_versions()`, `analysis_capabilities()`, and `analyze()`. Every one has a working
    default, so a format with no native extractor still records a real (format-blind) analysis rather
    than nothing.
  - **`app/payload_analyzer.py`** — the shared machinery. Analyzers emit cheap `NativeNode`
    descriptions whose children may be a *callable*, and the budgeted breadth-first walk realises
    only the subtrees it will admit: the budget bounds what is built, not just what is stored.
    Counting what was dropped means visiting it, so visiting is capped too — past the cap the record
    says its `droppedNodeCount` is a floor instead of reporting a comfortable number.
  - **EDI X12 (`app/edix12_analysis.py`)** — interchange → functional group → transaction set →
    segment → element, with composites regrouped under their element position rather than flattened
    into siblings. **Every observed group and transaction set is retained**: the node budget is
    raised, if needed, to fit the whole envelope, so a bounded X12 analysis drops elements and never
    envelopes. This is the gap the ticket names — the canonical normalizer reads only
    `functional_groups[0].transaction_sets[0]`, so a two-group interchange lost its second group at
    import.
  - **COBOL copybook (`app/cobolcopybook_analysis.py`)** — record → group → field → 88-condition
    with level numbers, PICTURE, USAGE and OCCURS bounds, plus the **source line** each was declared
    on (recovered by `iter_definition_lines`, matched by name in traversal order so a repeated
    `FILLER` resolves to its own line). Clauses the parser does not read — `REDEFINES`, level-66
    `RENAMES`, `COPY … REPLACING` — are found by scanning the source, because an ignored `REDEFINES`
    leaves no trace in the parsed tree; each one found makes the record `partial` with a stated
    reason instead of presenting a partial tree as a complete one.
  - **Capability data on every record** (`capabilities`, apiome-db V210; contract `1.0.0` → `1.1.0`).
    Warnings say what went wrong in *this* source; capabilities say what would go wrong in any
    source — what the analyzer models, what it knowingly does not, and the bounds it ran under. A
    construct missing from a tree is otherwise ambiguous: the source had none, or the analyzer has no
    word for one. Additive and defaulted, so every V209 row stays readable as "declared none", which
    is what was true of it.
  - **Failures are non-fatal but explicit.** An analyzer that raises, one that overruns the intake
    stage wall clock, and a store that refuses the write each leave the import completed and say so —
    a declared `failed` record naming the analyzer, a `PAYLOAD_ANALYZED` / 
    `PAYLOAD_ANALYSIS_STORE_FAILED` job event, and an `analysis` block on the job summary. Failure
    messages name the exception *type* only: a parser error quotes the source span that broke it, and
    that span may be a credential (IXH-1.4).
  - **Deterministic and redaction-safe.** The same AST and bytes fingerprint identically, so a
    re-import of unchanged source is recognised by content rather than appending a redundant
    sequence; changed source appends the next one and the superseded record stays citable. Observed
    values live only in a node's `value`, never in `attributes`, so
    `store_analysis`'s value-visibility pass governs all of them — under the default `structural`
    policy nothing observed reaches the store.

### Changed
- `PAYLOAD_ANALYSIS_SCHEMA_VERSION` is `1.1.0`; `PayloadAnalysisDocument` and the detail-read
  `analysis` summary both carry `capabilities`.

## [1.200.0] - 2026-07-27

### Added
- **Revision-scoped payload analysis contract (#4794, CPDO-1.1)** — the durable record the catalog
  has never had. A catalog read reconstructs the imported source on every request and reduces it to
  generic entity/field rows, so X12 envelopes and delimiters, copybook levels, PICTURE clauses,
  OCCURS bounds and 88-conditions are derived, rendered, and discarded. A **payload analysis** is one
  immutable record of what an analyzer observed in one source revision, naming the bytes it analysed
  (`source_hash`), the contract it was written against (`schemaVersion`), and the analyzer that wrote
  it — so a reader can tell whether it still describes the source in front of it.
  - New `apiome.payload_analysis` (apiome-db V209), keyed by tenant, catalog project and source
    revision. Rows are write-once (the shared V128 trigger); a re-import mints a new revision and
    therefore a new analysis, and an analyzer upgrade *appends* a sequence rather than rewriting one,
    so an evidence reference stays resolvable. Writes are idempotent by content fingerprint.
  - **Absence is declared, never fabricated.** Statuses are `available` / `partial` / `unavailable` /
    `failed`, each non-available one carrying a closed reason code (`not_analyzed`,
    `no_source_captured`, `unsupported_format`, `bounds_exceeded`, `analyzer_failed`). Three
    invariants are enforced *twice* — as V209 CHECK constraints and as
    `PayloadAnalysisDocument.contract_violations()` at the API boundary: a record describing source
    bytes must name them, a record describing nothing must contain nothing, and anything other than
    `available` must say why. A legacy revision therefore reports `unavailable` with a reason, never
    an empty tree that claims to be complete.
  - **It is not a second copy of the payload.** A `ValueVisibility` policy (`none` / `structural`
    default / `full`) governs observed values and is recorded on the record itself, so "no values
    here" is always a stated policy. Redaction runs before the write (the store never holds more than
    policy allows) *and* on read (a request can only narrow, never widen — values the store never
    held cannot be re-materialised). A record carrying values its own declared visibility forbids is
    itself a contract violation, which is what stops raw analyzer output from being stored as though
    a policy had run.
  - **Bounded.** `bound_tree` applies a 5000-node / 32-level budget by breadth-first admission, so
    envelopes survive and deep leaves are what get dropped; `metrics.truncated` and
    `droppedNodeCount` report it, and a bounded record cannot claim to be `available`.
  - New `GET /v1/catalog/{tenant}/{item}/analysis` returns the record — native tree, source
    locations, warnings, redaction metadata, and the identity a CPDO-1.3 manifest will cite. Gated on
    `imports:view`; item existence is checked before the permission so a cross-tenant id 404s rather
    than confirming itself with a 403. `?valueVisibility=` narrows; an unknown level is a 422.
  - The catalog detail read gains an `analysis` **summary** — status and counts, no payload material,
    readable by anyone who can read the item. It is built without reading the `tree` column, so the
    detail endpoint's cost is independent of the analysed payload's size, and a store fault degrades
    that one field to `failed` rather than failing the whole item.
  - Retention: `apiome.purge_payload_analysis(retention_days DEFAULT 90)` drops superseded analyses
    and those of soft-deleted revisions. Age alone is never sufficient — the current analysis of a
    live revision is the catalog record.
  - Documented in `docs/payload_analysis.md`, with `document_json_schema()` publishing the contract
    generated from the model so it cannot drift. OpenAPI 1.64.1 → 1.65.0.

## [1.198.0] - 2026-07-26

### Added
- **Secret scrubbing on intake, completed (#4393, MFI-29.6)** — the IXH-1.4 scrubber gains the
  two halves the ticket still owed it. **Entropy detection**: a credential no named pattern can
  identify (an opaque token under a neutral key) is now caught by its Shannon entropy, with the
  floor calibrated in the measured gap between identifier-shaped strings and generated
  credential material, and maximal-run matching plus UUID/hex/numeric exemptions keeping
  embedded payloads and operation ids untouched. **Per-tenant mode**: a new append-only
  versioned policy (`intake_secret_scrub_policies`, apiome-db V208) selects `enforce` (redact
  the persisted source — the shipped default, unchanged behaviour) or `warn_only` (report the
  identical findings and persist content untouched, including keeping an archive whole).
  Resolution is format override → format default → tenant → default, and the winning tier,
  mode, and policy version are recorded on every `secret_scrub` job-summary block and
  pre-flight report. The MFI-EPIC-32 collection/captured-traffic formats (`har`, `insomnia`,
  `bruno`, `postman`, `http-file`) resolve to `enforce` regardless of the tenant mode unless
  overridden per format — what MFI-32.5 gates on. New governance API
  `GET`/`PUT /v1/tenants/{slug}/governance/secret-scrub-policy` (+ `/versions`), tenant-admin
  only and audited with the full policy body. Detection now runs against the original text, so
  a finding after a collapsed PEM block reports its true line number, and an archive's report
  names the members that carried something (a line number alone is ambiguous across a fileset).
  Overlap resolution checks neighbouring spans rather than scanning every claimed span, keeping
  detection near-linear on the token-dense captures this protects (8k credentials ≈ 0.9s).
  Message scrubbing stays mode-independent: `warn_only` governs persisted source material, not
  what may reach a log aggregator. OpenAPI 1.63.0 → 1.64.0.

### Fixed
- `test_scrubbing_preserves_document_structure` asserted a document tree for every scrubbing
  fixture and so failed on the line-oriented `.http` fixture; the structural contract is now
  stated in each format's own terms (parsed shape for JSON/YAML, unchanged line count with
  non-redacted lines byte-identical for request files).

## [1.193.0] - 2026-07-26

### Added
- **LLM tool / function-calling schema bundle import adapter (#5128, IXH-7.3)** — new
  `llm-tools` `ImportSource` detects OpenAI `{type:function, function:{name,parameters}}`,
  Anthropic `{name, input_schema}`, and bare `{name, parameters}` arrays (or `{tools:[…]}`
  wrappers), normalizes each tool to a canonical operation under `ApiParadigm.AGENT`, and
  records per-tool dialect provenance. Mixed-dialect bundles are accepted (not rejected);
  each tool keeps its dialect on `operation.extras.dialect`. Ships a native lint pack
  (description presence/specificity, parameter descriptions, enum-over-freetext, required
  hygiene, duplicate names), MCP↔llm-tools tool-surface fingerprint bridge, corpus ladder
  with negatives, golden snapshots, format sniff, lint capability matrix row, and UI
  catalog mapping. OpenAPI 1.59.0 → 1.60.0.

## [1.192.0] - 2026-07-26

### Added
- **Kubernetes CRD structural-schema import adapter (#5127, IXH-7.2)** — new
  `k8s-crd` `ImportSource` detects `apiVersion: apiextensions.k8s.io/*` +
  `kind: CustomResourceDefinition`, parses multi-document YAML streams into one
  `CanonicalApi` with a Service per CRD, and normalizes each version's
  `openAPIV3Schema` via SchemaCoercer with stable versioned type keys. Deprecated
  and non-served versions are labelled (not dropped); `x-kubernetes-*` extensions
  are preserved in extras for the coverage ledger. Ships a native lint pack
  (structural-schema pruning + required-field hygiene), corpus ladder with
  negatives, golden snapshots, format sniff, lint capability matrix row, and UI
  catalog mapping. OpenAPI 1.58.0 → 1.59.0.

## [1.191.0] - 2026-07-26

### Added
- **Google API Discovery import adapter (#5126, IXH-7.1)** — new `discovery`
  `ImportSource` detects `kind: discovery#restDescription` / `discoveryVersion`,
  parses nested resources/methods/parameters/schemas, and normalizes to the REST
  paradigm with stable HTTP operation keys and SchemaCoercer `$ref` resolution.
  Live directory listing and selected-API import run through the SSRF-guarded
  fetcher against the public Discovery directory. Corpus ladder (valid + negative),
  golden snapshots, format sniff, lint capability matrix row, UI catalog mapping,
  and CLI registry dispatch (`apiome import discovery`) ship with the adapter.
  OpenAPI 1.57.0 → 1.58.0.

## [1.190.0] - 2026-07-26

### Added
- **Resource guards and streaming intake limits (#5124, IXH-6.5)** — documented
  `GuardProfile` (raw/decoded bytes, expansion ratio, nesting depth, entity count,
  `$ref`/include depth and fan-out, per-stage wall-clock, per-job memory ceiling,
  archive compression ratio) with provisional defaults until IXH-1.5 measurements.
  Tier resolution (`default` / `elevated` via `APIOME_GUARD_PROFILE` or license hint).
  New resource taxonomy codes: `INPUT_ENTITY_LIMIT`, `INPUT_REF_LIMIT`,
  `INPUT_TIME_LIMIT`, `INPUT_MEMORY_LIMIT`. Limit-trip messages name the dimension and
  configured value. Multipart uploads stream to a bounded tempfile (no base64 double).
  Archive budget breaches map to resource codes; path/symlink faults to
  `INPUT_UNSAFE_CONSTRUCT`. Guards apply on commit import, preflight, preview, and
  schema validation. OpenAPI 1.56.0 → 1.57.0.

## [1.189.0] - 2026-07-26

### Added
- **Unified intake/delivery error taxonomy (#5123, IXH-6.4)** — export job failures now
  carry the same taxonomy fields as import (`code`, `category`, `message`, `remediation`,
  `retriable`) from `delivery_error_taxonomy.py`, sharing `JobErrorCategory` with intake.
  Internal faults never surface a bare stringified exception; the user-facing message
  includes the job id as a correlation id. OpenAPI `ExportJobError` is extended
  additively (1.55.0 → 1.56.0). UI remediation and CLI exit codes key off the taxonomy.

## [1.188.0] - 2026-07-26

### Added
- **Async job retention sweep and paginated job listing (#5122, IXH-6.3)** — terminal
  `async_job` rows are reaped by a scheduled sweep (lint-waiver pattern: batched
  `FOR UPDATE SKIP LOCKED`) with configurable per-(kind, state) retention hours
  (defaults: completed/canceled 168h, failed 720h; `0` disables that pair). Each tick
  also calls `reap_expired_export_job_artifacts`, writes slim `async_job_history` before
  DELETE (CASCADE removes artifacts), and prunes history older than 90 days. List
  endpoints `GET …/imports` and `GET …/export/…/jobs` are paginated (`limit`/`offset`/
  `total`, newest-first) with `state` and date filters; unbounded full dumps are gone.
  OpenAPI 1.54.0 → 1.55.0.

## [1.187.0] - 2026-07-26

### Fixed
- **Shared-store import rollback and commit (#5121, IXH-6.2)** — `POST …/imports/{job_id}/rollback`
  (and commit replay) no longer 404 on a non-owning instance under round-robin. Both endpoints
  read the shared `async_job` record (in-memory owner record remains the fast path); the
  per-kind `extra` bag now carries `commit_response`, `rollback_response`, and — for
  `pending-approval` — `owner_resource_constraint: held_preview_transaction`. Preview
  two-phase commit/rollback is still not wired through REST (no held preview transaction /
  sticky owner routing); callers get a documented **501** naming that constraint instead of
  a bare 404. State transitions stay idempotent.

## [1.186.0] - 2026-07-26

### Fixed
- **Shared export artifact store (#5120, IXH-6.1)** — completed export downloads no longer
  404 on a non-owning instance under round-robin. Delivery bytes are persisted to
  `apiome.export_job_artifact` (DB BYTEA behind a driver interface; object-store stubbed
  for larger payloads), keyed by tenant + job with a `sha256:` content hash. The owning
  process keeps its in-memory `EmitResult` as a fast path only. Emit enforces
  `APIOME_EXPORT_ARTIFACT_MAX_BYTES` (default 32 MiB) with a clear failure rather than a
  truncated body; expired artifacts return **410**; download responses expose `Digest` and
  `X-Content-SHA256`. Retention sweep of rows remains IXH-6.3 (`reap_expired_export_job_artifacts`
  is ready for that sweep).

## [1.181.0] - 2026-07-25

### Added
- **Export preview manifest (#5109, IXH-4.1)** — new
  `POST /v1/export/{tenant_slug}/preview-manifest`: a deterministic **structural
  manifest of the emitted artifact**. Every canonical entity (services → operations,
  channels, types → fields) is listed with its stable canonical key, its per-entity
  fidelity status and reason from the shared CPDO-1.3 taxonomy (entities the artifact
  does not carry state their drop reason), and — for carried entities — its location
  in the bundle: the emitted file, the 1-based line in the download-serialized text,
  and a JSON Pointer where derivable. Locations are **artifact-derived**: resolved
  against the actually-emitted bundle serialized exactly as the download packages it,
  via a pointer→line walk for JSON targets (OpenAPI), declaration scanners for text
  targets (proto3, GraphQL SDL), and a name-keyed search for other JSON targets
  (AsyncAPI 3, Avro) — an unresolvable location is `null`, never a guess. The emit
  runs read-only (no artifact, no job row, no field-identity persistence) and a
  severe conversion is described, not blocked. Entities are cursor-paginated with the
  shared page-cursor codec, and full manifests are cached per (tenant, revision,
  target, options) so paging re-emits nothing. Backs the Export Studio's structural
  artifact explorer with two-way entity ↔ code selection (apiome-ui).

## [1.180.0] - 2026-07-25

### Added
- **Re-import delta on the preview manifest (#5106, IXH-3.4)** — when a
  `POST /v1/tenants/{tenant_slug}/import/preview-manifest` request names the catalog
  `project_slug` its commit would use and an existing catalog item lives under it, the
  response carries a `reimport` block computed **before** the commit: `canonical_diff`
  between the current revision's canonical model (re-parsed from its stored source,
  exactly as the convert flow does) and the candidate — by stable key, never raw text —
  grouped and counted by entity family.
  - An identical re-import is an explicit **no-op**: matching candidate/current
    fingerprints (the pre-flight's own revision fingerprint), empty entries, so clients
    can offer to skip a commit that would create an empty revision.
  - Where the format's breaking-change classifier grades the diff, per-entry
    `severity` / `rule_id` / `rationale` and the overall severity are joined on; a
    failed or unavailable classification leaves every entry ungraded with
    `classifier: null` — stated, never implied safe.
  - First-time imports (no existing item under the slug), non-catalog routing, and an
    unreconstructable current source all yield `reimport: null`. The delta is computed
    per request and never cached; the manifest cache and hash are unchanged.

## [1.179.0] - 2026-07-25

### Added
- **Import preview manifest API (#5103, IXH-3.1)** —
  `POST /v1/tenants/{tenant_slug}/import/preview-manifest`: the pre-flight extended into
  the full entity tree (services → operations, types, channels) with stable keys, source
  locations, per-entity provenance, a coverage ledger over the shared CPDO-1.3
  status/reason taxonomy, the adapter capability reference, and cursor pagination with
  stated truncation. (Entry recorded retroactively — the release shipped without one.)

## [1.178.0] - 2026-07-25

### Added
- **Export pre-flight — source lint and target-readiness ranking (#5099, IXH-2.4)** —
  `POST /v1/tenants/{tenant_slug}/export/preflight` ranks every export target for one
  source revision **before** a job exists. The export path previously only lints and
  validates the *emitted* artifact, so a user picked a target, waited for a job, and
  only then learned the source was too thin for it.
  - The **source** is linted under the tenant's resolved style guide (the same engine
    and scoring formula an import pre-flight uses), and the report carries that grade,
    score, tallies, and — unless `include_findings: false` — the ranked findings.
  - Each target reports its projected fidelity envelope (tier, preserved %,
    DROP/APPROX/SYNTH counts from the prediction engine an export job embeds in its
    result), a **capability verdict** naming which construct classes the source uses
    and which the target can carry, the tenant export quality-policy verdict (IXH-2.3)
    with any honoured waiver, a composite `readiness` score, a `band`, and a one-line
    `rationale`.
  - Targets come back best-first — `ready` → `caution` → `blocked` → `unavailable`,
    then descending score, then key. A target the policy **blocks** is ranked and
    returned with its reason, never hidden. `ranking_fingerprint` lets a caller assert
    the ranking is unchanged without diffing the body.
  - Nothing is emitted and nothing is persisted: no export job, no artifact, no
    field-identity rows. The tenant policy is read **once** per ranking and a waiver is
    looked up only when a block would otherwise stand, so the default policy adds no
    queries.

### Changed
- `evaluate_export_quality()` accepts a pre-loaded policy and defers its waiver lookup
  until a blocking verdict makes one meaningful; the verdict → API-model adaptation now
  lives with the policy engine (`verdict_response_model`) so the import pre-flight, the
  export pre-flight, and the coming delivery gate cannot drift apart on it.

## [1.177.0] - 2026-07-25

### Added
- **Tenant import/export quality policy and waivers (#5098, IXH-2.3)** — a
  tenant-scoped, versioned policy now governs *intake* and *delivery*, not just
  publishing. Per scope (`import` / `export`) it carries three independent floors —
  minimum grade, minimum score, and a severity that must not appear — plus an
  enforcement mode (`advisory` reports the shortfall, `block` refuses the
  operation), per-format overrides, whether an override is permitted and by which
  role slugs, and the waiver lifetime. Resolution is **format override → tenant →
  default** and the winning tier is named on every verdict (`policy.source`).
  - `GET/PUT /v1/tenants/{tenant_slug}/governance/quality-policy` (+ `/versions`)
    manage it; writes are tenant-administrator-only, append an immutable version,
    and are written to the access audit.
  - `GET/POST /v1/tenants/{tenant_slug}/governance/quality-waivers` record and list
    accepted risk with actor, reason, scope, and expiry. A grant is refused with
    403 unless the policy permits overrides **and** names the caller's effective
    role — enforcement is server-side, not UI-only.
  - `POST …/import/preflight` (IXH-2.1) now returns the real verdict: `scope`,
    `format_key`, `min_grade`, `block_on_severity`, `enforcement`, the `failures`
    list, `override_roles`, the applied `policy_version_id`, and any honoured
    `waiver_id`. A cached report re-evaluates policy on every response, so a waiver
    recorded between two calls takes effect immediately.
  - `POST …/imports` (both JSON and multipart) enforces the policy **before a job is
    created**: a blocked import returns **409** with the new
    `QUALITY_POLICY_BLOCKED` taxonomy code, its remediation, and the verdict. Dry
    runs and repository auto-refreshes are not gated. A tenant on the default
    policy pays nothing — the gate returns before it looks at the document.
  - Quality waivers are swept by the **existing** CLX-4.2 waiver-expiry sweep, which
    now claims both ledgers on one tick and emits `lint.waiver.expiring` with a
    `kind` of `lint_finding` or `quality:import` / `quality:export`.
  - `evaluate_export_quality()` ships the export half of the gate for IXH-2.4/2.5 to
    call; nothing on the export path is gated yet.
  - Default behaviour is unchanged for every existing tenant: no policy row means no
    floors, advisory only, override permitted.

## [1.176.0] - 2026-07-25

### Added
- **Pre-flight policy override flag (#5097, IXH-2.2)** — `ImportPreflightPolicy`
  gained `allow_override`, which states whether a user may commit anyway against a
  blocking verdict by recording a waiver. Only meaningful when `blocking` is true;
  `false` means the gate is absolute and a client must not offer an override path.
  The placeholder verdict returns `true` (nothing blocks yet), so the import
  wizard's quality step never renders "override forbidden" for a policy that does
  not exist. IXH-2.3 populates it from tenant policy.

## [1.175.0] - 2026-07-25

### Added
- **Pre-flight lint and rank API (#5096, IXH-2.1)** — new
  `POST /v1/tenants/{tenant_slug}/import/preflight` scores a candidate document
  *before* anything is imported. It drives the existing
  `run_adapter_import_job` pipeline with `dry_run` forced on (so no catalog item,
  project, version, type row, or job artifact can be written) and returns an
  `ImportPreflightReport`: detected adapter + confidence, routing decision,
  canonical entity counts, revision fingerprint, the full lint report with
  findings **ranked by severity then rule weight** (each carrying rule id,
  severity, message, location, remediation, and a docs pointer), the resolved
  style guide identity, the secret-scrub report, and an advisory policy verdict
  (the shape IXH-2.3 will populate). A document that cannot be imported is a 200
  with `ok: false` and an intake-taxonomy `error` code, never a 5xx.
  New `src/app/import_preflight.py`; the pipeline gained an optional
  `ImportRunArtifacts` out-parameter so pre-flight reads the *same* lint report a
  commit would persist rather than recomputing it. Reports are cached per tenant
  by content hash and invalidated when the tenant's style guide changes.
- **`FORMAT_UNRECOGNIZED` intake error code** — reported when no registered
  importer recognizes a document (distinct from `FORMAT_MISMATCH`, which means
  the document is not the *selected* format).

## [1.174.2] - 2026-07-25

### Added
- **Round-trip conformance matrix (#5093, IXH-1.7)** — every `(shipped source
  format × shipped emit target)` cell now runs import → fidelity predict → emit →
  re-import → `canonical_diff`, then reconciles every difference against the
  fidelity `LossinessReport` (`DROP`/`APPROX`/`SYNTH` must explain it; unexplained
  diffs and `OK` over-claims fail). Results publish as
  `tests/golden/roundtrip/matrix.json` (+ Markdown summary for IXH-1.8). New
  `src/app/roundtrip_matrix.py` (reusable reconcile/run path for IXH-4.4) and
  `tests/corpus_roundtrip.py` (representative selection + matrix runner). Regenerate
  with `pytest tests/test_roundtrip_matrix.py --update-roundtrip-matrix` (or
  `UPDATE_ROUNDTRIP_MATRIX=1`). First run surfaces 1202 fidelity/emitter/re-import
  gaps as documented strict xfails in `tests/roundtrip_xfails.py` (fixing a cell
  fails the suite until its entry is removed); 23 cells already pass.

## [1.174.1] - 2026-07-24

### Added
- **Canonical golden snapshots and corpus conformance runner (#5092, IXH-1.6)** — every
  `valid` corpus entry now runs detect → parse → normalize → fingerprint → lint and is
  compared against a checked-in snapshot of its canonical model (`raw` excluded) plus its
  fingerprint, entity counts, and lint roll-up, stored one file per entry under
  `tests/golden/corpus/` (240 snapshots). A normalizer change that silently drops a field,
  reorders a list, or renames a canonical key now fails as an identity-keyed structural
  diff built on the shipped `canonical_diff` — naming the entity, its canonical key, the
  changed fields, and (for keyed lists) the exact members added or removed, e.g.
  `changed type Person — fields: fields (-Person.email)` — instead of an opaque blob diff.
  Regenerate with `pytest tests/test_corpus_golden.py --update-golden` (or
  `UPDATE_CORPUS_GOLDENS=1`). Determinism is asserted by running each pipeline twice, and
  the store is completeness- and orphan-checked. New `tests/corpus_snapshot.py` (runner +
  store + diff renderer) and `tests/corpus_adapter_support.py` (entry selection, tool
  gating, known-bug maps, fileset assembly — extracted from `test_corpus_import.py` so
  both corpus suites gate on the same knowledge).
- **Fingerprint order-invariance is now asserted (#5092)** — reordering a structured
  source's mapping keys must not change the version fingerprint. This surfaced 24 corpus
  entries across four adapters where it does: `json-schema` and `jtd` normalizers never
  call `normalize_ordering`, and `fhir`/`raml` call it on only some return paths, so a
  `Type.fields` list keeps source declaration order. Recorded as documented strict xfails
  in `KNOWN_ORDER_SENSITIVE_FINGERPRINTS` (fixing a normalizer fails the suite until its
  entries are removed), which keeps the debt tracked for the 1.7/1.8 conformance work. No
  behavior changed: a fingerprint is stable for a fixed source, which every fixture is.

## [1.174.0] - 2026-07-24

### Security
- **Hardened XML intake (#5090, IXH-1.4)** — all six XML-based adapters (XSD, WSDL,
  WADL, OData/EDMX, ISO 20022, XML-RPC) now parse through `src/app/secure_xml.py`,
  which refuses DTDs, entity definitions/references, external `SYSTEM`/`PUBLIC`
  identifiers, and XInclude directives, and bounds document size and element depth.
  Previously every one used bare `ElementTree`, which expands internal entities — a
  billion-laughs document expanded during *format detection*. `defusedxml` is now a
  declared dependency rather than a pyx12 transitive.
- **Intake resource guards (#5090)** — new `src/app/intake_resource_guard.py` applies
  the published `oas_resource_limits.json` bounds (which already list `import` in
  `appliesTo`) at the intake parse seam: document size, YAML alias-expansion cost,
  and nesting depth, plus alias-cycle rejection. `import_ingestion.parse_document`
  had no caps at all, so an alias bomb was an out-of-memory and a deep flow document
  a stack exhaustion. Reuses `safe_oas_parse`'s analysis primitives, now exported.
- **Secret scrubbing on intake (#5090, nucleus of MFI-29.6)** — new
  `src/app/intake_secret_scrub.py` redacts credential *values* (AWS keys, GitHub /
  Slack / Google / Stripe tokens, JWTs, private-key blocks, URL-embedded basic-auth
  and connection strings, cookie jars, secret-named assignments) from the persisted source, job
  event messages and contexts, leaving document structure byte-for-byte intact. The
  job summary gains a `secret_scrub` report (types and line numbers, never values)
  and a `SECRETS_REDACTED` warning event. Archives, whose stored blob cannot be
  rewritten safely, withhold the verbatim source when a member carries a secret.
  Detection logging no longer echoes exception messages, which quote source spans.
- **Archive intake hardening (#5090)** — zip and tar members are screened on their
  declared size *and* read through a hard ceiling, so a header that under-declares
  its size cannot materialize past the per-file limit; corrupt-member faults now
  surface as `ArchiveIntakeError` instead of escaping as internal errors. Fixes a
  latent bug where `tarfile.SkipHeader` (which does not exist) made any tar
  containing a directory entry raise `AttributeError` out of intake.

### Added
- **Adversarial corpus (#5090, IXH-1.4)** — new `adversarial/` corpus tier with a
  `guard` field naming the defense each entry targets: 11 committed fixtures (XML
  entity expansion, XXE file and SSRF reads, parameter-entity indirection, XInclude,
  deep nesting, secret-bearing OpenAPI and Postman documents) plus 11 built at test
  time by the committed `scripts/generate_adversarial_corpus.py` (zip/tar bombs,
  path-traversal archives, a 10^5-node document, 5000-deep nesting, a 200-link `$ref`
  cycle, a YAML alias bomb, two credential-bearing documents, and a 1 GiB sparse
  document), keeping repo size flat and credential-shaped literals out of the repo.
  New taxonomy codes `INPUT_UNSAFE_CONSTRUCT`, `INPUT_TOO_LARGE`, `INPUT_DEPTH_LIMIT`,
  `INPUT_EXPANSION_LIMIT`. Tests: `test_corpus_adversarial.py` (per-fixture wall-clock
  and `tracemalloc` peak budgets, no persistence, traversal refused before extraction,
  secrets absent from source/events/logs), `test_secure_xml.py` (per-adapter
  assertions), `test_intake_resource_guard.py`, `test_intake_secret_scrub.py`.

## [1.173.0] - 2026-07-24

### Added
- **Intake error taxonomy + negative corpus (#5089, IXH-1.3)** — stable, additive-only
  error codes for import intake failures (`src/app/intake_error_taxonomy.py`: category,
  retriability, remediation per code). Failed import jobs now carry a structured
  `error` object (`code`, `category`, `message`, `remediation`, `retriable`) in the
  job-status contract; the in-process pipeline classifies parse/normalize failures
  (empty input, encoding faults, wrong-format-but-plausible uploads, malformed
  documents) and `ImportSourceError` accepts an optional explicit `code`. Registry-level
  format detection now treats a raising adapter `detect()`/sniffer as no-match instead
  of surfacing a 500. The examples corpus gains a `negative/` tier: >= 5 malformed /
  truncated / misrouted / encoding-fault fixtures per shipped adapter, each with a
  manifest-declared `failure_class` + `expected_error_code` asserted end-to-end by
  `tests/test_corpus_negative.py` (pipeline) and `tests/test_spec_import_contract.py`
  (HTTP, never a 5xx).

## [1.172.0] - 2026-07-24

### Added
- **OpenAPI-native passthrough detection (#4008, MFI-22.7)** — catalog → OpenAPI conversion
  classifies the source before the lossy emitter runs. OpenAPI/Swagger adopt the captured
  document (`passthrough`; Swagger 2.0 upgrades structurally to OpenAPI 3.1 with an informational
  note); TypeSpec routes through a `tsp` native OpenAPI emit seam (`typespec_native`; missing
  `tsp` → 422, no silent lossy fallback); every other format stays on 22.1–22.5 (`lossy`).
  Preview/commit return a guaranteed high-fidelity report for the near-lossless modes, and
  dry-run/commit responses expose `conversionMode`. New `src/app/conversion_passthrough.py`;
  `ConversionSource.source_text` carries captured source for TypeSpec/OpenAPI when `api.raw` is
  absent. Tests: `tests/test_conversion_passthrough.py` plus convert route/job coverage.

## [1.158.0] - 2026-07-22

### Added
- **License plan quota limits: projects, versions, AI (#64)** — the license catalog now
  carries the three quota limits a plan grants, so paid tiers differentiate from free.
  New apiome-db migration `V195` populates `max_projects`, `max_versions` and the new
  `max_ai_requests` keys on the seeded Free/Paid/Sponsor `licenses.seats` (Free unchanged
  at 1/3/0, Sponsor unlimited via `-1`) and documents the canonical key set. New
  `license_capacity.license_quotas` resolves those keys from the tenant's license (Free
  defaults when unlicensed; `-1` = unlimited), and `GET /v1/tenants/{tenant_slug}/license`
  gains a `quotas` block (`LicenseQuotasSchema`) reporting them alongside seats. Project
  and version quotas are enforced by apiome-ui on the write paths; the AI cap is stored and
  reported only (no usage meter yet), mirroring how V097 seat *storage* preceded OLO-5.3
  seat *enforcement*.

## [1.156.0] - 2026-07-22

### Added
- **Sign-in/sign-up/link audit events (OLO-1.6, #4191)** — a durable, append-only record of
  authentication outcomes so support and security review can answer *who signed in/up, with which
  provider, and which identities were linked*. New migration `apiome-db/V193` adds the hash-chained
  `apiome.auth_events` ledger (event type, user, provider, salted IP/User-Agent hashes, outcome,
  stable error code), reusing the `access_audit` (V120) pattern. New pure seam
  `app/auth_events.py` maps an OLO-1.3 resolution decision to an `AuthEvent`
  (`event_from_decision`) and reduces client IP/UA to salted SHA-256 (`hash_client_value` — the raw
  values are never stored). New `Database` methods: `write_auth_event` / `log_auth_event`
  (best-effort append — a failed audit write never blocks the sign-in it records),
  `list_auth_events_for_user` (the login-history read path feeding #1607/#534/#2418), and
  `prune_auth_events` (documented tail retention). Retention policy and usage documented in
  `docs/AUTH_EVENTS.md`.

## [1.155.0] - 2026-07-22

### Added
- **Agent outputs: `llms.txt`, catalog and release manifests (APX-3.4,
  private-suite#2459)** — deterministic, machine-readable portal metadata generated
  from a published version's approved canonical content, so coding agents can discover
  and consume an Apiome portal safely. New pure generator `app/slate_agent_outputs.py`
  and read API under the existing `/v1/versions` prefix:
  - `GET /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/agent-outputs` —
    returns the JSON **index** (the versioned metadata listing every output with its
    stable URL, media type, ETag and size) by default, or one raw output via
    `?output=llms.txt|robots.txt|catalog|release` served with that output's real
    media type.
  - The **catalog / format-capability manifest** (`slate.catalog.v1`) inventories every
    operation, schema and channel with a stable fragment id and canonical human-page URL,
    plus the capabilities Slate actually supports for the source format (Try It and code
    samples are REST-only at the commercial-MVP boundary; reference, search and changelog
    apply to every native format).
  - The **release manifest** (`slate.release.v1`) carries the version label, publish time,
    content digest, canonical/changelog URLs, latest/deprecated flags and linked change
    counts from the stored changelog.
  - Outputs are deterministic (pure, no clock — every timestamp caller-supplied — with
    total, stable ordering and content-addressed ETags) and cacheable (`Cache-Control`
    + `If-None-Match` → `304`). Only **published** revisions are eligible (400 otherwise),
    reads are tenant-scoped by token, and a published-but-private portal withholds every
    API name, description, URL and count — `robots.txt` disallows all crawling and the
    manifests carry `contentWithheld: true`, so private content is never emitted.
  - New setting `APIOME_SLATE_PORTAL_BASE_URL` (default `https://portal.apiome.dev`)
    configures the portal base the human-page and agent-output URLs are built under.

## [1.154.0] - 2026-07-22

### Added
- **Git-triggered immutable preview builds and provider status (APX-3.3,
  private-suite#2458)** — the preview control plane on top of the APX-3.1
  routing tables (migration `V191`), under the existing `/v1/slate` prefix:
  - `POST /v1/slate/git/connections` and `GET /v1/slate/git/connections` —
    register and list a site's git provider connection. The webhook secret is
    Fernet-sealed and the repository token is envelope-sealed at rest; neither is
    ever returned — a read reports only *whether* they are set.
  - `POST /v1/slate/git/events` — the signature-verified webhook receiver. It
    verifies `X-Hub-Signature-256` over the **raw** body, resolves the connection
    from the payload's repository, and creates exactly **one preview per source
    digest** (`UNIQUE (connection_id, source_digest)`), so a redelivered event is
    a no-op. A ping, a tag push and a branch deletion are accepted and ignored; a
    bad signature is 401.
  - `GET /v1/slate/git/previews[/{id}]` — previews with their immutable commit
    URL, moving branch alias, changed-page deep links, expiry/access state and
    the provider-status payload.
  - `POST /v1/slate/git/previews/{id}/checks` — record a check outcome; a pass is
    the only path that advances the branch alias (optimistic-concurrency token).
  - `POST /v1/slate/git/previews/{id}/retry` and
    `POST /v1/slate/git/connections/{id}/cleanup` — retry and expiry cleanup,
    each appended to an append-only preview audit.
  - Honest boundary, enforced in SQL: there is no Slate build worker (7.3,
    #3419) and no first-party provider check-run adapter, so `build_dispatched`
    is FALSE for every row (`CHECK (NOT build_dispatched)`) and a status can
    never claim `outcome = 'dispatched'` (`CHECK (outcome <> 'dispatched' OR
    dispatch_enabled)`). The wire payload reports both as not dispatched, each
    naming the tier that will attach it.

## [1.153.0] - 2026-07-20

### Added
- **Slate unified observability, residency, usage and budget control plane
  (UXE-3.4, private-suite#2476)** — the control plane the authoring Insights
  surface consumes:
  - `GET  /v1/slate/insights/metric-families`, `.../insights/services` and
    `.../insights/residency-stages` — the catalogs as data. Every metric family
    carries the question it *cannot* answer, every service carries what drives
    its number, and every one of the six residency stages carries the gap its
    promise leaves, so the UI prints what the API returns rather than holding a
    second copy.
  - `GET  /v1/slate/environments/{environment_id}/insights` — the lane: policy,
    all six residency lanes, OTLP export destinations, budgets, synthetic
    checks, `policyVersion`, `signalsDigest`, `updatedBy` and an `enforcement`
    block.
  - `PUT  .../insights/policy` — retention, sampling, tail ceilings and the
    privacy threshold.
  - `PUT  .../insights/residency/{stage}` — one processing stage, its regions
    and what its promise does not cover.
  - `POST|PUT|DELETE .../insights/exports[/{export_id}]` — OTLP destinations.
  - `POST|PUT|DELETE .../insights/budgets[/{budget_id}]` — spend budgets and
    their alert thresholds.
  - `POST|PUT|DELETE .../insights/checks[/{check_id}]` — synthetic probes.
  - `POST|GET .../insights/tail` and `DELETE .../insights/tail/{session_id}` —
    live tail sessions.
  - `POST .../insights/alerts/{alert_id}/acknowledge` — budget alert
    acknowledgement, written as a person and a time together or not at all.
  - `GET  .../insights/metrics`, `.../logs`, `.../traces[/{trace_id}]`,
    `.../usage`, `.../alerts`, `.../synthetic-results` and `.../audit` — the
    read surface, correlated on release, environment and region through the
    same three columns on every signal table.
  - `GET  .../insights/audit/export` and `.../insights/usage/export` — CSV
    evidence.
- **Honesty is a property of the response types, not of handler discipline.**
  `basis`, `observed`, `metered` and `billable` are `Literal` pydantic defaults
  that no handler can assign: constructing a usage rollup with `billable=true`
  is a validation error rather than a code review finding. `enforcement.enforced`
  and a tail session's `eventsDelivered` are literals for the same reason.
  V190's CHECKs and `slate_insights_store`'s SQL literals say the same thing one
  and two layers down.
- **Every policy read and every policy write states that no collector is
  attached**, in a sentence rather than a flag.
- **Correlation is a precondition.** A metric point that cannot be keyed to a
  release, environment and region is dropped and *reported* under `dropped`
  rather than emitted unkeyed, because a chart whose drill-down lands somewhere
  else is worse than a chart with a gap in it.
- **A forecast is never summed into a total**, and measured cache savings are
  reported only when every contributing row was metered.
- **CSV evidence cannot run code and cannot lie by omission** — formula-leading
  cells are apostrophe-prefixed, truncation is stated in words rather than left
  as an inference, both exports write their own audit row, and every usage row
  carries `basis`, `metered` and `billable` as constants so a forwarded
  spreadsheet says what it is without the page around it.

### Changed
- `main.py` registers `slate_insights_router` after `slate_functions_router`, so
  `/environments/{id}/insights*` sits alongside the cache, security and function
  planes. Literal path segments are registered before every sibling path
  parameter — `/tail` before `/tail/{session_id}`, `/traces` before
  `/traces/{trace_id}` — because FastAPI matches in registration order; the
  resolved table is asserted in the test suite rather than trusted to reading
  order.

### Security
- Refusals are HTTP 409 carrying `{code, message, reason}`, the message being
  the domain module's own sentence character for character. Reads require
  `VERSIONS/VIEW` and writes `VERSIONS/PUBLISH`; both CSV exports are VIEW, so
  an auditor is not gated behind the permission to change observability. A
  scope miss answers 404 rather than 403, so a cross-tenant probe cannot confirm
  a lane exists.
- A live tail is refused without a stated reason, above the lane's sampling or
  event ceilings, or with an allowlist widened beyond the redaction allowlist —
  and a refused attempt is audited even when the caller set `dryRun`.
- An OTLP export supplying an inline header value is refused by name rather than
  having the value silently dropped, so an operator who pasted a bearer token
  cannot come away believing it was stored and used.

## [1.152.0] - 2026-07-19

### Added
- **Slate edge functions and safe personalization control plane (UXE-3.3,
  private-suite#2475)** — the control plane the authoring Edge surface consumes:
  - `GET  /v1/slate/functions/presets`, `.../runtimes` and `.../capabilities` —
    the runtime, limit and capability catalogs as data, each entry carrying its
    own expected impact and the condition that makes it unsafe, so a preset is
    its fields rather than its name.
  - `GET  /v1/slate/environments/{environment_id}/functions` — the lane: policy,
    functions, versions, secret references, capability grants, egress rules,
    personalization variants, `policyVersion`, `functionsDigest` and an
    `enforcement` block.
  - `POST|PUT|DELETE .../functions[/{function_id}]` plus `.../versions`,
    `.../rollout`, `.../revert` and `GET .../revisions` — every function write
    stores its prior body first, so a revert applies a stored document rather
    than reconstructing intent from a sentence.
  - `PUT|DELETE .../functions/{function_id}/secrets`, `.../capabilities` and
    `.../egress` — grants are rows, and absence is denial.
  - `POST|PUT|DELETE .../functions/variants[/{variant_id}]` — a personalization
    variant states its audience, fallback, cache-key effect, analytics dimension
    and privacy classification together, or it is refused.
  - `POST .../functions/approvals`, `POST .../functions/simulate`,
    `GET .../functions/invocations[/{invocation_id}]` and
    `GET .../functions/audit[/export]`.
- **Deterministic, query-free policy evaluation** — `simulate` answers a test
  request against the stored policy with no database access and no clock of its
  own, reporting the deciding function, the resolved variant and its fallback,
  the cache-key effect, and **every candidate that lost and why**. A recorded
  simulation can be re-checked later rather than merely believed.
- **Secrets are references, and that is a schema fact rather than a rule.**
  `slate_function_secret_refs` has no column capable of holding a value, so
  storing one is not discouraged but impossible.
- **Capabilities and egress are deny-by-default, modelled as the absence of a
  row.** There is no `granted` boolean, so a bug that fails to write cannot
  accidentally grant. Every grant carries a reason, because the question at
  review is never what was granted but why.
- **Reach is what the server refuses**, and it owns that policy: a secret
  referenced across a project boundary, an unapproved egress destination, an
  enforcing function with no prior simulation, no approval from a second person
  or no active version, a variant with no fallback, a variant that varies a
  shared cache key on an identity credential, a personal-class variant claiming
  no consent was needed, a residency violation, and a limit above the lane's
  ceiling each have a named refusal and no acknowledgement path. Breadth, cache
  fragmentation, a 0→100 rollout jump, a missing analytics dimension and a limit
  near the ceiling warn instead and can be acknowledged. The UI renders those
  sentences verbatim rather than restating them, so the two cannot drift.

### Notes
- **Nothing executes.** `deploy/` remains a single Caddyfile with no edge runtime
  behind it, so a recorded function inspects no requests and runs no code. That
  boundary is enforced rather than documented:
  `slate_function_invocations.executed` can never be true and `source` can never
  be `edge-observed` while `edge_attached` is false — both CHECK constraints, and
  no code path sets `edge_attached`. `record_invocation` writes those three
  values as SQL literals rather than parameters, so it offers no way to pass a
  dishonest one; every policy response carries an `enforcement` block saying so;
  and `basis`, `observed`, `executed` and `enforced` are literal pydantic
  defaults no handler can assign. This matters more than it did for cache or
  WAF: an unenforced cache rule wastes a purge and an unenforced WAF rule fails
  to stop an attacker, while an unenforced capability policy means somebody
  believes their function cannot reach the internet and it can.
- Two thresholds here are invented rather than derived, and should be replaced if
  the product has real numbers: a 0.9 near-ceiling ratio for resource limits and
  a 90-day maximum capability grant window.

## [1.151.0] - 2026-07-19

### Added
- **Slate Edge WAF, DDoS, bot and rate-limit security control (UXE-3.2,
  private-suite#2474)** — the security control plane the authoring Security
  surface consumes:
  - `GET  /v1/slate/security/presets` and `.../managed-groups` — the managed WAF
    tiers, bot and rate presets, and the curated WAF group catalog as data. Each
    states its expected impact and what it is unsafe for, because a preset an
    operator cannot reason about is one they will turn off during an incident
    and never turn back on.
  - `GET  /v1/slate/environments/{environment_id}/security` — the lane's tier,
    presets, group modes, custom rules, exceptions and concurrency token, plus
    an `enforcement` block stating that no delivery tier is attached.
  - `PUT  .../security/presets` and `PUT .../security/managed-groups/{group_id}`
    — change posture. Weakening carries a required reason: disabling the WAF
    with no stated cause is the change nobody can explain afterwards.
  - `POST|PUT|DELETE .../security/rules[/{rule_id}]` — custom rules with an
    explicit precedence. Every write records the prior body to
    `slate_security_rule_revisions` first, so a revert applies a stored document
    rather than reconstructing intent from an audit sentence.
  - `POST .../security/rules/{rule_id}/rollout` and `.../revert`, and
    `GET .../revisions` — staged rollout and the revert path. A rule in
    `simulate` records what it would have done and acts on nothing, so reaching
    enforcement is a deliberate sequence of audited writes rather than one
    checkbox. A rule that never simulated cannot be enforced.
  - `POST .../security/exceptions` and `DELETE .../exceptions/{exception_id}` —
    scoped carve-outs. Every exception expires; one that cannot lapse stops
    being an exception and becomes the policy.
  - `POST .../security/approvals` — dual control. Unlike V186's release
    approvals, the author cannot be the approver, and that is a CHECK constraint
    rather than a convention. It compares immutable identity keys rather than
    the nullable user ids, so offboarding an author cannot retroactively weaken
    a recorded two-person approval.
  - `POST .../security/simulate` — evaluates a test request against the stored
    policy deterministically and answers the action, the deciding rule, and
    every rule that lost and why. That last part is what makes "every block can
    be investigated" true rather than aspirational.
  - `GET  .../security/events[/{event_id}]` — security events joined to rule,
    route, release, region and action, with redacted request evidence.
  - `GET  .../security/audit` and `.../audit/export` — the append-only policy
    audit, and a CSV export for review evidence. The export neutralizes CSV
    injection (an actor display name is attacker-influenced text), does not
    silently truncate, and writes its own audit row: who read the evidence is
    itself audit-worthy.
- **Deterministic, query-free policy evaluation** — `slate_security.py` holds
  the catalogs, the refusal and warning vocabulary and the simulator, with no
  database import and no clock: `now` is always a parameter. The same inputs
  always produce the same verdict, which is what lets a recorded simulation be
  re-checked later rather than merely believed.
- **Lockout is what the server refuses**, and it owns that policy rather than
  sharing it with the UI: a rule that would block the whole site or the
  documentation root, an enforcing rule that never simulated, an enforcing block
  with no second-person approval, an unbounded or non-expiring exception, and a
  rate budget below the floor ordinary reading needs each have a named refusal
  and no acknowledgement path. Breadth, shadowing and a 0→100 rollout jump warn
  instead and can be acknowledged.
- **Request evidence is redacted by allowlist, not filtered by denylist** — a
  denylist fails open on the field nobody thought of. `redact_evidence` drops
  every unlisted key, flattens each surviving value to a scalar, and reduces a
  client address to a `/24` or `/48` network prefix. The database agrees
  independently: `evidence - <allowed keys> = '{}'` is a CHECK constraint, so
  storing a cookie or an authorization header is impossible rather than merely
  discouraged. Every event carries a `retain_until`, because request data is a
  liability, and the audit row rather than the captured user agent is the thing
  that should live forever.

### Notes
- **Nothing is blocked.** `deploy/` remains a single Caddyfile with no WAF, no
  bot management and no CDN, so these rules inspect no requests and challenge
  and block nobody. The boundary is enforced rather than documented:
  `slate_security_events.mitigated` cannot be true and `source` cannot be
  `edge-observed` while `edge_attached` is false — both CHECK constraints — and
  no code path sets `edge_attached`. Simulation responses carry
  `basis: policy-simulation` and `observed: false` as literal defaults the
  handlers never assign, so the response is structurally unable to lie. DDoS
  status reports *unavailable* rather than any protection state, because with
  nothing in the request path a green badge would be a false statement rather
  than an inert one.

## [1.150.0] - 2026-07-19

### Added
- **Slate Edge cache presets, expert rules, trace and purge control (UXE-3.1,
  private-suite#2473)** — the cache control plane the authoring Cache surface
  consumes:
  - `GET  /v1/slate/cache/presets` — the four roadmap §29.3 presets as data:
    every TTL, eligibility, rationale and what each preset forbids. The UI
    prints what this returns rather than holding a second copy of the numbers.
  - `GET  /v1/slate/environments/{environment_id}/cache` — the lane's preset,
    overrides, expert rules and concurrency token, plus an `enforcement` block
    stating that no delivery tier is attached.
  - `PUT  /v1/slate/environments/{environment_id}/cache/preset` — change the
    preset. Bypass without an expiry is refused, because an incident mode that
    outlives its incident becomes the configuration.
  - `POST`/`PUT`/`DELETE .../cache/rules[/{rule_id}]` — expert rules with route
    matchers, eligibility, browser/edge TTL, stale-while-revalidate,
    stale-if-error, cache key, query/header/cookie variation, tags and bypass
    conditions.
  - `POST .../cache/trace` — evaluate a test request and explain the result:
    eligibility, cache key and its components, TTLs, bypass and winning rule,
    plus every rule considered and why it did not win.
  - `POST .../cache/purge` — estimate and record a purge by release, tag,
    prefix, host or URL, with the estimate's basis named on the wire.
  - `GET  .../cache/purges` and `.../cache/audit` — purge history and the
    append-only audit trail.
  - Every mutating route accepts `dryRun`, which runs every gate and writes
    nothing. A refused action still writes audit when it is not a dry run.
- **Deterministic presets and evaluation** — `app/slate_cache.py` is pure: the
  preset table is literals, evaluation injects its clock, and rules sort by a
  total order that `UNIQUE (environment_id, ordinal)` in V187 enforces.
  `rules_digest` content-addresses the evaluated ruleset, so a trace is
  reproducible from its recorded inputs.
- **The server is the authority on unsafe cache variants.** Varying a shared
  cache key on an identity credential, serving stale personalized content, a
  `private` route with an edge TTL and `no-store` with a TTL are refused with
  named reasons and no acknowledgement path — each would serve one reader's
  content to another. Fragmentation and cost concerns warn instead and can be
  acknowledged.

### Fixed
- **`/v1/slate/*` answered 422 for every request** (private-suite#2473).
  `validate_authentication` declares `tenant_slug: str` with no default; other
  routers satisfy it as a path parameter, but the Slate routers deliberately
  read tenancy from the credential, so FastAPI bound it as a *required query
  parameter*. The existing route tests could not see this because they override
  the dependency wholesale, substituting the signature that was wrong. New
  `app/slate_auth.py` resolves the slug from an explicit `tenantSlug`, the JWT
  `current_tenant_id` claim or the API key, then delegates to the unchanged
  `validate_authentication` so no authorization logic is duplicated.
  `tests/test_slate_tenant_auth.py` overrides nothing and sweeps every Slate
  route for a required `tenant_slug` query parameter.

### Notes
- Nothing here evicts anything. `deploy/` is a single Caddyfile with no CDN
  behind it, so a purge records intent, scope, estimate and actor — real,
  auditable evidence — and says so. `outcome` is never `dispatched`; V187's
  `outcome <> 'dispatched' OR edge_attached` CHECK makes that a database
  guarantee. The trace carries `basis: policy-evaluation` and `observed: false`.
  The delivery tier is APX-3.2; this is the control plane it will report into.

## [1.149.0] - 2026-07-19

### Added
- **Managed Slate hosting and immutable versioned deployment (APX-3.1,
  private-suite#2456)** — the deployment control plane the Release Center
  (UXE-2.4) consumes:
  - `GET  /v1/slate/sites/{site_id}/releases` — the release timeline, newest
    first, optionally scoped to one environment. Every row carries the nine
    facts blueprint §28.3 requires: status, environment, source commit/branch,
    artifact digest, actor, checks, created/active time, domains and traffic.
  - `GET  /v1/slate/releases/{release_id}` — one release with its full
    evidence: checks, phases, logs, changed pages, approvals, regions and
    append-only audit.
  - `POST /v1/slate/sites/{site_id}/releases` — record a built release. The
    artifact signature is verified at record time, so unverifiable bytes never
    become routable.
  - `GET  /v1/slate/environments/{environment_id}` — lane state: active
    release, routing version, region rollout and the measured activation SLO.
  - `POST /v1/slate/environments/{environment_id}/promote` — route a lane to an
    already-built artifact. Never rebuilds; refusals are named reasons carrying
    operator-facing sentences, and a refused promotion still writes audit.
  - `POST /v1/slate/environments/{environment_id}/rollback` — route back to the
    most recent retained artifact. Deliberately ignores approval freshness, so
    the approval policy cannot become an outage amplifier.
  - `POST /v1/slate/sites/{site_id}/retention` — reap artifacts that have
    fallen outside the site's rollback window; the active release is never
    reaped.
  - Both mutating routes accept `dryRun`, which runs every gate and returns the
    plan without changing routing, so the impact sheet describes a validated
    action rather than a guess.
- **Content-addressed, signed artifacts** — `app/slate_artifacts.py` computes
  domain-separated content/source/config digests (the content digest is a
  Merkle-style fold over sorted, length-prefixed paths, so an identical rebuild
  on another machine lands on the same identity) and signs them with a
  dedicated key, separate from the JWT secret and fail-closed in production.
- **Atomic activation** — a routing change is one conditional `UPDATE` on the
  environment row guarded by a `routing_version` token, so a concurrent
  promotion is recorded as a `conflict` and refused rather than silently
  overwriting the winner. There is no last-write-wins path.

### Changed
- `Settings` gains `APIOME_SLATE_ARTIFACT_SIGNING_KEY` and
  `APIOME_SLATE_ARTIFACT_SIGNING_KEY_ID`. Production refuses to start without a
  configured signing key rather than signing artifacts with a known default.

## [1.148.0] - 2026-07-18

### Added
- **Source-to-model change review (DCW-2.3, private-suite#2360)** — the
  transactional review/apply surface for the Designer's editable source
  workspace:
  - `POST /v1/versions/{tenant}/{project}/{revision}/source-review` — parse a
    candidate source text (DCW-0.2 safe parser + the same dialect meta-schema
    and local `$ref` integrity checks as export) and classify it against the
    revision's current merged document into additions/updates/deletions/
    unsupported-preserved changes grouped by document, path, operation,
    component, and schema, with structural blockers (referenced-component
    deletions listing every referencing pointer, model-owned `/openapi`,
    `/info`, `/x-metadata` values, unrepresentable shared response/parameter
    shapes). Never mutates. Returns the base digest and a change-set digest.
  - `POST /v1/versions/{tenant}/{project}/{revision}/source-apply` — apply a
    reviewed candidate once in a single transaction
    (`Database.apply_source_change_set`): tenant scope, published
    immutability, draft-lock ownership, and the versions:edit permission are
    rechecked inside the transaction after a FOR UPDATE row lock; stale base
    digests answer 409 `STALE_BASE` with the current digest and resolution
    choices (never last-write-wins); replaying an applied change set is
    idempotent; canonical class/property/path/security-scheme/server rows,
    the preservation envelope, and the `apiome.source_change_audit` entry
    (V185) commit or roll back together.
  - `app/source_change_review.py` — pure classification engine (deep diff,
    pointer→scope grouping, capability-driven unsupported-preserved
    classification, blockers, `$ref` integrity, change-set digest).
  - `app/source_change_apply.py` — pure write planning with a DCW-2.1
    fidelity loop: the plan's predicted regeneration re-extracts the
    preservation envelope so unabsorbed constructs round-trip losslessly, and
    `compare_candidate_to_merged` rejects any lost or altered value while
    reporting deterministic generator enrichments. OpenAPI 1.30.0 → 1.31.0.

## [1.147.0] - 2026-07-18

### Added
- **Round-trip preservation envelope (DCW-2.1, private-suite#2352)** — the
  backend half of the Designer's lossless hybrid source workspace:
  - `apiome.version_preservation_claims` + `apiome.preservation_audit` (V184):
    version-scoped JSONB preservation payload keyed by RFC 6901 JSON Pointer
    with optional source-file/digest provenance, soft-delete retention with a
    `purge_preservation_claims` sweep, and an append-only envelope audit
    written in the same transaction as every envelope change.
  - `GET/PUT /v1/versions/{tenant}/{project}/{revision}/preservation` —
    tenant/version-scoped envelope reads/writes. Writes validate against the
    server-generated canonical document and the DCW-0.1 capability matrix:
    canonical/preserved claims for the same pointer, duplicate or nested
    pointers, unsupported dialects, and oversized envelopes are rejected with
    deterministic structured errors and no mutation; published revisions
    answer 409. Responses carry a semantic fingerprint that reports the
    intentionally excluded lexical differences.
  - `app.preservation_envelope` — pure extract/validate/apply engine with
    deterministic array insertion/reordering, pointer moves, canonical
    deletions (with array-index rebasing), and collision behavior; golden
    OAS 3.1/3.2 corpus covers unknown fields under arrays, `$ref` siblings,
    move/delete, and null/false/empty extension values.
  - `app.safe_oas_parse` + `app.oas_resource_limits` — field-for-field mirror
    of the designer's DCW-0.2 resource-limits artifact: duplicate keys
    (YAML **and** JSON — closing the documented JSON gap), alias-expansion,
    nesting-depth, document-size, multi-document, and circular-alias
    violations all fail with structured, non-mutating diagnostics.
  - OpenAPI 1.29.0 → 1.30.0.

## [1.138.0] - 2026-07-15

### Added
- **Webhook payload upgrade (CTG-3.3, #4477)** — publishing a version now fans
  a `version.published` event out over the existing push-webhook channels,
  embedding the CTG-3.1 classified changelog (severity counts, top changes
  with rule id / path / severity, max severity). Subscriptions gain an
  optional `minSeverity` threshold (`docs-only` | `non-breaking` | `breaking`,
  V179): filtered subscriptions receive only publishes whose classified max
  severity meets the threshold (fail-safe: unclassifiable publishes are
  delivered); unfiltered subscriptions receive every publish (backwards
  compatible). Retry/dead-letter semantics unchanged. Payload schema in
  `docs/publish_webhooks.md`. OpenAPI 1.17.0 → 1.18.0.

## [1.137.0] - 2026-07-15

### Added
- **Changelog read APIs (CTG-3.2, #4476)** — expose the CTG-3.1 stored
  classifications to the dashboard:
  `GET /v1/versions/{tenant}/{project}/changelogs` (one summary row per
  published revision — status, max severity, counts — including revisions with
  no stored row yet) and
  `GET /v1/versions/{tenant}/{project}/{revision}/changelog` (full
  `ctg.changelog.v1` payload with baseline labels). OpenAPI 1.16.0 → 1.17.0.

## [1.136.0] - 2026-07-15

### Added
- **Publish pipeline classification (CTG-3.1, #4475)** — after successful
  publish, a background task classifies the revision vs the prior published
  baseline (`get_prior_published_baseline_revision_id`), builds a
  `ctg.changelog.v1` payload, and upserts `apiome.version_changelogs`
  (`ready` / `initial` / `failed`). Classification failures never undo
  publish. Ops backfill: `scripts/backfill_version_changelogs.py` (after
  V178). OpenAPI 1.15.0 → 1.16.0.

## [1.135.0] - 2026-07-15

### Added
- **CI tokens & scoped keys (CTG-2.3, #4473)** — workspace `api_keys.scopes`
  (`*`, `diff:read`, `lint:read`). Restricted machine keys are allowlisted to
  `POST /v1/diff/{tenant}/classified` and catalog/MCP `GET …/lint` + `…/lint/gate`
  only; writes and other routes return 403. Control Panel key creation offers a
  scope picker (default full access). OpenAPI 1.14.0 → 1.15.0.

## [1.134.0] - 2026-07-15

### Added
- **Classified diff markdown Accept (CTG-2.1, #4471)** —
  `POST /v1/diff/{tenant_slug}/classified` now returns the CTG-1.3 markdown
  changelog when `Accept: text/markdown` (or `text/md`) is sent; JSON remains
  the default. Powers `apiome diff --format md`. OpenAPI 1.13.0 → 1.14.0.

## [1.133.0] - 2026-07-15

### Added
- **Changelog generator (CTG-1.3, #4469)** — deterministic ordered/grouped
  changelog over CTG-1.1 classified diffs: breaking → non-breaking → docs-only,
  grouped by path. Stable **markdown** and **JSON** (`ctg.changelog.v1`)
  renderers plus **"since \<version\>"** aggregation across intermediate hops
  (`build_changelog`, `changelog_since`, `render_changelog_markdown` /
  `render_changelog_json` in `app.changelog_generator`). Docs:
  `docs/changelog_generator.md`. OpenAPI 1.12.0 → 1.13.0 (library surface; no
  new HTTP routes — persist/publish is CTG-3.1).

## [1.132.0] - 2026-07-15

### Added
- **Classified diff REST endpoint (CTG-1.2, #4468)** —
  `POST /v1/diff/{tenant_slug}/classified` wraps the CTG-1.1 classifier for
  **stored-vs-stored** and **inline-vs-stored** (uploaded candidate OpenAPI vs a
  stored base). Response includes classified changes, summary counts, and
  `maxSeverity`. Inline documents over 10MB UTF-8 are rejected with `413`.
  Auth: JWT or API key with `versions:view`. Docs: `docs/change_taxonomy.md`.
  OpenAPI 1.11.0 → 1.12.0.

## [1.131.0] - 2026-07-15

### Added
- **Change taxonomy & classifier (CTG-1.1, #4467; corpus CTG-1.4, #4470)** — OpenAPI
  document classifier that grades every base→head change as **breaking** /
  **non-breaking** / **docs-only**, each with a stable rule id, JSON Pointer, and
  before/after values. Unknown kinds fail safe to breaking with `unclassified=True`.
  Extensible rule registry (`register_rule` / `override_severity`) for later GOV
  style-guide re-severity. Pure API: `classify_openapi_changes` in
  `app.change_taxonomy` (REST endpoint is CTG-1.2). Regression corpus under
  `tests/fixtures/diff/` with golden outputs. Docs: `docs/change_taxonomy.md`.
  OpenAPI 1.10.1 → 1.11.0 (library surface; no new HTTP routes yet).

## [1.130.0] - 2026-07-15

### Added
- **AsyncAPI importer persistence (REPO-3.3, #2772)** — catalog AsyncAPI imports
  now write the normalized event model into MFI-2.2 tables (`api_artifacts` →
  channels / services / messages) via `canonical_persistence`, promote message
  payload and headers schemas into designer `classes` (UUIDs on
  `message.extras.payload_class_id` / `headers_class_id`), keep channel
  `bindings` lossless, and mark individual malformed channels
  `extras.status=parse_error` without aborting the rest of the document.
  Acceptance coverage for Streetlights 2.6 + Anyway Jobs 3.0 (YAML/JSON intake,
  v2/v3 action normalization, round-trip through the persist codec + emitter).

## [1.129.1] - 2026-07-15

### Added
- **Export-fidelity user and format-author guidance (EFP-3.3, #4818)** — published
  the emitter-author projection contract
  (`docs/export_projection_author_guide.md`): the four obligations for every newly
  supported target construct (capability, reason, documentation, fixtures),
  reason-code truthfulness rules, documentation-link governance (allowlist, review
  and version-update ownership), and the corpus fixture/waiver gate. Cross-linked
  from `docs/emitter_spi.md`. The `projection-evidence` OpenAPI description now
  points to the user interpretation guide (`docs/guide/export-fidelity.md`);
  OpenAPI 1.10.0 → 1.10.1 (no contract shape changes).

## [1.129.0] - 2026-07-15

### Added
- **Projection evidence guardrails (EFP-3.2, #4817)** — always-on source
  redaction (`native_id` / `native_name` / `source_location` plus scrubbed edge
  text), TTL manifest cache, documented performance budgets
  (`docs/projection_evidence_guardrails.md`), privacy-safe
  `export.projection` telemetry (preview failures, stale acknowledgements,
  evidence pages, documentation-link counts), and
  `POST /v1/export/{tenant}/projection-metrics` for whitelisted UI metrics
  (e.g. `aggregation_used`). `redact_source` is ignored; responses always set
  `redacted: true`.

## [1.124.1] - 2026-07-15

### Fixed
- **CI suite regressions after CLX-4.3 / format emitters** — JSON Schema detection declines
  JTD-exclusive documents and shares dialect tags with its sniffer (no false ambiguity on
  `optionalProperties` / `json-schema-2020-12`); stale tests updated for WSDL emit support,
  lint-rule transparency fields, style-guide `externalLintProfile`, and Connect-RPC tests that
  require the `buf` toolchain.

## [1.124.0] - 2026-07-15

### Added
- **Transparent rules, benchmark corpus, and scanner evaluation (CLX-4.3, #4861)** —
  foundational quality program so blocking lint claims stay auditable.
  - **Blocking-rule transparency catalog** (`app.scanner_rule_transparency`, revision `1`):
    every error-severity rule across schema lint, MCP surface lint, conformance, and trust
    posture carries stable id, reference, rationale, remediation, false-positive guidance,
    scan-mode requirements, and a corpus `fixtureId`. Catalog APIs enrich descriptors;
    `GET /v1/mcp/lint/rules` publishes the MCP surface catalog.
  - **Scanner-evaluation corpus** under `tests/fixtures/scanner_evaluation/` — safe/unsafe
    MCP surfaces, OWASP MCP Top 10 examples, ToolBench-style usability defects, multi-format
    catalog pointers, and ops-failure inventory over external-linter fixtures. Differential +
    determinism tests (`test_scanner_evaluation_corpus.py`) gate scanner updates before release.
  - **Docs** — `docs/scanner_evaluation.md` (corpus layout, release gate, unassessed coverage,
    dynamic-scan consent risks, adapter deprecation policy); `docs/guide/axis-score.md`;
    generated MCP rule reference pages; algorithm `algorithmDocsPage` on axis evaluations.

## [1.123.0] - 2026-07-14

### Added
- **CI, webhook, SARIF, and attestable lint outputs (CLX-4.2, #4860)** — governance now runs
  before merge/release with machine-readable results and exact policy provenance, instead of a
  human reading a dashboard.
  - **Lint gate endpoints** — `GET /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/lint/gate`
    and `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/versions/{version_id}/lint/gate`
    (`app.lint_gate`): evaluate the pinned policy pack over the subject's current evidence
    (persisting a reproducible `lint_policy_evaluations` row), optionally diff regressions
    against a baseline revision/snapshot (`baselineRevisionId` / `baselineVersionId`, CLX-4.1
    per-scanner fingerprint semantics), and emit the verdict as JSON, SARIF 2.1.0, JUnit XML,
    Markdown, or a signed in-toto attestation (`?format=` or `Accept`). HTTP status is always
    200 — the CI exit code belongs to the CLI and reflects only configured policy failures
    (AC-1).
  - **`newOnly` gating (AC-3)** — the CI verdict's unwaived-errors gate can be scoped to newly
    introduced findings so pre-existing debt does not block; required-coverage and axis gates
    always evaluate the full head revision.
  - **Policy-aware SARIF (AC-2)** — verbatim scanner rule ids and locations,
    `properties.apiome` per result (policy state, regression flag, scanner, fingerprint),
    standard `suppressions` for waived findings, and run-level provenance (input / scanner /
    policy / report fingerprints, AC-4) in `runs[0].properties.apiome` (`app.lint_gate_emit`).
  - **Attestable evidence summaries** — in-toto Statement v1 in a DSSE envelope, HMAC-SHA256
    signed with `APIOME_LINT_ATTESTATION_SIGNING_SECRET` (unsigned but well-formed when unset);
    offline verification via `apiome lint verify-attestation` (`app.lint_attestation`).
  - **Provider-neutral lint webhooks** — `lint.scan.completed` (new evidence run recorded;
    fingerprint-dedup re-scans stay silent), `lint.regression.detected` and
    `lint.coverage.failed` (fired only by deliberate gate evaluations, never plain policy
    reads), and `lint.waiver.expiring` (periodic sweep; exactly-once per grant via the V176
    `expiry_notified_at` claim, re-armed when a waiver is renewed) over the existing
    HMAC-signed push-webhook channels (`app.lint_notifications`,
    `app.lint_waiver_expiry_sweep`).
  - **Redaction guarantee (AC-5)** — every artifact and webhook payload carries ids and
    fingerprints only; raw configuration, raw artifacts, protected source, and credentials
    never appear in outputs.

## [1.122.0] - 2026-07-14

### Added
- **Catalog-wide lint posture and remediation workspace (CLX-4.1, #4859)** — a persistent triage
  surface over the CLX-1.x substrate so teams can own risk instead of exporting one-off reports.
  - **Cross-catalog read paths** — the newest evidence run per (subject, scanner) across the
    tenant's latest live catalog revisions and MCP snapshots, joined with axis evaluations, latest
    policy evaluations, and finding decisions (`app.lint_workspace`,
    `GET /v1/lint/workspace/{findings,summary,trends}`). Findings merge per scanner via the shared
    `app.lint_evidence.merged_findings_from_runs`, so the workspace and policy evaluation can never
    disagree about "current findings". Regressions (`isNew`) diff each scanner's latest run against
    its previous one.
  - **Queue filters and facets** — severity / effective state / axis / grade / coverage / profile /
    scanner (source) / subject type / project / owner / rule / category / new / free-text, with
    pre-pagination facet counts and severity/newest/rule/subject sorts.
  - **Trends that separate genuine remediation from policy change (AC-4)** — `remediatedFindings`
    counts only fingerprints that disappeared without being waived or false-positived; waiver
    grants/expiries, false-positive marks, and policy pack publications are distinct series.
  - **Waiver request → review** — a new `waiver_requested` decision state (V175): requesting is an
    editor action, approving into `waived` (or rejecting) needs the new `lint_findings:publish`
    permission. Requested waivers still gate CI exactly like `open`.
  - **Bulk actions: authorized, audited, reversible (AC-3)** — `POST /v1/lint/workspace/decisions/bulk`
    (≤200 items) enforces `lint_findings` RBAC (per-item publish gating), appends the existing
    immutable decision events, and returns per-item `beforeState` so clients can build the exact
    inverse request. The single `POST /v1/lint/decisions` upsert now enforces the same guard, so
    bulk authorization cannot be bypassed one decision at a time — keyless legacy API-key callers
    without a resolvable user now receive 403 on decision mutations.
  - **Saved views** — per-user named filter bundles (`lint_workspace_saved_views`, V175) with
    validated filter blobs, mirroring the MCP saved-search surface.
  - **RBAC** — new `lint_findings` resource seeded into the built-in role grids (Owner/Admin:
    full + publish; Editor: view/edit; Viewer: view).
  - Docs: `docs/lint_workspace.md`. UI: the ADE **Lint Posture** workspace (queue with bulk
    select, finding detail linking revision/evidence/policy/history, trends tab, saved views).

### Fixed
- **Lint decisions proxy never reached the backend (CLX-1.3 follow-up, #4859)** — the
  `/v1/lint/*` routers take the tenant slug as a **required `tenant_slug` query parameter**
  (they have no slug path segment), but the UI's `/api/lint/decisions` proxy never sent it, so
  every call failed request validation (422) and decisions silently never loaded. The decisions
  and new workspace proxies now resolve the session tenant's slug and forward it; a route test
  pins the contract against the real auth dependency (dependency-override tests could not see
  it).

## [1.121.0] - 2026-07-14

### Added
- **MCP trust baselines, drift, and shadowing detection (CLX-3.4, #4858)** — a point-in-time score
  cannot detect a *rug pull*, so this pins an operator-approved **baseline** and diffs every later
  rediscovery/release against what was actually blessed, classifying each material change and gating
  the configured risk deltas.
  - **Trust manifest** (`app.mcp_trust_manifest`) — one comparable fingerprint composed from
    identity, transport (with volatile timing dropped), the **reused** `surface_fingerprint`
    (capabilities / tool-resource-prompt metadata / normalized schemas), the policy-relevant tool
    authority annotations (`readOnlyHint` / `destructiveHint` / `openWorldHint` / `idempotentHint`),
    and the source/SBOM digests. Existing discovery fingerprints/history are reused, not duplicated.
  - **Drift classification** — `diff_trust_manifests` classifies every change as **normal_change**,
    **quality_regression**, **security_regression**, or **coverage_loss**, and each change carries an
    old→new evidence reference (AC1). The surface diff and schema severity come from the canonical
    `diff_surfaces` / `classify_change` engines.
  - **Gate over configured risk deltas** — a `DriftGate` decides pass/warn/blocked; blocking is
    enforced only when `APIOME_MCP_TRUST_DRIFT_GATE_ENABLED` is on, advisory otherwise.
  - **Shadowing** (AC3) — `detect_shadowed_names` groups tool/resource/prompt names exposed by more
    than one *enabled* endpoint in the host scope; a same-host collision is flagged strongest.
  - **Baseline approval** (AC2) — `mcp_trust_baselines` (V174) stores the approved snapshot, the full
    manifest envelope, the required administrator **rationale**, and the gating categories; approving
    a new baseline supersedes the prior one and writes a `registry_audit` policy event.
  - **REST** (`POST|GET .../trust-baseline`, `GET .../trust-drift`, `GET .../data-quality/shadowing`),
    **CLI** (`apiome mcp trust-baseline-approve` / `trust-baseline-show` / `trust-drift` /
    `shadowing`), push-webhook drift alerts (`mcp.trust.drift`, kill-switched by
    `APIOME_MCP_TRUST_DRIFT_NOTIFY_ENABLED`), config flags, V174 migration, OpenAPI + semver bumps,
    docs, and comprehensive engine/route/CLI/migration tests.

## [1.120.0] - 2026-07-14

### Added
- **Consent-gated, sandboxed MCP dynamic probes (CLX-3.3, #4857)** — the first MCP engine that
  *sends a live server something and watches what it does*, so a finding can graduate from
  **suspected** (a static signal) to **observed** (a probe witnessed the behaviour) to
  **exploited-in-test** (a probe demonstrated it against a live server in isolation). It fills the
  guarded `make_proven_finding` door CLX-3.2 shipped unused — and keeps the guarantee, because only
  an exploited-in-test finding ever becomes `ProbeEvidence`.
  - **Three profiles** (`app.mcp_probe`). `passive` (default) is read-only — it re-reads the
    transcript discovery already captured, sends nothing, needs no consent, and never touches a
    business tool. `safe-active` sends benign protocol-layer messages (never a side-effecting
    business-tool call); `payload-fuzzing` sends crafted canary payloads to tool parameters. A
    passive profile *cannot* emit an exploit tier — the ceiling is enforced at probe registration and
    again at report assembly.
  - **Consent (AC2).** An active run requires a `ConsentRecord` carrying an allowlisted target, a
    declared ownership assertion, an acknowledging user, a dedicated (non-production) test identity,
    and — for fuzzing — explicit per-run approval. The whole record is copied into the audit trail.
    The allowlist is `apiome.mcp_probe_targets` (V173); enrolling requires the ownership assertion,
    which the schema makes unstorable to omit.
  - **Isolation (AC3).** `IsolationSpec` is the least-privilege sandbox contract a stdio target must
    run inside — read-only rootfs, no host socket, dropped capabilities, restricted egress, hard
    pids/memory/CPU/wall-clock limits, disposability. It fails closed: `require_isolation` refuses a
    stdio probe under any spec that is not provably locked down. The bytes-on-the-wire runner is
    injected as a `ProbeTransport`, so the policy is testable without real infrastructure.
  - **Kill switch, rate & concurrency, audit (AC5).** `mcp_probe_enabled` (default **false**) is a
    global kill switch that freezes active probing without touching the read-only passive lane.
    Per-tenant concurrency/rate caps are read from the audit table (`apiome.mcp_probe_runs`), so they
    hold across replicas and restarts; per-run request/byte caps are enforced by a counting transport,
    not merely recorded. Every active run and every refusal is audited.
  - **Bridge to trust posture** (`app.mcp_probe_rules`): registers `REQUIRES_PROBE` rules
    (`protocol.proven-auth-bypass`, `protocol.proven-input-injection`) that turn exploited-in-test
    evidence into `proven` posture findings and move `proven_count`. Loaded from the probe side to
    keep the import graph acyclic; skipped-and-reported when no probe evidence exists.
  - **REST** — `GET /v1/mcp/probes/catalog`; `POST|GET|DELETE .../endpoints/{id}/probe-targets`;
    `POST .../versions/{vid}/probe`; `GET .../probe-runs`. **CLI** — `apiome mcp probe-catalog`,
    `probe-target-add`/`probe-target-list`, `probe`, `probe-runs`. See `docs/mcp_probes.md`.

## [1.119.0] - 2026-07-14

### Added
- **MCP source, supply-chain, and trust-posture scans (CLX-3.2, #4856)** — a third MCP scan
  engine (`app.mcp_trust_posture`), separate from the surface lint and the conformance engine for
  the same reason those are separate: it carries its own score and fingerprint, so adding it moves
  neither of the others' persisted scores. It assesses what a server is *built from*.
  - **Explicit source lane.** `apiome.mcp_endpoint_sources` (V172) links an endpoint to the git
    repo / package / image / registry identity it comes from, recording *how the link is known*
    (`provenance`) and *how strongly the artifact is pinned* (`verification_state`) as two
    independent axes. Pin strength is derived from whether the reference actually carries an
    immutable digest — never asserted — and a source with no digest is `unverified`, with its
    findings confidence-downgraded to `medium`. `POST|GET|DELETE .../endpoints/{id}/sources`.
  - **Coordinates-only SBOM.** `apiome.mcp_source_sboms` (V172, write-once) stores a dependency
    inventory as component coordinates only (name / purl / version / license) — never source or
    file content. `app.mcp_sbom` ingests CycloneDX/SPDX and derives from lockfiles.
    `POST .../sources/{sid}/sbom`.
  - **Static inspection with locations** (`app.mcp_static_checks`): unsafe command execution,
    dynamic eval, disabled TLS, permissive CORS, privileged containers, unpinned base images,
    broad OAuth scopes, and Gitleaks-style secret detection that emits a **redacted preview and
    entropy, never the secret**.
  - **Metadata poisoning rules** (`app.mcp_trust_posture_rules`): hidden instructions, invisible
    /bidi characters, exfiltration directives, credential-in-description, unconstrained execution
    parameters, tool-name shadowing, filesystem-root templates, unauthenticated writes, and
    undeclared destructive tools.
  - **Dependency vulnerabilities** (`app.mcp_vulnerability`): OSV lookup **by package coordinate
    only** — no source, manifest, or repository identity ever leaves the process
    (`query_payload_for_audit` makes this checkable). **Off by default**
    (`mcp_vulnerability_scan_enabled`); a disabled or unreachable lookup records `not_run` /
    `unavailable`, never an empty pass.
  - Every rule maps to the **OWASP MCP Top 10** (`app.mcp_owasp`), and the report names the risks
    its evaluated rules do *not* cover so an unmentioned risk never reads as an absent one.
  - **Two honesty guarantees, enforced structurally.** (1) Every finding carries an
    `exploitability`; `make_finding` can only ever produce `static_signal`, and `proven` requires
    probe evidence no rule has — so `proven_count` is 0 until CLX-3.3 (#4857) and the UI cannot
    label a static signal exploitable. (2) A rule whose evidence is absent is *skipped and
    reported*, never a pass; the evidence run is recorded as `partial` coverage.
  - `GET .../versions/{vid}/trust-posture?profile=&failOn=&minScore=&requireFullCoverage=&format=`
    runs and gates a named profile (`mcp-trust-posture` / `mcp-metadata-posture` /
    `mcp-supply-chain`), with SARIF/JUnit output. `GET /v1/mcp/trust-posture/rules` publishes the
    catalog. CLI: `apiome mcp trust-posture`, `apiome mcp trust-posture-rules`,
    `apiome mcp source link|list|retire`.
  - Fills the previously-unassessed `supply_chain` axis (`app.axis_score`), making it gateable
    through the existing policy `axis_gates` with no new gate code — exactly as CLX-3.1 filled
    `protocol`. See `docs/mcp_trust_posture.md`.

## [1.118.0] - 2026-07-14

### Added
- **MCP protocol conformance and agent-readiness rules (CLX-3.1, #4855)** — a new conformance
  engine (`app.mcp_conformance`) that asks the two questions the surface lint cannot: did the
  server *behave* like an MCP server, and can an agent actually use its tools safely?
  - Two rule packs, 22 rules: `app.mcp_conformance_rules` (version negotiation, server identity,
    declared-vs-listed capability cross-check, JSON-RPC id echo, error-code discipline,
    pagination) and `app.mcp_agent_readiness` (descriptions, constrained parameters, output
    schemas, recovery guidance, bounded lists, destructive-operation declaration, annotations,
    naming). Every rule cites the MCP specification revision (`2025-06-18`) it derives from and a
    resolvable source reference.
  - `GET /v1/mcp/{tenant}/endpoints/{id}/versions/{vid}/conformance` runs and **gates** a named
    profile (`mcp-conformance` / `mcp-protocol` / `mcp-agent-readiness`) with `failOn` / `minScore`,
    and can emit SARIF or JUnit through the existing gate serializer. `GET /v1/mcp/conformance/rules`
    publishes the rule catalog with its specification citations.
  - `app.mcp_protocol_transcript` records the JSON-RPC exchanges discovery *already performs* as
    redacted evidence — parameter key names, result shapes and counts, cursor digests, scrubbed
    error text; never wire data, tool arguments, or credentials. Its passive-method allow-list makes
    it structurally impossible to record (and therefore to invoke) a business tool. Transcripts
    persist to `apiome.mcp_protocol_transcripts` (migration **V171**), one immutable row per snapshot.
  - Rules based on the persisted surface are deterministic and recomputable offline; rules needing
    live protocol evidence are **skipped and reported** (`skippedRules`, evidence coverage
    `partial`) when no transcript was captured — an unobserved behaviour never reads as a pass.
  - Conformance writes its own evidence run under scanner id `apiome.mcp-conformance` and fills the
    `protocol` axis, which previously always read "No protocol-conformance scanner evidence yet" —
    so it is gateable via the existing policy `axis_gates` with no new gate code.

### Fixed
- **Policy gates evaluated only the newest scanner's findings** — `_findings_from_evidence_or_report`
  took the single most recent evidence run for a subject, so when several scanners covered it (an
  MCP snapshot is now scanned by both the surface lint and the conformance engine; a catalog
  revision may add Buf or GraphQL ESLint), every other scanner's findings were silently discarded
  and an unwaived error could pass the gate merely because a different scanner ran after the one
  that found it. Policy now evaluates the latest run of *each* scanner.

## [1.117.36] - 2026-07-14

### Added
- **Format lint capability matrix and adapter evidence migration (CLX-2.4, #4854)** —
  published `GET /v1/lint/format-capabilities` classifies every sniffed/importable format as
  native / adapted / unsupported (planned Smithy/RAML/TypeSpec/Avro/OData/API Blueprint/WS-I
  packs stay linked to existing MFI issues). GraphQL ESLint joins the CLX-2.1 adapter SPI
  (`graphql.eslint`); Buf and GraphQL ESLint persist CLX-1.1 evidence; catalog evidence coverage
  is format-aware. Catalog UI **Source-format checks** strip shows which scanners ran.
  OpenAPI **1.0.83**.

## [1.117.35] - 2026-07-14

### Added
- **Independent OpenAPI compatibility evidence (CLX-2.3, #4853)** — `oasdiff`
  adapter on the CLX-2.1 SPI (`ScanMode.BREAKING`); persists breaking / dangerous /
  informational findings plus changelog markdown in CLX-1.1 evidence; REST
  `POST/GET …/compatibility/evidence` emits normalized JSON / SARIF / JUnit gate
  output. Native compatibility merge gates remain unchanged. OpenAPI **1.0.82**.

## [1.117.34] - 2026-07-14

### Added
- **Spectral, Vacuum, and Redocly OpenAPI validation packs (CLX-2.2, #4852)** —
  curated `baseline` / `tenant_guide` / `strict` profiles on the CLX-2.1 adapter SPI;
  Spectral is the parity-selected default bulk runner (compatibility reference); Vacuum
  and Redocly run as secondary adapters with source rule IDs, locations, tool/version, and
  remediation links preserved in CLX-1.1 evidence. Multi-file local `$ref` resolution is
  tested under the no-network sandbox. Style guides gain `externalLintProfile`; discover
  packs via `GET /v1/lint/external-adapters`. OpenAPI **1.0.81**.

## [1.117.33] - 2026-07-14

### Added
- **Sandboxed external-linter adapter framework (CLX-2.1, #4851)** — restricted adapter SPI
  over the MFI-5.x toolchain runner: adapters declare formats, scan modes, and availability;
  commands run under no-network sandbox with bounded I/O/resources and secret-redacted logs;
  shared JSON / JSONL / SARIF parsers preserve source rule IDs and locations; timeout /
  unavailable / malformed / crash map to CLX-1.1 coverage evidence. Buf lint is the first
  real adapter (`buf.lint`); `proto_lint.run_buf_lint` delegates to it. Fixture corpus and
  conformance tests cover a fake tool plus gated real `buf`. OpenAPI **1.0.80**.

## [1.117.32] - 2026-07-14

### Added
- **Versioned policy packs, waivers, and remediation states (CLX-1.3, #4850)** — extend
  style guides into immutable `style_guide_policy_versions` packs (rules + axis gates +
  required coverage + CI outcomes); finding lifecycle / waivers with rationale, expiry,
  actor, and audit events; append-only `lint_policy_evaluations` that keep raw evidence
  separate from policy decisions. New REST surfaces for guide policy settings/versions,
  `GET …/lint/policy`, and `/v1/lint/decisions`. OpenAPI **1.0.79**.

## [1.117.31] - 2026-07-14

### Added
- **Multi-axis score and coverage model (CLX-1.2, #4849)** — versioned
  `clx-axis-v1` evaluations stored in append-only `lint_axis_evaluations` (V168)
  for catalog revisions and MCP endpoint versions. Axes expose score/grade,
  severity counts, coverage, weight, and explicit not-assessed reasons; quality
  remains the backwards-compatible legacy axis; composite is published only when
  required coverage (quality) is present. New `GET …/lint/axes` routes and
  optional axis fields on lint report responses. OpenAPI **1.0.78**.

## [1.117.30] - 2026-07-14

### Added
- **Revision-scoped lint evidence contract (CLX-1.1, #4848)** — immutable,
  append-only `lint_evidence_runs` substrate (V167) shared by catalog revisions
  and MCP endpoint versions: scanner/adapter provenance, execution profile,
  outcome (`passed`/`findings`/`not_run`/`unavailable`/`failed`/`blocked_by_policy`),
  input/source and redacted-config fingerprints, raw-artifact reference,
  source-neutral normalized finding envelope, and coverage. Native reports are
  mirrored into evidence at score-capture time without changing existing lint
  responses; the migration backfill preserves existing report fingerprints.
  New `GET …/lint/evidence` routes for schema revisions and MCP endpoint
  versions expose provenance and per-scanner coverage where a never-run scanner
  reads `not_run`, never clean. OpenAPI **1.0.77**.

## [1.117.29] - 2026-07-14

### Added
- **Tenant MCP policy change history (MTG-5.2, #4786)** — append-only
  `tenant_mcp_policy_changes` ledger written on non-noop admin
  `PUT …/mcp-policy`; `GET /v1/tenants/{slug}/mcp-policy/history` returns
  newest-first who/when/before/after tool-enablement snapshots. OpenAPI **1.0.76**.

## [1.117.28] - 2026-07-14

### Added
- **MCP capability profiles / presets (MTG-5.1, #4785)** — documented toolset
  matrices (`catalog_only`, `search_catalog`, `full_read`) in
  `app.mcp_capability_presets` / `docs/MCP_CAPABILITY_PRESETS.md`, exposed as
  `GET /api-keys/mcp-capability-presets` for Tenants draft policy packs.
  OpenAPI **1.0.75**.

## [1.117.27] - 2026-07-14

### Added
- **OpenAPI version bump & MTG governance contract tests (MTG-3.5, #4779)** —
  OpenAPI **1.0.74** closes the MTG EPIC-3 REST release train; CI snapshots lock
  tenant mcp-policy and per-key capability component schemas plus path/method
  presence for the governance surface.

## [1.117.26] - 2026-07-14

### Added
- **Admin authorization & read models for MCP governance (MTG-3.4, #4778)** —
  shared `require_tenant_admin_session` rejects `auth_method=api_key` on
  mutation routes (even when the key’s `created_by` is a tenant admin) while
  member JWT sessions may still `GET` the policy read model. Wired into
  mcp-policy and mcp-keys. OpenAPI **1.0.73**.

## [1.117.25] - 2026-07-14

### Added
- **Per-key MCP capability update API (MTG-3.3, #4777)** — tenant-admin
  `PUT /v1/tenants/{tenant_slug}/mcp-keys/{key_id}/capabilities` with
  `{ mode: inherit|explicit, enabled_tools?: string[] }` (inherit clears the
  explicit list; explicit must be ⊆ tenant ceiling → 422 with
  `offending_tool_ids`) plus `POST …/capabilities/preview` that returns the
  effective enable-set via the shared MTG-1.4 resolver. Key metadata responses
  now include `enabled_tools`. OpenAPI **1.0.72**.

## [1.117.24] - 2026-07-14

### Added
- **MCP API key REST management (MTG-3.2, #4776)** — tenant-admin lifecycle over
  `apiome.mcp_api_keys`: `GET`/`POST /v1/tenants/{tenant_slug}/mcp-keys` and
  `GET`/`PATCH`/`DELETE …/mcp-keys/{key_id}`. Create returns plaintext `secret`
  once; list/get never include secret or hash; revoke soft-sets `revoked_at`.
  Capability grant writes remain MTG-3.3. OpenAPI **1.0.71**.

## [1.117.23] - 2026-07-14

### Added
- **Tenant MCP policy CRUD (MTG-3.1, #4775)** — `GET`/`PUT
  /v1/tenants/{tenant_slug}/mcp-policy` for ceiling, default enable-set, and
  anonymous flags. Member GET; tenant-admin PUT; unknown tool ids and
  default-not-subset-ceiling yield 422. OpenAPI **1.0.70**.

## [1.117.22] - 2026-07-14

### Added
- **Anonymous MCP call policy resolver (MTG-2.3, #4772)** — extends
  `app.mcp_effective_policy` with `allow_anonymous_mcp` / `anonymous_enabled`
  snapshot fields plus `resolve_tool_anonymous` /
  `is_tool_anonymously_allowed` / `tool_in_anonymous_enable_set`. Authenticated
  key resolution unchanged. OpenAPI **1.0.69**.

## [1.117.21] - 2026-07-14

### Added
- **MCP governance upgrade regression (MTG-1.5, #4769)** — pytest proving a
  pre-migration shaped key (`capability_mode=inherit`) plus post-seed tenant
  (`default_mode=all`, empty tool rows) enables every MTG-1.1 registry tool.
  Pair with apiome-db V163 tenant/key backfill; no OpenAPI surface change.

## [1.117.20] - 2026-07-14

### Added
- **MCP effective policy resolver (MTG-1.4, #4768)** — pure
  `app.mcp_effective_policy` shared by MCP call gates and REST “preview
  effective”: `registry ∩ ceiling ∩ (inherit defaults | explicit key tools)`.
  Documents tenant `default_mode` / legacy unseeded semantics; mcp package
  re-exports the same helpers.

## [1.117.19] - 2026-07-13

### Added
- **MCP tool & toolset registry (MTG-1.1, #4765)** — shared catalog of every Apiome MCP
  tool id, description, and toolset (`health`, `catalog`, `search`, `document`, `structure`),
  including governance capability ids `spec.mcp` / `spec.catalog`. Exposed as
  `GET /api-keys/mcp-tools` for CLI and Control Panel enumeration. OpenAPI **1.0.68**.

## [1.117.2] - 2026-07-11

### Added
- **Publish gate UX for style-guide violations (#4437, GOV-2.5)** — error-severity guide
  violations now block `POST …/publish` with HTTP 422 (same pattern as the description gate).
  `skipPublishChecks` requires a non-empty `forcePublishReason`, recorded to
  `workflow_audit` as `version.publish_checks_override`. Warn/info violations do not block.

## [1.115.0] - 2026-07-11

### Added
- **Style-guide engine integration & score mapping (#4430, GOV-1.4)** — assigned style guides
  (GOV-1.1–1.3) now have runtime effect: every lint entry point (editor lint, catalog lint,
  import scoring, conversion scoring, publish precheck) resolves and applies the governing
  guide. See `docs/guide/lint-and-quality.md`.
  - New module `app.style_guide_engine`: resolves the guide **project → tenant → default**,
    compiles rule rows (enable/disable, severity overrides, GOV-1.3 custom rules) into a
    content-hash-cached `CompiledStyleGuide`, and re-scores engine results through the shared
    severity-weighted formula (`error` ≫ `warning` ≫ `info`, per-rule capped). Under the
    default guide, scores/grades/fingerprints are byte-identical to the pre-guide engine —
    pinned by a new grade-stability regression corpus. Findings from rules outside the GOV-1.2
    registry (external-tool extras) pass through ungoverned. Resolution is strictly
    best-effort: any fault degrades to the in-code "Apiome Recommended" defaults.
  - New `db` accessors `get_assigned_style_guide` (single-query precedence chain, tenant-scoped)
    and `get_style_guide_rules` (V159 rows for compilation).
  - `GET …/lint` responses now report the applied guide (`guideId` / `guideName` /
    `guideSource`).
  - Publish prechecks compute the guide's error-level violation count and return it on a new
    `PublishPrecheckOutcome` — the signal the GOV-2.5 publish gate will enforce (advisory for
    now; a lint fault never blocks publishing).

## [1.114.0] - 2026-07-11

### Added
- **Custom rule DSL, Spectral-compatible subset (#4429, GOV-1.3)** — tenants can author custom
  lint rules in YAML (`rules.<id>: {description, severity, given, then}`) with the core
  functions `pattern`, `casing`, `enumeration`, `truthy`, `defined`, `undefined`, and `length`.
  See `docs/guide/custom-rules.md`. JS-function rules remain out of scope (v2).
  - New module `app.custom_rule_dsl`: strict validation with pointer-carrying errors
    (`rules.my-rule.then.functionOptions.match`), duplicate-key rejection, and cardinality caps;
    `validate_custom_definition` re-validates `style_guide_rules.custom_def` values (GOV-1.1).
  - New route `POST /v1/lint/custom-rules/validate`: echoes the parsed rules on success; a
    malformed guide returns HTTP 422 whose detail carries a `message` and a `pointer` to the
    offending YAML node. Custom ids may not shadow built-in rule ids (GOV-1.2).
  - Sandboxed evaluation engine for GOV-1.4: user regexes run under a hard `regex`-engine
    timeout (no catastrophic backtracking), JSONPath evaluation spends from a bounded per-rule
    node budget (adversarial `$..*..*..*` aborts deterministically), and `[*]` follows Spectral
    object-property semantics so `$.paths[*][*]` selects operations with real key paths.

## [1.113.0] - 2026-07-11

### Added
- **Built-in lint-rule catalog registry (#4428, GOV-1.2)** — every built-in lint rule now has one
  durable descriptor: a stable id (the exact string findings carry in `rule`), its pack, category,
  default severity, one-line rationale, and a docs anchor into the new rule reference page
  (`docs/guide/lint-rules.md`, generated by `scripts/generate_lint_rule_docs.py`).
  - New module `app.lint_rule_registry` aggregates the OpenAPI spec-linter catalogue (now enriched
    with rationales), the cross-format common pack, and every registered format pack (AsyncAPI,
    GraphQL, protobuf, Arazzo) — derived from the live engines so the registry cannot drift.
  - New route `GET /v1/lint/rules`: returns the full catalog, sorted by rule id, so style guides
    (GOV-1.1/GOV-1.4) and UIs can enable/disable and document rules by id. Shipped rule ids are
    intentionally unchanged — they are hashed into finding ids and report fingerprints, so captured
    scores stay valid on upgrade.

## [1.108.0] - 2026-07-07

### Added
- **Duplicate / near-duplicate detection (#4664, V2-MCP-36.1 / MCAT-22.1)** — advisory review list
  for catalog endpoints that likely describe the same MCP server.
  - New route `GET /v1/mcp/{tenant_slug}/data-quality/duplicates`: groups tenant endpoints sharing a
    normalized `endpoint_url`, the same network host (when fingerprints do not prove distinct
    servers), or an identical current `surface_fingerprint`. Published endpoints in other tenants
    that match the same keys are returned as cross-tenant hints. Nothing is auto-merged.

## [1.107.0] - 2026-07-07

### Added
- **Capability directory (#4663, V2-MCP-35.4 / MCAT-21.4)** — browsable, paginated index of every live
  tool/resource/prompt across the caller's catalog.
  - New route `GET /v1/mcp/{tenant_slug}/capabilities`: lists capability items from each endpoint's
    current snapshot with owning-server context (links back without a second read). Filter by name
    substring, capability type, endpoint id, host, category, grade, and visibility; sort by server,
    name, or type. Tenant scoping matches every other catalog route.

## [1.105.0] - 2026-07-07

### Added
- **Cross-server capability search (#4661, V2-MCP-35.2 / MCAT-21.2)** — find capabilities ("who
  offers a geocoding tool?") across the tenant catalog with keyword + semantic matches grouped by
  owning server.
  - New route `GET /v1/mcp/{tenant_slug}/capabilities/search`: merges V127 FTS hits with optional
    V149 per-item pgvector nearest-neighbour matches (when
    `APIOME_MCP_SIMILARITY_EMBEDDINGS_ENABLED` is on). Each capability carries `match_source`
    (`keyword` / `semantic` / `both`) and a documented relevance→grade ranking (MCAT-9.7).
    Results paginate at the server-group level; visibility and composable host/category/grade
    filters match the flat search route. Empty queries and no-match queries return `groups: []`.
  - DB: `search_mcp_capability_items_semantic`, `store_mcp_capability_item_embedding`; V149 adds
    optional `mcp_capability_items.embedding vector(2000)` with a partial cosine-HNSW index
    (apiome-db 0.30.0).
  - Pure aggregation: `merge_cross_server_capability_hits`, `group_cross_server_capability_hits`,
    `build_capability_item_embedding_text`.

## [1.104.0] - 2026-07-07

### Added
- **Faceted catalog search (#4660, V2-MCP-35.1 / MCAT-21.1)** — the catalog's rich metrics become
  queryable facets: filter and aggregate endpoints by grade band, transport, category, safety
  posture, complexity band, protocol version, and discovery health, with live facet counts.
  - New route `GET /v1/mcp/{tenant_slug}/facets`: repeatable per-dimension filter params with
    multi-facet **AND** / within-facet **OR** semantics, plus `visibility` and `limit`/`offset`
    paging. The response carries the matching endpoint page (browse-shaped rows) and per-dimension
    `{label, count}` buckets aggregated over the *same filtered set*, so counts are always live.
    Every bucket label — including the NULL-bucket sentinels `ungraded` / `uncategorized` /
    `unknown` — is itself a valid filter value; an invalid vocabulary value is a `422`, and an
    empty match returns an empty page with zeroed counts. Tenant-scoped from the token like every
    catalog route.
  - New pure module `app.mcp_facets`: the facet vocabulary (grades, transports, safety postures,
    complexity bands, health labels, sentinels), the complexity banding thresholds shared with the
    SQL mirror, and request-side normalization (`normalize_catalog_facet_filters`).
  - DB layer: composable facet WHERE-clause builder plus derived-facet SQL expressions — health
    (the inventory `derive_health` precedence in SQL), safety posture from strict-boolean
    `destructiveHint` / `readOnlyHint` annotations, and a complexity band over each surface's
    busiest tool's top-level `input_schema` property count. No migration: every facet derives from
    existing columns/JSONB.
  - Browse enrichment: browse rows (and `McpBrowseEndpointOut`) now carry `protocol_version`,
    `health`, `has_destructive`, `read_only_only`, and `complexity_band`, so the catalog grid
    facets on every dimension without a second read.

## [1.103.0] - 2026-07-07

### Added
- **Provenance & discovery-source tracking (#4659, V2-MCP-34.5 / MCAT-20.5)** — the catalog now
  records and surfaces *how it knows things*: how each endpoint was added and which discovery run
  (manual / sweep / registry) produced each version snapshot.
  - Discovery persistence stamps provenance at write time: `record_mcp_discovery_version` stores
    the producing job's `trigger` and id on the new `mcp_endpoint_versions.discovery_trigger` /
    `discovery_job_id` columns (V148), threaded from the running job row by the discovery engine.
    Endpoint reads carry the new `mcp_endpoints.added_via` column.
  - New pure module `app.mcp_provenance`: `build_endpoint_provenance` deterministically assembles
    the full picture — how the endpoint was added, first/last discovery, per-version origins
    (newest-first, capped with overflow counted), per-origin version counts, and completed-run
    tallies per trigger. A snapshot with no attributable run reads **`unrecorded`**, never any
    concrete origin, and the assembly handles `registry` alongside the two implemented triggers.
  - Wire models: `McpEndpointOut.added_via`; `McpEndpointVersionSummary.discovery_trigger` /
    `discovery_job_id` on the version list/detail reads.
  - The report card (MCAT-19.1) gains a **Provenance** section (identity-adjacent): added-via,
    the current snapshot's origin, completed-run tallies, and a per-version origin table in both
    Markdown and HTML — present even for a never-discovered endpoint (how it was added is a fact
    from registration).
  - The catalog inventory export (MCAT-19.2) gains `added_via` and `current_version_origin`
    columns (CSV + JSON), with `unrecorded` distinguished from never-discovered (empty).
  - New `Database.list_mcp_discovery_trigger_stats` per-trigger job tallies for the provenance
    assembly.

## [1.102.0] - 2026-07-07

### Added
- **Deprecation & lifecycle signal detection (#4658, V2-MCP-34.4 / MCAT-20.4)** — servers mark
  tools "deprecated"/"experimental"/"beta" informally in descriptions, annotations, and naming;
  the catalog now aggregates those markers per capability.
  - New pure module `app.mcp_lifecycle_signals`: a deterministic detector
    (`assess_capability_lifecycle` per item, `detect_lifecycle_signals` per snapshot) over each
    capability's **annotations** (boolean flags like `deprecated: true`, status keys like
    `stability: "beta"`), **name/title tokens** (whole tokens only — `search_beta` counts,
    `alphabet` never does), and **description phrases** (a curated table; verb-like bare words
    such as "preview"/"sunset" are deliberately excluded so "previews a document" is not a
    signal). Each capability rolls up to a single stage (deprecated > experimental > beta >
    stable), signals carry stable ids, sources, verbatim matches, and bounded excerpts, and all
    itemization is capped with overflow counted, never silently dropped. Pure: no DB, no network.
  - **No signal is never a "stable" claim** (the AC's wording): an unmarked capability's stage is
    `unspecified`, the aggregate absence statement carries an explicit disclaimer, and `stable`
    is reported **only** when an annotation explicitly declares it.
  - The capability-list API (`GET …/versions/{id}`) now serializes a `lifecycle` block on every
    item — computed on the fly from the item's own stored fields, no persistence — so the UI can
    render per-capability badges.
  - The report card (MCAT-19.1) gains a **Lifecycle Signals** section: the export route runs the
    detector over the reported snapshot's capability items and `build_report_card` shapes it via
    the new optional `lifecycle_signals` input; both renderers itemize flagged capabilities with
    stage labels and per-signal summaries, with "Not scanned" reserved for a never-discovered
    endpoint.

## [1.101.0] - 2026-07-07

### Added
- **License & terms signal detection (#4657, V2-MCP-34.3 / MCAT-20.3)** — whether a server may be
  used, and under what terms, is often buried in its `instructions` text; the report card now
  surfaces it as informational findings.
  - New pure module `app.mcp_license_signals`: a deterministic detector
    (`detect_license_signals`) that scans a snapshot's advertised text — `instructions`, the
    server title, and the validated branding `website_url` — for **SPDX license identifiers**
    (curated common ids; short collision-prone ids like `MIT` matched case-sensitively so German
    "mit" never reads as a license), **license/terms/usage-restriction phrases** ("licensed
    under", "terms of service", "non-commercial", …), and **license/terms-pointing URLs** (an
    ordinary link is not a signal). Signals carry a stable id, the source, the verbatim match,
    and a bounded context excerpt; scanning and itemization are bounded
    (`MAX_SCANNED_CHARS`/`MAX_SIGNALS`) with overflow stated, never silently dropped.
  - **Informational only, no enforcement** — a signal means "the text mentions this", never
    "this is the server's license"; nothing gates cataloging or invocation. When nothing matches,
    the status is **`not_stated`** with a pre-worded statement that explicitly disclaims any "no
    license" verdict (the AC's "absence reported as 'not stated'"), and the report names which
    sources were actually scanned so "nothing to scan" reads differently from "nothing found".
  - The report card (MCAT-19.1) gains a **License & Terms** section: the export route runs the
    detector over the reported snapshot (no persistence — computed on the fly, per the pure/
    informational scope) and `build_report_card` shapes it via the new optional
    `license_signals` input; both the Markdown and HTML renderers itemize the signals and render
    the careful "not stated" wording, with "Not scanned" reserved for a never-discovered endpoint.

## [1.100.0] - 2026-07-07

### Added
- **Server branding capture (#4656, V2-MCP-34.2 / MCAT-20.2)** — a text-only catalog card can now
  show a server's advertised logo and website, making it far more recognizable, while a server that
  advertises nothing falls back unchanged.
  - New pure module `app.mcp_client.branding`: turns the verbatim `serverInfo` branding
    (`websiteUrl` + `icons[]`, now parsed onto `ServerInfo`) into a small, storage-ready
    `ServerBranding` — a website URL and the first usable display icon (with its MIME type). Every
    URL is validated first: **`https`-only** (plaintext, `data:`/`file:` and other schemes dropped),
    host must **not** be a private/non-globally-routable IP literal (the transport's SSRF class, via
    `resilience.private_address_reason`), and length-bounded. Any value failing a guard is omitted.
  - Assets are **referenced, never fetched or executed** server-side (the card renders the icon as an
    `<img>` with `referrer-policy: no-referrer` and the site as a `nofollow` link) — the acceptance
    criteria's "fetched within guards or omitted".
  - `DiscoverySurface.to_version_row` persists the validated branding to a new
    `apiome.mcp_endpoint_versions.server_branding` (JSONB) column (apiome-db **V147**). It is
    **descriptive metadata on the immutable snapshot and deliberately excluded from the surface
    fingerprint**, so a purely cosmetic rebrand never mints a spurious version and existing
    fingerprints are unchanged (no re-snapshot churn); branding is captured whenever a real surface
    change mints a snapshot.
  - Surfaced on `McpEndpointVersionSummary`/`Detail` (`server_branding` → `McpServerBranding`) and on
    the browse projection `McpBrowseEndpointOut`, so both the identity card and the catalog card can
    render a logo/site.

## [1.99.0] - 2026-07-07

### Added
- **Host & transport metadata capture (#4655, V2-MCP-34.1 / MCAT-20.1)** — the catalog now records
  what it can learn about the *service* hosting a server, not just its capability surface. During the
  discovery handshake — **reusing the connection it already opens, no extra calls** — the client
  observes non-invasive transport facts and persists them as the endpoint's latest observation.
  - New pure module `app.mcp_client.transport_meta`: extracts host/port/scheme, a TLS certificate
    summary (issuer, validity window, subject CN, DNS SANs, serial) from the negotiated session's
    peer certificate, negotiated TLS protocol/cipher, an allow-list of notable response headers
    (`server`, rate-limit hints, HSTS, `via`, `x-powered-by`), and connect/handshake timing.
  - `StreamableHttpTransport` observes the first response (the `initialize` handshake) once into
    `observed_transport`; `app.mcp_discovery_engine` threads it through and refreshes it on the
    endpoint on **every** successful run (changed or unchanged), since the facts are volatile.
  - Persisted to `apiome.mcp_endpoints.transport_metadata` (JSONB) + `transport_metadata_at`
    (apiome-db **V146**) — on the mutable endpoint, not the immutable version snapshot, so it never
    feeds the surface fingerprint. Surfaced on `McpEndpointOut` for the identity card / report.
  - **Best-effort and never fatal:** a plain-`http` endpoint, a missing/invalid/unparseable
    certificate, an absent network stream, or a persistence error all degrade to empty fields /
    a skipped write rather than failing discovery. Existing SSRF/transport-security guards are
    unchanged (no new connections are made).

## [1.98.0] - 2026-07-07

### Added
- **Scheduled catalog digest reports (#4654, V2-MCP-33.5 / MCAT-19.5)** — an opt-in, per-tenant
  recurring "here's your catalog this window" delivered without opening the app. A background sweep
  (`app.mcp_catalog_digest_sweep`) is wired into `app.main` on the `APIOME_MCP_DIGEST_MIN_INTERVAL`
  floor (default 300s), mirroring the RAR-3.2 refresh and MCAT-5.1 discovery sweeps, with a global
  `APIOME_MCP_DIGEST_ENABLED` kill switch.
  - New table `apiome.mcp_catalog_digest_configs` (apiome-db V145): per-tenant `enabled` (opt-in,
    **default off**), `cadence_seconds` (NULL = the global `APIOME_MCP_DIGEST_DEFAULT_CADENCE`,
    default weekly), `send_empty` (empty-window policy) and `last_digest_at` (window/cadence anchor).
  - Due-selection (`Database.list_due_mcp_catalog_digests`) computes each due tenant's window bounds
    in one DB `now()` (no clock skew); the window is `(last_digest_at, now]`, bounded to one cadence
    back on the first send. Each tenant is serialized behind a per-tenant advisory lock (single-flight)
    and its anchor advances every tick — success, empty-skip, or failure — so a broken tenant cannot
    monopolize the sweep.
  - The digest compiles from **real window data**, tenant-scoped: new endpoints, all changes, grade
    movements (a `LAG`-over-`version_seq` comparison of `mcp_version_scores.grade`), and
    discovery-health problems (MCAT-5.3 quarantine / consecutive-failure signals). The **pure**
    `app.mcp_catalog_digest` compiler classifies breaking changes with the same
    `mcp_change_severity.classify_change` the change feed uses.
  - **Empty window sends nothing** unless the tenant set `send_empty` (then an explicit "no changes"
    digest). Delivery reuses the RAR-5.4 push-webhook fan-out, tagged `mcp.catalog.digest`; the
    payload carries only catalog identity/activity (never an `endpoint_url` or credential).
  - New tenant-scoped routes: `GET`/`PUT /v1/mcp/{tenant}/digest/config` (manage opt-in/cadence/
    empty-window policy) and `POST /v1/mcp/{tenant}/digest/preview` (compile the current window
    without sending). Every route scopes by the token tenant, not the URL slug.
  - New settings: `APIOME_MCP_DIGEST_ENABLED`, `APIOME_MCP_DIGEST_DEFAULT_CADENCE`,
    `APIOME_MCP_DIGEST_MIN_INTERVAL`.

## [1.97.0] - 2026-07-07

### Added
- **Catalog change feed (#4653, V2-MCP-33.4 / MCAT-19.4)** — subscribable **RSS / Atom / JSON Feed**
  so people tracking a server (or a whole published catalog) are *told* what changed without polling
  the UI. A read-only projection over `mcp_endpoint_versions` + `mcp_version_changes`.
  - Two new **anonymous** routes: `GET /mcp/feed/{tenant}/{slug}?format=rss|atom|json` (one endpoint's
    change history) and `GET /mcp/feed/{tenant}?format=…` (the whole published catalog's history).
    `format` defaults to `rss`; an unrecognized value is a `400`. Entries emit added / removed /
    modified changes, newest snapshot first.
  - **Breaking changes are flagged.** Each entry's severity comes from the same
    `app.mcp_change_severity.classify_change` the churn timeline and evolution series use; a breaking
    change carries a `breaking` category/tag *and* a `[breaking]` title suffix, so even a title-only
    reader surfaces it.
  - **Private endpoints excluded; never a data leak.** The endpoint feed resolves its subject through
    the same public gate the `mcp_v_public_endpoints` view enforces (`Database.get_public_mcp_endpoint_feed_head`:
    tenant live, endpoint not deleted, enabled, published, public-visible); an unpublished / private /
    unknown target renders an identical **empty** feed with a `200` — never a `404` — so existence is
    never disclosed and a private endpoint's changes never appear. The catalog feed
    (`Database.get_public_catalog_changes`) enforces the same predicate in SQL. No credential (the raw
    `endpoint_url`) is ever read.
  - **Cacheable.** A content-addressed `ETag` (a hash of the rendered feed) and a `public, max-age=300`
    `Cache-Control`; a matching `If-None-Match` yields `304 Not Modified`, so a polling reader pays
    almost nothing until the catalog moves.
  - Rendering is a pure, database-free layer (`app.mcp_change_feed`): deterministic, XML built with
    `ElementTree` (escaping hostile server-reported names), and validated as `rss20` / `atom10`.

## [1.96.0] - 2026-07-07

### Added
- **Embeddable status badges (#4652, V2-MCP-33.3 / MCAT-19.3)** — a public, cacheable **SVG badge**
  a server author can drop into a README to advertise the catalog's assessment of a **published**
  endpoint (like a CI badge).
  - New **anonymous** route `GET /mcp/badge/{tenant}/{slug}.svg?metric=grade|health|version&theme=light|dark`
    renders a shields-style flat badge. `metric` selects the signal — `grade` (A–F lint grade),
    `health` (the derived operational label), or `version` (the server-reported version); `theme`
    selects the light/dark **label variant**. Unrecognized `metric`/`theme` values normalize to
    `grade`/`light` so a badge URL always renders.
  - **Never a data leak.** The endpoint is resolved through the same public gate the
    `mcp_v_public_endpoints` view enforces (`Database.get_published_mcp_endpoint_badge`: tenant live,
    endpoint not deleted, enabled, published, public-visible). An unpublished, private, or unknown
    target renders the neutral `unknown` badge with a `200` — never a `404` — so the response never
    discloses whether such an endpoint exists. No credential (the raw `endpoint_url`) is ever read.
  - **Cacheable.** A content-addressed `ETag` (a hash of the rendered SVG) and a `public, max-age`
    `Cache-Control` (300s for a resolved badge, 60s for `unknown` so a freshly published endpoint's
    real badge appears promptly). A matching `If-None-Match` yields `304 Not Modified`.
  - Rendering is a pure, database-free layer (`app.mcp_badge`): deterministic, XML-escaped against
    hostile server-reported values, and self-contained (no external fonts or images).

## [1.95.0] - 2026-07-07

### Added
- **Catalog inventory export (#4651, V2-MCP-33.2 / MCAT-19.2)** — a tenant-scoped CSV / JSON export
  of the whole MCP catalog as data (for a spreadsheet or a notebook), not the browse UI.
  - New route `GET /v1/mcp/{tenant_slug}/endpoints:export?format=csv|json&scope=all|public` streams
    one flat row per cataloged endpoint: id, name, host, transport, category, visibility, published
    flag, current grade/score, per-kind capability counts (tools/resources/resource templates/
    prompts) and their total, last discovery status/time, and a derived **health** label
    (`healthy` / `failing` / `undiscovered` / `disabled` / `quarantined`).
  - **Streamed for large catalogs.** The catalog is walked one bounded **keyset page** at a time
    (`Database.list_mcp_endpoints_export_page`, ordered by primary key) and serialized incrementally
    by the pure `app.mcp_catalog_inventory` layer, so a large catalog exports without ever holding
    every row in memory. CSV is written through the stdlib `csv` writer (**RFC-4180 escaping**);
    JSON is a streamed `{success, tenant_slug, scope, generated_at, endpoints[], count}` wrapper.
  - **Visibility respected.** Scoping comes from the validated token's tenant — never the URL slug —
    so the export only ever contains the caller's own catalog. `scope=public` restricts to published
    endpoints (the published-only variant). **Only each endpoint's host is exported** (via
    `urlparse().hostname`, which strips any embedded `user:pass@` credential and port) — the stored
    URL never appears in the output.
  - The action-style `:export` path (matching the repo's `imports:batch` / `:manifest` convention)
    avoids colliding with the `endpoints/{endpoint_id}` route.

## [1.94.0] - 2026-07-07

### Added
- **Server report-card export (#4650, V2-MCP-33.1 / MCAT-19.1)** — a shareable one-page report for
  an endpoint version, serializing the in-app Insight assessment (identity, grade + score breakdown,
  capability surface, safety posture, documentation coverage, composite trust radar, and the
  change-since-previous summary) into Markdown or HTML.
  - New route `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/report?format=markdown|html[&version_id=]`
    returns the rendered document as a downloadable attachment. It **reuses** the metrics the Insight
    endpoints already compute (`app.mcp_surface_metrics`, `app.mcp_insight_aggregation`, the persisted
    `mcp_version_scores.report` and `mcp_version_changes`) — no new computation.
  - New pure module `app.mcp_report_card` assembles a deterministic `ReportCard` view model and
    renders Markdown / self-contained HTML (the HTML embeds an `@media print` stylesheet, so **PDF is
    the browser's print-to-PDF of the same document** — the ticket's "PDF via the same HTML").
  - Visibility is honoured by the standard token-tenant scoping (a private/cross-tenant endpoint is
    `404`); a **never-discovered or never-scored** endpoint yields a graceful *partial* report rather
    than an error; and **no credential secret is ever emitted** — only the auth *posture* and
    `auth_type` label reach the report.

## [1.85.0] - 2026-07-07

### Added
- **Breaking-change classification (#4638, V2-MCP-30.3 / MCAT-16.3)** — a pure, deterministic
  classifier `app.mcp_change_severity.classify_change(change)` that assigns each surface change
  (an `mcp_version_changes` row, or the equivalent diff-engine dict) one of three severities:
  - `breaking` — a removed capability, or a modification that adds a required parameter, removes a
    parameter, narrows an enum, or changes a type (a client aligned to the *before* surface breaks);
  - `additive` — a new capability, a new optional parameter, a loosened constraint, or a purely
    descriptive (title/description) edit;
  - `review` — a real change whose impact is not deterministically decidable (annotation flip,
    resource URI/`mimeType` move, reshaped schema keyword, protocol/capabilities shift, or a schema
    that appeared/vanished/arrived in an unexpected shape) — unknown/edge shapes land here rather
    than being silently called additive.
  JSON-Schema comparison is delegated to a new shared `app.schema_compatibility.classify_schema_change`
  helper, so the MCP and OpenAPI surfaces judge "breaking" the same way; prompt `arguments` are judged
  param-style. A companion `severity_counts(changes)` rolls a collection up.
- **Severity surfaced on the API** — every `McpVersionChangeOut` (the version-changes and on-demand
  compare endpoints) now carries a `severity`, and each `insight/evolution` point carries a
  `severity_counts` (`breaking`/`additive`/`review`/`total`) classifying the churn that snapshot
  introduced — the breaking-change markers the churn timeline (16.1) and grade/surface trend (16.4)
  overlay. Computed on read from the persisted change `detail`, so no migration/backfill is needed.

## [1.84.0] - 2026-07-06

### Added
- **Capability relationship graph (#4632, V2-MCP-29.2 / MCAT-15.2)** — a pure, deterministic
  edge-inference helper `app.mcp_capability_graph.compute_capability_graph(surface)` that turns a
  normalized `DiscoverySurface` into a node-link graph: one node per capability (tool / resource /
  resource template / prompt) plus edges emitted only on concrete signals (precision over recall):
  - **prompt → tool** — a prompt whose text (description or argument names/descriptions) names a
    tool's exact identifier as a whole token;
  - **tool → resource** — a tool whose description or `uri`-shaped input-schema parameter literals
    contain a resource's concrete `uri` (or a resource template's literal URI prefix) verbatim;
  - **shared type** (undirected) — two items whose `input_schema`/`output_schema` share a `$ref`
    target or a non-generic schema `title`.

  Isolated (unconnected) nodes are always returned. Exposed read-only at
  `GET /v1/mcp/{tenant_slug}/endpoints/{id}/insight/graph?version_id=` (defaults to the endpoint's
  current surface), mirroring the 14.2 `insight/*` routes' tenant-scoped `404` behaviour. Unit-tested
  in `tests/test_mcp_capability_graph.py` and `tests/test_mcp_insight_routes.py`.

## [1.83.0] - 2026-07-06

### Added
- **Insight aggregation REST endpoints (#4628, V2-MCP-28.2)** — read-only, pre-aggregated,
  cache-friendly series over an endpoint's discovery/invocation history so the browser never runs
  N queries per panel nor holds raw item rows. Four new tenant-scoped routes on the MCP catalog
  router:
  - `GET /v1/mcp/{tenant_slug}/endpoints/{id}/insight/surface?version_id=` — the deterministic
    `app.mcp_surface_metrics` (28.1) roll-up for a snapshot (defaults to the endpoint's current
    surface): per-type counts, per-tool `input_schema` complexity, annotation and documentation
    coverage.
  - `GET …/insight/evolution` — the per-version time series (oldest first): capability counts,
    quality score/grade, and the churn (added/removed/modified) each snapshot introduced.
  - `GET …/insight/reliability` — discovery-job success rate + run-latency stats from
    `mcp_discovery_jobs`, and test-invocation error rate + latency percentiles (p50/p95/p99) from
    `mcp_test_invocations`.
  - `GET /v1/mcp/{tenant_slug}/insight/catalog` — a tenant-wide roll-up (endpoint/published/
    discovered counts, per-kind capability totals, average score, A-F grade distribution) that
    feeds 18.1.

  New pure module `app.mcp_insight_aggregation` holds the roll-up math — a faithful Python port of
  PostgreSQL's continuous `percentile_cont`, latency statistics, and the discovery/invocation
  reliability aggregators — so percentiles are unit-testable against a hand-computed fixture and the
  route and its tests share one source of truth. New `Database` reads
  (`get_mcp_evolution_series`, `list_mcp_discovery_job_stats`, `list_mcp_invocation_stats`,
  `get_mcp_catalog_insight`) fetch the minimal tenant-scoped rows each series aggregates. Every
  route respects tenant scoping (a cross-tenant id reads as `404`) and returns an empty/zero series
  (never a `500`) for an endpoint with no history. New Pydantic response models under
  `McpInsight*`. Feeds the 15–22 visualization panels.

## [1.82.0] - 2026-07-06

### Added
- **Capability-surface metrics service (#4627, V2-MCP-28.1)** — a pure, deterministic metrics
  layer over a discovered MCP surface so every insight panel reads one canonical set of derived
  numbers instead of recomputing them ad-hoc. New `app.mcp_surface_metrics.compute_surface_metrics(
  surface) → SurfaceMetrics` walks a normalized `DiscoverySurface` and returns per-type item
  counts; per-tool `input_schema` complexity (top-level property / required / optional counts,
  documented-parameter count, max nesting depth, and `enum`/`oneOf` usage); the count of tools
  declaring an `outputSchema`; behavioural-annotation coverage (how many tools assert
  `readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint`); and documentation coverage
  (% of items with a `description`, % with a `title`, % of tool parameters documented). The
  schema walk is total — nested objects, unresolved `$ref` nodes, `array` items/tuple validation,
  and `oneOf`/`anyOf`/`allOf` branches are handled, with a `MAX_SCHEMA_DEPTH` budget capping
  runaway recursion. Output is deterministic and carries a stable `metrics_fingerprint`, so the
  result is cacheable per `surface_fingerprint`. Mirrors the pure-function style of
  `app.schema_lint` / `app.mcp_lint` / `app.mcp_score`; no I/O, no DB, no network. Feeds the
  MCAT-14.2 insight aggregation endpoints and the 15–22 visualization panels.

## [1.80.0] - 2026-07-05

### Added
- **Validation gating & report (#3854, MFX-5.3)** — the export job now surfaces an
  **emitted-artifact validation gate + report** alongside the fidelity envelope on completed
  jobs. New `app.export_validation_gate.build_validation_report(validation) →
  EmittedValidationReport` maps the MFX-5.1 `EmittedArtifactValidation` into four bands
  (`valid` / `invalid` / `skipped` / `not_applicable`) with `blocks_delivery` and `warns`
  gates, ready-to-render `headline` / `message` copy, per-target tool identity, and structured
  `ValidationFinding` rows (message, JSON-pointer path, bundle file, line/column when available).
  `EmittedArtifactValidation` now carries `findings` in addition to the legacy `errors`
  one-liners. Completed jobs attach the report on `ExportJobResult.validation` (null for
  dry-runs); `EMITTED_ARTIFACT_INVALID` failures embed the full report in `error.context`.
  Tests in `tests/test_export_validation_gate.py` and MFX-5.3 cases in
  `tests/test_export_job_engine.py`.

## [1.79.0] - 2026-07-05

### Added
- **Validate emitted artifact (#3852, MFX-5.1)** — the async export job now **re-validates the
  emitted artifact through its matching MFI import parser** before delivery, so a buggy emitter
  that produced output illegal in its own target format is caught rather than shipped. New
  `app.export_validation.validate_emitted_artifact(target_format, emit_result, *, api)` dispatches
  per emitter `format`, reusing (not rebuilding) the existing re-import paths — the OpenAPI /
  GraphQL / AsyncAPI round-trip modules (`round_trip_openapi` / `round_trip_graphql` /
  `round_trip_asyncapi`), `fastavro` for Avro, and `buf` for protobuf — and collapses each into a
  uniform `EmittedArtifactValidation` (`applicable` / `validated` / `valid` / `errors` / `detail`).
  The job's validation stage now **fails the job** with a structured `EMITTED_ARTIFACT_INVALID`
  error (carrying the parser detail) when a validator ran and rejected the artifact, emits
  `ARTIFACT_VALIDATED` on success, and honestly reports `VALIDATION_SKIPPED` (a `warn`) when a
  toolchain-backed validator (`asyncapi-parser`, `buf`) is unavailable in the runtime — a
  possibly-valid export is never failed for a check that could not run — or
  `VALIDATION_NOT_APPLICABLE` for a target with no importer (the sample no-op). Replaces the
  `validate_emitted_result` placeholder seam (which reported `VALIDATION_DEFERRED`) with
  `build_validation_events`.

## [1.78.0] - 2026-07-05

### Added
- **Export artifact streaming & temp retention (#3850, MFX-4.3)** — the async export job
  download route `GET /v1/export/{tenant_slug}/jobs/{job_id}/download` now **streams** the
  emitted artifact in 64 KiB chunks (`iter_download_chunks` → `StreamingResponse`) instead of
  buffering the whole bundle, with an up-front `Content-Length` (new
  `ExportDownloadArtifact.content_length`) so clients still get download progress. The retained
  `EmitResult` is now **temporary**: a completed job stamps an expiry `now + APIOME_EXPORT_ARTIFACT_RETENTION_HOURS`
  (new setting, default **24h**; set `0` to disable and keep the pre-4.3 process-lifetime
  retention), advertised to pollers on the new `ExportJobResult.download_expires_at`. After the
  window elapses the download route returns **410 Gone** (distinct from the 409 for a
  dry-run/incomplete job — the artifact existed but is gone; resubmit to regenerate) and the
  bytes are dropped; a lazy sweep (`_expire_stale_artifacts`) on each download resolve reclaims
  every other job's expired artifact too, so no background reaper is needed.
  `get_export_job_emit_result` honours the same expiry. apiome-rest 1.77.0 → 1.78.0.

## [1.77.0] - 2026-07-05

### Added
- **Multi-file export bundle download (#3849, MFX-4.2)** — the async export job download route
  `GET /v1/export/{tenant_slug}/jobs/{job_id}/download` now delivers **multi-file** targets
  (protobuf packages, WSDL+XSD, Smithy multi-namespace, per-subject Avro `.avsc`) as an
  `application/zip` bundle instead of rejecting them with 409. `resolve_export_download`
  branches on the retained `EmitResult`: a single file is served inline as before (MFX-4.1), a
  bundle of two-plus files is zipped by the new `build_export_zip`. The zip carries every
  emitted file at its bundle-relative path — each serialized through `serialize_file_content`,
  so bundle bytes match the `size_bytes` the job manifest reports — plus a root `manifest.json`
  (`build_bundle_manifest`) listing the resolved target, bundle media type, and per-file
  metadata (path, media type, serialized size, Schema Registry subject). Zip entries use pinned
  timestamps so the same emit result packages to byte-identical bytes. The bundle is named
  `<target>.zip`; `ExportDownloadArtifact.body` now carries `str` (single file) or `bytes` (zip).

## [1.70.0] - 2026-07-01

### Added
- **Normalized parsed model in catalog detail (#4087, MFI-25.2)** — `GET /v1/catalog/{tenant_slug}/{item_id}`
  now returns a `parsed` array: a normalized, paradigm-tagged entity list derived from the item's
  canonical model (MFI-EPIC-2), so the detail Overview (MFI-25.3) can render the actual parsed entities
  rather than only the aggregate `summary` counts. The shape is stable and presentation-agnostic —
  *entity groups → entities (`name`, `tag`, `meta`) → fields (`name`, `type`, `description`, `required`)* —
  grouped the way each paradigm reads most naturally: GraphQL as Operations (QUERY/MUTATION/SUBSCRIPTION)
  + Types (OBJECT/INPUT/ENUM/…), gRPC as Services & methods (streaming signatures) + Messages (protobuf
  field numbers), AsyncAPI as Channels + Operations (SEND/RECEIVE) + Messages (inline payload schemas),
  with a generic Operations/Types/Channels fallback for every other paradigm. New
  `src/app/catalog_parsed_model.py` reconstructs the canonical model from the item's captured source
  (the same parse+normalize path the convert endpoint uses, MFI-22.6) and projects it; an item with no
  reconstructable model (no captured content, URL-only, or unparseable source) degrades to `[]` so a
  detail read never errors. New response schemas `CatalogParsedGroup` / `CatalogParsedEntity` /
  `CatalogParsedField` on `CatalogItemDetailSchema`. Documented in `docs/catalog_parsed_model.md`.

## [1.68.0] - 2026-06-30

### Added
- **Conversion REST API (#4007, MFI-22.6)** — `POST /v1/catalog/{tenant_slug}/{item_id}/convert`, the
  single convert verb behind the UI preview (MFI-22.4), the CLI, and the API. The `dryRun` **query
  param is authoritative** (falling back to the body's `dryRun`, defaulting to a safe dry-run so a
  malformed body never silently commits): `dryRun=true` reconstructs the catalog item's canonical model
  from its captured source, emits the OpenAPI 3.1 document (MFI-22.1) and analyzes fidelity (MFI-22.3),
  returning `{report, openapi, sourceFormat, target}` with **no side effects**; `dryRun=false` runs the
  MFI-22.5 commit job, returning the created `{projectId, versionId, versionRecordId, createdProject,
  reconverted, provenanceId, report}`. New `src/app/catalog_conversion.py` rebuilds the `ConversionSource`
  from a stored item: it pulls the captured source (`resolve_source_payload`), resolves the source's
  `ImportSource` adapter robustly (canonical format → registry key → advertised `formats` → content
  sniff, so `protobuf`→`grpc` / `asyncapi-3`→`asyncapi` resolve), and `parse`→`normalize`s it back into
  a `CanonicalApi`; failures map to `ConversionError` (no captured source → 422, unknown format → 400,
  unparseable → 422). The pure emit+analyze step was extracted into `conversion_job.preview_conversion`
  so the dry-run and commit paths share one code path (the previewed document equals the committed one).
  `target` is `openapi` only (400 otherwise; the verb is target-generic for future emitters); a Project's
  id — or an unknown id — yields 404. Tests: `tests/test_catalog_conversion.py` (10),
  `tests/test_catalog_convert_route.py` (8), and `preview_conversion` cases in `tests/test_conversion_job.py`;
  full rest suite green (2803 passed, 31 skipped). The CLI half (`apiome convert`) ships in
  apiome-cli.

## [1.67.0] - 2026-06-30

### Added
- **Convert-to-project/version job + provenance (#4006, MFI-22.5)** — the step after a user confirms a
  catalog → OpenAPI conversion: it makes the conversion real. New module `src/app/conversion_job.py`
  orchestrates one job — emit the OpenAPI 3.1 document from the source canonical model (MFI-22.1/22.2,
  optionally closing cheap gaps with user-supplied `defaults` for a missing info title/version or
  servers), analyze its fidelity (MFI-22.3), **mint or re-version a publishable OpenAPI Project** from
  the emitted document by *reusing the spec-import submit→commit engine* (a first convert creates a new
  Project + `v1`; a re-convert of a changed source appends a *new version* to the previously-converted
  Project — looked up via the provenance ledger — instead of duplicating it), run the existing OpenAPI
  lint/score (MFI-EPIC-4) on the result, and **persist provenance** (source artifact id + source
  revision + source format/protocol + the fidelity report + converter tool versions). The
  orchestration is written against small ports (`SpecCommitter`/`LintScorer`/`ProvenanceStore`) so its
  decision logic is pure and unit-testable with fakes, while production wiring (`SpecImportCommitter`,
  `DbLintScorer`, `DbConversionProvenanceStore`) lives in swappable default adapters. New DAO methods
  `create_conversion_provenance` / `get_latest_conversion_for_source` / `get_conversions_for_project`
  over the new **`apiome.conversion_provenance`** append-only ledger (apiome-db V139). Tests in
  `tests/test_conversion_job.py` (24 new); full rest suite green (2781 passed, 31 skipped). The REST
  endpoint + CLI that call this job are MFI-22.6. apiome-rest 1.66.0 → 1.67.0.

## [1.66.0] - 2026-06-30

### Added
- **Fidelity / completeness gap analyzer (#4004, MFI-22.3)** — reads a canonical → OpenAPI conversion
  and produces the fidelity preview a user must see before committing. New pure, I/O-free module
  `src/app/fidelity.py`:
  - `analyze_fidelity(api, EmitResult) -> FidelityReport` consumes the emitter's per-value **provenance**
    (`source`/`inferred`/`default`, MFI-22.1) and the paradigm projection's **losses**
    (`inferred`/`n/a`, MFI-22.2) — no re-derivation of the conversion.
  - The report carries a **completeness checklist** (`ChecklistItem` per load-bearing OpenAPI construct:
    `info` fields, `servers`, `paths`, operation id/summary, parameters, `requestBody`, `responses`,
    `components.schemas`, security, `tags`, `examples`, `externalDocs`, `deprecated`), each with a
    `Coverage` tag (`present`/`inferred`/`partial`/`missing`/`n/a`), a count, up to three example
    coordinates, and a human-readable reason; the enumerated projection `losses`; and a rolled-up
    **score** (0-100) + **A-F grade** (reusing `schema_lint.GRADE_THRESHOLDS`, the MFI-4.2 banding)
    weighted by how load-bearing each inferred/partial/missing construct is, plus a per-`n/a`-loss
    penalty; and a coarse **fidelity tier** (`high`/`medium`/`low`) that drives the MFI-22.4 warning.
  - Pure & deterministic: fixed checklist order, sorted+capped examples, so the same `(api, result)`
    yields an equal report.
  - Acceptance: an OData-style REST model scores **high** (near-lossless); an AsyncAPI event model scores
    **low** with its pub/sub + channel-binding losses enumerated; a gRPC model without HTTP annotations
    flags **inferred paths** plus inferred (defaulted) media types and status codes.
  - Tests: `tests/test_fidelity.py` (21 new). Full rest suite green (2757 passed, 31 skipped). Docs:
    `docs/fidelity_analyzer.md`. apiome-rest 1.65.0 → 1.66.0.

## [1.65.0] - 2026-06-30

### Added
- **Paradigm projection strategies (#4003, MFI-22.2)** — a pluggable projection layer that maps a
  non-REST `CanonicalApi` onto the OpenAPI (path/verb/response) vocabulary and **declares what each
  projection loses**, feeding the fidelity analyzer (MFI-22.3). New module `src/app/projection.py`:
  - A `ProjectionStrategy` SPI (base class + paradigm registry `register_projection`/`get_projection`)
    with one strategy per `ApiParadigm`, each resolving an operation's `(method, path)` binding (or
    declaring it un-representable) and recording losses on a `LossTracker`:
    - **RPC** (`RpcProjection`, gRPC/Smithy/Thrift/OpenRPC, and A2A/MCP agent descriptors) — honors a
      `google.api.http` / Smithy `http` annotation from `extras`; else synthesizes
      `POST /{Service}/{Method}` (the gRPC-transcoding convention). Streaming is surfaced as an
      `x-apiome-streaming` extension plus an `n/a` loss.
    - **Graph** (`GraphProjection`, GraphQL) — SOFA-style: queries → `GET`, mutations → `POST` under
      `/graphql`, arguments → parameters; **subscriptions are `n/a`** (not emitted, reported as a loss).
    - **Event** (`EventProjection`, AsyncAPI/CloudEvents) — explicitly low-fidelity: each pub/sub
      operation becomes a *non-normative* path with an `x-apiome-event-action` note and a
      document-level `x-apiome-fidelity` caveat recommending schemas-only consumption; pub/sub
      action, channel bindings, and correlation ids are `n/a`. Payloads stay faithful in
      `components.schemas`.
    - **REST** (`RestProjection`) / **Data-schema** (`DataSchemaProjection`) — the identity /
      components-only projections (a data-schema model with a service still gets best-effort bindings).
  - New fidelity primitives on the Emitter SPI (`src/app/emitter.py`): `LossKind`
    (`inferred`/`n/a`), `Loss`, and `LossTracker`, plus a `losses` field on `EmitResult` carrying the
    projection's fidelity losses alongside the provenance. `OpenApiEmitter` now delegates route/loss
    decisions to the paradigm's projection instead of a single hard-coded best-effort binding.
  - Tests: `tests/test_projection.py` (20 new) — each paradigm emits a schema-valid OpenAPI 3.1 doc
    and reports its `inferred`/`n/a` set; subscriptions/streaming/pub-sub are surfaced as losses, not
    silently dropped. `tests/test_openapi_emitter.py` updated for the spec-compliant RPC path. Full
    `apiome-rest` suite green.

## [1.64.0] - 2026-06-30

### Added
- **Canonical → OpenAPI 3.1 emitter SPI (#4002, MFI-22.1)** — the inverse of the Normalizer SPI
  (MFI-2.3) and the first half of MFI-EPIC-22 (Catalog → OpenAPI Conversion). Three new pure,
  I/O-free modules:
  - `src/app/emitter.py` — the **Emitter SPI**: an `Emitter` ABC + format registry
    (`register_emitter`/`get_emitter`/`available_emit_formats`) mirroring the normalizer's; the
    **provenance** primitives (`Provenance` = `source`/`inferred`/`default`, `ProvenanceRecord`,
    `ProvenanceTracker` keyed by RFC-6901 JSON Pointer) that feed the fidelity analyzer (MFI-22.3);
    the `EmitResult` envelope (document + provenance); and `SchemaEmitter`, the exact inverse of the
    normalizer's `SchemaCoercer` (canonical `TypeRef`/`Constraints`/`Type` → JSON-Schema fragments —
    OAS 3.1 schemas *are* JSON Schema).
  - `src/app/openapi_emitter.py` — `OpenApiEmitter` (registered `openapi-3.1`): walks a
    `CanonicalApi` and emits a schema-valid OpenAPI 3.1 document — identity/version/description →
    `info`, servers → `servers`, operations → `paths`+methods (with `operationId`/`summary`/`tags`),
    messages → `requestBody`/`responses` (media types + headers), types → `components.schemas`.
    Emission is deterministic (all collections ordered by key/name) and every value is
    provenance-tagged. Non-REST models are handled best-effort: an operation with no HTTP verb/route
    gets a synthesized `POST` binding (marked `inferred`) and a types-only model emits a
    components-only document — covering the acceptance criterion's REST + RPC + data-schema sources.
    On REST input the emitter is a **fixed point** of the reference normalizer
    (`normalize(emit(normalize(doc))) == normalize(doc)`).
  - `src/app/openapi_validator.py` — validates a whole OpenAPI document against the bundled official
    **OpenAPI 3.1 meta-schema** (`data/openapi_3_1_meta_schema.json`, vendored so validation is
    fully offline) via the draft 2020-12 `jsonschema` engine already used by `schema_validation.py`.
  - Tests: `tests/test_emitter.py`, `tests/test_openapi_emitter.py`, `tests/test_openapi_validator.py`
    (44 new tests). Full `apiome-rest` suite green.

## [1.62.0] - 2026-06-30

### Added
- **Protobuf breaking-change classifier (#3768, MFI-9.5)** — `src/app/proto_breaking.py`, the
  fifth gRPC/Protobuf capability and the Protobuf provider on the MFI-3.3 breaking-change SPI,
  wrapping `buf breaking`. A registered `ProtobufBreakingChangeClassifier` (format key `protobuf`)
  subclasses the format-agnostic `BuiltinBreakingChangeClassifier`, so the synchronous SPI already
  grades a Protobuf diff from structure alone (a reused wire `field_number` and a changed `type`
  are breaking, an added optional field is safe) even with no `buf` binary — satisfying the
  acceptance criteria on the always-available path. The authoritative `buf breaking` overlay is the
  async `classify_async` / convenience `classify_protobuf(base, target, against_files=…,
  target_files=…, strictness=…)`: `run_buf_breaking(target_files, against_files, strictness=…)`
  materialises the new and baseline `.proto`s into two scratch `buf` modules (the new one carrying a
  `buf.yaml` that enables the one breaking category for the strictness — `buf` reads breaking rules
  from the input module; the baseline one carrying MFI-9.1's build-only config) and runs
  `buf breaking <new> --against <baseline> --error-format=json` through the MFI-5.1 toolchain runner
  (breaks on exit 100 are the normal outcome; absent/timeout/non-building protos raise
  `ProtoBreakingError`), and `breaking_changes()` maps buf's newline-delimited JSON into
  `ProtoBreakingChange`s namespaced `protobuf.buf-breaking.<type>` at `breaking` severity.
  Strictness is the configurable `BufBreakingStrictness` (`WIRE` / `WIRE_JSON` / `PACKAGE` /
  `FILE`), defaulting to `WIRE_JSON` (the default for services). Because `buf breaking`'s output is
  file-scoped (not a canonical coordinate), the overlay applies buf's verdict at that granularity:
  it forces the overall verdict to `breaking` when buf finds a break, and caps structural
  over-approximations to `dangerous` when buf finds the diff wire/JSON-compatible; the per-change
  attribution stays the structural baseline's, and it degrades gracefully to that baseline when the
  sources or the tool are unavailable. Registered in `breaking_change.load_format_breaking_change_classifiers`.
  Docs in `docs/proto_breaking.md`; 26 tests in `tests/test_proto_breaking.py` (+2 gated real-`buf`
  e2e). apiome-rest 1.61.0 → 1.62.0.

## [1.61.0] - 2026-06-30

### Added
- **Protobuf lint pack (#3767, MFI-9.4)** — `src/app/proto_lint.py`, the fourth gRPC/Protobuf
  capability, scoring a compiled descriptor set through the always-on MFI-4.1 lint engine. A
  registered native `ProtobufRulePack` (format key `protobuf`) adds three pure, deterministic
  rules over the canonical model — `protobuf.package-version-suffix` (the package is versioned,
  `foo.v1`, mirroring buf's `PACKAGE_VERSION_SUFFIX`), `protobuf.field-no-required` (no proto2/
  Editions `required` one-way-door field), and `protobuf.reserved-on-deletion` (a field/enum
  number gap no `reserved` range covers, the single-artifact heuristic for "always reserve a
  deleted number"). The authoritative `buf lint` (categories MINIMAL→STANDARD + COMMENTS) is
  wrapped via the MFI-5.1 toolchain runner: `run_buf_lint(files)` materialises a scratch buf
  module (reusing MFI-9.1's `materialize_proto_module`) and runs `buf lint --error-format=json`
  (violations on exit 100 are the normal outcome; absent/timeout/non-building protos raise
  `ProtoLintError`), and `buf_findings()` maps buf's newline-delimited JSON into `LintFinding`s
  namespaced `protobuf.buf.<type>` at `warning` severity. `lint_protobuf_result(model,
  buf_report=None)` merges buf + native + common into one score (buf opt-in, degrading
  gracefully), and `lint_protobuf(files)` does it end-to-end (compile → normalize → buf lint →
  score). Exposed `materialize_proto_module` / `BUF_MODULE_YAML` from `proto_descriptor` for
  reuse. Docs in `docs/proto_lint.md`; 28 tests in `tests/test_proto_lint.py` (+1 gated real-buf
  e2e). apiome-rest 1.60.0 → 1.61.0.

## [1.60.0] - 2026-06-30

### Added
- **gRPC live discovery via Server Reflection (#3766, MFI-9.3)** — `src/app/grpc_reflection.py`
  (`discover_endpoint`), the third gRPC import path: crawl a **running** server that ships no
  `.proto` source. It connects to a `host:port` target, calls `ListServices` to enumerate the
  surface, then `FileContainingSymbol` for each service (its file + transitive deps), and the pure
  `build_descriptor_set` seam dedups the returned `FileDescriptorProto`s by name, orders them
  deterministically (stable MFI-3.1 fingerprint), and packs a `google.protobuf.FileDescriptorSet`
  whose bytes feed `read_file_descriptor_set` — the **same** `CompiledDescriptorSet` MFI-9.1
  compiles from source, so `result.compiled()` flows into the MFI-9.2 `ProtoNormalizer` unchanged
  (files declaring a discovered service flagged as targets, pulled-in deps as imports). The crawl
  tries the modern `grpc.reflection.v1` service and **falls back to `grpc.reflection.v1alpha`** on
  `UNIMPLEMENTED` (driving the bidi `ServerReflectionInfo` stream via `channel.stream_stream` with
  the version-specific method path, since `grpcio-reflection` ships v1alpha stubs only). **Network
  opt-in (MFI-5.3) posture:** the target host is vetted by the new `ssrf_guard.validate_host()`
  (companion to `validate_url` for bare host:port targets) **before** any channel opens, and auth
  is attached as lower-cased gRPC **metadata** built from the shared credential-vault model
  (`mcp_auth.build_auth_headers`: `none`/`bearer`/`header`/`oauth2`). Validity is a return value
  (`GrpcReflectionResult`: reflection disabled / unreachable / no services → `ok=False` + reason);
  only an unsafe target or malformed credential raises `GrpcReflectionError` (4xx). Added the
  `grpcio` + `grpcio-reflection` dependencies. Tests in `tests/test_grpc_reflection.py` (incl. a
  real in-process gRPC server end-to-end). Docs: `docs/grpc_reflection.md`.

## [1.56.0] - 2026-06-30

### Added
- **GraphQL breaking-change classifier (#3774, MFI-10.5)** — `src/app/graphql_diff.py`
  (`GraphQlBreakingChangeClassifier`), the GraphQL provider on the MFI-3.3 breaking-change
  classifier SPI, mirroring MFI-8.4's `@asyncapi/diff` integration. Registered under the
  `graphql` format key, its synchronous baseline (inherited from
  `BuiltinBreakingChangeClassifier`) already grades a GraphQL diff from structure alone; the
  authoritative async `classify_async` (+ convenience `classify_graphql(base, target)`) runs
  **GraphQL-Inspector's `diff`** over the two canonical SDL strings MFI-10.2 preserved on
  `CanonicalApi.raw` (via a new bundled `graphql-inspector-diff` Node tool —
  `toolchain/graphql-inspector-diff.mjs` wrapping `@graphql-inspector/core@6.2.0` +
  `graphql@16.9.0`) and **overlays** the tool's `BREAKING`/`DANGEROUS`/`NON_BREAKING` verdict onto
  the structural grades wherever a change's schema-coordinate path joins a canonical entity the
  diff reports — an exact `Type.field`/`Root.field` match joins a field/operation; falling back
  to the bare leading segment folds an enum-value/union-member change onto its owning type. A
  change that joins nothing keeps the structural grade, and the whole path degrades gracefully to
  the structural baseline when the SDL or tool is unavailable. Acceptance criterion: removing a
  field grades `BREAKING`, adding an enum value grades `DANGEROUS`, both correctly surfaced on the
  diff view. Tests in `tests/test_graphql_diff.py`. Docs: `docs/graphql_diff.md`.

## [1.55.0] - 2026-06-30

### Added
- **GraphQL lint pack (#3773, MFI-10.4)** — `src/app/graphql_lint.py` (`GraphqlRulePack`), a
  `RulePack`-SPI implementation registered under the `graphql` format key (the one the MFI-10.2
  normalizer emits), so a GraphQL artifact is scored by the always-on lint engine
  (`lint_canonical_model`) through the same 0–100 / A–F / `report_fingerprint` formula as every
  other format (MFI-4.2). It encodes the SDL-checkable semantics of the three `graphql-eslint`
  configs the roadmap names: **naming-convention** (`graphql.naming-type-pascal-case`,
  `graphql.naming-field-camel-case` over object/input/root fields, `graphql.naming-argument-camel-case`,
  `graphql.naming-enum-value-upper-case`), **require-description** for the GraphQL-specific gaps
  the cross-format common pack does not cover (`graphql.enum-value-missing-description`,
  `graphql.argument-missing-description`), and **schema-recommended**
  (`graphql.require-deprecation-reason`). All rules are pure over the canonical model — no I/O,
  no Node — mirroring the pure-Python GraphQL toolchain (MFI-10.1/10.2/10.3). The authoritative
  `graphql-eslint` verdicts are *wrapped* rather than re-implemented: `eslint_findings(...)` maps
  the linter's standard ESLint JSON output into `LintFinding`s namespaced `graphql.eslint.*`
  (severity folded `2`→error / `1`→warning / else→info), to be fed by the MFI-4.3 external-linter
  adapter; `lint_graphql_result(model, eslint_report=None)` merges them with the native + common
  packs and degrades gracefully when none are supplied, and `lint_graphql(raw, ...)` runs it
  end-to-end from raw SDL (parse → normalize → lint). Tests in `tests/test_graphql_lint.py`.

## [1.49.0] - 2026-06-29

### Added
- **AsyncAPI → canonical model (#3760, MFI-8.2)** — `src/app/asyncapi_normalizer.py`
  (`AsyncApiNormalizer`), a `Normalizer`-SPI implementation that maps the dereferenced
  AsyncAPI document from MFI-8.1 (`parse_asyncapi(...).document`) into a `CanonicalApi` of
  paradigm `EVENT`, handling both AsyncAPI 2.x and 3.x by dispatching on the document's own
  `asyncapi` version. **Servers → `Server`** (v2 `url`; v3 `host` + `pathname` recombined into
  the URL, the split kept in `extras`; transport `protocol` preserved and the first server's
  protocol becomes the artifact `protocol`). **Channels → `Channel`** (wire `address` = stable
  key, address `parameters`, protocol `bindings`). **Operations → `Operation`** (`action` drives
  the kind — `send`/`publish` → `PUBLISH`, `receive`/`subscribe` → `SUBSCRIBE`; the dereferenced
  `channel` is matched back to its declaring channel by address for `channel_ref`; the original
  action verb and any `reply` are kept in `extras`; operations grouped into `Service`s by first
  tag, `default` when untagged). **Messages → `Message`** (role `EVENT`, inline `payload` →
  `payload_schema` since the parser has inlined every `$ref`, `headers` schema → header fields,
  `contentType`/`defaultContentType` → `content_types`, `correlationId` → `extras`). New `Keys`
  builders (`channel` / `operation_event` / `event_message` / `channel_parameter`) centralize the
  event key grammar. The model finishes through `normalize_ordering`, so the MFI-3.1 fingerprint
  is invariant to source declaration order yet flips on any structural change. Self-registers
  under `asyncapi-2` and `asyncapi-3`; `import_source.load_builtin_import_sources()` imports the
  module so it registers ahead of the MFI-8.5 import-source adapter. Tests
  (`tests/test_asyncapi_normalizer.py`): multi-channel v2 + v3 mapping, action/channel/message
  fidelity, idempotence, fingerprint stability across source order, description-only edits
  ignored, lossless JSONB round-trip, registry resolution + error paths, and a gated end-to-end
  suite feeding the real MFI-8.1 parser output into the normalizer. Docs `normalizer_spi.md` and
  `canonical_model.md` extended.

## [1.48.0] - 2026-06-29

### Added
- **AsyncAPI parser + validate (#3759, MFI-8.1)** — a Python seam over the official JavaScript
  `@asyncapi/parser` for parsing, validating and dereferencing AsyncAPI 2.6 / 3.0 / 3.1 (and the
  wider 2.x/3.x families). A small repo-committed Node wrapper (`toolchain/asyncapi-parse.mjs`)
  reads a document on `stdin`, validates it, resolves in-document `$ref`s, strips the parser's
  `x-parser-*` bookkeeping keys, and emits a single canonical-JSON object
  (`{ok, asyncapiVersion, identity, document, diagnostics}`) on `stdout` — an invalid document is
  reported in the body, never as a crash. It is bundled as a new `asyncapi-parser` tool
  (`src/app/toolchain_packaging.py`; pinned `@asyncapi/parser` 3.6.0, installed + wrapped in the
  `Dockerfile`) so `app.toolchain_runner` runs it by bare name in the same constrained sandbox as
  the other CLIs. The new `src/app/asyncapi_parser.py` service (`parse_asyncapi(...)`) shells out
  through the runner and adapts the wrapper contract into typed results
  (`AsyncApiParseResult` / `AsyncApiIdentity` / `AsyncApiDiagnostic`): it captures
  `info.title`/`version` + the document `id`, exposes `ok` / `errors` / `supported_version` /
  `raise_if_invalid()`, and maps tool failures (unavailable / timeout / non-JSON) to
  `AsyncApiParseError`. This is the parse/validate foundation the AsyncAPI → canonical-model
  mapping (MFI-8.2) builds on. Tests: `tests/test_asyncapi_parser.py` (a Node-free seam suite
  replaying the wrapper contract incl. authentic dereferenced payloads, plus a gated end-to-end
  suite that runs the real wrapper against `tests/fixtures/asyncapi/`), and an extension to
  `tests/test_toolchain_packaging.py` for the new tool key.

## [1.46.0] - 2026-06-29

### Added
- **Catalog item detail + source material (#4018, MFI-23.9)** — `GET /v1/catalog/{tenant_slug}/{item_id}`
  now returns a `CatalogItemDetailSchema`: the MFI-23.2 envelope plus a normalized-content `summary`
  (services/operations/types/channels counts) and a `source` material descriptor (input kind / label
  / URL / downloadable), both derived from the latest revision's `format_metadata` via the new pure,
  unit-tested `catalog_detail.py` helpers (tolerant of camel/snake + nested `counts` shapes; sparse
  until the import path records that provenance). A new `GET /v1/catalog/{tenant_slug}/{item_id}/source`
  endpoint makes the original source material viewable/downloadable — it streams captured inline
  content as a typed attachment, 307-redirects to a recorded source URL, or 404s when nothing was
  captured. Both reads stay on the non-publishable slice (a Project id → 404) and authenticate via JWT
  or API key. Tests: `tests/test_catalog_detail.py` and additions to `tests/test_catalog_routes.py`.

## [1.45.0] - 2026-06-29

### Added
- **Non-publishable enforcement at the publish endpoint (#4017, MFI-23.8)** — `POST
  …/{version}/publish` now refuses with **409** when the owning project is a catalog item
  (`publishable = false`, the MFI-23.1 slice — an OpenAPI-worthy non-OpenAPI import that may be
  incomplete), with a message pointing at the convert-to-OpenAPI flow that mints a new publishable
  project. The guard is strict (`publishable is False`), so projects with a missing/None/True flag
  publish exactly as before; the existing description/compatibility prechecks are unchanged. The
  project row is fetched once and reused for the commit-policy lookup. Tests:
  `tests/test_publish_catalog_item_gate.py`.

## [1.44.0] - 2026-06-29

### Added
- **Route OpenAPI-worthy non-OpenAPI imports → catalog (#4016, MFI-23.7)** — the generalized
  import job (MFI-1.2) now decides, at the end of every adapter run, whether a finished import
  becomes a publishable **Project** or a non-publishable **catalog item** (MFI-23.1), and records
  *why*. New `import_routing.py` exposes `decide_import_routing(adapter, model) → ImportRoutingDecision`,
  a pure function that branches on the canonical model's **emitted format**: OpenAPI/Swagger
  (`openapi-3.0`/`openapi-3.1`/`swagger-2.0`, including **TypeSpec-emitted OpenAPI**, which routes by
  emitted format, not source tool) → publishable Project (`publishable=True`, as today); every other
  OpenAPI-worthy import (gRPC/GraphQL/AsyncAPI/OData/… — has operations and/or channels) → catalog
  item (`publishable=False`); a pure data-schema source (Avro/Protobuf-schema/JSON-Schema/XSD — types
  but no callable surface) → catalog item additionally flagged `schemas_only`. The
  `ImportRoutingDecision` (target/publishable/schemas_only/reason + paradigm/format/counts) is recorded
  on the in-process pipeline's completed-job `summary` under `routing` and surfaced as a new
  `ROUTING_DECIDED` event between normalize and version, so the UI can explain where an import landed
  and why. The decision is consumed by the canonical→catalog persistence hook (a later format epic):
  it reads `routing.publishable` to call `db.create_project(..., publishable=...)`. Tests:
  `apiome-rest/tests/test_import_routing.py` (19 — every paradigm, the OpenAPI/TypeSpec carve-out,
  schemas-only flagging, edge cases, summary/event recording) + an updated event-sequence assertion in
  `test_import_source_pipeline.py`. Full rest suite green (2195 passed, 2 pre-existing live-DB skips).
  apiome-rest 1.43.0 → 1.44.0.

## [1.43.0] - 2026-06-29

### Added
- **Catalog list + detail REST API (#4011, MFI-23.2)** — read-only endpoints over the *Catalog*
  (the `publishable = false` slice of projects from MFI-23.1): `GET /v1/catalog/{tenant_slug}` and
  `GET /v1/catalog/{tenant_slug}/{item_id}` (`catalog_routes.py`, registered in `main.py`). The
  responses deliberately mirror the Projects contract (id/name/slug/description/timestamps/creator/
  `qualityScore`/`qualityGrade`) so the Catalog screen (MFI-23.3) can be cloned from the Projects
  dashboard, while additionally carrying each item's latest-revision format/source projection
  (`sourceFormat`, `protocol`, `formatMetadata`, `toolVersions`) and the `publishable = false`
  invariant via `CatalogItemSchema`. Both endpoints are tenant-scoped, authenticate via JWT or API
  key, and the list supports `include_deleted` for trash/restore parity with `/v1/projects`. The
  single-item read returns 404 for an id that is not a catalog item (e.g. a publishable Project),
  reusing the `get_catalog_items_for_tenant` / `get_catalog_item_by_id` projections from MFI-23.1.
  A matching Next.js `/api/catalog` proxy (list + `[itemId]` detail) was added in apiome-ui,
  cloned from the projects proxy. Tests: `apiome-rest/tests/test_catalog_routes.py` (12) +
  `apiome-ui/tests/api/catalog-proxy.test.ts` (10). Full rest suite green (2176 passed, 2
  pre-existing live-DB skips). apiome-rest 1.42.0 → 1.43.0; apiome-ui 0.25.0 → 0.26.0.

## [1.42.0] - 2026-06-29

### Added
- **Catalog item entity & non-publishable guarantee (#4010, MFI-23.1)** — a *catalog item* (an
  OpenAPI-worthy non-OpenAPI import that must not become a publishable Project) is now modelled as a
  projection over the existing `projects` + `versions` tables, with the Project-vs-Catalog boundary
  enforced at the data layer rather than hidden in the UI. `Database.create_project` gains a
  `publishable` flag (default `True` for Projects; `False` for catalog items, used by the import
  routing in MFI-23.7) that round-trips through INSERT/RETURNING; new `get_catalog_items_for_tenant`
  / `get_catalog_item_by_id` reads return only the `publishable=false` slice, projecting the latest
  revision's `source_format`/`protocol`/`format_metadata`/`tool_versions` (MFI-7.1/7.2) and the
  captured lint `quality_score`/`quality_grade`; and `set_version_source_format` persists a
  revision's format/protocol/provenance at import. A new `CatalogItemSchema` (always
  `publishable=false`) carries the project-compatible fields plus the format/source projection, and
  `publishable` is surfaced on `ProjectSchema` and every project SELECT/RETURNING — but is
  deliberately omitted from the `update_project` whitelist so the flag stays immutable through the
  app, backed by the write-once `publishable` trigger added in apiome-db V138. Tests in
  `tests/test_catalog_item.py` (15 tests); full suite green (2164 passed, 2 pre-existing live-DB
  skips).

## [1.41.0] - 2026-06-29

### Added
- **Format auto-detection (#3737, MFI-1.5)** — a new `app.format_detection` module sniffs an
  ingested document's format so the importer can route it without the user knowing whether a file
  is RAML, OpenAPI, or Smithy. It extends the MFI-1.1 detection seam: every registered
  `ImportSource.detect()` (importable formats, e.g. OpenAPI today) is ranked alongside cheap marker
  sniffers for the formats whose full adapters arrive in later epics — `#%RAML`, `FORMAT: 1A`
  (API Blueprint), `$version`/`namespace` (Smithy/TypeSpec), `<wsdl:definitions>` / `<edmx:Edmx>`
  (WSDL/OData), `asyncapi:` (AsyncAPI 2/3), `syntax = "proto3"` (protobuf), `{"type":"record"}`
  (Avro), and GraphQL root types / `schema {}`. The highest-confidence match wins; sniffer-only
  formats are reported with `importable: false`; and when two formats tie within an ambiguity
  margin the result is flagged `ambiguous` with the close set so a caller can prompt the user. A new
  authenticated `POST /v1/import/detect` exposes the verdict. The sniffers are intentionally **not**
  registered as no-op adapters, so the source list (UI cards / CLI `import --list`) is not polluted
  with not-yet-importable formats. Implemented in `apiome-rest/src/app/format_detection.py`
  (+ `detect_import_source_candidates` in `import_source.py`, the `/detect` route in
  `import_sources_routes.py`); tests in `tests/test_format_detection.py` and
  `tests/test_import_sources_routes.py`.

## [1.40.0] - 2026-06-29

### Added
- **Import-source enumeration endpoint (#3735, MFI-1.3)** — a new authenticated, non-tenant route
  `GET /v1/import/sources` lists every registered import-source adapter (MFI-1.1 registry) as its
  public `ImportSourceDescriptor` (key, label, description, Lucide `icon`, paradigm, `input_kinds`,
  live-discovery flag, emitted `formats`), sorted by key and wrapped in `ImportSourceListResponse`.
  This is the source list the UI's `ImportDialog` source cards (MFI-1.3) and the CLI format list
  (MFI-1.4) read, so registering an adapter server-side surfaces it everywhere with no client code
  change. Implemented in `apiome-rest/src/app/import_sources_routes.py`; tests in
  `tests/test_import_sources_routes.py`.

## [1.39.0] - 2026-06-29

### Added
- **Lint REST/UI/CLI surfacing (#3749, MFI-4.4)** — the per-version lint report
  (`GET /v1/versions/{tenant}/{project}/{version}/lint`) now surfaces the quality score that was
  *persisted on the version at import time* (#3609 for specs, MFI-4.2 for canonical models)
  alongside the live recompute, so REST, the ADE lint panel, and the CLI `apiome lint`
  command all show the same authoritative captured signal. `LintReportResponse` gains
  `capturedScore`, `capturedGrade`, `capturedReportFingerprint`, and a `scoreIsStale` flag.
  `scoreIsStale` is true only when a captured fingerprint exists and differs from the live
  report's fingerprint (i.e. the stored score is out of date); it is always false when a base
  revision is compared (that report folds in extra compatibility findings) or when no score has
  been captured. The read is tenant-scoped via the new `Database.get_version_quality_score`
  helper and best-effort — a read failure degrades to "no captured score" and never breaks the
  authoritative live lint. No migration: the score already lives on `versions.quality_*`.

## [1.38.0] - 2026-06-29

### Added
- **Score/grade/fingerprint reuse (#3747, MFI-4.2)** — roll a canonical-model import's lint
  findings up to a stored quality signal per version, the same way specs (#3609, V124) and MCP
  (#3655, V130) already do. The `LintReport` returned by the import-source SPI now mirrors the
  shape of `app.schema_lint.LintResult` / `app.mcp_score.MCPScoreResult`: alongside its findings
  it carries a weighted 0–100 `score`, an A–F `grade` (the V124 house bands), a stable
  `report_fingerprint`, and per-rule / per-severity tallies — all on one comparable scale. A new
  `LintReport.from_lint_result()` adapts an engine result into that shape so every adapter's
  report is identical. The SPI default `ImportSource.lint()` now lints the canonical model
  through MFI-4.1's `lint_canonical_model` and rolls it up (previously an empty report), so every
  format adapter produces a deterministic score with no format-native override; the OpenAPI
  adapter delegates to `lint_openapi_spec` and now carries its fingerprint through, falling back
  to the canonical engine when no native document is present (rather than returning an unscored
  report). New `app.import_source_pipeline.capture_canonical_quality_score(version_record_id,
  tenant_id, model)` — the canonical analogue of `_capture_version_quality_score` /
  `_capture_mcp_version_score` — lints the model and persists the rolled-up score/grade/
  fingerprint onto the revision's `versions.quality_*` columns (reused via
  `Database.set_version_quality_score`; one `api_artifacts` row per `versions` row, so no
  migration is needed). It is strictly best-effort (a scoring failure never breaks an
  already-committed import) and is wired into `run_adapter_import_job`, guarded on a persisted
  version target (`options.version_record_id` + `payload.tenant_id`) and skipped on dry runs — a
  no-op in today's preview-only adapter path until canonical→catalog persistence wires a version
  through, then an automatic capture on every new version. The in-process job summary now carries
  the fingerprint and the severity tally. Pure and deterministic: the same fixed model always
  yields the same score/grade/fingerprint. 8 new tests across `tests/test_import_source.py`,
  `tests/test_openapi_import_source.py`, `tests/test_import_source_pipeline.py`, and the new
  `tests/test_canonical_quality_capture.py`; full rest suite green (2110 passed, 2 pre-existing
  live-DB skips). apiome-rest 1.37.0 → 1.38.0.

## [1.37.0] - 2026-06-29

### Added
- **Lint engine + rule-pack SPI (#3746, MFI-4.1)** — generalize the OpenAPI-only linter into
  a pluggable engine that runs registered **rule packs** over the canonical model (MFI-2.1),
  so quality checks are written once and reused for every paradigm (REST/RPC/event/graph/
  data-schema). New `app.lint_engine` provides `lint_canonical_model(api, *, extra_findings)
  -> LintResult`, a `LintRule` (stable `rule_id` + group + severity bound to a pure check) and
  a `RulePack` SPI with a format-keyed registry (`register=True` / `register_rule_pack` /
  `get_rule_pack` / `available_lint_formats`), mirroring the fingerprint-hasher and
  breaking-change-classifier registries. The format-agnostic `CommonRulePack` always runs and
  covers the two cross-format hygiene concerns the roadmap calls out — **missing descriptions**
  (artifact, type, field, operation, message, channel) and **unstable identifiers**
  (auto-generated/positional names like `InlineObject1` / `schema1` / `_12` that wreck diff
  alignment across re-imports, flagged by a conservative documented heuristic). A format whose
  ecosystem has its own rules registers a pack under its format key; `lint_canonical_model`
  runs the common pack plus that pack (if any), folds in caller-supplied `extra_findings` (e.g.
  compatibility flags from `app.breaking_change`), and rolls everything up through the new
  shared `app.schema_lint.assemble_lint_result` so the score/grade/fingerprint formula is
  identical across formats. The OpenAPI behavior is unchanged: `lint_openapi_spec` remains the
  OpenAPI rule pack and reproduces its current findings exactly (its tests are untouched). The
  engine is pure (no DB/network/clock) and deterministic (entities visited in sorted-key order,
  findings re-sorted by `(path, rule, id)`). 30 tests in `tests/test_lint_engine.py` (clean
  model scores 100/A, dirty model surfaces every common rule, per-paradigm linting, determinism,
  stable id hashes, sort order, input purity, `extra_findings` folding, the unstable-name
  heuristic positives/negatives, and the SPI register/lookup/dispatch/duplicate/empty-format
  guards); full rest suite green. apiome-rest 1.36.0 → 1.37.0. See
  `docs/lint_engine_spi.md`.

## [1.36.0] - 2026-06-29

### Added
- **Versioning + tagging reuse (#3745, MFI-3.4)** — give every imported artifact a
  dated version *only when its fingerprint changes*, reusing the proven MCP
  version-on-change recipe over the canonical model. New `app.versioning` provides a
  pure `decide_version(model, *, previous, when, existing_tags) -> VersionDecision`
  that fingerprints the freshly normalized model (MFI-3.1), compares the semantic
  fingerprint against the artifact's current version, and returns a `VersionDecision`:
  `VersionAction.CREATE` on the first import (no diff — nothing to compare) or when the
  fingerprint changed, `VersionAction.SKIP` on an unchanged re-import (mints nothing and
  leaves `current_version` put). A created version is stamped with a minute-precision
  UTC date/time tag (`format_version_tag` / `mint_version_tag`, e.g. `2026-06-26T14:03Z`)
  carrying the same `-N` same-minute collision suffix as the MCP tagger, and — when the
  previous model is supplied — the before→after `ModelDiff` (MFI-3.2) the new version
  carries. The decision also reports the `current_version_tag` the artifact should point
  at afterward (advanced only on a change, mirroring `mcp_endpoints.current_version_id`).
  The module is pure (no DB/network/clock read): the import time and previously recorded
  version are inputs, so the persistence wiring (per-format catalog write, MFI-2.2 and
  the format epics) reuses one audited decision instead of re-deriving it per format. 27
  tests in `tests/test_versioning.py` (no-change-skips and change-creates-dated-version
  +diff per paradigm, doc-only-edit skips, diff orientation/removal, fingerprint-only
  deciding without a previous model, same-minute tag collision suffixing, determinism,
  JSON round-trip, input-not-mutated); full rest suite green (2072 passed, 2 pre-existing
  live-DB skips). apiome-rest 1.35.0 → 1.36.0.

## [1.35.0] - 2026-06-29

### Added
- **Breaking-change classifier SPI (#3744, MFI-3.3)** — grade an MFI-3.2 model diff
  breaking-vs-safe, uniformly for every paradigm. New `app.breaking_change` provides
  `classify(model_diff, base, target) -> ClassificationResult`, which grades each change
  in the diff with a three-tier `Severity` (`safe` / `dangerous` / `breaking` — the
  common ground of GraphQL-Inspector, Buf, and Confluent) and returns a per-change
  `ChangeClassification` (severity + stable `rule_id` + rationale, carrying the change's
  category/kind/key so a diff view joins severities back onto rendered changes), the
  worst `overall_severity`, a `breaking` convenience boolean, and a `counts_by_severity`
  tally. `classify` dispatches by `target.format`: a registered per-format
  `BreakingChangeClassifier` (SPI + `register_breaking_change_classifier` /
  `get_breaking_change_classifier` / `available_breaking_change_formats`, mirroring the
  normalizer, fingerprint-hasher, and diff-labeler registries) when present, otherwise
  the format-agnostic `BuiltinBreakingChangeClassifier` baseline — removal is breaking,
  additive surface is safe, an added mandatory (non-nullable, no-default) field is
  dangerous, and a modification is graded as the worst over its moved canonical
  attributes (a type narrowed to non-null / route / verb / kind / status / wire-identity
  move is breaking; a default, constraint, deprecation, content-type, or folded
  member-list move is dangerous; a widening is safe). Format packs either wrap the
  canonical CLI via the EPIC-5 toolchain runner (Buf breaking, GraphQL-Inspector,
  `@asyncapi/diff`, `smithy diff`, Confluent `/compatibility`) by overriding `classify`,
  or subclass the builtin to sharpen individual rules. `classify_models(base, target)`
  is a diff-then-classify convenience. The builtin path is pure (no DB/network), and
  `ClassificationResult` round-trips losslessly to JSONB for persistence alongside the
  version diff (MFI-3.4). Documented in `docs/breaking_change_spi.md`; 28 tests in
  `tests/test_breaking_change.py`.

## [1.34.0] - 2026-06-29

### Added
- **Compare-any-two model diff (#3743, MFI-3.2)** — uniform "what changed between two artifacts?"
  over the MFI-2.1 canonical model, generalizing the MCP surface diff (V2-MCP-EPIC-18.2/24.3). New
  `app.diff` provides `diff(base, target) -> ModelDiff` listing every service / operation / message /
  channel / type / field **added**, **removed**, or **modified**, each with its before/after
  self-projection and a per-attribute `FieldChange` breakdown for modifications, plus overall and
  per-category `DiffCounts`. The diff is taken over `app.fingerprint.canonical_payload`, so it is in
  lock-step with change detection: documentation-only edits and source declaration-order differences
  are invisible, and identical models produce an empty diff (`ModelDiff.identical`). Entities are
  paired by their stable canonical `key`, so a rename reads as remove + add and the comparison is
  exact for *any two* versions (adjacent or arbitrarily distant) and across formats; categories are
  flattened and globally keyed so parent/child changes are never double-counted (a type with one new
  field is *not* itself "modified"). A per-format label SPI (`DiffLabeler` +
  `register_diff_labeler`/`get_diff_labeler`/`available_diff_formats`, mirroring the normalizer and
  fingerprint-hasher registries) lets format epics enrich `EntityChange.label` purely additively;
  documented in `docs/diff_spi.md`. 31 new tests in `tests/test_diff.py`.

## [1.33.0] - 2026-06-29

### Added
- **Canonical fingerprint SPI (#3742, MFI-3.1)** — uniform change detection over the MFI-2.1
  canonical model. New `app.fingerprint` provides `canonical_fingerprint(api)`, a SHA-256 over a
  *canonicalized* projection of a `CanonicalApi`: identity-keyed collections are order-normalized via
  `normalize_ordering` (order-meaningful `enum_values`/`union_members`/server variables left in
  place), documentation/presentation keys (`description`, `title`, `raw`) are scrubbed structurally
  while opaque semantic bags (`extras`/`bindings`/`payload_schema` and literal `default`/`value`/
  `enum`) are carried verbatim, then serialized with `json.dumps(sort_keys=True,
  separators=(",",":"))` and hashed — generalizing the MCP report-fingerprint recipe
  (V2-MCP-EPIC-18.1). Identical artifacts hash identically across runs; doc-only edits and source
  declaration-order differences do not flip the digest; any single structural change does. A
  per-format hash hook SPI (`FingerprintHasher` + `register_fingerprint_hasher`/
  `get_fingerprint_hasher`/`available_fingerprint_formats`, mirroring the normalizer registry) lets
  format epics attach special hashes (Avro Parsing Canonical Form, protobuf descriptor-set, XSD QName
  canonicalization); `fingerprint(api)` returns a `FingerprintResult` with the always-present
  semantic fingerprint plus the format hash when a hasher is registered. The Avro PCF vs.
  semantic-hash distinction (PCF strips defaults/aliases/doc; the semantic hash keeps them) is
  documented in `docs/fingerprint_spi.md`. 21 new tests in `tests/test_fingerprint.py`.

## [1.32.0] - 2026-06-28

### Added
- **Toolchain sandbox security & resource limits (#3752, MFI-5.3)** — the MFI-5.1 runner shells
  out to third-party parser/linter/diff CLIs on **user-supplied input** (a security surface: SSRF,
  code exec, zip bombs), so every tool subprocess now runs under an OS sandbox. New
  `app.toolchain_sandbox` defines a `SandboxPolicy` the runner applies on every call (its
  `default_policy`, built from settings, overridable per call): **no network by default** — the
  child is launched in a fresh Linux network namespace (`unshare(CLONE_NEWUSER|CLONE_NEWNET)`) so it
  cannot reach the metadata IP / internal services / the internet, with `best_effort` (isolate when
  the kernel allows, else log + continue) or `strict` (fail closed) enforcement; **`setrlimit`
  clamps** in a `preexec_fn` for CPU-seconds, address space, file size, child processes, open files,
  and a zeroed core-dump limit; and **input/output size caps** enforced in the runner — an oversized
  `stdin` is rejected before spawning and a tool whose combined stdout+stderr exceeds the cap is
  killed mid-stream (a zip-bomb guard). New typed errors carry the tool key: `ToolInputTooLargeError`,
  `ToolOutputTooLargeError`, `ToolResourceLimitError` (CPU/file-size kill — `SIGXCPU`/`SIGXFSZ`),
  `ToolSandboxError` (strict isolation unavailable). A tool needing the network for explicit live
  discovery opts out via `SandboxPolicy.for_live_discovery()`, and its fetches must then route through
  the SSRF guard (`app.ssrf_guard`, #3612) — the runner's no-network default is the belt, the SSRF
  guard the braces. The platform-admin `GET /v1/ops/toolchain` now also reports the active `sandbox`
  posture. New `APIOME_TOOLCHAIN_*` settings (no-network, enforcement mode, input/output/file-size
  byte caps, open files, optional CPU/memory/process clamps); documented in `docs/toolchain_sandbox.md`;
  tests in `tests/test_toolchain_sandbox.py`. apiome-rest 1.31.0 → 1.32.0.

## [1.31.0] - 2026-06-28

### Added
- **Tool runtime packaging (#3751, MFI-5.2)** — bundle the pinned external parser/linter/diff CLIs
  the multi-format import roadmap shells out to (via the MFI-5.1 runner) into the REST runtime image,
  and make a missing tool a clean "format unavailable" signal instead of a crash. New
  `app.toolchain_packaging` declares `BUNDLED_TOOLS` as the single source of truth: `buf` (1.50.0),
  `tsp` (0.65.0), `smithy` (1.53.0), `drafter` (4.0.0), `amf` (5.7.1), `asyncapi` (2.16.0), `rover`
  (0.27.0), each a `BundledTool` (key, executable, **pinned version**, `APIOME_<KEY>_BIN`
  override, version-probe args, runtime label) that registers into the runner registry. The
  `Dockerfile` gains a `tools` build stage installing exactly those versions (build-arg pinned,
  mirroring the Python source of truth): native binaries (buf/rover) from GitHub releases, smithy's
  self-contained CLI zip, drafter built from its pinned tag, the AMF assembly jar + a `java -jar`
  wrapper, and tsp/asyncapi via npm with node wrappers — all on `PATH` at `/opt/apiome-tools/bin`.
  Tools are optional/lazy: non-raising `probe_tool`/`probe_all` (a PATH/override lookup, no subprocess)
  report `available: false` so a format degrades to "unavailable"; the new platform-admin
  `GET /v1/ops/toolchain` surfaces per-tool pinned version + availability (`?verify=true` also runs
  each available tool's version probe). Footprint documented in `docs/toolchain_packaging.md`
  (~465 MB added; drafter's build toolchain stays in the builder stage). Tests in
  `tests/test_toolchain_packaging.py`.

## [1.30.0] - 2026-06-28

### Added
- **Polyglot toolchain runner service (#3750, MFI-5.1)** — the shared seam every format adapter
  uses to shell out to a non-Python parser/linter/diff CLI (buf, tsp, smithy, drafter, AMF, the
  AsyncAPI CLI, graphql-inspector) and get structured JSON back. `app.toolchain_runner` provides a
  `ToolSpec` (key, executable, base args, default timeout, env overrides/passthrough, `parses_json`)
  with a by-key registry (`register_tool`/`get_tool`/`available_tools`/`describe_tools`, mirroring
  the ImportSource registry) and a `ToolchainRunner` that runs a tool in a **constrained** `asyncio`
  subprocess: explicit argv (never a shell), a sanitized environment that forwards only an allow-list
  of host vars (so `DATABASE_URL`/JWT/cloud secrets never reach a third-party CLI), an optional cwd, a
  per-call timeout that kills the process, JSON parsing of stdout, and a process-wide concurrency cap
  (`asyncio.Semaphore`, `APIOME_TOOLCHAIN_MAX_CONCURRENCY`, default 4). Failure modes are typed
  errors carrying the tool key — `ToolNotRegisteredError`, `ToolNotAvailableError` (missing binary),
  `ToolTimeoutError`, `ToolExecutionError` (non-zero exit + captured streams), `ToolOutputError`
  (non-JSON stdout). A built-in `sample-echo` tool (portable JSON echo via the current Python
  interpreter) is the acceptance vehicle so the runner is exercisable without bundling a real CLI.
  Tool runtime packaging (MFI-5.2) and OS-level sandboxing — no-network, FS isolation, CPU/mem caps —
  (MFI-5.3) are deferred. New settings `toolchain_max_concurrency` / `toolchain_default_timeout_seconds`;
  documented in `docs/toolchain_runner.md`; tests in `tests/test_toolchain_runner.py` (14 tests).

## [1.29.0] - 2026-06-28

### Added
- **Generalized spec-import job pipeline (#3734, MFI-1.2)** — the async submit→poll→commit/rollback
  import engine (`app.spec_import_engine`) is no longer OpenAPI-only. A new in-process driver,
  `app.import_source_pipeline.run_adapter_import_job`, drives *any* registered `ImportSource`
  adapter (MFI-1.1) through **parse → normalize → version(fingerprint) → lint**, emitting the same
  `SpecImportJobStatus` contract (events, percent, summary) the worker produces and honoring the
  `dry_run` / `incremental_mode` options. `_drive_job` resolves the adapter from
  `metadata.source_kind`: OpenAPI/Swagger (and any unrecognized kind) stay on the `apiome-ui`
  `tsx` worker exactly as before, while every other registered source runs in-process. The
  in-process path is preview-only (no catalog write — canonical→catalog persistence is a later
  format epic); its completed-job `summary` carries the revision fingerprint, paradigm/format,
  entity counts, and lint score. Tests: `tests/test_import_source_pipeline.py` (pipeline unit
  coverage) and new end-to-end cases in `tests/test_spec_import_contract.py` driving the `sample`
  adapter through the REST job API; full `tests/` suite green.

## [1.26.0] - 2026-06-28

### Added
- **Normalizer SPI (#3740, MFI-2.3)** — the contract + base utilities that turn a parsed source
  document of any API format into the MFI-2.1 canonical model (`app.canonical_model.CanonicalApi`),
  so each format epic writes only its own mapping. `app.normalizer` provides: the `Normalizer`
  abstract contract (`format` + `paradigm` identity, a single `normalize()` method) with a
  by-format-key registry (`register_normalizer`/`get_normalizer`/`available_formats`, plus a
  `register=True` class flag); `Keys`, deterministic stable-key builders matching the documented
  key grammar (`GET /pets/{id}`, `GET /pets/{id}#path.id`, `User.email`, …) so diffs line up by
  identity; `coerce_constraints` + `SchemaCoercer`, which map a JSON-Schema fragment into canonical
  `TypeRef`/`Constraints`/named `Type`s (reusing the JSON-Schema vocabulary — OpenAPI 3.1 schemas
  *are* JSON Schema — including both the 3.1 numeric and 3.0 boolean `exclusiveMinimum/Maximum`
  forms); and `normalize_ordering`, which sorts identity-keyed collections so output is byte-stable
  regardless of source declaration order. The reference implementation `app.openapi_normalizer`
  (`OpenApiNormalizer`) maps a parsed **OpenAPI 3.0/3.1** document into a REST `CanonicalApi`
  (info→identity, servers, `components.schemas`→types, paths→operations grouped by tag,
  parameters, request/response messages with payload refs/inline schemas and headers) and
  self-registers both `openapi-3.0` and `openapi-3.1`. Documented in `docs/normalizer_spi.md`;
  SPI/utility tests in `tests/test_normalizer.py` and end-to-end reference-normalizer tests in
  `tests/test_openapi_normalizer.py`.

## [1.25.0] - 2026-06-28

### Added
- **Canonical API model (#3738, MFI-2.1)** — one paradigm-agnostic internal model
  (`app.canonical_model.CanonicalApi`) that every importable API description format normalizes into,
  so versioning/fingerprint/diff/lint/browse are written once across REST, RPC, event-driven, graph,
  and data-schema paradigms. The model is a tree — artifact → services → operations
  (`kind` + `streaming` + verb/route) → parameters/messages, plus channels (event addresses/bindings)
  and types (record/enum/union/scalar/alias/map) with fields carrying nullability-and-list-aware
  `TypeRef`s, defaults, protobuf field numbers, and JSON-Schema-vocabulary constraints. Every entity
  carries a deterministic stable `key` (GraphQL coordinates / protobuf field numbers / XSD QNames) so
  diffs line up by identity, plus an `extras` bag (and a top-level `raw` AST bag) so normalization is
  lossy-but-never-destructive. Plain Pydantic v2, so it round-trips to/from JSONB losslessly for the
  MFI-2.2 persistence tables. Documented in `docs/canonical_model.md`; paradigm-coverage and
  round-trip tests in `tests/test_canonical_model.py`.

## [1.24.0] - 2026-06-27

### Added
- **Capability search index & query (#3692, V2-MCP-23.2 / MCAT-9.2)** — tenant-scoped free-text
  search over the MCP catalog. `GET /v1/mcp/{tenant_slug}/search?q=…` matches the caller's *current*
  capability surface, backed by the V127 capability-item `tsvector` GIN index (the `@@` predicate
  reuses the index's exact expression, so the index does the matching). `scope` selects what is
  searched — a single capability kind (`tool` / `resource` / `resource_template` / `prompt`), every
  capability kind (omit `scope`), or the endpoints themselves (`scope=endpoint`, matched on
  name + description + category). Hits are ranked by full-text relevance then quality score, and the
  `host` / `category` / `grade` / `visibility` filters compose. Each hit carries its owning
  endpoint's browse context (host, category, score/grade, visibility) and a credential-redacted URL,
  so a result renders without a second read. Like every catalog route, scoping comes from the token's
  `tenant_id` (never the URL slug), so a search only ever returns the caller's own catalog; the
  public-directory variant waits on the MCAT-1.6 public read view. `limit` (1–200, default 50) and
  `offset` paginate.

## [1.23.0] - 2026-06-27

### Added
- **Private browse: endpoints & detail (#3691, V2-MCP-23.1 / MCAT-9.1)** — a tenant-scoped browse
  read over the MCP catalog for the ADE browse view. `GET /v1/mcp/{tenant_slug}/browse` returns every
  live endpoint the caller's tenant owns, bucketed by the host its URL points at, each carrying its
  *current* version snapshot's capability counts (tools / resources / resource templates / prompts),
  quality score/grade, and last-discovered time. Hosts are derived from the stored URL (credentials
  redacted) and the groups are returned in alphabetical host order with per-host endpoint/capability
  totals. Like every catalog route, scoping comes from the token's `tenant_id` (never the URL slug),
  so a tenant only ever browses its own catalog. The browse *detail* half reuses the existing endpoint
  and version-detail reads (tools/resources/prompts + version/score).

## [1.22.0] - 2026-06-27

### Added
- **Invocation logging & safety guards (#3689, V2-MCP-22.3 / MCAT-8.3)** — wraps the test-harness
  route (`POST /v1/mcp/{tenant_slug}/endpoints/{id}/test`) with an audit log and two safety gates so
  a live test call against an external MCP server is recorded, never fired destructively by accident,
  and cannot flood the target.
  - **Redacted invocation log** — every *dispatched* call is recorded in `apiome.mcp_test_invocations`
    (endpoint, version, item, outcome, latency, acting user). Secrets never reach the log: the
    request's auth headers are not part of the row at all, and both the `arguments` and the response
    payload are passed through a new `redact_sensitive_args` helper that masks any secret-named field
    (`token`, `password`, `authorization`, `api_key`, …) before storage. The new row id is returned
    as `invocationId`. Logging is **best-effort** — a DB failure is swallowed (warning logged) and
    never fails the call, since the live invocation has already happened.
  - **Destructive/open-world confirm gate** — a tool whose annotations assert `destructiveHint` or
    `openWorldHint` (as a JSON `true`) is refused with `428` unless the request sets `confirm=true`,
    so an irreversible or open-world tool is never invoked without explicit acknowledgement. A hint
    that is absent or not a clean boolean is treated as unset (no spurious gate).
  - **Per-endpoint rate limit** — accepted, fully-validated calls are throttled per endpoint with an
    in-process fixed window (`429` with `Retry-After` when exhausted), in addition to the global
    per-tenant middleware, so the console cannot flood the external server. Honours the global
    `rate_limit_enabled` kill switch; the ceiling is `APIOME_MCP_TEST_RATE_LIMIT_PER_MINUTE`
    (default 30).
  - New `confirm` request field and `invocation_id` response field; new
    `insert_mcp_test_invocation` DB method (reuses the existing `mcp_test_invocations` table from
    V130 — no schema changes). Tests: 15 route/unit tests over a mocked DB and invocation service
    (redaction of secret args + secrets echoed in responses, the `is_error`/latency log shaping,
    best-effort log failure, headers never logged, the confirm gate for both hints + the safe/
    non-boolean cases, and the rate-limit enforce/disable paths) plus the pure `redact_sensitive_args`
    helper.

## [1.21.0] - 2026-06-27

### Added
- **Test-harness REST endpoints (#3688, V2-MCP-22.2 / MCAT-8.2)** — exposes the MCP invocation
  service (MCAT-8.1) to the UI/CLI as a single tenant-scoped route:
  `POST /v1/mcp/{tenant_slug}/endpoints/{id}/test` with
  `{item_type, item_name, arguments?, auth_override?, timeout_seconds?}`.
  - Names a `tool`/`resource`/`prompt` on the endpoint's **current** discovered surface, looks it
    up in `mcp_capability_items`, and dispatches to the matching method (`tools/call`,
    `resources/read` against the resource's stored concrete `uri`, or `prompts/get`).
  - **Argument validation before the call leaves the server**: a tool's `arguments` are validated
    against its stored JSON Schema `inputSchema` with `jsonschema` (→ `422` on mismatch); a prompt's
    against its declared required arguments. A malformed *stored* schema (the server's fault) is not
    held against the caller — local validation is skipped and the remote server is left to reject.
  - **Optional ephemeral auth override** (`auth_override: {auth_type, payload}`) used for this one
    call only — validated through the same auth-type model that gates stored credentials and **never
    persisted**; when omitted, the endpoint's stored credential is used. `auth_type: none` overrides
    a stored credential to test anonymously.
  - **Per-call timeout** (`timeout_seconds`, 1–120s, default 30) bounds each request in the
    connect → handshake → invoke sequence. The response carries the three outcomes distinctly
    (success / tool-level `isError` / classified transport failure) with `latency_ms`. A remote-server
    failure is reported **in-band** (`completed=false` with a classified `error`), not as a 5xx.
  - Scoped to the caller's token tenant (cross-tenant id → `404`); `409` when the endpoint has no
    discovered surface yet; `404` when the named capability is not on the current surface.
  - New `McpEndpointTestRequest` / `McpAuthOverride` / `McpEndpointTestResponse` models. Tests: 23
    route tests over a mocked DB and invocation service (the three outcomes, schema-invalid args,
    resource/prompt dispatch, ephemeral override applied + not persisted, timeout pass-through,
    tenant scoping, and the not-found/not-discovered/bad-input guards). No schema changes.

## [1.20.0] - 2026-06-27

### Added
- **MCP tool invocation service (#3687, V2-MCP-22.1 / MCAT-8.1)** — the in-process core of the
  MCP query & test harness: connect to a cataloged endpoint with the Epic-2 client, attach its
  stored Epic-6 credentials, invoke one capability, and report content, `isError`, and latency.
  - New `app/mcp_invoke.py` with `invoke_tool` (`tools/call`), `read_resource` (`resources/read`),
    and `get_prompt` (`prompts/get`). Each connects, runs the `initialize` handshake, sends the
    call, and returns an `InvocationResult` carrying `latency_ms` (the connect→response round trip,
    session teardown excluded).
  - **Three outcomes are drawn distinctly** per the MCP tools spec: a tool that runs and succeeds
    (`completed=True`, `is_error=False`, content returned); a tool that runs but reports a
    tool-level error (`isError:true` → `completed=True`, `is_error=True`, error content still
    returned — *not* a transport failure); and a failed call (a top-level JSON-RPC protocol error
    **or** a transport/handshake failure → `completed=False` with a classified `DiscoveryError`,
    reusing the discovery taxonomy so `jsonrpc_error` vs `auth_required` vs `timeout` … is named,
    not collapsed).
  - The service never raises for an expected remote failure (every path returns a latency-bearing
    result); it raises only `ValueError` for a caller error (empty name, non-mapping arguments).
    An `INVOCATION_METHODS` registry maps the catalog `item_type` to its method so the test-harness
    route (MCAT-8.2) can dispatch from a stored capability kind. No schema changes.
  - Tests: unit coverage over a mocked httpx transport (the three outcomes, structured content,
    `resources/read`/`prompts/get`, argument guards, `as_dict` shaping) plus an integration test
    that calls a real loopback stub server end to end. Bump apiome-rest 1.19.0 → 1.20.0;
    ROADMAP updated.

## [1.18.0] - 2026-06-27

### Added
- **MCP scoring, grading & fingerprint persistence (#3685, V2-MCP-21.4 / MCAT-7.4)** — the
  deterministic MCP lint findings (MCAT-7.1…7.3) now roll up into a stored quality score per
  discovered version:
  - New `app/mcp_score.py`: `score_mcp_surface(surface)` consumes the findings from
    `mcp_lint.lint_mcp_surface` and returns an `MCPScoreResult` with a weighted **0-100 score**
    (100 minus capped per-rule severity penalties, so a MUST/`error` failure is weighted heavier
    than a SHOULD/`warning`, which outweighs an `info` advisory), an **A-F grade** from the V124
    house bands (A≥90 … F<60 — the same thresholds the OpenAPI lint score uses), per-rule and
    per-severity tallies, and a stable **report fingerprint** for staleness detection. Pure and
    deterministic: the same surface always yields the same score, grade, and fingerprint.
  - New DB helper `Database.set_mcp_version_score` upserts the score into `apiome.mcp_version_scores`
    (one row per version; a re-score overwrites the row and moves `scored_at`), mirroring the
    per-revision `set_version_quality_score`. The table already existed from V130 — no migration.
  - The score is **auto-captured at version creation**: when discovery records a new
    `mcp_endpoint_versions` snapshot, `mcp_discovery_engine._capture_mcp_version_score` lints,
    scores, and persists it best-effort — a scoring failure is logged and never breaks the
    (already committed) discovery, the MCP analogue of `_capture_version_quality_score()`.

## [1.14.0] - 2026-06-27

### Added
- **Credential REST + redaction (#3681, V2-MCP-20.5 / MCAT-6.5)** — tenants can now set, inspect
  and clear the outbound credential for one of their MCP endpoints, with secrets redacted on every
  response:
  - New tenant-scoped routes under `/v1/mcp/{tenant_slug}/endpoints/{id}/credentials`:
    `PUT` sets/replaces a credential, `GET` returns its **redacted** status, and `DELETE` clears it.
    Each route re-validates the endpoint against the caller's token tenant, so a cross-tenant id
    reads as `404`.
  - **Secrets are never returned.** The plaintext payload supplied on `PUT` is validated against its
    `auth_type` (reusing the MCAT-6.1 auth-type model, so a malformed or header-injecting secret is
    rejected with `422` at the boundary), sealed via the MCAT-6.2 envelope encryption, and stored as
    ciphertext. Every read projects through `mcp_credential_status_from_row`, which reports only
    `auth_type`, a `configured` flag, a fixed `masked_secret` placeholder, `key_version`, non-secret
    `oauth_metadata` and timestamps — the ciphertext and the decrypted secret have no field to escape
    through.
  - `auth_type` on `PUT` must be a secret-bearing scheme (`bearer`/`header`/`oauth2`/`env`); the
    anonymous `none` state is reached by `DELETE` (idempotent — `removed` reports whether a row was
    actually dropped). When credential encryption is not configured a `PUT` fails closed with `503`
    rather than storing an unprotected secret.
  - New DB helpers `upsert_mcp_endpoint_credentials` (one row per endpoint, bumps
    `last_refreshed_at`) and `delete_mcp_endpoint_credentials`.

## [1.13.0] - 2026-06-27

### Added
- **Encryption-at-rest for MCP credentials (#3678, V2-MCP-20.2 / MCAT-6.2)** — outbound MCP
  credentials are now sealed with AES-256-GCM **envelope encryption** before they reach
  `apiome.mcp_endpoint_credentials.encrypted_payload`, so the database holds ciphertext only:
  - New `app/mcp_credential_crypto.py`: a per-secret random data-encryption key (DEK) encrypts the
    JSON payload and is itself wrapped by an environment-supplied master key. `seal_credential_payload`
    returns `(ciphertext, key_version)`; `unseal_credential_payload` decrypts in-memory at connect
    time and is fail-safe (returns `None` for a tampered/foreign/wrong-version blob or a missing key).
  - **Key rotation** via the `key_version` column: several master keys can be configured at once
    (`APIOME_MCP_CREDENTIAL_ENCRYPTION_KEYS`, a JSON version→key map) with a selectable active
    version (`APIOME_MCP_CREDENTIAL_ACTIVE_KEY_VERSION`); old rows stay decryptable while new
    secrets seal under the active key, and `reseal_credential_payload` migrates a row onto it. The
    key-version is bound into the GCM AAD so a row cannot be silently re-pointed at another key.
  - The MCAT-6.1 `decrypt_credential_payload` seam in `app/mcp_credentials.py` is now wired to this
    module; misconfigured keys fail fast at startup (`validate_credential_encryption_keys`). Secrets
    never appear in logs or error messages.

## [1.8.6] - 2026-06-27

### Added
- **Change-report & compare API (#3672, V2-MCP-18.5 / MCAT-4.5)** — four tenant-scoped read
  surfaces over an endpoint's discovery version history, so a UI/CLI can render the timeline,
  inspect any snapshot, and diff any two versions:
  - `GET /v1/mcp/{tenant_slug}/endpoints/{id}/versions` — version history **newest-first**,
    each row carrying `version_seq`, the human-readable date/time `version_tag`, the quality
    `score`/`grade` (when scored), the per-direction `change_counts` it introduced, and an
    `is_current` flag.
  - `GET …/versions/{vid}` — one version's **full surface**: server identity, declared
    `capabilities`, `instructions`, score, change counts, and every normalized capability item.
  - `GET …/versions/{vid}/changes` — the stored `previous → this` diff (empty for the first
    version), in the same stable order an on-demand compare produces.
  - `GET …/versions/compare?base={vid}&target={vid}` — an **on-demand structured diff between
    any two versions** (adjacent or not), computed by the canonical surface diff engine
    (`diff_surfaces`, #3669). The order is normalized older→newer so `added`/`removed` read in
    the natural direction; the same version on both sides yields an empty diff with
    `fingerprint_changed = false`; the result carries `counts` and the `added`/`removed`/
    `modified` `changes`.

  Every route re-validates the endpoint against the caller's **token tenant** (the URL slug is
  informational), and the version reads are scoped to that endpoint, so a cross-tenant or
  cross-endpoint id reads as `404`. New Pydantic models (`McpEndpointVersionSummary`,
  `McpEndpointVersionDetail`, `McpCapabilityItemOut`, `McpVersionChangeOut`,
  `McpVersionCompareResponse`, …) and DB readers (`list_mcp_endpoint_versions`,
  `get_mcp_endpoint_version`, `get_mcp_version_changes`) back the routes; the surface
  reconstruction helper shared with version-creation is now the public
  `reconstruct_surface`, and `compare_endpoint_versions` powers the compare route.

## [1.8.4] - 2026-06-26

### Changed
- **Version creation on change — canonical diff wiring (#3670, V2-MCP-18.3 / MCAT-4.3)** — the
  discovery persistence step (`app.mcp_discovery_engine`) now computes the `previous → new`
  change set with the canonical surface diff engine (`diff_surfaces`, #3669) instead of the
  legacy inline raw-entry diff. On re-discovery, an unchanged `surface_fingerprint` still
  creates **no** new version (only `last_discovered_at` is stamped, so a stable server never
  spams the history); a changed fingerprint inserts exactly one new version
  (`version_seq+1`) with its capability items and the diff persisted as `mcp_version_changes`
  rows, and advances `mcp_endpoints.current_version_id` — all in one transaction. Because the
  diff now runs over each surface's *semantic projection* (the same fields that feed the
  fingerprint), it is in lock-step with change detection — volatile/vendor fields never
  produce phantom change rows — and it records **server-metadata** changes (server
  version/title/name, protocol version, instructions, capabilities) that the prior
  capability-only raw diff missed, with per-field before/after detail. The first version
  emits one `added` row per capability and suppresses synthetic "changed from null"
  server-metadata rows. The previous snapshot is reconstructed from its stored rows via
  `DiscoverySurface.from_rows`, so version-creation and the on-demand compare API (MCAT-4.5)
  share a single diff implementation. `compute_version_changes` is replaced by
  `compute_version_change_rows`.

## [1.8.3] - 2026-06-26

### Added
- **MCP surface diff engine (#3669, V2-MCP-18.2 / MCAT-4.2)** — a pure
  `app.mcp_client.diff.diff_surfaces(base, target)` that compares **any two** normalized
  `DiscoverySurface` objects and returns a structured `SurfaceDiff`: every capability item
  (tool/resource/resource_template/prompt) **added**, **removed**, or **modified**, plus
  server-metadata changes (`protocol_version`, `server_name/title/version`, `instructions`,
  `capabilities`). Items are keyed by `(item_type, name)`, so a rename reads as remove + add and
  an in-place edit reads as a single modify carrying a per-field `FieldChange` breakdown
  (`description`, `inputSchema`/`outputSchema`, `annotations`, prompt `arguments`, resource
  `uri`/`mimeType`, …) with before/after detail. The comparison runs over each surface's *semantic
  projection* — exactly the fields that feed the surface fingerprint (#3668) — so volatile/vendor
  fields (the reserved `_meta` block, a resource `size` hint, unknown extension keys) never produce
  phantom changes and identical surfaces yield an empty diff with `fingerprint_unchanged` true.
  Output is deterministic (changes ordered server-first, then by kind and name) and maps one-to-one
  onto `mcp_version_changes` rows via `SurfaceDiff.to_change_rows(version_id)`, with `counts`
  aggregating added/removed/modified. Diffing arbitrary versions directly (not chaining adjacent
  step-diffs) keeps non-adjacent `vX → vY` comparisons exact. Feeds version-creation (MCAT-4.3) and
  the on-demand compare API (MCAT-4.5). New module `src/app/mcp_client/diff.py`; new tests
  `tests/test_mcp_diff.py`.

## [1.8.2] - 2026-06-26

### Changed
- **Canonical surface fingerprint — semantic projection (#3668, V2-MCP-18.1 / MCAT-4.1)** — the MCP
  `surface_fingerprint` (`DiscoverySurface.fingerprint`) is now computed over a documented *semantic
  projection* of the surface rather than the verbatim wire entries. Only the fields that define the
  server's offering feed the hash: per item, the allow-list in `FINGERPRINT_FIELDS` (tool
  name/title/description/inputSchema/outputSchema/annotations; resource & template
  name/title/description/uri(or uriTemplate)/mimeType/annotations; prompt name/title/description/
  arguments) and, at the surface level, `protocolVersion`, `serverInfo` (name/title/version),
  `capabilities`, and `instructions`. Volatile and vendor-specific data is excluded so it can never
  flip the fingerprint: the reserved `_meta` block is stripped *recursively* at every depth (including
  inside `inputSchema`, prompt `arguments`, and `capabilities`), and a resource's volatile `size` hint
  and any unknown extension keys fall outside the allow-list. Result: an identical offering yields an
  identical fingerprint across runs and hosts, while a single semantically meaningful change (e.g. a
  tool description edit) flips it. The verbatim wire entry is still retained per item (`raw`) for
  storage/round-trip; only the fingerprint narrows to the semantic fields. No DB or API surface change.

## [1.8.1] - 2026-06-26

### Added
- **MCP endpoint lifecycle — delete (#3667, V2-MCP-17.5 / MCAT-3.5)** — endpoints can now be retired
  via `DELETE /v1/mcp/{tenant_slug}/endpoints/{id}`. The endpoint row is *soft* deleted (stamped
  `deleted_at`, flipped to `enabled = false`, `current_version_id` cleared) so it disappears from
  browse/list/get and is skipped by the discovery sweep, while its slug stays reserved against the
  `(tenant_id, slug)` unique constraint. Its child data is *hard* deleted in the same tenant-scoped
  transaction: the credential vault row (the security-critical purge), every discovery job, and every
  version snapshot — whose capability items, change logs and scores cascade away via the
  `ON DELETE CASCADE` chain off `mcp_endpoint_versions`. The route returns a teardown summary
  (`credentials_purged`, `versions_deleted`, `jobs_deleted`) and `404` when the endpoint is not the
  caller's tenant's (or was already deleted). New `database.py` method `soft_delete_mcp_endpoint`, new
  `models.py` response model `McpEndpointDeleteResponse`; covered by route and DB-layer unit tests in
  `tests/test_mcp_catalog_routes.py`. (Enable/disable already shipped in #3663 via the `enabled` PATCH
  field, so this completes the enable/disable/delete lifecycle.)

## [1.6.6] - 2026-06-26

### Added
- **MCP catalog endpoint CRUD (#3663, V2-MCP-17.1 / MCAT-3.1)** — tenants can now register and manage
  external MCP servers in a catalog. New `app/mcp_catalog_routes.py` exposes the `mcp_endpoints_router`
  (registered in `main.py`) with tenant-scoped CRUD over `apiome.mcp_endpoints`:
  `POST /v1/mcp/{tenant_slug}/endpoints` (register), `GET …/endpoints` (list),
  `GET …/endpoints/{id}` (fetch), and `PATCH …/endpoints/{id}` (partial update). Tenant scoping comes
  from the existing `validate_authentication` dependency (JWT Bearer or `X-API-Key`): every query is
  scoped to the caller's `tenant_id` — never the URL slug — so a cross-tenant id reads as `404`. The
  catalog `slug` is auto-derived from the endpoint name (or an explicit `slug` override) and made
  unique within the tenant by the DB layer (`base`, then `base-2`, `base-3`, …), with the
  `(tenant_id, slug)` unique constraint as a backstop that surfaces as `409`. New `database.py` methods
  `list_mcp_endpoints`, `get_mcp_endpoint`, `insert_mcp_endpoint`, `update_mcp_endpoint`, and the
  `_next_available_mcp_slug` resolver; new `models.py` request/response models
  (`McpEndpointCreate` / `McpEndpointUpdate` / `McpEndpointOut`, transport + visibility enums, positive
  cadence bound, camelCase aliases). Covered by route, model, and DB-layer unit tests in
  `tests/test_mcp_catalog_routes.py`; OpenAPI docs are generated for all four operations.

## [1.6.3] - 2026-06-26

### Added
- **MCP discovery list methods + pagination (#3659, V2-MCP-16.3)** — the capability-enumeration layer
  of the MCP discovery client (`app/mcp_client/discovery.py`), sitting on top of the `initialize`
  handshake. `discover_listings()` walks `tools/list`, `resources/list`, `resources/templates/list`
  (result key `resourceTemplates`), and `prompts/list`, returning a `DiscoveryListings` of raw items
  per category. Each endpoint is queried **only** when the server declared its owning capability in
  `initialize` (the single `resources` capability gates both resource endpoints); undeclared endpoints
  are skipped and reported in `DiscoveryListings.skipped`. The lower-level `paginate()` helper follows
  the opaque `cursor`/`nextCursor` loop to exhaustion, accumulating every page. Because the cursor is
  server-supplied, the loop is guarded against non-terminating servers two ways — a repeated cursor (a
  cycle) and exceeding `DEFAULT_PAGE_LIMIT` pages both raise `McpPaginationError`; a declared endpoint
  that returns a JSON-RPC error raises `McpDiscoveryError`. Covered by mocked-httpx unit tests plus an
  integration test that pages a real multi-page loopback stub and confirms undeclared capabilities are
  never requested.

## [1.6.2] - 2026-06-26

### Added
- **MCP initialize handshake + version negotiation (#3658, V2-MCP-16.2)** — the lifecycle layer on top
  of the Streamable HTTP transport (`app/mcp_client/handshake.py`). `initialize_session()` sends
  `initialize` with our `protocolVersion`, `capabilities`, and `clientInfo`; parses `serverInfo`,
  `capabilities`, and `instructions`; and negotiates the protocol version (echo, result-level fallback,
  `-32602` fallback-and-retry, disconnect on unsupported). The negotiated version is recorded on the
  transport (pinning `MCP-Protocol-Version` on later requests) and returned on `InitializeResult`,
  after which `notifications/initialized` completes the handshake. Covered by mocked-httpx unit tests
  plus an integration test negotiating against real loopback stub servers for both supported revisions.

## [1.6.1] - 2026-06-26

### Added
- **MCP transport client over Streamable HTTP (#3657, V2-MCP-16.1)** — the network foundation of the
  MCP discovery client (`app/mcp_client/transport_http.py`). `StreamableHttpTransport` speaks JSON-RPC
  2.0 to a single `…/mcp` endpoint per the MCP `2025-06-18` spec: every message is `POST`ed with
  `Accept: application/json, text/event-stream`, and both response shapes are handled transparently —
  a single `application/json` object or a `text/event-stream` SSE stream drained until the matching
  response id arrives (server-initiated messages on the stream are dispatched to an optional handler).
  Notifications are sent without an id and accept `202`. The server's `Mcp-Session-Id` is captured at
  `initialize` and echoed on every later request, `MCP-Protocol-Version` is pinned on all
  post-initialization requests, and the session is torn down with `DELETE` (a `405` refusal is
  tolerated). `400`/`405` surface as `McpHttpStatusError`; a `404` while a session is active surfaces
  as `McpSessionExpiredError` and clears the local session. Transport security: plaintext `http://` is
  allowed only to loopback hosts (local reference servers) unless `allow_insecure_http=True`, and an
  `Origin` header is always sent. Covered by mocked-httpx unit tests plus an integration test against a
  real loopback stub MCP server.

## [1.4.0] - 2026-06-24

### Added
- **Observability & error handling (#3617, RC1-3.2)** — production-grade diagnosability for the REST
  service. Structured JSON logging via `structlog` (`app/logging_config.py`, mirroring the MCP setup)
  emits one JSON object per line with `timestamp`, `level`, `logger`, `event` and a per-request
  `request_id` that is bound for the whole request lifetime — so every log line a handler emits is
  correlated to its request. A new `ObservabilityMiddleware` (`app/observability.py`, installed as the
  outermost layer) assigns/propagates the id via the `X-Request-ID` header (reusing an upstream value
  when present), records an in-process metrics registry (total requests, requests/sec, error rate,
  in-flight gauge, latency p50/p95/p99), and logs one access line per request.
- **Consistent error envelope** — exception handlers wrap every `4xx`/`5xx` (including
  `RequestValidationError` and the rate limiter's `429`) in a uniform shape that *preserves* FastAPI's
  `detail` for backward compatibility while adding an `error` object (`status`/`message`/`type`/
  `request_id`) and a top-level `request_id`. An unhandled-exception handler logs the full stack trace
  correlated to the request id (error tracking) and returns a safe generic 500 that never leaks
  internal details.
- **Health / readiness probes** — `GET /livez` (liveness, no DB), `GET /readyz` (readiness; `503` when
  the database is unreachable), and the backward-compatible `GET /health`. Wired into `docker-compose`
  (the `rest` healthcheck now uses `/readyz`; the `mcp` service gained a `/health` healthcheck).
- **Minimal ops dashboard** (platform-admin only) — `GET /v1/ops/metrics`, `/v1/ops/backups`,
  `/v1/ops/status`, and a dependency-free HTML `/v1/ops/dashboard`. Backup status is read from the
  RC1-1.3 backup manifests (`app/backup_status.py`): latest backup per scope, age, and a `stale` flag
  against the configured RPO window.
- New settings: `APIOME_LOG_LEVEL`, `APIOME_LOG_JSON`, `APIOME_REQUEST_ID_HEADER`,
  `APIOME_BACKUP_DIR`, `APIOME_BACKUP_STALE_AFTER_HOURS`.

## [1.3.0] - 2026-06-23

### Added
- **Mock Server (#3615, RC1-2.2)** — provision a hosted mock from any published version and consume
  the designed API before a backend exists. New management plane `POST/GET /v1/mocks/{tenant_slug}`
  (provision, list), `GET/DELETE /v1/mocks/{tenant_slug}/{id}` (inspect, destroy), and
  `PUT .../active-scenario` (switch scenario), all tenant-scoped + authenticated. The OpenAPI
  document generated for the version (same output as `/v1/swagger/...`) is frozen into the instance,
  so the mock is stable for its lifetime. New public data plane `ANY /v1/mock/{id}/...` replays
  schema-valid responses synthesised deterministically from the response schemas
  (`app/mock_data_generator.py`, validated with `jsonschema`) and applies the selected scenario
  (`app/mock_engine.py`). Per-operation scenarios override status / latency / body and are selectable
  per instance or per request via the `X-Mock-Scenario` header; four built-ins ship (happy-path,
  server-error, not-found, slow). Free-tier guardrails: instances auto-expire (`410 Gone` past
  `expires_at`) and are rate limited per instance (`429` with `Retry-After`). Backed by migration
  V123 (`apiome.mock_instances`). Configurable via `APIOME_MOCK_SERVER_ENABLED` (default on),
  `APIOME_MOCK_DEFAULT_TTL_HOURS` (default 24), `APIOME_MOCK_MAX_TTL_HOURS` (default 168),
  and `APIOME_MOCK_RATE_LIMIT_PER_MINUTE` (default 60).

## [1.2.0] - 2026-06-23

### Added
- **SSRF guard for user-supplied URL fetches (#3612)** — a new `app/ssrf_guard.py` vets every URL
  the import-from-URL and public repository-registration paths fetch: http/https only, no embedded
  credentials, and DNS resolution with rejection of any non-public address (loopback, RFC1918,
  link-local incl. the `169.254.169.254` metadata IP, multicast, reserved, unspecified — IPv4 and
  IPv6 including IPv4-mapped). Installed as an httpx request event hook so each redirect hop is
  re-validated, closing redirect-based bypasses. Applied to `import_ingestion._fetch_url_text`, the
  generic-URL branch of `repository_validation.validate_public_clone_url`, and the GitLab branch
  (whose API origin is derived from the tenant-supplied host). Set
  `APIOME_SSRF_ALLOW_PRIVATE=true` to disable IP filtering for local development.
- **Per-tenant rate limiting (#3612)** — a new `app/rate_limit.py` middleware buckets requests by
  API key (hashed) → tenant slug (from the path) → client IP, enforcing a configurable fixed window.
  Authenticated traffic uses the higher limit, public traffic the lower; over-limit requests get
  `429` with `Retry-After`, and every response carries `X-RateLimit-{Limit,Remaining,Reset}`.
  Configurable via `APIOME_RATE_LIMIT_ENABLED` (default on),
  `APIOME_RATE_LIMIT_AUTHENTICATED_PER_MINUTE` (default 600),
  `APIOME_RATE_LIMIT_PUBLIC_PER_MINUTE` (default 120), and
  `APIOME_RATE_LIMIT_WINDOW_SECONDS` (default 60). `/health` and the docs are exempt. Limits
  are per replica (in-process counter); a shared store is the path to multi-replica enforcement.

### Fixed
- **GitLab clone-URL SSRF + crash (#3612)** — `parse_gitlab_project_path` built its API origin from
  `urlparse(...).host` (nonexistent attribute; raised `AttributeError`) and the GitLab branch
  fetched the tenant-controlled host with an unguarded client. Now reconstructs the origin from
  `hostname`/`port` and routes the fetch through the SSRF guard.

## [1.0.26] - 2026-06-23

### Added
- **Registry coverage/stats endpoint (#3454)** — `GET /v1/types/{tenant_slug}/stats` returns the
  tenant's registry coverage KPIs as a single server-side aggregate: core type count, tenant type
  count, imported count, properties bound, bound class count, unresolved `$ref` count, and
  namespace count. Backed by `Database.get_registry_coverage_stats(tenant_id)`, which aggregates
  over the extended `apiome.primitives` table (type/namespace/import counts and unresolved `refs`
  edges) and the tenant's `apiome.class_properties` bindings on the existing `apiome-db`
  connection — replacing the client-side stat computation in the Primitives overview dashboard
  (#3467). Gated by the `require_primitives_registry` entitlement and tenant-scoped to the
  authenticated caller. (The endpoint, model, and DB aggregate first shipped alongside #3467; this
  release documents and formally closes #3454.)

## [1.0.23] - 2026-06-23

### Added
- **Primitives type-registry entitlement & feature gating (#3478)** — the advanced Type Registry
  surface can now be gated behind a per-tenant `primitives-registry` entitlement. A reusable
  `require_primitives_registry` dependency (`app/feature_gating.py`) guards every `/v1/types/*`
  route (resolver, namespaces, settings, stats) plus the `/v1/primitives/*` import pipeline
  (`/import`, `/import/review`, `/import/stage`, `/imports`, `/imports/{id}`) and the `/unresolved`
  resolver. Baseline primitives CRUD (list/get/create/update/delete) and `/health` are never gated.
- **`Database.tenant_has_feature_flag(tenant_id, user_id, flag_name)`** — resolves a named feature
  flag for a tenant/user with precedence per-user override → per-tenant override → license default,
  honoring the flag's global master switch (`apiome.feature_flags.enabled`).

### Changed
- **`APIOME_PRIMITIVES_REGISTRY_GATING` operator switch (default off)** — when off, the gate is
  a pass-through and behavior is unchanged (every authenticated tenant reaches the advanced routes);
  when on, non-entitled tenants receive `403`. The `primitives-registry` flag is seeded by
  apiome-db migration `20260623-130000.sql` (bundled into the Paid and Sponsor plans, not Free)
  and is managed through the existing admin Feature-Flag panel.

## [1.0.20] - 2026-06-22

### Added
- **Import review: conflicts, dedupe, validation report (#3464)** — the Primitives import path no
  longer skips duplicates silently. New `app/primitives_review.py` provides the pure review logic:
  each imported definition is classified against the registry as **New** (nothing shares its `$id`),
  **Identical** (an existing type has the same `$id` and an identical schema), or **Conflict** (same
  `$id`, different schema), and a caller's per-type resolution choice (**keep** / **overwrite** /
  **rename**) is turned into a concrete commit decision by `decide()`.
- **`POST /v1/primitives/{tenant_slug}/import/review`** — a dry-run that writes nothing and returns
  the classification, a draft 2020-12 validation report, the `$ref` rewrites, the unresolved-ref
  mapping, and the resolution choices each conflict offers. This is the report the import wizard
  (#3469) renders before commit; the same classification drives the commit, so the committed result
  matches the review.

### Changed
- **`POST /v1/primitives/{tenant_slug}/import`** now honors review choices. New request fields:
  `dedupe` (default `true` — an Identical definition is skipped as a duplicate) and `resolutions`
  (a `name -> {action, new_name}` map). On commit, a conflict resolved `overwrite` updates the
  existing row in place, `rename` creates a copy under a new (slugified) name, and the default
  `keep` leaves the existing type but **surfaces** the conflict instead of dropping it. The import
  report gains `overwritten` / `renamed` / `identical` buckets (and their totals) plus a per-type
  `reviews` list, so the report can be shown to match the outcome; provenance counts reflect rows
  written (created + overwritten + renamed) vs. passed over (deduped + kept).
- Regenerated `openapi.{json,yaml}` for the new endpoint, request fields, and `ImportResolution`
  model; bumped to 1.0.20 (npm) / 1.0.90 (py).

## [1.0.19] - 2026-06-22

### Added
- **`$ref` rewrite + namespace/scope mapping (#3463)** — imported definitions now have their refs
  rewritten for their committed place in the registry instead of carrying document-local pointers.
  New `app/primitives_rewrite.py` provides `rewrite_import_schema()`, which (1) rewrites every
  intra-source pointer (`#/$defs/Money`, `#/definitions/Money`, `#/types/Money`) to a relative
  registry ref at the sibling's committed `$id` (`./money`, matching the `$id` leaf-slug; a deeper
  pointer like `#/$defs/Money/properties/c` is preserved as `./money#/properties/c`), and (2) maps a
  recognized string `format` (`email`, `uuid`, `uri`, `date`, `date-time`, `time`) to its seeded
  `std/v0/types` core type by injecting a relative `$ref` (mirroring the seed's
  `{"$ref": "../primitives/string", "format": "email"}` shape; an author's explicit `$ref` is never
  overridden). Because both rewrites produce ordinary registry-relative `$ref` values, the existing
  resolver (#3456) turns them into persisted `refs` edges with no separate internal-edge bookkeeping
  — so imported refs are stored relative and resolve via Epic 3, and core-format mapping resolves to
  the core type. `POST /v1/primitives/{tenant_slug}/import` applies this on commit for both the JSON
  Schema and type-def-bundle paths; a new `map_core_formats` request flag (default `true`) toggles
  the format mapping, and the import report gains a per-type `rewrites` map for the review table.

### Changed
- **Import commit no longer persists `internal` ref edges (#3463).** The `$defs`/`types` sibling
  pointers that #3461/#3462 captured as `{status: "internal"}` edges are now rewritten to relative
  registry refs and resolved like any other edge, so a committed primitive's `refs` carries only
  `resolved`/`unresolved` edges. (The staging path's per-candidate `internal_refs` metadata is
  unchanged.)

## [1.0.18] - 2026-06-22

### Added
- **Type-definition bundle importer (#3462)** — the `type-def-bundle` source kind now expands into
  many interlinked primitives instead of being enumerated shallowly. New `app/primitives_bundle.py`
  provides `parse_type_def_bundle()` (a parsed `.json`/`.yaml` bundle → discrete types) and
  `expand_zip_bundle()` (a `.zip` archive whose JSON/YAML members are each one type → a merged bundle
  document). A bundle reads its types from a `types` container (`$defs`/`definitions` accepted as
  equivalents); each type captures its **inter-type** `$ref` edges — refs at a sibling bundle type
  (`#/types/Money`, `#/$defs/Money`, `#/definitions/Money`) — as `internal` edges in the `refs` JSONB
  column for the rewrite stage (#3463), and is validated against draft 2020-12. The staging pipeline
  (`POST /import/stage`) now deep-parses bundle candidates (internal refs + per-type validation,
  matching the JSON Schema path), and `POST /v1/primitives/{tenant_slug}/import` with
  `source_kind='type-def-bundle'` commits a bundle of N types as N `apiome.primitives` rows with their
  refs intact. A malformed bundle (no recognizable container, no usable types, bad/oversized/duplicate
  zip members) is rejected with a clear 400 / `BundleError` message. The per-definition commit loop is
  shared by the JSON Schema and bundle paths via `_commit_imported_definitions()`.

## [1.0.16] - 2026-06-22

### Added
- **Import pipeline core + ingestion (#3460)** — new `POST /v1/primitives/{tenant_slug}/import/stage`,
  the single orchestration path for all import sources. It ingests a document by one of four
  methods — `paste` / `file` (inline text), `url` (http/https fetch), or `git` (a file from a public
  github.com repo, reusing the repository-scan fetcher) — parses it as JSON **or** YAML, and detects
  the candidate types it carries, dispatched on source kind: `$defs`/`definitions` for `json-schema`
  (a bare document is one candidate), the `types`/`$defs` container for `type-def-bundle`, and
  `components.schemas` for `openapi`. The result is *staged*, not committed — each candidate carries
  its JSON Pointer and `$ref` count for the downstream parse (#3461/#3462), `$ref` rewrite (#3463),
  and conflict review (#3464) stages. Every staged import records an auditable `staged`
  `apiome.primitive_imports` row (reusing #3448; no new table). The legacy paste-and-commit
  `POST /v1/primitives/{tenant_slug}/import` is unchanged. New `app/import_ingestion.py` (per-method
  fetch + JSON/YAML parse), `app/import_pipeline.py` (pure detection + staging), and
  `PrimitiveImportStageRequest` / `PrimitiveImportStageResult` / `StagedTypeCandidate` /
  `GitSourceLocator` models.

## [1.0.13] - 2026-06-22

### Added
- **Resolver API + dependency listing (#3459)** — new `POST /v1/types/{tenant_slug}/resolve`
  re-resolves every `$ref` dependency edge across the tenant's primitives against the *current*
  registry state and returns the per-primitive dependency listing the resolver UI (#3470) and
  Designer consume. Each stored edge's `resolved`/`unresolved` status is recomputed with the same
  existence test as save-time resolution (#3456) — so a target created since the edge was last
  computed now resolves and a deleted one now dangles — and the refreshed edges are persisted for
  the tenant's own primitives whose status changed ("re-resolve updates statuses"). Each resolved
  edge is enriched with its dependency target's id and name so the response is the dependency
  graph. The top-level counts mirror the coverage KPIs of `GET …/unresolved` (#3457/#3454), plus
  `reresolved_primitive_count` for how many primitives this pass updated. New `ResolveResponse` /
  `ResolvedPrimitiveRefs` / `ResolvedRefEdge` models and `app/type_resolver.py` (pure edge
  re-evaluation + dependency enrichment); system-core rows are listed but never written back.

## [1.0.12] - 2026-06-22

### Added
- **Unresolved-reference detection, flags & counts (#3457)** — a primitive's relative `$ref`
  edges are resolved and flagged `resolved`/`unresolved` on save/import (#3456); this adds the
  detection surface and the re-resolve-clears behavior on top of it. New
  `GET /v1/primitives/{tenant_slug}/unresolved` returns the tenant's total unresolved-edge count,
  the number of affected primitives, and a per-primitive breakdown (each with only its unresolved
  edges) — feeding the registry coverage/stats KPIs (#3454) and the resolver UI (#3470). New
  `UnresolvedRefsResponse`/`UnresolvedRefPrimitive` models and DB aggregates
  `count_unresolved_refs` / `get_primitives_with_unresolved_refs` (scoped to the caller's tenant,
  aggregating over the `apiome.primitives.refs` JSONB column). Creating, importing, or repinning a
  primitive now runs a best-effort reconcile (`mark_refs_resolved_to_target`) that clears the
  unresolved flag on the tenant's other primitives whose dangling edge pointed at the new type's
  `$id`, so "fixing the target clears on re-resolve" without re-saving each dependent by hand.

## [1.0.11] - 2026-06-22

### Added
- **Type definition draft 2020-12 validation (#3452)** — the Primitives create, update, and
  import endpoints now strictly validate the supplied `schema` against the JSON Schema
  **draft 2020-12 meta-schema** server-side (new `app/schema_validation.py`, backed by the
  `jsonschema` library). An invalid schema is rejected at the REST boundary with HTTP 422 and a
  structured, field-level `errors` list (`path` / `message` / `keyword`) instead of being
  persisted. Valid types persist with a stable, derived JSON Schema `$id` (the
  `apiome.primitives.schema_id` column) — an author-declared `$id` is honored, otherwise it is
  computed from the namespace base URI (or a stable tenant-default base) plus a url-safe slug of
  the name — and a stamped `draft` (default `2020-12`, read from `$schema`). The stored schema
  document is stamped with its `$id`/`$schema` so it is self-describing. `PrimitiveCreateRequest`/
  `PrimitiveUpdateRequest` gained optional `namespace`/`base_uri` placement fields (and `enabled`
  on update); `PrimitiveSchema` now exposes `schema_id`/`draft`/`namespace`/`base_uri`. The import
  path runs the same validator per `$defs` definition, recording invalid definitions in the import
  report (`error: "invalid_schema"` with `details`) without blocking the valid ones.

## [1.0.10] - 2026-06-22

### Added
- **Namespace CRUD API (#3451)** — added the type-registry namespace endpoints
  `GET/POST/PUT /v1/types/{tenant_slug}/namespaces` over the existing `apiome-db`
  connection. Namespaces (scope, base URI, version root, visibility, default) are persisted in
  the new `apiome.type_namespaces` table, whose `namespace`/`base_uri` columns mirror those on
  `apiome.primitives` (the type-count join key). `GET` lists system-core (`std/*`) namespaces plus
  the caller tenant's own, each with its tenant-scoped type count. `POST`/`PUT` require a tenant
  administrator and operate on tenant-owned namespaces only; the namespace path is immutable, and
  base URI / version root are derived from the path when omitted. System-core namespaces are
  platform-governed and read-only via the API (no platform-admin role is exposed), so creating or
  modifying one returns 403. Backed by `TypeNamespaceSchema`/`TypeNamespaceCreateRequest`/
  `TypeNamespaceUpdateRequest` models and `Database.list/get/create/update_type_namespace()` DAOs.

## [1.0.9] - 2026-06-22

### Added
- **Type-registry service skeleton + health (#3450)** — added an anonymous
  registry-layer health/ping endpoint `GET /v1/primitives/health` that reports the
  `apiome-db` connection status backing the registry's `apiome.primitives` storage
  (overall `status`, `connection`, and whether the storage table is present). The existing
  tenant-scoped primitive CRUD/import endpoints are unchanged and remain authenticated, so
  current clients are unaffected. Backed by a new `Database.registry_ping()` probe and a
  `RegistryHealthResponse` model.

## [1.0.8] - 2026-06-22

### Added
- **Primitive import provenance & property binding (#3448)** — every
  `POST /v1/primitives/{tenant}/import` now records an auditable provenance row in the new
  `apiome.primitive_imports` table (source kind, options, and a JSON outcome report with
  imported/skipped/errors) and marks imported primitives `source='imported'`. New read
  endpoints `GET /v1/primitives/{tenant}/imports` and `GET /v1/primitives/{tenant}/imports/{id}`
  expose the history and its report. Class properties gained a `primitive_id` foreign key to
  `apiome.primitives` plus a stored `primitive_ref`, surfaced on the Designer read path so a bound
  property reloads its `$ref`; bindings are carried through class and version copies.

## [1.0.7] - 2026-06-22

### Removed
- **Separate type-registry database (#3447)** — removed the separate type-registry database
  and its dedicated REST connection, configuration, and health reporting. The type registry
  now lives in the main `apiome-db` database; `GET /health` reports only the core
  database status again. Reverses #3446.

## [1.2.0] - 2024-12-07

### Added
- **JSON Schema Endpoints**
  - New endpoint: `GET /v1/json/{tenant-slug}/{project-slug}/{version-slug}` - Get JSON Schema for all classes in a version
  - New endpoint: `GET /v1/json/{tenant-slug}/{project-slug}/{version-slug}/{class-name}` - Get JSON Schema for a single class
  - Content negotiation support for JSON and YAML formats (same as OpenAPI endpoints)
  - API key authentication for private versions (same as OpenAPI endpoints)
  - Full compliance with JSON Schema Draft 2020-12 specification
  - Schema definitions using $defs keyword
  - Automatic $id generation for schema identification
  - Support for nested and inline properties
  - Support for composition patterns (allOf, anyOf, oneOf)

- **New Python Module: `jsonschema_generator.py`**
  - Function: `generate_jsonschema_spec()` - Generate JSON Schema for all classes
  - Function: `generate_class_jsonschema_spec()` - Generate JSON Schema for single class
  - Reuses OpenAPI schema builder for consistency
  - Automatic format conversion to JSON Schema keywords

- **JSON Schema Documentation**
  - `docs/JSON_SCHEMA_ENDPOINTS.md` - Complete endpoint documentation
  - `docs/JSON_SCHEMA_QUICK_REFERENCE.md` - Developer quick reference guide

## [1.1.0] - 2024-12-07

### Added
- **Arazzo 1.0.1 Workflow Specification Endpoints**
  - New endpoint: `GET /v1/arazzo/{tenant-slug}/{project-slug}/{version-slug}` - Get workflows for all classes in a version
  - New endpoint: `GET /v1/arazzo/{tenant-slug}/{project-slug}/{version-slug}/{class-name}` - Get workflow for a single class
  - Content negotiation support for JSON and YAML formats (same as OpenAPI endpoints)
  - API key authentication for private versions (same as OpenAPI endpoints)
  - CRUD workflow generation (Create, Read, Update, Delete) for each class
  - Step dependency management and output capture
  - OpenAPI schema references in workflow payloads

- **New Python Module: `arazzo_generator.py`**
  - Function: `generate_arazzo_spec()` - Generate Arazzo spec for all classes
  - Function: `generate_class_arazzo_spec()` - Generate Arazzo spec for single class
  - Automatic CRUD workflow pattern generation
  - Step dependency chain creation
  - Success criteria definition

- **Comprehensive Documentation**
  - `README.md` - Complete project documentation with examples
  - `docs/ARAZZO_ENDPOINTS.md` - Detailed endpoint documentation
  - `docs/ARAZZO_QUICK_REFERENCE.md` - Developer quick reference guide
  - `docs/ARAZZO_IMPLEMENTATION.md` - Implementation summary and technical details

- **Test Suite**
  - `test_arazzo_endpoints.py` - Complete test coverage for Arazzo endpoints
  - Endpoint registration tests
  - Spec format validation tests
  - Workflow structure tests
  - Step dependency tests

### Changed
- Updated root endpoint (`/`) to list new Arazzo endpoints in the endpoint discovery response
- Updated `main.py` with new endpoint handlers and imports

### Technical Details
- Arazzo specification version: 1.0.1
- Maintains 100% parity with OpenAPI endpoints
- Same authentication and authorization patterns
- Same content negotiation behavior
- Same error handling and HTTP status codes

## [1.0.0] - 2024-11-XX

### Added
- Initial release
- OpenAPI 3.1.0 specification endpoints
- Swagger UI integration
- API key authentication
- Multi-tenant support
- Content negotiation (JSON/YAML)
- Database integration with PostgreSQL

[1.2.0]: https://github.com/your-org/apiome-rest/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/your-org/apiome-rest/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/your-org/apiome-rest/releases/tag/v1.0.0



