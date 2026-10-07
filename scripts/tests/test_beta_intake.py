"""Beta feedback intake stays consistent (RC1-4.1, #3620).

Three files describe one triage flow and drift silently if edited apart:

* ``.github/ISSUE_TEMPLATE/beta-feedback.yml`` — the issue form reporters fill in;
* ``.github/beta-labels.json`` — the labels triage applies;
* ``scripts/sync_beta_labels.py`` — what pushes those labels to GitHub.

GitHub accepts a form that applies a label the repository does not have (the label is simply
dropped), so a typo would not fail anywhere but here.

Run with: ``python3 -m unittest scripts/tests/test_beta_intake.py`` (needs PyYAML).
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import sync_beta_labels  # noqa: E402  (path set up above)

FORM_PATH = ROOT / ".github" / "ISSUE_TEMPLATE" / "beta-feedback.yml"
CONFIG_PATH = ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml"
RUNBOOK_PATH = ROOT / "docs" / "runbooks" / "BETA_TRIAGE.md"


def form_field(form: dict, field_id: str) -> dict:
    """Return the form body element with the given ``id``.

    Args:
        form: The parsed issue form.
        field_id: The element's ``id``.

    Returns:
        The matching body element.

    Raises:
        AssertionError: If no element has that id.
    """
    for element in form["body"]:
        if element.get("id") == field_id:
            return element
    raise AssertionError(f"form has no field with id {field_id!r}")


class BetaFormTest(unittest.TestCase):
    """The issue form is valid and agrees with the label set."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.form = yaml.safe_load(FORM_PATH.read_text(encoding="utf-8"))
        cls.labels = sync_beta_labels.load_labels()
        cls.names = {label["name"] for label in cls.labels}

    def test_has_the_keys_github_requires(self) -> None:
        for key in ("name", "description", "body"):
            self.assertIn(key, self.form)
        self.assertTrue(self.form["description"])

    def test_every_applied_label_is_declared(self) -> None:
        self.assertEqual(self.form["labels"], ["beta", "triage:new"])
        for name in self.form["labels"]:
            self.assertIn(name, self.names)

    def test_ids_are_unique(self) -> None:
        ids = [element["id"] for element in self.form["body"] if "id" in element]
        self.assertEqual(len(ids), len(set(ids)))

    def test_the_core_questions_are_required(self) -> None:
        for field_id in ("workflow", "trying", "happened", "impact"):
            with self.subTest(field=field_id):
                self.assertIs(form_field(self.form, field_id)["validations"]["required"], True)

    def test_workflow_options_and_wf_labels_match_one_to_one(self) -> None:
        options = form_field(self.form, "workflow")["attributes"]["options"]
        wf_labels = [label for label in self.labels if label["name"].startswith("wf:")]
        self.assertEqual(sorted(options), sorted(label["workflow"] for label in wf_labels))
        self.assertEqual(len(options), len(set(options)))

    def test_only_wf_labels_carry_a_workflow(self) -> None:
        for label in self.labels:
            with self.subTest(label=label["name"]):
                self.assertEqual("workflow" in label, label["name"].startswith("wf:"))

    def test_impact_is_the_reporters_view_not_a_severity_label(self) -> None:
        # Severity is a triage decision; the reporter's answer must never look like one.
        options = form_field(self.form, "impact")["attributes"]["options"]
        self.assertEqual(len(options), 4)
        for option in options:
            self.assertNotIn("sev:", option)

    def test_blank_issues_stay_enabled(self) -> None:
        config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertIs(config["blank_issues_enabled"], True)


