"""Check emitted OMG IDL with reference IDL compilers — MFX-28.1 (#4168).

No single free compiler reads every IDL 4.2 building block the writer uses, so each checks the
building blocks it implements:

* **omniidl** (omniORB) — the CORBA building blocks: modules, interfaces, exceptions, ``raises``,
  unions, typedefs, recursion through sequences. It predates IDL 4 annotations, so ``@optional`` /
  ``@key`` are removed before it reads the document.
* **idlc** (Eclipse Cyclone DDS) — the data types *with* their annotations, the DDS profile whole.
  It reads no interfaces, exceptions, wide characters or recursive types, so the CORBA profile's
  document is checked without its interfaces and exceptions, wide types narrowed, and only when it
  declares no recursive type (a forward declaration marks one).

Each compiler is found through ``APIOME_OMNIIDL_BIN`` / ``APIOME_IDLC_BIN`` or on ``PATH``; tests skip
the check when it is missing. Wiring them into export validation is MFX-28.3 (#4170).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from typing import List, Optional

__all__ = ["IDLC", "OMNIIDL", "check_with_reference_compilers", "reference_compiler_errors"]


def _tool(env_key: str, name: str) -> Optional[str]:
    configured = os.environ.get(env_key)
    if configured and os.path.isfile(configured):
        return configured
    return shutil.which(name)


#: The compilers, or ``None`` when not installed here.
OMNIIDL = _tool("APIOME_OMNIIDL_BIN", "omniidl")
IDLC = _tool("APIOME_IDLC_BIN", "idlc")


def _run(argv: List[str], text: str) -> List[str]:
    """Compile ``text`` as ``x.idl`` in a scratch directory; return the error lines (empty when accepted)."""
    with tempfile.TemporaryDirectory(prefix="apiome-idl-") as scratch:
        path = os.path.join(scratch, "x.idl")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        try:
            result = subprocess.run(argv + [path], capture_output=True, text=True, timeout=60, cwd=scratch)
        except subprocess.TimeoutExpired:
            return [f"{os.path.basename(argv[0])} timed out"]
    if result.returncode == 0:
        return []
    lines = (result.stderr + result.stdout).splitlines()
    return [line for line in lines if line.strip() and "extensibility" not in line] or [f"exit {result.returncode}"]


def _without_annotations(text: str) -> str:
    return re.sub(r"@\w+(?:\([^)]*\))?\s*", "", text)


def _data_types_only(text: str) -> str:
    """The document without its interface and exception blocks, wide character types narrowed."""
    out: List[str] = []
    closing: Optional[str] = None
    for line in text.splitlines():
        stripped = line.strip()
        indent = line[: len(line) - len(line.lstrip())]
        if closing is not None:
            if stripped == "};" and indent == closing:
                closing = None
            continue
        if re.match(r"(interface|exception)\s", stripped):
            if not stripped.endswith("};"):
                closing = indent
            continue
        out.append(line)
    return "\n".join(out).replace("wstring", "string").replace("wchar", "char") + "\n"


def reference_compiler_errors(text: str, *, profile: str = "corba") -> List[str]:
    """The reference compilers' errors for an emitted document (empty when every available one accepts it).

    Args:
        text: The emitted ``.idl`` document.
        profile: The profile it was written with (``corba`` or ``dds``).

    Returns:
        ``"<compiler>: <line>"`` entries.
    """
    errors: List[str] = []
    if profile == "dds":
        if IDLC:
            errors += [f"idlc: {line}" for line in _run([IDLC, "-o", "."], text)]
        return errors
    if OMNIIDL:
        errors += [f"omniidl: {line}" for line in _run([OMNIIDL, "-bdump"], _without_annotations(text))]
    data = _data_types_only(text)
    recursive = re.search(r"^\s*(struct|union) \w+;$", text, re.MULTILINE)
    if IDLC and not recursive and re.search(r"\b(struct|union|enum|typedef)\b", data):
        errors += [f"idlc: {line}" for line in _run([IDLC, "-o", "."], data)]
    return errors


def check_with_reference_compilers(text: str, *, profile: str = "corba") -> None:
    """Assert the available reference compilers accept ``text`` (see :func:`reference_compiler_errors`)."""
    errors = reference_compiler_errors(text, profile=profile)
    assert not errors, "\n".join(errors) + "\n\n" + text
