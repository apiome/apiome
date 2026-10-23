"""VSAM cluster definitions (IDCAMS) import — FMT-11.3 (#5484).

Covers the IDCAMS command reader (JCL wrapping, comments, continuations, abbreviations, IF/THEN
guards, DATA / INDEX components), the LISTCAT listing reader, the canonical projection (a record per
cluster with its primary and alternate keys, the envelope as declared metadata, declared limits for
what IDCAMS cannot describe), filesets with cross-member references, every refusal's taxonomy code,
detection, and the registry / ledger wiring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import pytest

from app.canonical_model import ApiParadigm, CanonicalApi, CanonicalField, Type, TypeKind
from app.data_contract_facts import SCHEMA_ONLY_FORMATS
from app.fileset import IntakeFileset
from app.format_capability_registry import capability_for
from app.format_version_coverage import version_coverage_for
from app.import_preview_manifest import PROVENANCE_EXTRA_KEYS, _mainframe_misc_capability_rows
from app.import_source import (
    DetectionInput,
    ImportSourceError,
    get_import_source,
    load_builtin_import_sources,
)
from app.mainframe_misc_import_source import CicsBmsImportSource, VsamIdcamsImportSource
from app.mainframe_misc_normalizer import VSAM_EXTRAS_KEY, VSAM_LIMIT_DETAILS
from app.vsam_idcams_parser import has_idcams_commands, is_listcat_listing, parse_vsam_text

load_builtin_import_sources()

EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "vsam-idcams"

KSDS = """  DEFINE CLUSTER (NAME(TEST.ORDER.KSDS) -
                  INDEXED -
                  KEYS(12 4) -
                  RECORDSIZE(100 300) -
                  SHAREOPTIONS(2 3) -
                  CYLINDERS(10 2) -
                  VOLUMES(VOL001 VOL002))
