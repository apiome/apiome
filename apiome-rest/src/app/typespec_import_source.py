"""Microsoft TypeSpec import source — MFI-22.3, MFI-14.1.

The :class:`~app.import_source.ImportSource` adapter that makes TypeSpec ``.tsp``
documents importable into the catalog.

* **A set of several ``.tsp`` files** is compiled by the bundled TypeSpec compiler to OpenAPI
  (MFI-14.1, :mod:`app.typespec_compile`), and the emitted OpenAPI — the epic's integration
  surface — is normalized by the OpenAPI normalizer, so the catalog item's diff and lint are the
  OpenAPI ones. The item stays a ``typespec`` item and records how it was built.
* **One ``.tsp`` file** is compiled the same way (MFI-14.2) when the compiler is available, so a
  single file and a project normalize alike. Without the compiler (``ADAPTER_UNAVAILABLE``) it is
  read by the built-in reader (:mod:`app.typespec_parser`) instead, and the item records which path
  ran in ``extras["typespec_compiled_via"]`` (``tsp`` or ``reader``). Setting
  :data:`COMPILE_SINGLE_FILES_ENV` to ``0`` pins the reader — the test suite does, so the corpus
  goldens do not depend on whether ``tsp`` is installed.
"""

from __future__ import annotations

import os
import posixpath
from typing import Any, Optional, Union

from . import (
    openapi_normalizer,  # noqa: F401 — compiled sets normalize through OpenAPI (MFI-14.1)
    typespec_normalizer,  # noqa: F401 — self-registers the normalizer
)
from .canonical_model import ApiParadigm, CanonicalApi
from .fileset import IntakeFileset
from .import_source import (
    NO_MATCH,
    DetectionInput,
    DetectionResult,
    ImportSource,
    ImportSourceError,
    InputKind,
)
from .typespec_compile import TypeSpecCompiled, compile_typespec_set, typespec_members
from .typespec_config import find_tspconfig
from .typespec_parser import TypeSpecDocument, TypeSpecParseError, is_typespec, parse_typespec
from .typespec_versioning import version_changes

__all__ = ["COMPILE_SINGLE_FILES_ENV", "MAX_RECORDED_DIAGNOSTICS", "TypeSpecImportSource"]

#: Most compile diagnostics recorded on a catalog item (the rest are counted, not listed).
MAX_RECORDED_DIAGNOSTICS = 50

#: Environment switch for MFI-14.2: ``0`` / ``false`` / ``off`` reads a single ``.tsp`` file with the
#: built-in reader even when the compiler is available. On by default.
COMPILE_SINGLE_FILES_ENV = "APIOME_TYPESPEC_COMPILE_SINGLE_FILES"

#: The entry-point name a single file is staged under when its own name is not a ``.tsp`` path.
_SINGLE_FILE_ROOT = "main.tsp"


def compile_single_files() -> bool:
    """Whether a single ``.tsp`` file is compiled through ``tsp`` (see :data:`COMPILE_SINGLE_FILES_ENV`).

    Returns:
        ``False`` when the switch is set to ``0``, ``false``, ``no`` or ``off``; ``True`` otherwise.
    """
    return os.environ.get(COMPILE_SINGLE_FILES_ENV, "1").strip().lower() not in {"0", "false", "no", "off"}


def _single_file_root(source_label: Optional[str]) -> str:
    """The name a single file is compiled under: its own file name when it is a ``.tsp``, else ``main.tsp``.

    Only the base name is kept, so a label such as ``specs/pets.tsp`` or a URL path never becomes
    a staged directory.
    """
    name = posixpath.basename((source_label or "").replace("\\", "/").split("?", 1)[0])
    return name if name.endswith(".tsp") and name != ".tsp" else _SINGLE_FILE_ROOT


