"""Unit tests for what a provider contract is — PFX-2.1 (#6925).

:mod:`app.provider_contract` is pure: reading JSON or YAML, deciding whether a document is OpenAPI
3.x (and saying where it is not), addressing it by content, and the publish request's own checks.
The fixtures under ``tests/fixtures/provider_contracts`` are an OpenAPI 3.0 YAML and an OpenAPI 3.1
JSON provider contract, and a Swagger 2.0 document that must be refused.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

from app.provider_contract import (
    CODE_CONTRACT_INVALID,
    CODE_CONTRACT_TOO_LARGE,
    CODE_REQUEST_INVALID,
    CODE_UNSUPPORTED,
    SOURCE_APIOME,
    ApiomeReference,
    ProviderContractError,
    PublishProviderContractRequest,
    check_request,
    contract_record_from_row,
    decode_base64,
    parse_apiome_reference,
    parse_openapi,
    prepare_contract,
    provider_contract_sha,
    sent_verification_results,
    stored_verification_results,
    validate_openapi_contract,
)

FIXTURES = Path(__file__).parent / "fixtures" / "provider_contracts"
LIMIT = 1_000_000


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _oas31() -> Dict[str, Any]:
    return json.loads(_fixture("ledger-api-3.1.json"))


def _refusal(call: Any, *args: Any, **kwargs: Any) -> ProviderContractError:
    with pytest.raises(ProviderContractError) as caught:
        call(*args, **kwargs)
    return caught.value


# ---------------------------------------------------------------------------------------------
# Reading JSON and YAML
# ---------------------------------------------------------------------------------------------


class TestParseOpenapi:
    def test_an_openapi_30_yaml_fixture_reads_as_the_json_it_stands_for(self) -> None:
        document, read_as = parse_openapi(
            _fixture("ledger-api-3.0.yaml"), content_type="application/yaml", max_bytes=LIMIT
        )
        assert read_as == "application/yaml"
        responses = document["paths"]["/invoices/{id}"]["get"]["responses"]
        # YAML reads `200:` as an integer key; the OpenAPI document means the string "200".
        assert set(responses) == {"200", "404"}
        # An unquoted date becomes its ISO-8601 text.
        assert responses["200"]["content"]["application/json"]["example"]["issued"] == "2026-11-01"

    def test_an_openapi_31_json_fixture_reads_unchanged(self) -> None:
        document, read_as = parse_openapi(
            _fixture("ledger-api-3.1.json"), content_type="application/json", max_bytes=LIMIT
        )
        assert read_as == "application/json"
        assert document == _oas31()

    @pytest.mark.parametrize(
        "raw, expected",
        [(b'  {"openapi": "3.1.0"}', "application/json"), (b"openapi: 3.1.0\n", "application/yaml")],
    )
    def test_without_a_content_type_the_format_is_sniffed(self, raw: bytes, expected: str) -> None:
        document, read_as = parse_openapi(raw, content_type=None, max_bytes=LIMIT)
        assert document == {"openapi": "3.1.0"}
        assert read_as == expected

    def test_content_type_parameters_are_ignored(self) -> None:
        _, read_as = parse_openapi(b"{}", content_type="application/json; charset=utf-8", max_bytes=LIMIT)
        assert read_as == "application/json"

    def test_a_media_type_that_is_neither_json_nor_yaml_is_unsupported(self) -> None:
        error = _refusal(parse_openapi, b"{}", content_type="application/xml", max_bytes=LIMIT)
        assert (error.code, error.pointer) == (CODE_UNSUPPORTED, "/contentType")

    def test_a_document_over_the_limit_is_too_large(self) -> None:
        error = _refusal(parse_openapi, b"x" * 11, content_type=None, max_bytes=10)
        assert error.code == CODE_CONTRACT_TOO_LARGE

    @pytest.mark.parametrize(
        "raw, content_type",
        [
            (b"\xff\xfe", None),
            (b'{"openapi": ', "application/json"),
            (b"openapi: [unclosed", "application/yaml"),
            (b'{"a": 1, "a": 2}', "application/json"),
            (b"- openapi\n", "application/yaml"),
            (b"a: 1\n---\nb: 2\n", "application/yaml"),
        ],
        ids=["not-utf8", "json-syntax", "yaml-syntax", "duplicate-key", "not-a-mapping", "multi-document"],
    )
    def test_what_does_not_parse_to_one_mapping_is_invalid_at_the_root(self, raw: bytes, content_type: Any) -> None:
        error = _refusal(parse_openapi, raw, content_type=content_type, max_bytes=LIMIT)
        assert (error.code, error.pointer) == (CODE_CONTRACT_INVALID, "")

    def test_a_billion_laughs_yaml_is_refused_not_expanded(self) -> None:
        bomb = "a: &a [x, x, x, x, x, x, x, x, x]\n" + "".join(
            f"{chr(98 + i)}: &{chr(98 + i)} [*{chr(97 + i)}, *{chr(97 + i)}, *{chr(97 + i)}, *{chr(97 + i)}]\n"
            for i in range(12)
        )
        error = _refusal(parse_openapi, bomb.encode(), content_type="application/yaml", max_bytes=LIMIT)
        assert error.code == CODE_CONTRACT_INVALID

    @pytest.mark.parametrize(
        "text, pointer",
        [
            ("openapi: 3.1.0\nx-blob: !!binary aGVsbG8=\n", "/x-blob"),
            ("openapi: 3.1.0\ninfo:\n  x-ratio: .nan\n", "/info/x-ratio"),
            ("openapi: 3.1.0\nx-set: !!set {a, b}\n", "/x-set"),
            # A list as a key does not even parse (YAML cannot hash it): refused at the root.
            ("openapi: 3.1.0\nx-map:\n  ? [a, b]\n  : 1\n", ""),
            ("openapi: 3.1.0\nx-keys:\n  1: a\n  '1': b\n", "/x-keys"),
        ],
        ids=["binary", "nan", "set", "list-key", "key-collision"],
    )
    def test_yaml_values_json_cannot_hold_are_refused_where_they_are(self, text: str, pointer: str) -> None:
        error = _refusal(parse_openapi, text.encode(), content_type="application/yaml", max_bytes=LIMIT)
        assert (error.code, error.pointer) == (CODE_CONTRACT_INVALID, pointer)

    def test_a_key_with_a_slash_is_escaped_in_the_pointer(self) -> None:
        text = "openapi: 3.1.0\npaths:\n  /a~b:\n    x-bad: !!binary aGk=\n"
        error = _refusal(parse_openapi, text.encode(), content_type="application/yaml", max_bytes=LIMIT)
        assert error.pointer == "/paths/~1a~0b/x-bad"


# ---------------------------------------------------------------------------------------------
# Is it OpenAPI 3.x?
# ---------------------------------------------------------------------------------------------


class TestValidateOpenapiContract:
    def test_both_fixtures_are_provider_contracts(self) -> None:
        yaml_document, _ = parse_openapi(_fixture("ledger-api-3.0.yaml"), content_type=None, max_bytes=LIMIT)
        assert validate_openapi_contract(yaml_document) == "3.0.3"
        assert validate_openapi_contract(_oas31()) == "3.1.0"

    def test_openapi_32_is_accepted(self) -> None:
        assert (
            validate_openapi_contract({"openapi": "3.2.0", "info": {"title": "T", "version": "1"}, "paths": {}})
            == "3.2.0"
        )

    def test_swagger_20_is_refused_at_swagger(self) -> None:
        error = _refusal(validate_openapi_contract, json.loads(_fixture("swagger-2.0.json")))
        assert (error.code, error.pointer) == (CODE_CONTRACT_INVALID, "/swagger")
        assert "Swagger 2.0 is not supported" in str(error)

    def test_asyncapi_is_refused_at_asyncapi(self) -> None:
        error = _refusal(validate_openapi_contract, {"asyncapi": "3.0.0", "info": {}})
        assert error.pointer == "/asyncapi"

    @pytest.mark.parametrize("version", [None, "", 3.1, "2.0", "4.0.0", "3.9.0", "three"])
    def test_a_missing_or_foreign_openapi_version_is_refused_at_openapi(self, version: Any) -> None:
        document: Dict[str, Any] = {"info": {"title": "T", "version": "1"}, "paths": {}}
        if version is not None:
            document["openapi"] = version
        error = _refusal(validate_openapi_contract, document)
        assert (error.code, error.pointer) == (CODE_CONTRACT_INVALID, "/openapi")

    def test_a_meta_schema_error_is_located_by_an_escaped_pointer(self) -> None:
        document = _oas31()
        del document["paths"]["/invoices/{id}"]["get"]["responses"]["404"]["description"]
        error = _refusal(validate_openapi_contract, document)
        assert error.code == CODE_CONTRACT_INVALID
        assert error.pointer == "/paths/~1invoices~1{id}/get/responses/404"
        assert "'description' is a required property" in str(error)
        assert "OpenAPI 3.1 schema" in str(error)

    def test_the_message_names_at_most_five_errors_and_counts_the_rest(self) -> None:
        document = _oas31()
        document["paths"] = {f"/p{i}": {"get": {"responses": {"200": {}}}} for i in range(8)}
        message = str(_refusal(validate_openapi_contract, document))
        assert "(8 error(s))" in message
        assert "(and 3 more)" in message

    def test_the_label_names_a_rendered_document(self) -> None:
        error = _refusal(validate_openapi_contract, {"swagger": "2.0"}, label="the document rendered from ledger@1.0")
        assert str(error).startswith("the document rendered from ledger@1.0")


# ---------------------------------------------------------------------------------------------
# Content address
# ---------------------------------------------------------------------------------------------


class TestProviderContractSha:
    def test_key_order_and_serialization_do_not_change_the_address(self) -> None:
        document = _oas31()
        reordered = json.loads(json.dumps(document, sort_keys=True))
        from_yaml, _ = parse_openapi(
            yaml.safe_dump(document).encode(), content_type="application/yaml", max_bytes=LIMIT
        )
        assert provider_contract_sha(document) == provider_contract_sha(reordered) == provider_contract_sha(from_yaml)

    def test_any_change_of_content_changes_the_address(self) -> None:
        document = _oas31()
        changed = _oas31()
        changed["info"]["version"] = "1.4.1"
        assert provider_contract_sha(document) != provider_contract_sha(changed)

    def test_it_is_64_lowercase_hex(self) -> None:
        sha = provider_contract_sha({"openapi": "3.1.0"})
        assert len(sha) == 64 and sha == sha.lower() and int(sha, 16) >= 0


class TestPrepareContract:
    def test_an_inline_contract_is_addressed_and_counted(self) -> None:
        contract = prepare_contract(_oas31(), content_type="application/json")
        assert contract.sha == provider_contract_sha(_oas31())
        assert (contract.oas_version, contract.operation_count, contract.source) == ("3.1.0", 1, "inline")
        assert contract.source_project_slug is None

    def test_the_30_fixture_declares_two_operations(self) -> None:
        document, _ = parse_openapi(_fixture("ledger-api-3.0.yaml"), content_type=None, max_bytes=LIMIT)
        assert prepare_contract(document, content_type="application/yaml").operation_count == 2

    def test_an_apiome_source_is_recorded_and_named_in_refusals(self) -> None:
        contract = prepare_contract(
            _oas31(),
            content_type="application/json",
            source=SOURCE_APIOME,
            source_project_id="p",
            source_version_id="v",
            source_project_slug="ledger-api",
            source_version_label="1.4.0",
        )
        assert (contract.source, contract.source_project_slug, contract.source_version_label) == (
            "apiome",
            "ledger-api",
            "1.4.0",
        )
        error = _refusal(
            prepare_contract,
            {"swagger": "2.0"},
            content_type="application/json",
            source=SOURCE_APIOME,
            source_project_slug="ledger-api",
            source_version_label="1.4.0",
        )
        assert "rendered from ledger-api@1.4.0" in str(error)


# ---------------------------------------------------------------------------------------------
# The request
# ---------------------------------------------------------------------------------------------


def _request(**fields: Any) -> PublishProviderContractRequest:
    return PublishProviderContractRequest.model_validate(fields)


class TestCheckRequest:
    def test_inline_content_alone_is_accepted(self) -> None:
        check_request(_request(content="e30="))

    def test_a_reference_alone_is_accepted(self) -> None:
        check_request(_request(apiomeVersion="ledger@1.0.0", contentType="application/json"))

    @pytest.mark.parametrize("fields", [{}, {"content": "e30=", "apiomeVersion": "ledger@1"}], ids=["neither", "both"])
    def test_exactly_one_source_is_required(self, fields: Dict[str, Any]) -> None:
        error = _refusal(check_request, _request(**fields))
        assert (error.code, error.pointer) == (CODE_REQUEST_INVALID, "")

    def test_a_contract_type_other_than_oas_is_unsupported(self) -> None:
        error = _refusal(check_request, _request(content="e30=", contractType="pact"))
        assert (error.code, error.pointer) == (CODE_UNSUPPORTED, "/contractType")

    def test_the_contract_type_is_case_insensitive(self) -> None:
        check_request(_request(content="e30=", contractType="OAS"))

    def test_a_yaml_content_type_with_a_reference_is_refused(self) -> None:
        error = _refusal(check_request, _request(apiomeVersion="ledger@1", contentType="application/yaml"))
        assert (error.code, error.pointer) == (CODE_REQUEST_INVALID, "/contentType")

    # PFX-2.4 (#6928): the shape of verificationResults.
    _REPORT_ID = "6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b"

    def test_a_report_id_alone_is_accepted_without_success(self) -> None:
        check_request(_request(content="e30=", verificationResults={"providerVerificationReportId": self._REPORT_ID}))

    def test_a_report_and_a_report_id_together_are_refused(self) -> None:
        error = _refusal(
            check_request,
            _request(
                content="e30=",
                verificationResults={
                    "success": True,
                    "content": "e30=",
                    "providerVerificationReportId": self._REPORT_ID,
                },
            ),
        )
        assert (error.code, error.pointer) == (CODE_REQUEST_INVALID, "/verificationResults")

    def test_a_report_id_that_is_not_a_uuid_is_refused(self) -> None:
        error = _refusal(
            check_request, _request(content="e30=", verificationResults={"providerVerificationReportId": "latest"})
        )
        assert (error.code, error.pointer) == (
            CODE_REQUEST_INVALID,
            "/verificationResults/providerVerificationReportId",
        )

    def test_success_is_required_without_a_report_id(self) -> None:
        error = _refusal(check_request, _request(content="e30=", verificationResults={"content": "e30="}))
        assert (error.code, error.pointer) == (CODE_REQUEST_INVALID, "/verificationResults/success")


class TestApiomeReference:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("ledger-api@1.4.0", ApiomeReference("ledger-api", "1.4.0")),
            (" ledger-api @ latest ", ApiomeReference("ledger-api", "latest")),
            ("1.4.0", ApiomeReference(None, "1.4.0")),
            ("latest", ApiomeReference(None, "latest")),
            ("ledger@v@2", ApiomeReference("ledger", "v@2")),
        ],
    )
    def test_project_and_version_are_read(self, value: str, expected: ApiomeReference) -> None:
        assert parse_apiome_reference(value) == expected

    @pytest.mark.parametrize("value", ["", "  ", "@1.0.0", "ledger@", "ledger@  "])
    def test_an_empty_side_is_refused_at_the_field(self, value: str) -> None:
        error = _refusal(parse_apiome_reference, value)
        assert (error.code, error.pointer) == (CODE_REQUEST_INVALID, "/apiomeVersion")


class TestBase64AndResults:
    def test_base64_decodes(self) -> None:
        assert decode_base64(base64.b64encode(b"hi").decode(), "/content", "it") == b"hi"

    def test_bad_base64_is_refused_at_its_pointer(self) -> None:
        error = _refusal(decode_base64, "not base64!", "/content", "the contract content")
        assert (error.code, error.pointer) == (CODE_REQUEST_INVALID, "/content")

    def test_no_results_store_nothing(self) -> None:
        assert stored_verification_results(None, {"status": "missing"}) is None

    def test_results_are_stored_as_sent_with_the_report_digest(self) -> None:
        report = b"<testsuite tests='3' failures='0'/>"
        body = _request(
            content="e30=",
            verificationResults={
                "success": True,
                "content": base64.b64encode(report).decode(),
                "contentType": "application/xml",
                "verifier": "schemathesis",
                "verifierVersion": "3.39.0",
            },
        )
        stored = stored_verification_results(body.verification_results, {"status": "verified"})
        assert stored is not None
        assert stored["success"] is True
        assert (stored["verifier"], stored["verifierVersion"], stored["contentType"]) == (
            "schemathesis",
            "3.39.0",
            "application/xml",
        )
        assert stored["contentBytes"] == len(report)
        assert len(stored["contentSha256"]) == 64

    def test_results_without_a_report_carry_no_digest(self) -> None:
        stored = stored_verification_results(
            _request(content="e30=", verificationResults={"success": False}).verification_results,
            {"status": "failed"},
        )
        assert stored == {
            "success": False,
            "verifier": None,
            "verifierVersion": None,
            "contentType": None,
            "content": None,
            "evidence": {"status": "failed"},
        }

    def test_a_named_report_is_stored_lower_cased(self) -> None:
        report_id = "6F1C2B3A-4D5E-4F60-8A7B-9C0D1E2F3A4B"
        stored = stored_verification_results(
            _request(
                content="e30=", verificationResults={"providerVerificationReportId": report_id}
            ).verification_results,
            {"status": "verified"},
        )
        assert stored is not None
        assert stored["providerVerificationReportId"] == report_id.lower()
        assert stored["success"] is None

    def test_sent_results_leave_out_the_evidence(self) -> None:
        assert sent_verification_results(None) is None
        assert sent_verification_results({"success": True, "evidence": {"status": "verified"}}) == {"success": True}

    def test_a_report_that_is_not_base64_is_refused(self) -> None:
        body = _request(content="e30=", verificationResults={"success": True, "content": "%%%"})
        error = _refusal(stored_verification_results, body.verification_results, {})
        assert error.pointer == "/verificationResults/content"


class TestRecordFromRow:
    def test_jsonb_given_as_text_is_parsed(self) -> None:
        record = contract_record_from_row(
            {
                "provider_slug": "ledger-api",
                "provider_name": "Ledger API",
                "provider_version": "1.4.0",
                "sha": "ab" * 32 + " ",
                "content": json.dumps({"openapi": "3.1.0"}),
                "oas_version": "3.1.0",
                "operation_count": 3,
                "content_type": "application/yaml",
                "source": "apiome",
                "source_project_slug": "ledger-api",
                "source_version_label": "1.4.0",
                "source_project_id": None,
                "source_version_id": None,
                "verification_results": json.dumps({"success": True}),
                "created_at": None,
            }
        )
        assert record.sha == "ab" * 32
        assert record.content == {"openapi": "3.1.0"}
        assert record.verification_results == {"success": True}
        assert (record.source, record.source_project_id) == ("apiome", None)