"""


def _adapter() -> VsamIdcamsImportSource:
    return VsamIdcamsImportSource()


def _import(text: str, name: str = "test.idcams") -> CanonicalApi:
    adapter = _adapter()
    return adapter.normalize(adapter.parse(text, source_label=name))


def _import_fileset(members: Dict[str, str], root: str) -> CanonicalApi:
    adapter = _adapter()
    return adapter.normalize(adapter.parse_fileset(IntakeFileset.from_members(members, root=root)))


def _code(text: str, name: str = "test.idcams") -> Optional[str]:
    try:
        _adapter().parse(text, source_label=name)
    except ImportSourceError as exc:
        return exc.code
    return None


def _type(api: CanonicalApi, key: str) -> Type:
    found = api.type_by_key(key)
    assert found is not None, f"{key} not in {[t.key for t in api.types]}"
    return found


def _field(api: CanonicalApi, type_key: str, name: str) -> CanonicalField:
    return next(f for f in _type(api, type_key).fields if f.name == name)


def _limits(api: CanonicalApi) -> Dict[str, int]:
    return {limit["construct"]: limit["count"] for limit in api.extras[VSAM_EXTRAS_KEY]["capability_limits"]}


# ===========================================================================
# Commands → records
# ===========================================================================


class TestCluster:
    def test_ksds_becomes_a_record_with_its_primary_key(self) -> None:
        api = _import(KSDS)
        assert api.paradigm is ApiParadigm.DATA_SCHEMA and api.format == "vsam-idcams"
        record = _type(api, "vsam.TEST_ORDER_KSDS")
        assert record.kind is TypeKind.RECORD
        key = _field(api, "vsam.TEST_ORDER_KSDS", "PRIMARY_KEY")
        assert key.type.name == "bytes"
        assert key.constraints is not None and (key.constraints.min_length, key.constraints.max_length) == (12, 12)
        assert key.extras[VSAM_EXTRAS_KEY] == {"role": "primary", "offset": 4, "length": 12, "unique": True}

    def test_envelope_is_declared_metadata(self) -> None:
        metadata = _type(_import(KSDS), "vsam.TEST_ORDER_KSDS").extras[VSAM_EXTRAS_KEY]
        assert metadata["dataset"] == "TEST.ORDER.KSDS"
        assert metadata["organisation"] == "KSDS"
        assert metadata["recordSize"] == {"average": 100, "maximum": 300, "fixed": False}
        assert metadata["shareOptions"] == {"crossRegion": 2, "crossSystem": 3}
        assert metadata["storage"] == {
            "space": {"unit": "cylinders", "primary": 10, "secondary": 2},
            "volumes": ["VOL001", "VOL002"],
        }

    def test_fixed_records_are_marked_fixed(self) -> None:
        api = _import("DEFINE CLUSTER (NAME(A.B) INDEXED KEYS(4 0) RECORDSIZE(80 80))")
        record = _type(api, "vsam.A_B")
        assert record.extras[VSAM_EXTRAS_KEY]["recordSize"]["fixed"] is True
        assert "fixed 80-byte records" in (record.description or "")

    def test_every_record_declares_its_missing_field_layout(self) -> None:
        assert _limits(_import(KSDS)) == {"vsam.record_layout": 1}

    @pytest.mark.parametrize(
        ("flag", "size", "organisation"),
        [("NONINDEXED", "(100 200)", "ESDS"), ("NUMBERED", "(64 64)", "RRDS"), ("NUMBERED", "(64 128)", "VRRDS")],
    )
    def test_organisations(self, flag: str, size: str, organisation: str) -> None:
        api = _import(f"DEFINE CLUSTER (NAME(X.Y) {flag} RECORDSIZE{size})")
        record = _type(api, "vsam.X_Y")
        assert record.extras[VSAM_EXTRAS_KEY]["organisation"] == organisation
        assert record.fields == []

    def test_unwritten_organisation_defaults_to_indexed(self) -> None:
        record = _type(_import("DEFINE CLUSTER (NAME(X.Y) KEYS(8 0) RECORDSIZE(40 40))"), "vsam.X_Y")
        assert record.extras[VSAM_EXTRAS_KEY]["organisation"] == "KSDS"
        assert record.extras[VSAM_EXTRAS_KEY]["organisationDeclared"] is False

    def test_linear_dataset_is_a_declared_limit_not_a_record(self) -> None:
        api = _import(KSDS + "  DEFINE CLUSTER (NAME(TEST.LDS) LINEAR CYLINDERS(5 1))\n")
        assert [t.key for t in api.types] == ["vsam.TEST_ORDER_KSDS"]
        assert _limits(api)["vsam.linear_dataset"] == 1

    def test_data_and_index_components(self) -> None:
        text = """DEFINE CLUSTER (NAME(P.KSDS) INDEXED) -
               DATA (NAME(P.KSDS.DATA) KEYS(6 0) RECORDSIZE(50 50) CONTROLINTERVALSIZE(4096)) -
               INDEX (NAME(P.KSDS.INDEX))"""
        api = _import(text)
        metadata = _type(api, "vsam.P_KSDS").extras[VSAM_EXTRAS_KEY]
        assert metadata["dataComponent"] == "P.KSDS.DATA"
        assert metadata["indexComponent"] == "P.KSDS.INDEX"
        assert metadata["controlIntervalSize"] == 4096
        assert _field(api, "vsam.P_KSDS", "PRIMARY_KEY").constraints.max_length == 6  # type: ignore[union-attr]

    def test_abbreviations(self) -> None:
        api = _import("DEF CLUSTER (NAME(Q.R) IXD KEYS(4 2) RECSZ(20 20) SHR(1 3) CYL(1 1) VOL(V1))")
        metadata = _type(api, "vsam.Q_R").extras[VSAM_EXTRAS_KEY]
        assert metadata["organisation"] == "KSDS"
        assert metadata["shareOptions"]["crossRegion"] == 1
        assert metadata["storage"]["volumes"] == ["V1"]

    def test_quoted_and_lowercase_names(self) -> None:
        api = _import("define cluster (name(low.case) indexed keys(4 0) recordsize(10 10))")
        assert _type(api, "vsam.LOW_CASE").extras[VSAM_EXTRAS_KEY]["dataset"] == "LOW.CASE"
        api = _import("DEFINE CLUSTER (NAME('Q.NAME') INDEXED KEYS(4 0) RECORDSIZE(10 10))")
        assert _type(api, "vsam.Q_NAME").extras[VSAM_EXTRAS_KEY]["dataset"] == "Q.NAME"

    def test_comments_jcl_and_if_guard(self) -> None:
        text = """//JOB1 JOB (ACCT)
