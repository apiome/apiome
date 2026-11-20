"""The generated OpenAPI construct matrix on the docs site — COA-2.1 (#7044).

``reference/openapi-construct-matrix.md`` publishes, as Apiome's fidelity statement for
OpenAPI, the construct × version matrix that :mod:`app.openapi_construct_audit` measures over
the construct corpus (``apiome-rest/tests/fixtures/openapi_construct_corpus``: the OpenAPI
Initiative's test and example documents plus Apiome's own construct fixtures).

The table lives between :data:`BEGIN_MARKER` and :data:`END_MARKER`; everything else on the
page is hand-written. ``scripts/generate_openapi_construct_matrix_doc.py`` rewrites the region,
and ``tests/test_openapi_construct_audit.py`` regenerates it in memory and fails when the
committed page differs — so the published matrix is always the one the tests measure.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import List

from .docs_site import DOCS_SITE_PAGES_ROOT
from .openapi_construct_audit import DocumentAudit, audit_corpus, build_matrix, render_matrix_markdown

__all__ = [
    "BEGIN_MARKER",
    "CORPUS_DIR",
    "END_MARKER",
    "OPENAPI_CONSTRUCT_MATRIX_PAGE",
    "REGENERATE_COMMAND",
    "apply_construct_matrix",
    "audit_monorepo_corpus",
    "render_construct_matrix",
]

#: The docs page holding the matrix, relative to the monorepo root.
OPENAPI_CONSTRUCT_MATRIX_PAGE = f"{DOCS_SITE_PAGES_ROOT}/reference/openapi-construct-matrix.md"

#: The construct corpus, relative to the monorepo root.
CORPUS_DIR = "apiome-rest/tests/fixtures/openapi_construct_corpus"

#: The command that regenerates the matrix (run from the monorepo root).
REGENERATE_COMMAND = "cd apiome-rest && uv run python scripts/generate_openapi_construct_matrix_doc.py"

BEGIN_MARKER = (
    "<!-- openapi-construct-matrix:begin — generated, do not edit by hand. "
    f"Regenerate with: {REGENERATE_COMMAND} -->"
)
END_MARKER = "<!-- openapi-construct-matrix:end -->"


def render_construct_matrix(audits: List[DocumentAudit]) -> str:
    """Render the generated region (markers included) from corpus audits.

    Args:
        audits: One :class:`~app.openapi_construct_audit.DocumentAudit` per corpus document.

    Returns:
        The begin marker, the matrix table and corpus size line, and the end marker.
    """
    counts = Counter(audit.version for audit in audits)
    table = render_matrix_markdown(build_matrix(audits), corpus_counts=dict(counts))
    return f"{BEGIN_MARKER}\n\n{table}\n{END_MARKER}"


def apply_construct_matrix(text: str, audits: List[DocumentAudit]) -> str:
    """Return the page ``text`` with its generated region replaced by a fresh matrix.

    Raises:
        ValueError: When the page does not hold exactly one begin marker followed by one end
            marker.
    """
    begin = text.find(BEGIN_MARKER)
    end = text.find(END_MARKER)
    if begin < 0 or end < begin or text.count(BEGIN_MARKER) != 1 or text.count(END_MARKER) != 1:
        raise ValueError(
            f"{OPENAPI_CONSTRUCT_MATRIX_PAGE} must contain exactly one {BEGIN_MARKER!r} "
            f"followed by one {END_MARKER!r}"
        )
    return text[:begin] + render_construct_matrix(audits) + text[end + len(END_MARKER) :]


def audit_monorepo_corpus(monorepo_root: Path) -> List[DocumentAudit]:
    """Audit the construct corpus of the monorepo checked out at ``monorepo_root``."""
    return audit_corpus(monorepo_root / CORPUS_DIR)

