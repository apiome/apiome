"""Unit tests for the bulk CSV member import / export decisions (EID-2.5, #5671)."""

import pytest

from app.member_csv import (
    EXPORT_COLUMNS,
    MAX_IMPORT_ROWS,
    OUTCOMES,
    ImportRow,
    MemberCsvError,
    classify_import,
    count_outcomes,
    export_members_csv,
    is_valid_email,
    member_provenance,
    parse_import_csv,
)

_ROLES = [
    {"id": "role-editor", "slug": "editor", "name": "Editor"},
    {"id": "role-rm", "slug": "release-manager", "name": "Release Manager"},
]


def _row(email, role="", line=2, name=""):
    return ImportRow(line=line, email=email, role=role, display_name=name)


def _classify(rows, *, members=(), accounts=None, seats_free=None):
    if accounts is None:
        accounts = {r.email.lower(): {"id": f"u-{r.email}", "email": r.email} for r in rows}
    return classify_import(
        rows,
        roles=_ROLES,
        member_emails=set(members),
        accounts=accounts,
        seats_free=seats_free,
    )


# ---------------------------------------------------------------------------
# parse_import_csv
# ---------------------------------------------------------------------------


def test_parse_reads_the_three_columns_with_line_numbers():
    rows = parse_import_csv(b"email,role,display_name\nada@acme.io,Editor,Ada\ngrace@acme.io,,Grace\n")
    assert rows == [
        ImportRow(line=2, email="ada@acme.io", role="Editor", display_name="Ada"),
        ImportRow(line=3, email="grace@acme.io", role="", display_name="Grace"),
    ]


def test_parse_matches_the_header_loosely_and_ignores_extra_columns():
    rows = parse_import_csv("﻿ Email , ROLE,status\n ada@acme.io ,editor,active\n".encode())
    assert rows == [ImportRow(line=2, email="ada@acme.io", role="editor", display_name="")]


def test_parse_skips_blank_rows_but_keeps_file_line_numbers():
    rows = parse_import_csv(b"email\n\nada@acme.io\n,,\ngrace@acme.io\n")
    assert [(r.line, r.email) for r in rows] == [(3, "ada@acme.io"), (5, "grace@acme.io")]


def test_parse_tolerates_short_rows():
    rows = parse_import_csv(b"email,role,display_name\nada@acme.io\n")
    assert rows[0].role == "" and rows[0].display_name == ""


@pytest.mark.parametrize(
    "content, message",
    [
        (b"", "empty"),
        (b"name,role\nAda,Editor\n", "no email column"),
        (b"\xff\xfe\x00bad", "not UTF-8"),
    ],
)
def test_parse_refuses_a_file_it_cannot_read(content, message):
    with pytest.raises(MemberCsvError, match=message):
        parse_import_csv(content)


def test_parse_caps_the_file_at_1000_rows():
    ok = "email\n" + "".join(f"p{i}@acme.io\n" for i in range(MAX_IMPORT_ROWS))
    assert len(parse_import_csv(ok.encode())) == MAX_IMPORT_ROWS
    with pytest.raises(MemberCsvError, match="more than 1000 rows"):
        parse_import_csv((ok + "one-too-many@acme.io\n").encode())


# ---------------------------------------------------------------------------
# classify_import
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["ada@acme.io", "a.b+c@sub.acme.co.uk"])
def test_valid_emails(value):
    assert is_valid_email(value)


@pytest.mark.parametrize("value", ["", "ada", "ada@acme", "a da@acme.io", "@acme.io"])
def test_invalid_emails(value):
    assert not is_valid_email(value)


def test_a_good_row_becomes_an_invite_with_the_role_to_send():
    [entry] = _classify([_row("ada@acme.io", "Release Manager", name="Ada")])
    assert entry["outcome"] == "invite"
    assert entry["role_id"] == "role-rm"
    assert entry["role_name"] == "Release Manager"
    assert entry["user_id"] == "u-ada@acme.io"
    assert entry["display_name"] == "Ada"
    assert entry["message"] is None