class LabelSetTest(unittest.TestCase):
    """The label set covers the triage flow the runbook describes."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.names = {label["name"] for label in sync_beta_labels.load_labels()}

    def test_has_the_full_severity_scale(self) -> None:
        self.assertTrue({"sev:critical", "sev:high", "sev:medium", "sev:low"} <= self.names)

    def test_has_every_triage_state(self) -> None:
        states = {"triage:new", "triage:needs-info", "triage:accepted", "triage:deferred", "triage:duplicate"}
        self.assertTrue(states <= self.names)

    def test_runbook_documents_every_label(self) -> None:
        runbook = RUNBOOK_PATH.read_text(encoding="utf-8")
        for name in sorted(self.names):
            with self.subTest(label=name):
                self.assertIn(f"`{name}`", runbook)


class LoadLabelsValidationTest(unittest.TestCase):
    """``load_labels`` rejects a bad edit before any ``gh`` call."""

    def write(self, payload: object) -> Path:
        """Write ``payload`` as JSON to a temporary file and return its path."""
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        with handle:
            json.dump(payload, handle)
        self.addCleanup(Path(handle.name).unlink)
        return Path(handle.name)

    def assert_rejected(self, labels: object, fragment: str) -> None:
        """Assert that loading ``labels`` raises a ValueError mentioning ``fragment``."""
        with self.assertRaises(ValueError) as caught:
            sync_beta_labels.load_labels(self.write({"labels": labels}))
        self.assertIn(fragment, str(caught.exception))

    def test_rejects_an_empty_set(self) -> None:
        self.assert_rejected([], "non-empty")

    def test_rejects_a_missing_field(self) -> None:
        self.assert_rejected([{"name": "x", "color": "FFFFFF"}], "missing 'description'")

    def test_rejects_a_hash_prefixed_colour(self) -> None:
        self.assert_rejected([{"name": "x", "color": "#FFFFFF", "description": "d"}], "6 hex digits")

    def test_rejects_an_overlong_description(self) -> None:
        self.assert_rejected([{"name": "x", "color": "FFFFFF", "description": "d" * 101}], "exceeds")

    def test_rejects_a_case_insensitive_duplicate(self) -> None:
        # GitHub label names are case-insensitive, so `Beta` and `beta` are the same label.
        label = {"color": "FFFFFF", "description": "d"}
        self.assert_rejected([{"name": "beta", **label}, {"name": "Beta", **label}], "declared twice")

    def test_the_shipped_set_is_valid(self) -> None:
        self.assertGreater(len(sync_beta_labels.load_labels()), 0)


class SyncCommandTest(unittest.TestCase):
    """The sync script builds the right ``gh`` calls and runs nothing on a dry run."""

    def setUp(self) -> None:
        self.labels = sync_beta_labels.load_labels()

    def run_main(self, *argv: str) -> tuple[int, str, str]:
        """Run ``main`` with captured output; returns (exit code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = sync_beta_labels.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_one_forced_create_per_label(self) -> None:
        commands = sync_beta_labels.build_commands(self.labels)
        self.assertEqual(len(commands), len(self.labels))
        for cmd, label in zip(commands, self.labels):
            self.assertEqual(cmd[:4], ["gh", "label", "create", label["name"]])
            self.assertIn("--force", cmd)
            self.assertEqual(cmd[cmd.index("--color") + 1], label["color"])
            self.assertNotIn("--repo", cmd)

    def test_repo_is_passed_through(self) -> None:
        for cmd in sync_beta_labels.build_commands(self.labels, "apiome/apiome"):
            self.assertEqual(cmd[-2:], ["--repo", "apiome/apiome"])

    def test_dry_run_prints_and_calls_nothing(self) -> None:
        with mock.patch.object(sync_beta_labels.subprocess, "run") as run:
            code, out, _ = self.run_main("--dry-run")
        run.assert_not_called()
        self.assertEqual(code, 0)
        self.assertEqual(len(out.strip().splitlines()), len(self.labels))
        self.assertIn("gh label create beta", out)

    def test_apply_runs_every_command(self) -> None:
        ok = mock.Mock(returncode=0, stderr="")
        with mock.patch.object(sync_beta_labels.subprocess, "run", return_value=ok) as run:
            code, _, _ = self.run_main("--repo", "apiome/apiome")
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, len(self.labels))

    def test_a_failed_label_does_not_stop_the_rest(self) -> None:
        results = [mock.Mock(returncode=1, stderr="HTTP 403")] + [
            mock.Mock(returncode=0, stderr="") for _ in self.labels[1:]
        ]
        with mock.patch.object(sync_beta_labels.subprocess, "run", side_effect=results) as run:
            code, _, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertEqual(run.call_count, len(self.labels))
        self.assertIn("HTTP 403", err)
        self.assertIn(f"1 of {len(self.labels)} labels failed", err)

    def test_an_invalid_file_exits_before_any_call(self) -> None:
        bad = Path(tempfile.mkdtemp()) / "labels.json"
        bad.write_text('{"labels": []}', encoding="utf-8")
        self.addCleanup(bad.unlink)
        with mock.patch.object(sync_beta_labels.subprocess, "run") as run:
            code, _, err = self.run_main("--labels-file", str(bad))
        run.assert_not_called()
        self.assertEqual(code, 1)
        self.assertIn("error:", err)


if __name__ == "__main__":
    unittest.main()
