"""``apiome properties copy <src-project> <names> --to <dst-project>`` (CLI 6.6, #3228).

The rules (:mod:`apiome_cli.property_copy`) and the command against a mocked REST API: one
``POST`` per new property, ``--rename``, ``--all``, conflicts (skipped, or overwritten with
``--update`` via ``PUT`` + ``expectedUpdatedAt``), ``--dry-run``, cross-tenant ``--to`` (exit 4) and
references to primitives the tenant lacks (exit 7, nothing written).
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import (
    EXIT_CROSS_TENANT,
    EXIT_ERROR,
    EXIT_PRIMITIVE_MISSING,
    EXIT_SUCCESS,
    EXIT_USAGE,
)
from apiome_cli.main import app
from apiome_cli.property_copy import (
    ACTION_CREATE,
    ACTION_SKIP,
    ACTION_UPDATE,
    CopyArgumentError,
    CopyItem,
    CrossTenantCopy,
    check_arguments,
    dangling_refs,
    iter_refs,
    needs_primitives,
    parse_destination,
    parse_names,
    plan_copy,
    ref_resolves,
    render_plan,
    render_summary,
    request_body,
)

runner = CliRunner()

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme",
}
_HOST = "http://localhost:8000/v1"
_SRC = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_DST = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_SRC_PROPS = f"{_HOST}/properties/acme/{_SRC}"
_DST_PROPS = f"{_HOST}/properties/acme/{_DST}"


def _p(name, data=None, description=None, **extra):
    return {"id": f"id-{name}", "name": name, "description": description, "data": data or {"type": "string"}, **extra}


_SOURCE = [
    _p("amount", {"type": "number", "minimum": 0}, "Minor units."),
    _p("currency", {"type": "string"}, "ISO 4217."),
    _p("customer_id", {"type": "string", "format": "uuid"}),
]
_PRIMITIVES = [{"id": "p1", "name": "string", "schema_id": "https://api.apiome.dev/types/std/v0/primitives/string"}]


@pytest.fixture(autouse=True)
def _cache_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))


# ---- rules ----------------------------------------------------------------------------------------


def test_parse_names() -> None:
    assert parse_names(" amount, currency,,amount ") == ["amount", "currency"]
    assert parse_names(None) == []


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"names": ["a"], "all_props": True}, "not both"),
        ({"names": []}, "Name the properties"),
        ({"names": ["a", "b"], "rename": "x"}, "exactly one"),
        ({"names": [], "all_props": True, "rename": "x"}, "exactly one"),
        ({"names": ["a"], "rename": " "}, "needs a name"),
        ({"names": ["a"], "update": True, "skip": True}, "not both"),
    ],
)
def test_check_arguments_refuses(kwargs, message) -> None:
    args = {"all_props": False, "rename": None, "update": False, "skip": False, **kwargs}
    with pytest.raises(CopyArgumentError, match=message):
        check_arguments(args.pop("names"), **args)


def test_parse_destination() -> None:
    assert parse_destination("billing-api", "acme") == "billing-api"
    assert parse_destination("ACME/billing-api", "acme") == "billing-api"
    with pytest.raises(CrossTenantCopy, match="Cannot copy to tenant 'globex'"):
        parse_destination("globex/billing-api", "acme")
    for bad in ("", "a/b/c", "/billing-api", "acme/"):
        with pytest.raises(CopyArgumentError):
            parse_destination(bad, "acme")


def test_plan_copy_conflicts_and_update() -> None:
    destination = [_p("currency", {"type": "string"}, "Different.", updated_at="t1"), _p("customer_id", {"type": "string", "format": "uuid"})]
    assert [(i.target, i.action) for i in plan_copy(_SOURCE, destination)] == [
        ("amount", ACTION_CREATE),
        ("currency", ACTION_SKIP),
        ("customer_id", ACTION_SKIP),
    ]
    # --update overwrites the differing one; the identical one stays skipped.
    assert [(i.target, i.action) for i in plan_copy(_SOURCE, destination, update=True)] == [
        ("amount", ACTION_CREATE),
        ("currency", ACTION_UPDATE),
        ("customer_id", ACTION_SKIP),
    ]
    assert plan_copy(_SOURCE[:1], destination, rename="gross_amount")[0].target == "gross_amount"


def test_iter_refs_and_needs_primitives() -> None:
    data = {"$ref": "a", "items": {"$ref": "b"}, "anyOf": [{"$ref": "#/defs/c"}]}
    assert list(iter_refs(data)) == ["a", "b", "#/defs/c"]
    only_local = [CopyItem(_p("x", {"$ref": "#/x"}), "x", ACTION_CREATE)]
    assert not needs_primitives(only_local)
    assert needs_primitives([CopyItem(_p("x", {"$ref": "money"}), "x", ACTION_CREATE)])
    assert not needs_primitives([CopyItem(_p("x", {"$ref": "money"}), "x", ACTION_SKIP)])


@pytest.mark.parametrize(
    ("ref", "ok"),
    [
        ("#/$defs/x", True),
        ("https://json-schema.org/draft/2020-12/schema", True),
        ("https://api.apiome.dev/types/std/v0/primitives/string", True),
        ("https://api.apiome.dev/types/std/v0/primitives/string#/x", True),
        ("https://api.apiome.dev/types/acme/money", False),
        ("std/v0/primitives/string", True),
        ("../primitives/string", True),
        ("./string", True),
        ("primitives/money", False),
        ("../", False),
    ],
)
def test_ref_resolves(ref, ok) -> None:
    assert ref_resolves(ref, _PRIMITIVES) is ok


def test_dangling_refs_lists_each_once() -> None:
    items = [
        CopyItem(_p("amount", {"$ref": "acme/money", "items": {"$ref": "acme/money"}}), "amount", ACTION_CREATE),
        CopyItem(_p("name", {"$ref": "std/v0/primitives/string"}), "name", ACTION_CREATE),
        CopyItem(_p("skipped", {"$ref": "acme/gone"}), "skipped", ACTION_SKIP),
    ]
    assert dangling_refs(items, _PRIMITIVES) == [("amount", "acme/money")]


def test_request_body() -> None:
    item = CopyItem(_SOURCE[0], "gross_amount", ACTION_CREATE)
    assert request_body(item) == {"name": "gross_amount", "description": "Minor units.", "data": {"type": "number", "minimum": 0}}
    update = CopyItem(_p("currency"), "currency", ACTION_UPDATE, existing=_p("currency", updated_at="t1"))
    assert request_body(update) == {"name": "currency", "description": "", "data": {"type": "string"}, "expectedUpdatedAt": "t1"}


def test_render_plan_and_summary() -> None:
    items = plan_copy(_SOURCE[:2], [_p("currency")])
    assert render_plan(items, source_project="payments-api", destination="billing-api").splitlines() == [
        "Copy from payments-api → billing-api:",
        "  amount    → amount  create",
        "  currency  → currency  skip (exists; pass --update to overwrite)",
    ]
    assert render_summary([(items[0], "created")], source_project="payments-api", destination="billing-api") == (
        "✔ Copied 'amount' from payments-api → billing-api."
    )
    renamed = CopyItem(_SOURCE[0], "gross_amount", ACTION_CREATE)
    assert "as 'gross_amount'" in render_summary([(renamed, "created")], source_project="a", destination="b")
    text = render_summary([(items[0], "failed: HTTP 500"), (items[1], "skipped")], source_project="a", destination="b")
    assert text.splitlines() == [
        "✘ Copied 0 properties from a → b (1 skipped, 1 failed).",
        "  Skipped (already in b): currency",
        "  amount: HTTP 500",
    ]


# ---- command --------------------------------------------------------------------------------------


def _mock(httpx_mock, *, destination=(), primitives=None):
    httpx_mock.add_response(url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _SRC}, is_optional=True)
    httpx_mock.add_response(url=f"{_HOST}/projects/acme/by-slug/billing-api", json={"id": _DST}, is_optional=True)
    httpx_mock.add_response(url=_SRC_PROPS, method="GET", json=_SOURCE)
    httpx_mock.add_response(url=_DST_PROPS, method="GET", json=list(destination), is_optional=True)
    if primitives is not None:
        httpx_mock.add_response(url=f"{_HOST}/primitives/acme", json=primitives)


def _writes(httpx_mock):
    return [(r.method, str(r.url), json.loads(r.content)) for r in httpx_mock.get_requests() if r.method in ("POST", "PUT")]


def _run(*args, json_mode=False):
    argv = (["--json"] if json_mode else []) + ["properties", "copy", "payments-api", *args]
    return runner.invoke(app, argv, env=_ENV)


def test_copy_one_property(httpx_mock) -> None:
    _mock(httpx_mock)
    httpx_mock.add_response(url=_DST_PROPS, method="POST", json={"id": "new"})
    result = _run("amount", "--to", "billing-api")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.output == "✔ Copied 'amount' from payments-api → billing-api.\n"
    assert _writes(httpx_mock) == [
        ("POST", _DST_PROPS, {"name": "amount", "description": "Minor units.", "data": {"type": "number", "minimum": 0}})
    ]


def test_rename(httpx_mock) -> None:
    _mock(httpx_mock)
    httpx_mock.add_response(url=_DST_PROPS, method="POST", json={"id": "new"})
    result = _run("amount", "--to", "billing-api", "--rename", "gross_amount")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert _writes(httpx_mock)[0][2]["name"] == "gross_amount"


def test_several_names_show_progress_and_skip_conflicts(httpx_mock) -> None:
    _mock(httpx_mock, destination=[_p("currency", {"type": "string"}, "Other.")])
    httpx_mock.add_response(url=_DST_PROPS, method="POST", json={"id": "new"}, is_reusable=True)
    result = _run("amount,currency,customer_id", "--to", "billing-api")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "[1/2] amount: created" in result.output and "[2/2] customer_id: created" in result.output
    assert "✔ Copied 2 properties from payments-api → billing-api (1 skipped)." in result.output
    assert [w[2]["name"] for w in _writes(httpx_mock)] == ["amount", "customer_id"]


def test_all_with_update_overwrites_after_yes(httpx_mock) -> None:
    _mock(httpx_mock, destination=[_p("currency", {"type": "string"}, "Other.", updated_at="t1")])
    httpx_mock.add_response(url=_DST_PROPS, method="POST", json={"id": "new"}, is_reusable=True)
    httpx_mock.add_response(url=f"{_DST_PROPS}/id-currency", method="PUT", json={"id": "id-currency"})
    result = _run("--all", "--to", "billing-api", "--update", "--yes")
    assert result.exit_code == EXIT_SUCCESS, result.output
    put = [w for w in _writes(httpx_mock) if w[0] == "PUT"][0]
    assert put[2] == {"name": "currency", "description": "ISO 4217.", "data": {"type": "string"}, "expectedUpdatedAt": "t1"}
    assert "(1 updated)" in result.output


def test_update_without_yes_or_a_terminal_writes_nothing(httpx_mock) -> None:
    _mock(httpx_mock, destination=[_p("currency", {"type": "string"}, "Other.")])
    result = _run("currency", "--to", "billing-api", "--update")
    assert result.exit_code == EXIT_USAGE
    assert _writes(httpx_mock) == []


def test_dry_run_shows_names_and_conflicts(httpx_mock) -> None:
    _mock(httpx_mock, destination=[_p("currency")])
    result = _run("--all", "--to", "billing-api", "--dry-run")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "currency     → currency  skip (exists; pass --update to overwrite)" in result.output
    assert _writes(httpx_mock) == []


def test_dry_run_json(httpx_mock) -> None:
    _mock(httpx_mock)
    result = _run("amount", "--to", "billing-api", "--rename", "gross", "--dry-run", json_mode=True)
    assert json.loads(result.stdout) == {
        "dryRun": True,
        "from": "payments-api",
        "to": "billing-api",
        "items": [{"source": "amount", "target": "gross", "action": "create"}],
    }


def test_json_reports_each_result(httpx_mock) -> None:
    _mock(httpx_mock, destination=[_p("currency")])
    httpx_mock.add_response(url=_DST_PROPS, method="POST", json={"id": "new"})
    result = _run("amount,currency", "--to", "billing-api", json_mode=True)
    assert [(i["target"], i["result"]) for i in json.loads(result.stdout)["items"]] == [
        ("amount", "created"),
        ("currency", "skipped"),
    ]


def test_a_failed_write_is_reported_and_exits_1(httpx_mock) -> None:
    _mock(httpx_mock)
    httpx_mock.add_response(url=_DST_PROPS, method="POST", status_code=409, json={"detail": "exists"})
    result = _run("amount", "--to", "billing-api")
    assert result.exit_code == EXIT_ERROR
    assert "amount: HTTP 409 — exists" in result.output


def test_cross_tenant_exits_4_before_any_request(httpx_mock) -> None:
    result = _run("amount", "--to", "globex/billing-api")
    assert result.exit_code == EXIT_CROSS_TENANT
    assert httpx_mock.get_requests() == []


def test_a_missing_primitive_exits_7_and_writes_nothing(httpx_mock) -> None:
    httpx_mock.add_response(url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _SRC})
    httpx_mock.add_response(url=f"{_HOST}/projects/acme/by-slug/billing-api", json={"id": _DST})
    httpx_mock.add_response(url=_SRC_PROPS, json=[_p("amount", {"$ref": "acme/money"})])
    httpx_mock.add_response(url=_DST_PROPS, json=[])
    httpx_mock.add_response(url=f"{_HOST}/primitives/acme", json=_PRIMITIVES)
    result = _run("amount", "--to", "billing-api")
    assert result.exit_code == EXIT_PRIMITIVE_MISSING
    assert "amount: $ref 'acme/money' matches no primitive in tenant 'acme'" in result.output
    assert "Import those primitives" in result.output
    assert _writes(httpx_mock) == []


def test_unknown_names_are_all_reported(httpx_mock) -> None:
    httpx_mock.add_response(url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _SRC})
    httpx_mock.add_response(url=f"{_HOST}/projects/acme/by-slug/billing-api", json={"id": _DST})
    httpx_mock.add_response(url=_SRC_PROPS, json=_SOURCE)
    result = _run("amont,curency", "--to", "billing-api")
    assert result.exit_code == EXIT_USAGE
    assert "Did you mean: amount?" in result.output and "Did you mean: currency?" in result.output


def test_argument_errors_exit_2() -> None:
    assert _run("--to", "billing-api").exit_code == EXIT_USAGE
    assert _run("a,b", "--to", "billing-api", "--rename", "x").exit_code == EXIT_USAGE
    assert runner.invoke(app, ["properties", "copy", "payments-api", "amount"], env=_ENV).exit_code == EXIT_USAGE