//STEP EXEC PGM=IDCAMS
//SYSIN DD *
  /* the order file */
  DEFINE CLUSTER (NAME(J.K) /* inline */ INDEXED KEYS(2 0) -
                  RECORDSIZE(10 10))
  IF LASTCC = 0 THEN -
    LISTCAT ENTRIES(J.K) ALL
/*
"""
        api = _import(text)
        assert [t.key for t in api.types] == ["vsam.J_K"]
        assert api.extras[VSAM_EXTRAS_KEY]["commands"] == [{"verb": "LISTCAT", "datasets": ["J.K"]}]


class TestAlternateIndexes:
    TEXT = (
        KSDS
        + """  DEFINE AIX (NAME(TEST.ORDER.AIX.CUST) RELATE(TEST.ORDER.KSDS) KEYS(10 20) -
              NONUNIQUEKEY UPGRADE RECORDSIZE(60 2048))
  DEFINE AIX (NAME(TEST.ORDER.AIX.DATE) RELATE(TEST.ORDER.KSDS) KEYS(8 40) UNIQUEKEY)
  DEFINE PATH (NAME(TEST.ORDER.PATH.CUST) PATHENTRY(TEST.ORDER.AIX.CUST) UPDATE)
  BLDINDEX INDATASET(TEST.ORDER.KSDS) OUTDATASET(TEST.ORDER.AIX.CUST TEST.ORDER.AIX.DATE)
"""
    )

    def test_alternate_keys_are_fields_of_the_base_record(self) -> None:
        api = _import(self.TEXT)
        customer = _field(api, "vsam.TEST_ORDER_KSDS", "ALTERNATE_KEY_CUST")
        assert customer.extras[VSAM_EXTRAS_KEY]["unique"] is False
        assert customer.extras[VSAM_EXTRAS_KEY]["offset"] == 20
        assert customer.extras[VSAM_EXTRAS_KEY]["paths"] == ["TEST.ORDER.PATH.CUST"]
        date = _field(api, "vsam.TEST_ORDER_KSDS", "ALTERNATE_KEY_DATE")
        assert date.extras[VSAM_EXTRAS_KEY]["unique"] is True

    def test_keys_are_numbered_by_offset(self) -> None:
        api = _import(self.TEXT)
        fields = sorted(_type(api, "vsam.TEST_ORDER_KSDS").fields, key=lambda f: f.field_number or 0)
        assert [f.name for f in fields] == ["PRIMARY_KEY", "ALTERNATE_KEY_CUST", "ALTERNATE_KEY_DATE"]

    def test_utility_commands_are_counted(self) -> None:
        api = _import(self.TEXT)
        assert api.extras[VSAM_EXTRAS_KEY]["commands"][0]["verb"] == "BLDINDEX"
        assert _limits(api)["vsam.utility_command"] == 1

    def test_repeated_qualifiers_use_the_whole_index_name(self) -> None:
        text = (
            KSDS
            + "DEFINE AIX (NAME(A.X.CUST) RELATE(TEST.ORDER.KSDS) KEYS(2 20))\n"
            + "DEFINE AIX (NAME(B.X.CUST) RELATE(TEST.ORDER.KSDS) KEYS(2 30))\n"
        )
        names = {f.name for f in _type(_import(text), "vsam.TEST_ORDER_KSDS").fields}
        assert {"ALTERNATE_KEY_A_X_CUST", "ALTERNATE_KEY_B_X_CUST"} <= names

    def test_fileset_resolves_relate_across_members(self) -> None:
        api = _import_fileset(
            {
                "base.idcams": KSDS,
                "aix.idcams": "DEFINE AIX (NAME(T.AIX.X) RELATE(TEST.ORDER.KSDS) KEYS(4 50))",
            },
            root="base.idcams",
        )
        assert _field(api, "vsam.TEST_ORDER_KSDS", "ALTERNATE_KEY_X").extras[VSAM_EXTRAS_KEY]["offset"] == 50
        assert api.extras[VSAM_EXTRAS_KEY]["input"] == "fileset"

    def test_gdg_is_a_declared_limit(self) -> None:
        api = _import(KSDS + "DEFINE GDG (NAME(DAILY.EXTRACT) LIMIT(30) SCRATCH)\n")
        assert api.extras[VSAM_EXTRAS_KEY]["gdgs"] == [{"name": "DAILY.EXTRACT", "limit": 30, "flags": ["SCRATCH"]}]
        assert _limits(api)["vsam.generation_data_group"] == 1


# ===========================================================================
# LISTCAT
# ===========================================================================


LISTING = """LISTING FROM CATALOG -- CATALOG.TEST
CLUSTER ------- TEST.ACCT.KSDS
     IN-CAT --- CATALOG.TEST
     HISTORY
       DATASET-OWNER-----(NULL)     CREATION--------2024.061
     ASSOCIATIONS
       DATA-----TEST.ACCT.KSDS.DATA
       INDEX----TEST.ACCT.KSDS.INDEX
       AIX------TEST.ACCT.AIX.NAME
  DATA ------- TEST.ACCT.KSDS.DATA
     ATTRIBUTES
       KEYLEN----------------10     AVGLRECL-------------150
       MAXLRECL-------------200     RKP--------------------4
       CISIZE--------------4096
       SHROPTNS(2,3)   RECOVERY     INDEXED           NOERASE
     STATISTICS
       REC-TOTAL---------118432
  INDEX ------ TEST.ACCT.KSDS.INDEX
     ATTRIBUTES
       KEYLEN----------------10     CISIZE--------------2048
"""


class TestListcat:
    def test_listing_becomes_a_record(self) -> None:
        api = _import(LISTING, "listcat.txt")
        key = _field(api, "vsam.TEST_ACCT_KSDS", "PRIMARY_KEY")
        assert key.extras[VSAM_EXTRAS_KEY]["offset"] == 4 and key.extras[VSAM_EXTRAS_KEY]["length"] == 10
        metadata = _type(api, "vsam.TEST_ACCT_KSDS").extras[VSAM_EXTRAS_KEY]
        assert metadata["origin"] == "listcat"
        assert metadata["recordSize"] == {"average": 150, "maximum": 200, "fixed": False}
        assert metadata["shareOptions"] == {"crossRegion": 2, "crossSystem": 3}
        assert metadata["controlIntervalSize"] == 4096
        assert "NOERASE" in metadata["flags"]

    def test_statistics_and_unlisted_indexes_are_declared(self) -> None:
        limits = _limits(_import(LISTING, "listcat.txt"))
        assert limits["vsam.listcat_statistics"] == 2
        assert limits["vsam.unlisted_alternate_index"] == 1

    def test_listing_without_cluster_is_refused(self) -> None:
        assert _code("LISTING FROM CATALOG -- CATALOG.TEST\n  DATA ------- X.DATA\n") == "INPUT_SEMANTIC_INVALID"


# ===========================================================================
# Refusals
# ===========================================================================


class TestRefusals:
    @pytest.mark.parametrize(
        ("text", "code"),
        [
            ("", "INPUT_EMPTY"),
            ("﻿DEFINE CLUSTER (NAME(A) INDEXED KEYS(1 0))", "INPUT_ENCODING_INVALID"),
            ("hello world\nthis is prose\n", "FORMAT_MISMATCH"),
            ("DEFINE CLUSTER (NAME(A) INDEXED KEYS(1 0) RECORDSIZE(9 9))\nFROBNICATE X\n", "INPUT_MALFORMED"),
            ("DEFINE CLUSTER (NAME(A) INDEXED KEYS(4 0 RECORDSIZE(9 9))\n", "INPUT_MALFORMED"),
            ("DEFINE CLUSTER (NAME(A) INDEXED KEYS(4 0) RECORDSIZE(9 9)))\n", "INPUT_MALFORMED"),
            ("DEFINE CLUSTER (NAME(A) INDEXED KEYS(4 0) RECORDSIZE(9", "INPUT_TRUNCATED"),
            ("DEFINE CLUSTER (NAME(A) INDEXED -\n", "INPUT_TRUNCATED"),
            ("DEFINE CLUSTER (NAME(A) INDEXED KEYS(1 0)) /* unterminated", "INPUT_TRUNCATED"),
            ("DEFINE CLUSTER (NAME(A) INDEXED KEYS(X 0))", "INPUT_MALFORMED"),
            ("DEFINE WIDGET (NAME(A))", "INPUT_MALFORMED"),
            ("DEFINE CLUSTER (INDEXED KEYS(1 0))", "INPUT_SEMANTIC_INVALID"),
            ("DEFINE CLUSTER (NAME(A) INDEXED RECORDSIZE(9 9))", "INPUT_SEMANTIC_INVALID"),
            ("DEFINE CLUSTER (NAME(A) NONINDEXED KEYS(2 0) RECORDSIZE(9 9))", "INPUT_SEMANTIC_INVALID"),
            ("DEFINE CLUSTER (NAME(A) INDEXED KEYS(8 4) RECORDSIZE(10 10))", "INPUT_SEMANTIC_INVALID"),
            ("DEFINE CLUSTER (NAME(A) LINEAR)", "INPUT_SEMANTIC_INVALID"),
        ],
    )
    def test_codes(self, text: str, code: str) -> None:
        assert _code(text) == code

    def test_duplicate_definition(self) -> None:
        assert _code(KSDS + KSDS) == "INPUT_SEMANTIC_INVALID"

    def test_unresolved_relate(self) -> None:
        assert _code("DEFINE AIX (NAME(A.AIX) RELATE(MISSING.KSDS) KEYS(4 0))") == "INPUT_REFERENCE_UNRESOLVED"

    def test_unresolved_pathentry(self) -> None:
        assert _code(KSDS + "DEFINE PATH (NAME(P) PATHENTRY(NOPE))") == "INPUT_REFERENCE_UNRESOLVED"

    def test_alternate_key_past_base_record(self) -> None:
        text = KSDS + "DEFINE AIX (NAME(A.AIX) RELATE(TEST.ORDER.KSDS) KEYS(10 295))"
        assert _code(text) == "INPUT_SEMANTIC_INVALID"

    def test_alternate_index_over_rrds(self) -> None:
        text = "DEFINE CLUSTER (NAME(R) NUMBERED RECORDSIZE(9 9))\nDEFINE AIX (NAME(A) RELATE(R) KEYS(2 0))"
        assert _code(text) == "INPUT_SEMANTIC_INVALID"

    def test_bms_source_is_a_format_mismatch(self) -> None:
        text = (EXAMPLES / "negative" / "04-wrong-format-bms.bms").read_text(encoding="utf-8")
        assert _code(text, "x.bms") == "FORMAT_MISMATCH"


# ===========================================================================
# Detection and wiring
# ===========================================================================


class TestDetection:
    def test_define_commands(self) -> None:
        result = _adapter().detect(DetectionInput(text=KSDS, filename="x.txt"))
        assert result.matched and result.confidence >= 0.9

    def test_jcl_step_is_stronger(self) -> None:
        text = "//S EXEC PGM=IDCAMS\n//SYSIN DD *\n" + KSDS
        assert _adapter().detect(DetectionInput(text=text)).confidence > 0.92

    def test_listing(self) -> None:
        assert is_listcat_listing(LISTING) and _adapter().detect(DetectionInput(text=LISTING)).matched

    def test_bms_is_not_claimed(self) -> None:
        text = (EXAMPLES / "negative" / "04-wrong-format-bms.bms").read_text(encoding="utf-8")
        assert not _adapter().detect(DetectionInput(text=text, filename="x.bms")).matched
        assert not has_idcams_commands(text)

    def test_bms_adapter_does_not_claim_idcams(self) -> None:
        assert not CicsBmsImportSource().detect(DetectionInput(text=KSDS, filename="x.idcams")).matched


class TestWiring:
    def test_registered(self) -> None:
        adapter = get_import_source("vsam-idcams")
        assert isinstance(adapter, VsamIdcamsImportSource)
        assert ".idcams" in adapter.file_extensions
        assert adapter.paradigm is ApiParadigm.DATA_SCHEMA

    def test_capability_seed_lists_every_limit(self) -> None:
        capability = capability_for("vsam-idcams")
        assert sorted(capability.canonical_projection.dropped_constructs) == sorted(VSAM_LIMIT_DETAILS)

    def test_version_coverage(self) -> None:
        coverage = version_coverage_for("vsam-idcams")
        assert coverage.reads and not coverage.writes

    def test_schema_only_and_provenance_key(self) -> None:
        assert "vsam-idcams" in SCHEMA_ONLY_FORMATS
        assert VSAM_EXTRAS_KEY in PROVENANCE_EXTRA_KEYS

    def test_ledger_rows(self) -> None:
        api = _import(KSDS + "  DEFINE CLUSTER (NAME(TEST.LDS) LINEAR)\n")
        rows = {row.source_construct: row.coverage.value for row in _mainframe_misc_capability_rows(api)}
        assert rows == {"vsam.linear_dataset": "not-parsed-by-adapter", "vsam.record_layout": "partially-mapped"}

    def test_parse_returns_document_for_normalize(self) -> None:
        with pytest.raises(ImportSourceError):
            _adapter().normalize(object())
        assert parse_vsam_text(KSDS).clusters[0].name == "TEST.ORDER.KSDS"


# ===========================================================================
# Corpus
# ===========================================================================


class TestCorpus:
    def test_stress_forms(self) -> None:
        path = EXAMPLES / "04-stress-cluster-forms.idcams"
        api = _import(path.read_text(encoding="utf-8"), path.name)
        organisations = {t.name: t.extras[VSAM_EXTRAS_KEY]["organisation"] for t in api.types}
        assert organisations == {
            "EXAMPLE_ORDER_KSDS": "KSDS",
            "EXAMPLE_AUDIT_ESDS": "ESDS",
            "EXAMPLE_SLOT_RRDS": "RRDS",
            "EXAMPLE_SLOTV_VRRDS": "VRRDS",
        }
        assert _limits(api)["vsam.linear_dataset"] == 1

    def test_real_world_unique_and_non_unique_alternates(self) -> None:
        path = EXAMPLES / "05-real-world-account-cluster.idcams"
        api = _import(path.read_text(encoding="utf-8"), path.name)
        iban = _field(api, "vsam.EXAMPLE_PROD_ACCOUNT_KSDS", "ALTERNATE_KEY_IBAN")
        assert iban.extras[VSAM_EXTRAS_KEY]["unique"] is True
        assert iban.constraints is not None and iban.constraints.max_length == 34
        assert (
            _field(api, "vsam.EXAMPLE_PROD_ACCOUNT_KSDS", "ALTERNATE_KEY_CUST").extras[VSAM_EXTRAS_KEY]["unique"]
            is False
        )

    def test_cluster_and_index_set(self) -> None:
        folder = EXAMPLES / "03-cluster-and-index-set"
        members = {path.name: path.read_text(encoding="utf-8") for path in folder.iterdir()}
        api = _import_fileset(members, root="cluster.idcams")
        broker = _field(api, "vsam.EXAMPLE_POLICY_KSDS", "ALTERNATE_KEY_BROKER")
        assert (broker.extras[VSAM_EXTRAS_KEY]["offset"], broker.extras[VSAM_EXTRAS_KEY]["length"]) == (40, 8)

    @pytest.mark.parametrize(
        ("name", "code"),
        [
            ("01-syntactic-unbalanced-parens.idcams", "INPUT_MALFORMED"),
            ("02-semantic-indexed-without-keys.idcams", "INPUT_SEMANTIC_INVALID"),
            ("03-truncated-mid-parameter.idcams", "INPUT_TRUNCATED"),
            ("06-unresolvable-relate-target.idcams", "INPUT_REFERENCE_UNRESOLVED"),
        ],
    )
    def test_negatives(self, name: str, code: str) -> None:
        assert _code((EXAMPLES / "negative" / name).read_text(encoding="utf-8"), name) == code
