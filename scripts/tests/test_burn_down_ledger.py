"""The RC1 bug burn-down ledger stays internally consistent (RC1-4.2, #3621).

``docs/next-steps/RC1_BURN_DOWN.md`` is what the release gate reads to answer "no open
Critical/High, every deferral documented". It is hand-edited, so the mistakes worth catching are
the ones a reviewer would skim past:

* a Critical/High quietly moved into the deferred table;
* a deferral with no reason or no revisit target;
* a gate marked GREEN while a blocker is still listed;
* a severity spelled differently from the GitHub label it must match.

Run with: ``python3 -m unittest scripts/tests/test_burn_down_ledger.py``.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import sync_beta_labels  # noqa: E402  (path set up above)

LEDGER_PATH = ROOT / "docs" / "next-steps" / "RC1_BURN_DOWN.md"

#: Severities that block the tag, and so may only sit in the open table.
BLOCKING = {"sev:critical", "sev:high"}

#: Severities that may be deferred.
DEFERRABLE = {"sev:medium", "sev:low"}

#: An issue reference in a table cell, e.g. ``[#4960](…)``.
_ISSUE = re.compile(r"\[#(\d+)\]")


def section(text: str, heading_prefix: str) -> str:
    """Return the body of the ``## <heading_prefix>…`` section, up to the next ``## `` heading.

    Args:
        text: The whole ledger.
        heading_prefix: The start of the heading text, e.g. ``"2. Open"``.

    Returns:
        The section body without its heading line.

    Raises:
        AssertionError: If no such section exists.
    """
    match = re.search(rf"^## {re.escape(heading_prefix)}[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not match:
        raise AssertionError(f"ledger has no section starting '## {heading_prefix}'")
    return match.group(1)


def table_rows(body: str) -> list[dict[str, str]]:
    """Parse the first Markdown table in a section into dicts keyed by header.

    Args:
        body: A section body containing one pipe table.

    Returns:
        One dict per data row (header and ``|---|`` separator excluded), with every cell
        stripped. Escaped pipes are not supported, and the ledger doesn't use them.
    """
    lines = [line.strip() for line in body.splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        return []
    split = lambda line: [cell.strip() for cell in line.strip("|").split("|")]  # noqa: E731
    header = split(lines[0])
    return [dict(zip(header, split(line))) for line in lines[2:]]


def issue_of(row: dict[str, str]) -> int:
    """Return the issue number referenced in a row's ``Issue`` cell.

    Raises:
        AssertionError: If the cell has no ``[#N]`` reference.
    """
    match = _ISSUE.search(row["Issue"])
    if not match:
        raise AssertionError(f"row has no issue reference: {row['Issue']!r}")
    return int(match.group(1))


class BurnDownLedgerTest(unittest.TestCase):
    """Structure and gate rules of the ledger."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = LEDGER_PATH.read_text(encoding="utf-8")
        cls.open_rows = table_rows(section(cls.text, "2. Open"))
        cls.deferred_rows = table_rows(section(cls.text, "3. Deferred"))
        cls.sev_labels = {
            label["name"] for label in sync_beta_labels.load_labels() if label["name"].startswith("sev:")
        }

    def test_tables_have_the_expected_columns(self) -> None:
        for rows, columns in (
            (self.open_rows, ["Issue", "Severity", "Source", "Next step", "Blocks tag"]),
            (self.deferred_rows, ["Issue", "Severity", "Reason", "Revisit", "Constraint"]),
        ):
            for row in rows:
                self.assertEqual(list(row), columns)

    def test_every_severity_is_a_real_label(self) -> None:
        for row in self.open_rows + self.deferred_rows:
            with self.subTest(issue=row["Issue"]):
                self.assertIn(row["Severity"], self.sev_labels)

    def test_open_table_holds_only_blockers(self) -> None:
        for row in self.open_rows:
            with self.subTest(issue=row["Issue"]):
                self.assertIn(row["Severity"], BLOCKING)
                self.assertEqual(row["Blocks tag"], "yes")
                self.assertTrue(row["Next step"])

    def test_no_blocker_is_deferred(self) -> None:
        # Deferring a Critical/High is a release-lead decision. It is made by editing this
        # rule and the row together, never by moving a row on its own.
        for row in self.deferred_rows:
            with self.subTest(issue=row["Issue"]):
                self.assertIn(row["Severity"], DEFERRABLE)

    def test_every_deferral_is_documented(self) -> None:
        for row in self.deferred_rows:
            with self.subTest(issue=row["Issue"]):
                self.assertGreater(len(row["Reason"]), 40, "a reason is a sentence, not a word")
                self.assertTrue(row["Revisit"])
                self.assertTrue(row["Constraint"], "use an em dash for 'none'")

    def test_no_issue_is_listed_twice(self) -> None:
        numbers = [issue_of(row) for row in self.open_rows + self.deferred_rows]
        self.assertEqual(len(numbers), len(set(numbers)))

    def test_gate_status_follows_the_open_table(self) -> None:
        match = re.search(r"^\*\*Gate status:\*\* (RED|GREEN)\s*$", self.text, re.M)
        self.assertIsNotNone(match, "ledger must state '**Gate status:** RED' or GREEN")
        self.assertEqual(match.group(1), "RED" if self.open_rows else "GREEN")

    def test_states_an_as_of_date(self) -> None:
        self.assertRegex(self.text, re.compile(r"^\*\*As of:\*\* \d{4}-\d{2}-\d{2}\s*$", re.M))


class ParserTest(unittest.TestCase):
    """The small parsers the ledger test relies on."""

    def test_section_stops_at_the_next_heading(self) -> None:
        text = "## 1. A\none\n## 2. B\ntwo\n"
        self.assertEqual(section(text, "1. A"), "one\n")
        self.assertEqual(section(text, "2. B"), "two\n")

    def test_missing_section_fails_loudly(self) -> None:
        with self.assertRaises(AssertionError):
            section("## 1. A\n", "9. Z")

    def test_table_rows_skips_header_and_separator(self) -> None:
        body = "intro\n\n| Issue | Severity |\n|---|---|\n| [#1] x | sev:low |\n"
        self.assertEqual(table_rows(body), [{"Issue": "[#1] x", "Severity": "sev:low"}])

    def test_table_rows_of_an_empty_section(self) -> None:
        self.assertEqual(table_rows("nothing here\n"), [])

    def test_issue_of_requires_a_reference(self) -> None:
        self.assertEqual(issue_of({"Issue": "[#4960](https://x) title"}), 4960)
        with self.assertRaises(AssertionError):
            issue_of({"Issue": "no reference"})


if __name__ == "__main__":
    unittest.main()
