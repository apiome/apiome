#!/usr/bin/env python3
"""Inventory of the repository's loose Markdown, with a disposition for every file (DOCS-1.14, #5631).

Hundreds of implementation notes (fix summaries, feature write-ups, test journeys) used to sit
beside the code in ``apiome-*/docs/`` and ``docs/`` with no index. This script sorts every tracked
``.md`` outside the documentation site (``apiome-docs/``) and the design mockups (``docs/mockups/``)
into one of three dispositions:

``keep``
    Stays where it is: package READMEs and changelogs, agent skills, test fixtures and the examples
    corpus, roadmaps, the runbooks the site links to, the contributor references in
    ``apiome-rest/docs`` and ``apiome-mcp/docs``, and any note that source code, tests, env
    templates or migrations point at by path.
``archive``
    Moved (``git mv``) to ``docs/archive/<package>/`` — read-only history that does not describe
    the product as it is. The inventory names the site page that now covers the area, if any.
``migrate``
    Content folded into a site page; the row names the page.

Usage::

    python scripts/legacy_docs_inventory.py --apply   # classify, move, write the inventory + allow-list
    python scripts/legacy_docs_inventory.py --check   # verify the committed inventory against the tree

``--apply`` was run once, by DOCS-1.14; ``--check`` keeps the inventory honest afterwards.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Where archived files go, and where the inventory lives.
ARCHIVE_DIR = "docs/archive"
INVENTORY = f"{ARCHIVE_DIR}/INVENTORY.md"
#: The loose-docs lint's allow-list (``scripts/check-loose-docs.sh``).
ALLOWLIST = "scripts/loose-docs-allowlist.txt"

#: Trees that are not loose docs at all and are not inventoried.
EXCLUDED_ROOTS = ("apiome-docs/", "docs/mockups/", f"{ARCHIVE_DIR}/")

#: Basenames the loose-docs lint always allows; never archived.
ALWAYS_ALLOWED = ("README.md", "CHANGELOG.md", "AGENTS.md")

#: Site of the documentation, for the "site page" column.
SITE = "https://apiome.github.io/apiome/"

#: Folders whose notes are archived unless kept by a rule below.
ARCHIVABLE_DIRS = (
    "apiome-ui/docs/",
    "apiome-browse/docs/",
    "apiome-db/docs/",
    "docs/next-steps/",
)

#: Single files outside those folders that are archived (planning/demo notes for finished work).
ARCHIVABLE_FILES = ("docs/BETTER_AUTH_MIGRATION.md", "docs/MOCK_DEMO_SCRIPT.md")

#: Files kept although they sit in an archivable folder, with the reason.
KEEP_OVERRIDES = {
    "docs/next-steps/RC1_BURN_DOWN.md": "read by the release gate (scripts/tests/test_burn_down_ledger.py)",
    "apiome-ui/docs/GITLAB_SSO_SETUP.md": "linked from AUTH_PROVIDER_SETUP.md, which the env templates and tests point at",
}

#: Docs-folder READMEs that are framework boilerplate rather than an index anything points at; they are
#: archived with them and replaced by a short pointer README.
ARCHIVED_READMES = ("apiome-ui/docs/README.md",)

#: Notes whose content was folded into a site page by DOCS-1.14 (kept or archived, the row says so).
MIGRATED = {
    "apiome-ui/docs/AUTH_PROVIDER_SETUP.md": "admin/auth-providers",
    "apiome-ui/docs/ENTRA_ID_APP_REGISTRATION.md": "admin/auth-providers",
    "apiome-ui/docs/GITLAB_SSO_SETUP.md": "admin/auth-providers",
}

#: File-name words that mark a record of past work rather than a description of the product.
NOTE_WORDS = re.compile(
    r"FIX|SUMMARY|IMPLEMENTATION|COMPLETE|REPORT|JOURNEY|CHECKLIST|STATUS|CHANGES|REFACTOR|"
    r"RESOLUTION|FINAL|VERIFICATION|DEBUG|MIGRATION|TEST|COVERAGE|DELIVERABLES|ENHANCEMENT|UPDATE|"
    r"IMPROVEMENT|REMOVED|DEMONSTRATION|BURN_DOWN|ORDER_OF_EXECUTION|CONVERSION|ISSUE|SOLUTION",
)

#: First match wins: file-name words → the site page that covers that area today.
AREA_PAGES: tuple[tuple[str, str], ...] = (
    (r"CATALOG_FORMAT_DETAILS", "bring-in/catalog-format-details"),
    (r"REVIEW", "govern/reviews"),
    (r"USER_MANAGEMENT", "admin/users"),
    (r"PAT_|PRIVATE_REPO", "bring-in/repositories"),
    (r"GENERAT|POJO|SCALA|PYTHON_GEN", "ship/export-a-spec"),
    (r"LEVEL_OF_DETAIL|GROUP_POSITION", "build/studio"),
    (r"OPENAPI|X_METADATA|EXTERNAL_DOCS|MULTIPLEOF|REQUIRED_FLAG|REGEX", "build/edit-classes-and-properties"),
    (r"CATALOG", "bring-in/catalog"),
    (r"LINKED_ACCOUNT|ACCOUNT_LINKING|LINK_BUTTON", "workspace/linked-accounts"),
    (r"AUTH|LOGIN|SIGNUP|SSO|OAUTH|ENTRA|BETTER_AUTH|EMAIL_CANONICAL|USER_ID", "admin/auth-providers"),
    (r"API_KEY", "workspace/api-keys"),
    (r"TENANT", "workspace/tenants"),
    (r"MEMBER|INVIT", "workspace/members"),
    (r"ROLE|RBAC|PERMISSION", "workspace/roles"),
    (r"NOTIFICATION", "workspace/notifications"),
    (r"KEYBOARD|SHORTCUT|HOTKEY", "workspace/keyboard"),
    (r"A11Y|ACCESSIB", "workspace/accessibility"),
    (r"THEME|DARK_MODE|PREFERENCE|FONT|DENSITY", "workspace/preferences"),
    (r"LICENS", "admin/licenses"),
    (r"FEATURE_FLAG", "admin/feature-flags"),
    (r"PROPERTY_TEMPLATE", "admin/property-templates"),
    (r"ADMIN", "admin/admin-console"),
    (r"DATABASE|SQL_EDITOR|DATA_BROWSER|UTF8|MIGRATION_2025", "admin/data-browser"),
    (r"DOCKER|DEPLOY|BUILD_SCRIPT|UV_SETUP|ENVIRONMENT|BACKUP", "getting-started/run-locally"),
    (r"MOCK", "reference/mock-runtime/one-mock-engine"),
    (r"MCP", "bring-in/mcp-servers"),
    (r"REPOSITOR|GITLAB|GITHUB|WEBHOOK", "bring-in/repositories"),
    (r"PRIMITIVE|NAMESPACE|SYSTEM_TYPE", "build/primitives-and-types"),
    (r"LINT|STYLE_GUIDE|SPECTRAL|RULESET|QUALITY|SCORE", "build/lint-and-quality"),
    (r"EXPORT|GENERATE|CODE_FORMAT|CODEGEN|SDK", "ship/export-a-spec"),
    (r"PUBLISH|SUNSET", "ship/publish-a-version"),
    (r"VERSION|DIFF|COMPARE|CHANGELOG", "build/versions"),
    (
        r"IMPORT|SWAGGER|PYDANTIC|TYPESCRIPT|GRAPHQL|ASYNCAPI|ARAZZO|PROTO|AVRO|RAML|WSDL|XSD|"
        r"JSON_SCHEMA|POSTMAN|SQL",
        "bring-in/import-a-spec",
    ),
    (r"PATH|RESPONSE|REQUEST|OPERATION|PARAMETER|ENDPOINT", "build/edit-paths"),
    (
        r"CANVAS|EDGE|LAYOUT|DRAG|DROP|MERMAID|NODE|ZOOM|MINIMAP|STUDIO|DIAGRAM|GRAPH",
        "build/studio",
    ),
    (
        r"CLASS|PROPERT|ENUM|CONST|DISCRIMINATOR|TUPLE|PATTERN|NESTED|DEPRECATED|ADDITIONAL|"
        r"CONTAINS|DEPENDENT|EXCLUSIVE|CONSTRAINT|ARRAY|SCHEMA|FORMAT|EXAMPLE|DEFAULT|NULLABLE|"
        r"READ_ONLY|WRITE_ONLY|REF|COMPOSITION|ONE_OF|ANY_OF|ALL_OF|INHERIT|EXTENSION",
        "build/edit-classes-and-properties",
    ),
    (r"PROJECT", "build/projects"),
    (r"DASHBOARD|HOME|LAUNCHER|EMPTY_STATE|NAVIGATION|SIDEBAR|LAYOUT", "getting-started/launcher-and-home"),
    (r"BROWSE|COPY_URL|YOUTUBE|CORS|REST_API|GETTING_STARTED|FEATURES|TROUBLESHOOTING", "ship/browse-published-specs"),
)


@dataclass(frozen=True)
class Row:
    """One inventoried file.

    Attributes:
        path: Repository-relative path the file had when it was inventoried.
        disposition: ``keep``, ``archive`` or ``migrate``.
        location: Where the file is now (``path`` when kept; under ``docs/archive/`` when archived).
        page: Site page (path under the site) that covers the area, or ``""``.
        note: Why it is kept, or what kind of note it was.
    """

    path: str
    disposition: str
    location: str
    page: str
    note: str


def tracked_markdown(root: Path = REPO_ROOT) -> list[str]:
    """Every tracked ``.md`` outside the excluded trees.

    Args:
        root: Repository root.

    Returns:
        Repository-relative paths, sorted.
    """
    out = subprocess.run(["git", "ls-files", "*.md"], cwd=root, check=True, capture_output=True, text=True)
    return sorted(p for p in out.stdout.splitlines() if p and not p.startswith(EXCLUDED_ROOTS))


def code_references(paths: list[str], root: Path = REPO_ROOT) -> set[str]:
    """The inventoried files that a non-Markdown tracked file points at by path.

    A file ``<pkg>/docs/<name>`` counts as referenced when a non-``.md`` file anywhere contains
    ``<pkg>/docs/<name>``, or a non-``.md`` file inside ``<pkg>/`` contains ``docs/<name>`` — so a
    common basename (``QUICK_REFERENCE.md``) in another package is not a false match.

    Args:
        paths: Inventoried paths.
        root: Repository root.

    Returns:
        The referenced paths.
    """
    out = subprocess.run(["git", "ls-files"], cwd=root, check=True, capture_output=True, text=True)
    sources = [p for p in out.stdout.splitlines() if p and not p.endswith(".md") and not p.startswith("docs/mockups/")]
    texts: dict[str, str] = {}
    for source in sources:
        try:
            texts[source] = (root / source).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

    referenced: set[str] = set()
    for path in paths:
        if Path(path).name in ALWAYS_ALLOWED:
            continue
        package, _, rest = path.partition("/")
        local = rest  # e.g. docs/AUTH_ERROR_CODES.md
        for source, text in texts.items():
            if path in text or (source.startswith(f"{package}/") and local and local in text):
                referenced.add(path)
                break
    return referenced


def area_page(path: str) -> str:
    """The site page covering a note's area, guessed from its file name.

    Args:
        path: Repository-relative path.

    Returns:
        A site page path such as ``build/studio``, or ``""`` when no rule matches.
    """
    name = Path(path).stem.upper().replace("-", "_")
    if path.startswith("apiome-browse/"):
        return "ship/browse-published-specs"
    for pattern, page in AREA_PAGES:
        if re.search(pattern, name):
            return page
    return ""


def keep_reason(path: str, referenced: set[str]) -> str | None:
    """Why a file stays where it is, or ``None`` when it is to be archived.

    Args:
        path: Repository-relative path.
        referenced: Paths that code points at (see :func:`code_references`).

    Returns:
        The reason, or ``None``.
    """
    name = Path(path).name
    if path in KEEP_OVERRIDES:
        return KEEP_OVERRIDES[path]
    if path in ARCHIVED_READMES:
        return None
    if name in ALWAYS_ALLOWED:
        return "package README / changelog"
    if path in referenced:
        return "referenced by code, tests, env templates or migrations"
    if path.startswith(("apiome-rest/docs/", "apiome-mcp/docs/")):
        return "contributor reference (SPI guides, wire contracts) for the package"
    if path.startswith((".github/", ".cursor/", ".claude/")):
        return "agent skill or repository template"
    if "/tests/" in path or "/test/" in path or "/e2e/" in path or path.startswith("apiome-ui/examples/"):
        return "test fixture or examples corpus"
    if path.startswith("docs/runbooks/"):
        return "operator runbook, linked from Admin → Operating Apiome"
    if path.startswith(ARCHIVABLE_DIRS):
        return None
    if "ROADMAP" in Path(path).name or path.startswith("docs/PLAN"):
        return "roadmap or plan"
    if path == "docs/guide/README.md":
        return "redirect map from the old guide folder to the site"
    if path == "docs/CORPUS_CONTRIBUTOR_GUIDE.md":
        return "contributor guide for the examples corpus"
    if path.startswith(ARCHIVABLE_DIRS) or path in ARCHIVABLE_FILES:
        return None
    return "package or repository documentation outside the docs folders"


def archive_location(path: str) -> str:
    """Where an archived file goes: ``docs/archive/<package>/<rest of path under docs/>``.

    Args:
        path: Repository-relative path.

    Returns:
        The new repository-relative path.
    """
    if path.startswith("docs/"):
        return f"{ARCHIVE_DIR}/repository/{path[len('docs/'):]}"
    package, _, rest = path.partition("/")
    rest = rest[len("docs/"):] if rest.startswith("docs/") else rest
    return f"{ARCHIVE_DIR}/{package}/{rest}"


def classify(paths: list[str], referenced: set[str]) -> list[Row]:
    """Give every path its disposition.

    Args:
        paths: Inventoried paths.
        referenced: Paths that code points at.

    Returns:
        One row per path, in path order.
    """
    rows = []
    for path in paths:
        reason = keep_reason(path, referenced)
        page = MIGRATED.get(path, "")
        if path in MIGRATED:
            location = path if reason else archive_location(path)
            note = f"provider registration steps migrated to the site; {reason}" if reason else "migrated to the site"
            rows.append(Row(path, "migrate", location, page, note))
        elif reason:
            rows.append(Row(path, "keep", path, "", reason))
        else:
            kind = "record of past work" if NOTE_WORDS.search(Path(path).stem.upper()) else "feature write-up or guide"
            rows.append(Row(path, "archive", archive_location(path), area_page(path), kind))
    return rows


def render_inventory(rows: list[Row]) -> str:
    """The Markdown inventory.

    Args:
        rows: Classified rows.

    Returns:
        The file's contents.
    """
    counts = {d: sum(1 for r in rows if r.disposition == d) for d in ("keep", "migrate", "archive")}
    lines = [
        "# Legacy docs inventory",
        "",
        "Every tracked Markdown file outside the documentation site (`apiome-docs/`) and the design",
        "mockups (`docs/mockups/`), as triaged by DOCS-1.14 ([#5631](https://github.com/apiome/apiome/issues/5631)).",
        "Generated by `scripts/legacy_docs_inventory.py`; `--check` verifies it against the tree.",
        "",
        f"**{len(rows)} files** — {counts['keep']} kept, {counts['migrate']} migrated, {counts['archive']} archived.",
        "",
        "- **keep** — stays where it is, for the reason given.",
        "- **migrate** — its content now lives on the site page named.",
        "- **archive** — moved to `docs/archive/`; read-only history that does not describe the product",
        "  as it is. *Site page* is where that area is documented today.",
        "",
        "| File | Disposition | Now at | Site page | Note |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        location = "" if row.location == row.path else f"`{row.location}`"
        page = f"[{row.page}]({SITE}{row.page})" if row.page else ""
        lines.append(f"| `{row.path}` | {row.disposition} | {location} | {page} | {row.note} |")
    return "\n".join(lines) + "\n"


def parse_inventory(text: str) -> list[Row]:
    """Read the rows back out of a rendered inventory.

    Args:
        text: The inventory's contents.

    Returns:
        The rows, in file order.
    """
    rows = []
    for line in text.splitlines():
        match = re.match(r"^\| `([^`]+)` \| (keep|migrate|archive) \| (?:`([^`]+)`)? \| (?:\[([^\]]+)\]\([^)]*\))? \| (.*) \|$", line)
        if match:
            path, disposition, location, page, note = match.groups()
            rows.append(Row(path, disposition, location or path, page or "", note))
    return rows


def render_allowlist(rows: list[Row]) -> str:
    """The loose-docs lint's allow-list: every kept or migrated file still under ``apiome-*/docs/``.

    Args:
        rows: Classified rows.

    Returns:
        The file's contents.
    """
    header = [
        "# Markdown files allowed under apiome-*/docs/ (scripts/check-loose-docs.sh, DOCS-1.14 #5631).",
        "# README.md, CHANGELOG.md and AGENTS.md are always allowed. Everything else belongs on the",
        "# documentation site (apiome-docs/docs/) — add a line here only for a contributor reference",
        "# that code points at, and say why in the pull request.",
    ]
    paths = sorted(
        r.location
        for r in rows
        if r.disposition in ("keep", "migrate")
        and re.match(r"^apiome-[^/]+/docs/", r.location)
        and Path(r.location).name not in ALWAYS_ALLOWED
    )
    return "\n".join(header + paths) + "\n"


def check(root: Path = REPO_ROOT) -> list[str]:
    """Verify the committed inventory against the tree.

    Args:
        root: Repository root.

    Returns:
        Problems: a kept file that no longer exists, an archived file missing from the archive, or
        an archived source path that is back in the tree (a replacement README is allowed).
    """
    inventory = root / INVENTORY
    if not inventory.exists():
        return [f"{INVENTORY} is missing"]
    rows = parse_inventory(inventory.read_text(encoding="utf-8"))
    if not rows:
        return [f"{INVENTORY} has no rows"]
    problems = []
    for row in rows:
        if not (root / row.location).exists():
            problems.append(f"{row.path}: inventoried as {row.disposition} at {row.location}, which does not exist")
        # A README archived with its folder's notes is replaced by a short pointer README.
        if row.location != row.path and (root / row.path).exists() and Path(row.path).name not in ALWAYS_ALLOWED:
            problems.append(f"{row.path}: archived to {row.location} but the original is back")
    return problems


def apply(root: Path = REPO_ROOT) -> list[Row]:
    """Classify, move the archived files with ``git mv``, and write the inventory and allow-list.

    Args:
        root: Repository root.

    Returns:
        The rows written.
    """
    paths = tracked_markdown(root)
    rows = classify(paths, code_references(paths, root))
    for row in rows:
        if row.location != row.path:
            (root / row.location).parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "mv", row.path, row.location], cwd=root, check=True)
    (root / INVENTORY).parent.mkdir(parents=True, exist_ok=True)
    (root / INVENTORY).write_text(render_inventory(rows), encoding="utf-8")
    (root / ALLOWLIST).write_text(render_allowlist(rows), encoding="utf-8")
    return rows


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Args:
        argv: Arguments (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply", action="store_true", help="classify, move and write the inventory")
    group.add_argument("--check", action="store_true", help="verify the committed inventory")
    group.add_argument("--dry-run", action="store_true", help="print the dispositions without changing anything")
    args = parser.parse_args(argv)

    if args.check:
        problems = check()
        for problem in problems:
            print(f"legacy docs inventory: {problem}", file=sys.stderr)
        if not problems:
            print(f"legacy docs inventory: {INVENTORY} matches the tree")
        return 1 if problems else 0
    if args.dry_run:
        paths = tracked_markdown()
        for row in classify(paths, code_references(paths)):
            print(f"{row.disposition}\t{row.path}\t{row.page}\t{row.note}")
        return 0
    rows = apply()
    print(f"legacy docs inventory: {len(rows)} files; wrote {INVENTORY} and {ALLOWLIST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
