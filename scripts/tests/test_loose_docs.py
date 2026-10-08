"""The loose-docs lint and the legacy docs inventory (DOCS-1.14, #5631).

``scripts/check-loose-docs.sh`` fails a pull request that adds a Markdown file under
``apiome-*/docs/`` that is not a README/CHANGELOG/AGENTS file or allow-listed; and
``scripts/legacy_docs_inventory.py --check`` keeps ``docs/archive/INVENTORY.md`` true to the tree.
The lint is exercised against throwaway git repositories, the inventory against the real one.

Run with: ``python3 -m unittest scripts/tests/test_loose_docs.py``.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import legacy_docs_inventory as inventory  # noqa: E402  (path set up above)

LINT = ROOT / "scripts" / "check-loose-docs.sh"


class LooseDocsLintTest(unittest.TestCase):
    """``check-loose-docs.sh`` over a scratch repository."""

    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="loose-docs-"))
        self.addCleanup(shutil.rmtree, self.repo)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        self.write("scripts/loose-docs-allowlist.txt", "# header comment\n\napiome-rest/docs/canonical_model.md\n")
        self.write("apiome-rest/docs/canonical_model.md", "# Canonical model\n")
        self.write("apiome-rest/docs/README.md", "# Index\n")
        self.write("apiome-ui/docs/CHANGELOG.md", "# Changelog\n")
        self.write("apiome-docs/docs/build/page.md", "# A site page, never a loose doc\n")
        self.write("docs/archive/apiome-ui/OLD_NOTE.md", "# Archived\n")

    def write(self, relative: str, text: str) -> None:
        """Create a file in the scratch repository."""
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def lint(self) -> subprocess.CompletedProcess[str]:
        """Run the lint against the scratch repository."""
        return subprocess.run(["bash", str(LINT), str(self.repo)], capture_output=True, text=True)

    def test_passes_readmes_changelogs_allow_listed_files_the_site_and_the_archive(self) -> None:
        result = self.lint()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no loose Markdown", result.stdout)

    def test_fails_a_new_note_tracked_or_not(self) -> None:
        self.write("apiome-ui/docs/BUTTON_FIX_SUMMARY.md", "# Fixed it\n")
        result = self.lint()
        self.assertEqual(result.returncode, 1)
        self.assertIn("apiome-ui/docs/BUTTON_FIX_SUMMARY.md", result.stderr)
        self.assertIn("apiome-docs/docs/", result.stderr)

    def test_fails_a_note_in_a_nested_folder(self) -> None:
        self.write("apiome-db/docs/notes/SCHEMA.md", "# Schema\n")
        result = self.lint()
        self.assertEqual(result.returncode, 1)
        self.assertIn("apiome-db/docs/notes/SCHEMA.md", result.stderr)

    def test_always_allows_agents_files(self) -> None:
        self.write("apiome-mcp/docs/AGENTS.md", "# Agents\n")
        self.assertEqual(self.lint().returncode, 0)

    def test_fails_a_stale_allow_list_entry(self) -> None:
        (self.repo / "apiome-rest/docs/canonical_model.md").unlink()
        result = self.lint()
        self.assertEqual(result.returncode, 1)
        self.assertIn("is allow-listed but does not exist", result.stderr)

    def test_passes_the_real_repository(self) -> None:
        result = subprocess.run(["bash", str(LINT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class InventoryTest(unittest.TestCase):
    """The classification rules and the committed inventory."""

    def test_the_committed_inventory_matches_the_tree(self) -> None:
        self.assertEqual(inventory.check(ROOT), [])

    def test_every_row_has_a_disposition_and_the_counts_add_up(self) -> None:
        rows = inventory.parse_inventory((ROOT / inventory.INVENTORY).read_text(encoding="utf-8"))
        self.assertGreater(len(rows), 800)
        self.assertEqual({row.disposition for row in rows}, {"keep", "migrate", "archive"})
        self.assertEqual(len({row.path for row in rows}), len(rows), "a file is inventoried twice")

    def test_the_allow_list_is_every_kept_file_under_a_package_docs_folder(self) -> None:
        rows = inventory.parse_inventory((ROOT / inventory.INVENTORY).read_text(encoding="utf-8"))
        committed = (ROOT / inventory.ALLOWLIST).read_text(encoding="utf-8")
        self.assertEqual(inventory.render_allowlist(rows), committed)

    def test_keep_rules(self) -> None:
        referenced = {"apiome-ui/docs/AUTH_ERROR_CODES.md"}
        reason = inventory.keep_reason
        self.assertIn("referenced by code", reason("apiome-ui/docs/AUTH_ERROR_CODES.md", referenced))
        self.assertIn("contributor reference", reason("apiome-rest/docs/normalizer_spi.md", set()))
        self.assertIn("README", reason("apiome-cli/README.md", set()))
        self.assertIn("runbook", reason("docs/runbooks/BACKUP_AND_DR.md", set()))
        self.assertIn("release gate", reason("docs/next-steps/RC1_BURN_DOWN.md", set()))
        self.assertIsNone(reason("apiome-ui/docs/BUILD_FIX_COMPLETE.md", set()))
        self.assertIsNone(reason("apiome-ui/docs/README.md", set()), "the boilerplate README is archived")
        self.assertIsNone(reason("apiome-ui/docs/PLANNED_FEATURE_ROADMAP_PATHS.md", set()))

    def test_archive_locations_mirror_where_a_file_came_from(self) -> None:
        self.assertEqual(inventory.archive_location("apiome-ui/docs/X.md"), "docs/archive/apiome-ui/X.md")
        self.assertEqual(
            inventory.archive_location("docs/next-steps/DEMO.md"), "docs/archive/repository/next-steps/DEMO.md"
        )

    def test_archived_notes_point_at_the_page_for_their_area(self) -> None:
        self.assertEqual(inventory.area_page("apiome-ui/docs/AUTO_LAYOUT_GUIDE.md"), "build/studio")
        self.assertEqual(inventory.area_page("apiome-ui/docs/ENUM_SORTING.md"), "build/edit-classes-and-properties")
        self.assertEqual(inventory.area_page("apiome-browse/docs/CORS_FIX_GUIDE.md"), "ship/browse-published-specs")
        self.assertEqual(inventory.area_page("apiome-ui/docs/ALL-TESTS-FIXED.md"), "")

    def test_every_site_page_named_by_a_rule_exists(self) -> None:
        site = ROOT / "apiome-docs" / "docs"
        pages = {page for _, page in inventory.AREA_PAGES} | set(inventory.MIGRATED.values())
        for page in pages:
            self.assertTrue(
                (site / f"{page}.md").exists() or (site / f"{page}.mdx").exists(), f"{page} is not a site page"
            )

    def test_the_inventory_round_trips(self) -> None:
        rows = [
            inventory.Row("a/docs/X.md", "archive", "docs/archive/a/X.md", "build/studio", "record of past work"),
            inventory.Row("b/README.md", "keep", "b/README.md", "", "package README / changelog"),
        ]
        self.assertEqual(inventory.parse_inventory(inventory.render_inventory(rows)), rows)


if __name__ == "__main__":
    unittest.main()
