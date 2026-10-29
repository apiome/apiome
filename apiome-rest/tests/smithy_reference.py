"""Check an emitted Smithy model with the Smithy CLI — MFX-20.1 (#3914).

``smithy validate`` loads the model (IDL ``.smithy`` or JSON AST ``.json``) with the prelude and runs
the built-in validators; a model with an ``ERROR`` or ``DANGER`` event fails. It runs in an empty
scratch directory so no ``smithy-build.json`` is picked up. A model applying a protocol trait from a
package the CLI does not bundle (``aws.protocols#restJson1``) is checked with
``--allow-unknown-traits``.

The CLI is found through ``APIOME_SMITHY_BIN`` or on ``PATH``; tests skip the check when it is
missing. Wiring it into export validation is MFX-20.3.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import List, Optional

__all__ = ["SMITHY", "check_with_smithy", "smithy_errors"]


def _tool() -> Optional[str]:
    configured = os.environ.get("APIOME_SMITHY_BIN")
    if configured and os.path.isfile(configured):
        return configured
    return shutil.which("smithy")


#: The Smithy CLI, or ``None`` when not installed here.
SMITHY = _tool()


def smithy_errors(content: str, *, file_name: str = "model.smithy", allow_unknown_traits: bool = False) -> List[str]:
    """``smithy validate``'s output for a model it rejects (empty when it validates).

    Args:
        content: The model text (IDL, or a JSON AST when ``file_name`` ends in ``.json``).
        file_name: The file name the model is written under.
        allow_unknown_traits: Pass ``--allow-unknown-traits`` (for protocol traits from unbundled packages).

    Returns:
        The non-empty output lines of a failed run.
    """
    assert SMITHY, "the Smithy CLI is not available"
    with tempfile.TemporaryDirectory(prefix="apiome-smithy-") as scratch:
        path = os.path.join(scratch, file_name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        argv = [SMITHY, "validate", "--quiet"] + (["--allow-unknown-traits"] if allow_unknown_traits else []) + [path]
        result = subprocess.run(argv, capture_output=True, text=True, timeout=300, cwd=scratch)
    if result.returncode == 0:
        return []
    return [line for line in (result.stdout + result.stderr).splitlines() if line.strip()]


def check_with_smithy(content: str, *, file_name: str = "model.smithy", allow_unknown_traits: bool = False) -> None:
    """Assert ``smithy validate`` accepts the model (see :func:`smithy_errors`)."""
    errors = smithy_errors(content, file_name=file_name, allow_unknown_traits=allow_unknown_traits)
    assert not errors, "\n".join(errors[:40]) + "\n\n" + content