class TypeSpecImportSource(ImportSource, register=True):
    """Adapter for Microsoft TypeSpec ``.tsp`` API definitions."""

    key = "typespec"
    label = "TypeSpec"
    description = "Import a Microsoft TypeSpec API definition (.tsp)."
    icon = "file-code"
    paradigm = ApiParadigm.REST
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = False
    formats = ("typespec", "tsp", "cadl")
    file_extensions = (".tsp", ".cadl")

    def detect(self, payload: DetectionInput) -> DetectionResult:
        text = payload.text
        if text is not None and is_typespec(text):
            if 'import "@typespec/' in text or "import '@typespec/" in text:
                return DetectionResult(
                    confidence=0.98,
                    format="typespec",
                    reason='`import "@typespec/..."` marker',
                )
            if "model " in text or "interface " in text:
                return DetectionResult(
                    confidence=0.96,
                    format="typespec",
                    reason="TypeSpec `model` / `interface` declarations",
                )
            return DetectionResult(
                confidence=0.94,
                format="typespec",
                reason="TypeSpec namespace marker",
            )

        filename = (payload.filename or "").lower()
        if filename.endswith(".tsp") and text is not None and is_typespec(text):
            return DetectionResult(
                confidence=0.85,
                format="typespec",
                reason="TypeSpec `.tsp` filename extension",
            )
        return NO_MATCH

    def parse(
        self, raw: str, *, source_label: Optional[str] = None
    ) -> Union[TypeSpecDocument, TypeSpecCompiled]:
        """Parse one ``.tsp`` file: compile it through ``tsp`` when possible (MFI-14.2).

        The file is read by the built-in reader first, so text that is not TypeSpec fails exactly
        as it always has. It is then compiled like a one-file project; when the compiler is not
        available on this server, the reader's document is returned instead.

        Args:
            raw: The file's text.
            source_label: Its name, which the compile stages it under when it is a ``.tsp`` path.

        Returns:
            The compiled file, or the reader's document without the compiler (or with
            :data:`COMPILE_SINGLE_FILES_ENV` off).

        Raises:
            ImportSourceError: When the text is not TypeSpec, or the compile refuses it (an import
                of a file that was not uploaded, a compile error, a timeout); see
                :func:`app.typespec_compile.compile_typespec_set`.
        """
        document = self._read(raw, source_label=source_label)
        if not compile_single_files():
            return document
        root = _single_file_root(source_label)
        try:
            return compile_typespec_set({root: raw}, root, source_label=source_label)
        except ImportSourceError as exc:
            if exc.code == "ADAPTER_UNAVAILABLE":
                return document
            raise

    def _read(self, raw: str, *, source_label: Optional[str] = None) -> TypeSpecDocument:
        """Read one file with the built-in reader (:mod:`app.typespec_parser`)."""
        try:
            return parse_typespec(raw, source_label=source_label)
        except TypeSpecParseError as exc:
            raise ImportSourceError(str(exc)) from exc

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> Union[TypeSpecDocument, TypeSpecCompiled]:
        """Parse a set: a TypeSpec project compiles through ``tsp`` (MFI-14.1, MFI-14.5).

        A set is a project when it holds several ``.tsp`` files or a ``tspconfig.yaml`` beside
        the root; a lone ``.tsp`` file is read like that one file.

        Raises:
            ImportSourceError: See :func:`app.typespec_compile.compile_typespec_set`.
        """
        root = fileset.root
        if root not in fileset.members:
            raise ImportSourceError("TypeSpec fileset is missing its root document")
        is_project = len(typespec_members(fileset.members)) > 1 or find_tspconfig(fileset.members, root)
        if not is_project:
            return self.parse(fileset.members[root], source_label=root or source_label)
        return compile_typespec_set(dict(fileset.members), root, source_label=source_label)

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        if isinstance(native_ast, TypeSpecCompiled):
            return self._normalize_compiled(native_ast, include_raw=include_raw)
        if not isinstance(native_ast, TypeSpecDocument):
            raise ImportSourceError(
                "TypeSpec source must be a TypeSpecDocument (see app.typespec_parser.parse_typespec)"
            )
        api = self._normalize_via_registry("typespec", native_ast, include_raw=include_raw)
        # MFI-14.2: say which path built the item; the compiled path records ``tsp``.
        return api.model_copy(update={"extras": {**api.extras, "typespec_compiled_via": "reader"}})

    def _normalize_compiled(self, compiled: TypeSpecCompiled, *, include_raw: bool) -> CanonicalApi:
        """Normalize a compiled set through the OpenAPI normalizer, keeping its TypeSpec identity.

        Args:
            compiled: The compiled set.
            include_raw: Whether to keep the sources on ``raw``.

        Returns:
            The canonical model, labelled ``typespec``, with ``extras`` naming the OpenAPI it
            was built from, the source files, namespaces, the emitted document's hash and the
            compile's warnings and, for a ``@versioned`` service, its versions and the changes
            between them.
        """
        api = self._normalize_via_registry("openapi-3.1", compiled.openapi, include_raw=False)
        extras = {
            **api.extras,
            "typespec_compiled_via": "tsp",
            "typespec_openapi_format": api.format,
            "typespec_source_files": list(compiled.source_files),
            "typespec_namespaces": list(compiled.namespaces),
            "typespec_openapi_sha256": compiled.openapi_sha256,
        }
        if compiled.config is not None:
            # MFI-14.5: which tspconfig settings shaped the emitted API, and which were left out.
            extras["typespec_tspconfig"] = compiled.config.path
            extras["typespec_tspconfig_applied"] = compiled.config.applied
            extras["typespec_tspconfig_ignored"] = list(compiled.config.ignored)
        if compiled.diagnostics:
            # MFI-14.3: the compile's warnings (compiler, library and built-in linter rules), for the
            # `typespec` lint pack; omitted when there are none so a clean project's model is unchanged.
            listed = compiled.diagnostics[:MAX_RECORDED_DIAGNOSTICS]
            extras["typespec_diagnostics"] = [diagnostic.as_dict() for diagnostic in listed]
            extras["typespec_diagnostic_count"] = len(compiled.diagnostics)
        if compiled.versions:
            # MFI-14.4: a @versioned service — every version, and what each step to the next changed
            # (OpenAPI compatibility analysis); the item itself is the newest version.
            extras["typespec_versions"] = [
                {"version": v.version, "openapi_sha256": v.openapi_sha256} for v in compiled.versions
            ]
            extras["typespec_latest_version"] = compiled.versions[-1].version
            extras["typespec_version_changes"] = version_changes(compiled.versions)
        raw = {"typespec": compiled.root_text, "openapi": compiled.openapi} if include_raw else None
        if raw is not None and compiled.versions:
            raw["openapi_versions"] = {v.version: v.openapi for v in compiled.versions}
        return api.model_copy(update={"format": "typespec", "extras": extras, "raw": raw})
