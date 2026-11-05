"""Per-target test-drive tooling registry — MFX-44.1 (#4367).

Which tools can *test drive* an emitted artifact — open an OpenAPI document in Swagger UI, run a
proto bundle through ``buf lint``, serve it as a mock — is **registry data**, not UI switch
statements. Each emitter declares the tools that apply to its output in
:attr:`app.emitter.Emitter.test_tools`; :func:`resolve_test_tools` turns the declaration into the
``test_tools`` list of its :class:`~app.emitter.EmitterDescriptor`, which ``GET /export/targets``
carries. Export Studio's Review step draws its **Test drive** tab strip from that list alone, so a new
emitter that declares tools needs no UI change.

Two kinds of tool:

* **Client-side** (``swagger-ui``, ``redoc``, ``graphiql``, ``asyncapi-render``) render the artifact in
  the browser. Nothing on the server can be missing, so they are always available.
* **Server-side** (``mock-server``, ``toolchain``) need this server: the Mock Server engine with the
  export test-drive binding, or the toolchain binary a check runs. Their entries say whether they are
  available here and, when not, why — so the UI can show *unavailable on this server* honestly
  instead of hiding the tool.

The ``mock-server`` tool is also *derived*: every target whose format the mock engine can serve
(:func:`app.export_mock.is_mock_servable_target`) gets it without declaring it, so a new OpenAPI-family
emitter is mockable the day it registers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "SERVER_SIDE_KINDS",
    "ExportTestTool",
    "ExportTestToolKind",
    "ExportTestToolSpec",
    "resolve_test_tools",
    "test_tool",
    "toolchain_check",
]


class ExportTestToolKind(str, Enum):
    """What a test-drive tool does with the emitted artifact."""

    SWAGGER_UI = "swagger-ui"  # interactive OpenAPI docs (MFX-44.2)
    REDOC = "redoc"  # read-only OpenAPI reference docs (MFX-44.2)
    GRAPHIQL = "graphiql"  # GraphQL schema explorer (MFX-44.3)
    ASYNCAPI_RENDER = "asyncapi-render"  # rendered AsyncAPI document (MFX-44.4)
    MOCK_SERVER = "mock-server"  # a live mock of the artifact (MFX-44.5)
    TOOLCHAIN = "toolchain"  # the format's own toolchain run on the artifact (MFX-44.6)


#: The kinds that run on this server and may therefore be unavailable on it.
SERVER_SIDE_KINDS = frozenset({ExportTestToolKind.MOCK_SERVER, ExportTestToolKind.TOOLCHAIN})

#: The default label of each kind (a toolchain check is labelled by its command instead).
_KIND_LABELS: Dict[ExportTestToolKind, str] = {
    ExportTestToolKind.SWAGGER_UI: "Swagger UI",
    ExportTestToolKind.REDOC: "ReDoc",
    ExportTestToolKind.GRAPHIQL: "GraphiQL",
    ExportTestToolKind.ASYNCAPI_RENDER: "AsyncAPI viewer",
    ExportTestToolKind.MOCK_SERVER: "Mock server",
    ExportTestToolKind.TOOLCHAIN: "Toolchain check",
}


@dataclass(frozen=True)
class ExportTestToolSpec:
    """One tool as an emitter declares it.

    Attributes:
        kind: The tool kind.
        params: Kind-specific parameters (a toolchain check's ``tool`` and ``check``), passed to the UI.
        label: The tab / row label; the kind's default when omitted.
    """

    kind: ExportTestToolKind
    params: Mapping[str, Any] = field(default_factory=dict)
    label: Optional[str] = None


def test_tool(kind: ExportTestToolKind, label: Optional[str] = None, **params: Any) -> ExportTestToolSpec:
    """Declare a test-drive tool of ``kind`` (with optional ``params``).

    Args:
        kind: The tool kind.
        label: Overrides the kind's default label.
        **params: Kind-specific parameters.

    Returns:
        The declaration, for an emitter's ``test_tools``.
    """
    return ExportTestToolSpec(kind=kind, params=dict(params), label=label)


# Not a pytest test, although its name starts with ``test``.
test_tool.__test__ = False  # type: ignore[attr-defined]


def toolchain_check(tool: str, check: str, label: Optional[str] = None) -> ExportTestToolSpec:
    """Declare a toolchain check: run ``tool``'s ``check`` on the emitted artifact (MFX-44.6).

    Args:
        tool: The toolchain runner's tool key (``buf``), whose availability gates the check.
        check: The check to run (``lint``, ``build``, ``compile``).
        label: The row label; ``"<tool> <check>"`` when omitted.

    Returns:
        The declaration, for an emitter's ``test_tools``.
    """
    return ExportTestToolSpec(kind=ExportTestToolKind.TOOLCHAIN, params={"tool": tool, "check": check},
                              label=label or f"{tool} {check}")


class ExportTestTool(BaseModel):
    """One test-drive tool for a target, as ``GET /export/targets`` reports it."""

    model_config = ConfigDict(frozen=True)

    kind: ExportTestToolKind = Field(description="The tool kind, e.g. ``swagger-ui`` or ``toolchain``.")
    label: str = Field(description="The tab / row label, e.g. ``Swagger UI`` or ``buf lint``.")
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Kind-specific parameters, e.g. a toolchain check's ``tool`` and ``check``.",
    )
    server_side: bool = Field(
        description="Whether the tool runs on this server (``mock-server``, ``toolchain``) rather than in the browser.",
    )
    available: bool = Field(
        default=True,
        description="Whether the tool can run here; a client-side tool always can.",
    )
    unavailable_reason: Optional[str] = Field(
        default=None,
        description="Why a server-side tool cannot run on this server, or ``null`` when it can.",
    )


def _tool_installed(tool: str) -> bool:
    """Whether the toolchain runner resolves ``tool`` on this server (the seam tests pin)."""
    from .toolchain_runner import is_tool_available

    return is_tool_available(tool)


def _availability(spec: ExportTestToolSpec) -> Optional[str]:
    """Why ``spec`` cannot run on this server, or ``None`` when it can."""
    if spec.kind == ExportTestToolKind.MOCK_SERVER:
        from .export_mock import mock_engine_unavailable_reason

        return mock_engine_unavailable_reason()
    if spec.kind == ExportTestToolKind.TOOLCHAIN:
        tool = str(spec.params.get("tool") or "")
        if not tool or not _tool_installed(tool):
            return f"The {tool or 'required'} toolchain is not installed on this server."
    return None


def resolve_test_tools(declared: Sequence[ExportTestToolSpec], *, target_format: str) -> List[ExportTestTool]:
    """Resolve an emitter's declared tools (plus the derived mock) into its descriptor's list.

    Args:
        declared: The emitter's :attr:`~app.emitter.Emitter.test_tools`, in display order.
        target_format: The emitter's registry format; a mock-servable format gains ``mock-server``
            when it does not declare it.

    Returns:
        One entry per tool, in declared order with a derived mock last, each with its availability.
    """
    from .export_mock import is_mock_servable_target

    specs = list(declared)
    if is_mock_servable_target(target_format) and all(s.kind != ExportTestToolKind.MOCK_SERVER for s in specs):
        specs.append(ExportTestToolSpec(kind=ExportTestToolKind.MOCK_SERVER))
    tools: List[ExportTestTool] = []
    for spec in specs:
        server_side = spec.kind in SERVER_SIDE_KINDS
        reason = _availability(spec) if server_side else None
        tools.append(ExportTestTool(kind=spec.kind, label=spec.label or _KIND_LABELS[spec.kind],
                                    params=dict(spec.params), server_side=server_side,
                                    available=reason is None, unavailable_reason=reason))
    return tools