@pytest.mark.parametrize("role", ["role-editor", "editor", "EDITOR", "Editor"])
def test_the_role_cell_matches_id_slug_or_name_in_any_case(role):
    [entry] = _classify([_row("ada@acme.io", role)])
    assert entry["role_id"] == "role-editor"


def test_an_empty_role_cell_means_the_default_role():
    [entry] = _classify([_row("ada@acme.io", "")])
    assert entry["outcome"] == "invite"
    assert entry["role_id"] is None


def test_each_bad_row_is_named_with_why():
    rows = [
        _row("not-an-email", line=2),
        _row("", line=3),
        _row("member@acme.io", line=4),
        _row("ada@acme.io", "Wizard", line=5),
        _row("ghost@acme.io", line=6),
    ]
    accounts = {"ada@acme.io": {"id": "u-ada"}, "member@acme.io": {"id": "u-m"}}
    report = _classify(rows, members={"member@acme.io"}, accounts=accounts)
    assert [(e["line"], e["outcome"]) for e in report] == [
        (2, "invalid-email"),
        (3, "invalid-email"),
        (4, "already-member"),
        (5, "unknown-role"),
        (6, "no-account"),
    ]
    assert all(e["message"] for e in report)
    assert "Wizard" in report[3]["message"]


def test_membership_is_matched_case_insensitively():
    [entry] = _classify([_row("Member@ACME.io")], members={"member@acme.io"})
    assert entry["outcome"] == "already-member"


def test_a_repeated_address_is_invited_once():
    report = _classify([_row("ada@acme.io", line=2), _row("ADA@acme.io", line=9)])
    assert [e["outcome"] for e in report] == ["invite", "already-member"]
    assert "line 2" in report[1]["message"]


def test_rows_past_the_free_seats_are_seat_cap():
    rows = [_row(f"p{i}@acme.io", line=i + 2) for i in range(4)]
    report = _classify(rows, seats_free=2)
    assert [e["outcome"] for e in report] == ["invite", "invite", "seat-cap", "seat-cap"]


def test_invalid_rows_do_not_spend_a_seat():
    rows = [_row("bad", line=2), _row("ghost@acme.io", line=3), _row("ada@acme.io", line=4)]
    report = _classify(rows, accounts={"ada@acme.io": {"id": "u-ada"}}, seats_free=1)
    assert [e["outcome"] for e in report] == ["invalid-email", "no-account", "invite"]


def test_no_seat_limit_when_seats_are_not_enforced():
    rows = [_row(f"p{i}@acme.io", line=i + 2) for i in range(50)]
    assert {e["outcome"] for e in _classify(rows, seats_free=None)} == {"invite"}


def test_sixty_rows_with_two_bad_ones_give_58_invites():
    """The acceptance criterion: 58 invites and a report that names the two bad rows."""
    lines = ["email,role,display_name"]
    for i in range(60):
        if i == 17:
            lines.append("broken-address,Editor,Broken")
        elif i == 41:
            lines.append("p41@acme.io,Astronaut,Unknown role")
        else:
            lines.append(f"p{i}@acme.io,Editor,Person {i}")
    rows = parse_import_csv("\n".join(lines).encode())
    report = _classify(rows, seats_free=100)
    counts = count_outcomes(report)
    assert counts["invite"] == 58
    bad = [(e["line"], e["outcome"]) for e in report if e["outcome"] != "invite"]
    assert bad == [(19, "invalid-email"), (43, "unknown-role")]


def test_count_outcomes_lists_every_outcome():
    counts = count_outcomes([{"outcome": "invite"}, {"outcome": "invite"}, {"outcome": "seat-cap"}])
    assert list(counts) == list(OUTCOMES)
    assert counts["invite"] == 2 and counts["seat-cap"] == 1 and counts["no-account"] == 0


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

