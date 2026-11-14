"""Bulk CSV member import and export (EID-2.5, #5671).

The Members screen's **Import CSV** and **Export CSV** share this module. It is pure: no I/O, no
database, no FastAPI. ``access_routes`` reads what the decisions need (roles, the roster,
accounts, free seats), and the logic here can be unit-tested on plain lists.

Import is a **dry run only**. :func:`classify_import` labels each row of an uploaded
``email,role,display_name`` file with what applying it would do. Applying it is not a second
create path: the client sends each ``invite`` row to the existing
``POST /v1/access/{tenant}/members``, so that route's seat guard, rate limit and audit entry
apply to every row exactly as they do to a hand-typed invitation.

Row outcomes, checked in this order (the first match wins):

* ``invalid-email`` — the address is blank or malformed.
* ``already-member`` — the address already belongs to a member of the tenant, or an earlier row
  of the same file already lists it.
* ``unknown-role`` — the ``role`` cell names no role of the tenant (by id, slug or name). An
  empty cell means the tenant's default role.
* ``no-account`` — no Apiome account uses the address. Invitations are not emailed, so the
  invite route would refuse it with a 404.
* ``seat-cap`` — the row is valid, but the tenant's free license seats ran out on earlier rows.
* ``invite`` — applying the row sends an invitation.

Export writes one row per member: email, status, role, two-factor, provenance (``invite``,
``sso:<id>`` or ``scim``), last sign-in and created. Importing an export back gives
``already-member`` rows, because every address in it is a member.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

from .database import normalize_email

#: Most data rows a single import file may hold.
MAX_IMPORT_ROWS = 1000

#: Largest accepted upload. 1,000 rows of three short cells fit well inside it.
MAX_IMPORT_BYTES = 1024 * 1024

#: Columns an import file may carry. Only ``email`` is required; others are ignored.
IMPORT_COLUMNS = ("email", "role", "display_name")

#: Columns of the export, in order.
EXPORT_COLUMNS = (
    "email",
    "status",
    "role",
    "two_factor",
    "provenance",
    "last_sign_in",
    "created",
)

OUTCOME_INVITE = "invite"
OUTCOME_ALREADY_MEMBER = "already-member"
OUTCOME_INVALID_EMAIL = "invalid-email"
OUTCOME_UNKNOWN_ROLE = "unknown-role"
OUTCOME_NO_ACCOUNT = "no-account"
OUTCOME_SEAT_CAP = "seat-cap"

#: Every outcome, in the order a report lists its counts.
OUTCOMES = (
    OUTCOME_INVITE,
    OUTCOME_ALREADY_MEMBER,
    OUTCOME_INVALID_EMAIL,
    OUTCOME_UNKNOWN_ROLE,
    OUTCOME_NO_ACCOUNT,
    OUTCOME_SEAT_CAP,
)

#: Provenance of a membership created by an invitation, the only path that exists today.
PROVENANCE_INVITE = "invite"

# The same shape check the team invite path uses (``teams.py``): one ``@``, a dot in the domain,
# no whitespace. Deliverability is not checked; the account lookup settles whether it is real.
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# A spreadsheet runs a cell that starts with one of these as a formula. The export prefixes such
# a cell with an apostrophe, and the import strips that apostrophe again (see `_csv_cell`).
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


class MemberCsvError(ValueError):
    """The upload as a whole cannot be read: not UTF-8, no ``email`` column, or too many rows."""


@dataclass(frozen=True)
class ImportRow:
    """One data row of an import file.

    Attributes:
        line: The row's line number in the file (the header is line 1), so a report points at
            the line a spreadsheet shows.
        email: The ``email`` cell, trimmed.
        role: The ``role`` cell, trimmed; empty for the tenant's default role.
        display_name: The ``display_name`` cell, trimmed. Shown in the report only: the invite
            route takes no name, because the account already has one.
    """

    line: int
    email: str
    role: str
    display_name: str


def is_valid_email(value: str) -> bool:
    """Return whether ``value`` is shaped like an email address.

    Args:
        value: The candidate address.

    Returns:
        ``True`` when the trimmed value has one ``@``, a dotted domain and no whitespace.
    """
    return bool(_EMAIL_PATTERN.match(value.strip()))


def _uncsv_cell(value: Optional[str]) -> str:
    """Trim a cell read from a file and undo the export's formula guard.

    Args:
        value: The raw cell, or ``None`` when the row is shorter than the header.

    Returns:
        The trimmed text, without the leading apostrophe :func:`_csv_cell` adds.
    """
    text = (value or "").strip()
    if len(text) > 1 and text[0] == "'" and text[1] in _FORMULA_PREFIXES:
        return text[1:]
    return text


def _csv_cell(value: Any) -> str:
    """Render one export cell so a spreadsheet never runs it as a formula.

    Args:
        value: The value. ``None`` becomes an empty cell; dates use ``isoformat``.

    Returns:
        The cell text, prefixed with ``'`` when it starts with a formula character.
    """
    if value is None:
        return ""
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    return f"'{text}" if text.startswith(_FORMULA_PREFIXES) else text


def parse_import_csv(content: bytes) -> List[ImportRow]:
    """Read an uploaded import file into rows.

    The header row is required and matched without regard to case or surrounding spaces.
    Columns other than :data:`IMPORT_COLUMNS` are ignored, so an export can be imported back
    as it is. Rows whose cells are all empty are skipped.

    Args:
        content: The uploaded bytes, UTF-8 (a byte-order mark is allowed).

    Returns:
        The data rows, in file order.

    Raises:
        MemberCsvError: When the file is not UTF-8, has no header or no ``email`` column, or
            holds more than :data:`MAX_IMPORT_ROWS` data rows.
    """
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise MemberCsvError("The file is not UTF-8 text. Save it as CSV (UTF-8) and try again.") from None

    reader = csv.reader(io.StringIO(text, newline=""))
    header = next(reader, None)
    if header is None:
        raise MemberCsvError("The file is empty. The first line must be a header: email,role,display_name.")
    columns = [cell.strip().lower() for cell in header]
    if "email" not in columns:
        raise MemberCsvError("The header has no email column. The first line must be: email,role,display_name.")

    def cell(record: Sequence[str], name: str) -> str:
        if name not in columns:
            return ""
        index = columns.index(name)
        return _uncsv_cell(record[index] if index < len(record) else None)

    rows: List[ImportRow] = []
    for record in reader:
        if not any(value.strip() for value in record):
            continue
        if len(rows) >= MAX_IMPORT_ROWS:
            raise MemberCsvError(
                f"The file has more than {MAX_IMPORT_ROWS} rows. Split it into files of "
                f"{MAX_IMPORT_ROWS} rows or fewer."
            )
        rows.append(
            ImportRow(
                line=reader.line_num,
                email=cell(record, "email"),
                role=cell(record, "role"),
                display_name=cell(record, "display_name"),
            )
        )
    return rows


def _role_index(roles: Iterable[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    """Index a tenant's roles by lower-cased id, slug and name, for the ``role`` cell.

    Args:
        roles: The tenant's roles (``id``, ``slug``, ``name``).

    Returns:
        A lookup from each lower-cased key to its role. An id wins over a slug, a slug over a
        name, if two roles ever collide.
    """
    index: Dict[str, Mapping[str, Any]] = {}
    roles = list(roles)
    for key in ("name", "slug", "id"):
        for role in roles:
            value = role.get(key)
            if value:
                index[str(value).strip().lower()] = role
    return index


def classify_import(
    rows: Sequence[ImportRow],
    *,
    roles: Iterable[Mapping[str, Any]],
    member_emails: Set[str],
    accounts: Mapping[str, Mapping[str, Any]],
    seats_free: Optional[int],
) -> List[Dict[str, Any]]:
    """Label each import row with what applying it would do. Changes nothing.

    Args:
        rows: The parsed rows (:func:`parse_import_csv`).
        roles: The tenant's roles (``id``, ``slug``, ``name``).
        member_emails: Normalized addresses of the tenant's current members, any status.
        accounts: Normalized address → account (``id``, ``email``) for every address that has
            an Apiome account.
        seats_free: License seats still free, or ``None`` when seats are not enforced. Each
            ``invite`` row takes one; once none are left, valid rows become ``seat-cap``.

    Returns:
        One report entry per row, in file order: ``line``, ``email``, ``role``,
        ``display_name``, ``outcome`` (one of :data:`OUTCOMES`), ``message`` (why, for every
        outcome but ``invite``), and for ``invite`` rows the ``user_id``, ``role_id`` and
        ``role_name`` to send.
    """
    role_lookup = _role_index(roles)
    first_line: Dict[str, int] = {}
    remaining = seats_free
    report: List[Dict[str, Any]] = []

    for row in rows:
        entry: Dict[str, Any] = {
            "line": row.line,
            "email": row.email,
            "role": row.role,
            "display_name": row.display_name,
            "outcome": OUTCOME_INVITE,
            "message": None,
            "user_id": None,
            "role_id": None,
            "role_name": None,
        }
        report.append(entry)

        if not is_valid_email(row.email):
            entry["outcome"] = OUTCOME_INVALID_EMAIL
            entry["message"] = "The email is missing." if not row.email else "This is not an email address."
            continue

        email = normalize_email(row.email)
        if email in member_emails:
            entry["outcome"] = OUTCOME_ALREADY_MEMBER
            entry["message"] = "Already a member of this workspace."
            continue
        if email in first_line:
            entry["outcome"] = OUTCOME_ALREADY_MEMBER
            entry["message"] = f"Listed earlier in this file, on line {first_line[email]}."
            continue
        first_line[email] = row.line

        role = role_lookup.get(row.role.lower()) if row.role else None
        if row.role and role is None:
            entry["outcome"] = OUTCOME_UNKNOWN_ROLE
            entry["message"] = f"No role named '{row.role}' in this workspace."
            continue

        account = accounts.get(email)
        if account is None:
            entry["outcome"] = OUTCOME_NO_ACCOUNT
            entry["message"] = "No Apiome account uses this email; ask them to sign up first."
            continue

        if remaining is not None and remaining <= 0:
            entry["outcome"] = OUTCOME_SEAT_CAP
            entry["message"] = "No member seat is left on the license for this row."
            continue
        if remaining is not None:
            remaining -= 1

        entry["user_id"] = account.get("id")
        if role is not None:
            entry["role_id"] = role.get("id")
            entry["role_name"] = role.get("name")

    return report


def count_outcomes(report: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    """Count report rows per outcome.

    Args:
        report: Entries from :func:`classify_import`.

    Returns:
        Every outcome in :data:`OUTCOMES`, zero when no row has it.
    """
    counts = {outcome: 0 for outcome in OUTCOMES}
    for entry in report:
        counts[entry["outcome"]] = counts.get(entry["outcome"], 0) + 1
    return counts


def member_provenance(member: Mapping[str, Any]) -> str:
    """Name how a membership was created: ``invite``, ``sso:<id>`` or ``scim``.

    Reads the membership's ``provisioned_by`` value. SSO provisioning (EID-1.3) and SCIM
    (EID-2.2) write it; until then every membership was made by an invitation, which is the
    value when the field is absent.

    Args:
        member: A roster row from ``Database.list_members``.

    Returns:
        The provenance label.
    """
    return str(member.get("provisioned_by") or PROVENANCE_INVITE)


def export_members_csv(
    members: Iterable[Mapping[str, Any]],
    last_sign_ins: Mapping[str, Any],
) -> str:
    """Write the roster as CSV, with :data:`EXPORT_COLUMNS` as the header.

    Args:
        members: Roster rows from ``Database.list_members``.
        last_sign_ins: User id → time of their latest successful sign-in, from
            ``auth_events``. A member with no entry gets an empty ``last_sign_in``.

    Returns:
        The CSV text.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(EXPORT_COLUMNS)
    for member in members:
        writer.writerow(
            [
                _csv_cell(member.get("email")),
                _csv_cell(member.get("status")),
                _csv_cell(member.get("role_name")),
                "enabled" if member.get("two_factor_enabled") else "disabled",
                _csv_cell(member_provenance(member)),
                _csv_cell(last_sign_ins.get(str(member.get("user_id")))),
                _csv_cell(member.get("joined_at")),
            ]
        )
    return buffer.getvalue()