_MEMBERS = [
    {
        "user_id": "u-ada",
        "email": "ada@acme.io",
        "status": "active",
        "role_name": "Editor",
        "two_factor_enabled": True,
        "joined_at": "2026-01-02T03:04:05+00:00",
    },
    {
        "user_id": "u-sam",
        "email": "-sam@acme.io",
        "status": "pending",
        "role_name": "=Release Manager",
        "two_factor_enabled": False,
        "joined_at": None,
        "provisioned_by": "sso:okta",
    },
]


def test_export_writes_the_documented_columns():
    text = export_members_csv(_MEMBERS, {"u-ada": "2026-06-01T09:00:00+00:00"})
    lines = text.strip().splitlines()
    assert lines[0] == ",".join(EXPORT_COLUMNS)
    assert lines[1] == "ada@acme.io,active,Editor,enabled,invite,2026-06-01T09:00:00+00:00,2026-01-02T03:04:05+00:00"


def test_export_never_writes_a_cell_a_spreadsheet_would_run():
    text = export_members_csv(_MEMBERS, {})
    assert "'-sam@acme.io,pending,'=Release Manager,disabled,sso:okta,," in text


def test_provenance_defaults_to_invite():
    assert member_provenance({}) == "invite"
    assert member_provenance({"provisioned_by": "scim"}) == "scim"


def test_an_export_imports_back_as_already_member_rows():
    """The acceptance criterion: the export round-trips through the import."""
    roles = _ROLES + [{"id": "role-x", "slug": "x", "name": "=Release Manager"}]
    rows = parse_import_csv(export_members_csv(_MEMBERS, {}).encode())
    assert [r.email for r in rows] == ["ada@acme.io", "-sam@acme.io"]
    report = classify_import(
        rows,
        roles=roles,
        member_emails={"ada@acme.io", "-sam@acme.io"},
        accounts={},
        seats_free=0,
    )
    assert {e["outcome"] for e in report} == {"already-member"}


# ---------------------------------------------------------------------------
# The reads behind the routes
# ---------------------------------------------------------------------------


def test_get_users_by_emails_is_one_query_keyed_by_normalized_address():
    from unittest.mock import patch

    from app.database import Database

    database = Database.__new__(Database)
    account = {"id": "u-1", "name": "Ada", "email": "Ada@Acme.io"}
    with patch.object(Database, "execute_query", return_value=[account]) as q:
        found = database.get_users_by_emails([" ADA@acme.io", "ada@acme.io", "ghost@acme.io", ""])
    assert found == {"ada@acme.io": {"id": "u-1", "name": "Ada", "email": "Ada@Acme.io"}}
    q.assert_called_once()
    assert q.call_args.args[1] == (["ada@acme.io", "ghost@acme.io"],)


def test_get_users_by_emails_skips_the_query_for_no_addresses():
    from unittest.mock import patch

    from app.database import Database

    database = Database.__new__(Database)
    with patch.object(Database, "execute_query") as q:
        assert database.get_users_by_emails(["", "  "]) == {}
    q.assert_not_called()


def test_list_member_last_sign_ins_reads_successful_sign_ins_for_the_tenant():
    from unittest.mock import patch

    from app.database import Database

    database = Database.__new__(Database)
    rows = [{"user_id": "u-1", "last_sign_in": "2026-06-01T00:00:00+00:00"}]
    with patch.object(Database, "execute_query", return_value=rows) as q:
        assert database.list_member_last_sign_ins("t-1") == {"u-1": "2026-06-01T00:00:00+00:00"}
    sql = q.call_args.args[0]
    assert "event_type = 'sign_in'" in sql and "outcome = 'success'" in sql
    assert q.call_args.args[1] == ("t-1",)


def test_member_seats_free_never_goes_below_zero():
    from unittest.mock import patch

    from app import license_capacity

    with patch.object(license_capacity, "db") as ldb:
        ldb.get_tenant_license_seats.return_value = {"max_users_per_tenant": 5}
        ldb.count_member_seats_in_use.return_value = 3
        assert license_capacity.member_seats_free("t") == 2
        ldb.count_member_seats_in_use.return_value = 7
        assert license_capacity.member_seats_free("t") == 0
