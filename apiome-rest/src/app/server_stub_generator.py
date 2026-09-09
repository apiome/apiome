"""Server stub generation — SDK-2.5 (#4490).

One entry point over the two server stub generators: :func:`generate_server_stubs` turns a
persisted :class:`~app.canonical_model.CanonicalApi` into a FastAPI project
(:mod:`app.fastapi_stub_generator`) and an Express/TypeScript project
(:mod:`app.express_stub_generator`), both planned from the *same*
:class:`~app.server_stub_plan.ServerStubPlan` so the two skeletons route, validate and type the
same contract the same way.

**Why here and not behind a generator SPI.** SDK-2.5's stated dependencies were the codegen
preprocessing pass (SDK-1.3, #4483) and the generator SPI (SDK-1.2, #4482). Both were closed
*not-planned*, along with the artifact store (SDK-1.1), the two MVP language generators
(SDK-2.1/2.2) and the dashboard/CLI surfaces (SDK-3.1/3.2) — so there is no SPI to register with
and no sandbox to run in. What *did* ship is the SDK-2.3 snippet renderer, the SDK-3.3 client kit
and the SDK-2.4 Go client generator, all of which read the canonical model directly and package
their output deterministically. This module follows that precedent: it is a pure function of the
canonical model, it is called from :mod:`app.sdk_kit`, and its output rides the kit's existing
archive under ``server/`` rather than an artifact store.

**What a consumer gets.** Two directories they can unzip and run. Each boots with every route
registered, every request validated against the contract before any user code executes, and every
operation answering ``501 Not Implemented`` with a problem document naming what to implement. The
FastAPI project's handler protocols and the Express project's handler interfaces are typed from
the contract, so an implementation whose signature does not match it fails ``mypy`` or ``tsc``
rather than production.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .canonical_model import CanonicalApi
from .express_stub_generator import (
    EXPRESS_STUB_SCHEMA_VERSION,
    ExpressStubProject,
    generate_express_stub,
)
from .fastapi_stub_generator import (
    FASTAPI_STUB_SCHEMA_VERSION,
    FastApiStubProject,
    generate_fastapi_stub,
)
from .server_stub_plan import (
    DEFAULT_MAX_OPERATIONS,
    ServerStubPlan,
    ServerStubSkip,
    StubFile,
    build_server_stub_plan,
)

__all__ = [
    "EXPRESS_DIRECTORY",
    "EXPRESS_STUB_SCHEMA_VERSION",
    "FASTAPI_DIRECTORY",
    "FASTAPI_STUB_SCHEMA_VERSION",
    "SERVER_STUB_SCHEMA_VERSION",
    "ServerStubBundle",
    "generate_server_stubs",
]

#: The addressable shape of the generated bundle, recorded in the kit manifest.
SERVER_STUB_SCHEMA_VERSION = "sdk.server-stubs.v1"

#: The directory each target's project is written under, relative to the bundle root.
FASTAPI_DIRECTORY = "fastapi"
EXPRESS_DIRECTORY = "express"


@dataclass(frozen=True)
class ServerStubBundle:
    """Both generated server stub projects, and the plan they were generated from.

    Attributes:
        plan: The shared plan, kept so a caller can report what was routed and what was not
            without re-deriving it from either project.
        fastapi: The generated FastAPI project.
        express: The generated Express project.
        files: Every file of both projects, prefixed with its target directory and ordered by
            path.
    """

    plan: ServerStubPlan
    fastapi: FastApiStubProject
    express: ExpressStubProject
    files: Tuple[StubFile, ...] = ()

    @property
    def skipped(self) -> Tuple[ServerStubSkip, ...]:
        """Operations neither project generated a route for, with reasons."""
        return self.plan.skipped

    @property
    def route_count(self) -> int:
        """How many operations each project routes."""
        return len(self.plan.operations)

    def file_map(self) -> Dict[str, str]:
        """Return ``path → text`` for every file, for callers that stage an archive."""
        return {item.path: item.text for item in self.files}


def generate_server_stubs(
    api: CanonicalApi,
    *,
    python_package_name: Optional[str] = None,
    npm_package_name: Optional[str] = None,
    license_header: Optional[str] = None,
    max_operations: int = DEFAULT_MAX_OPERATIONS,
) -> ServerStubBundle:
    """Generate both server stub projects from a canonical model.

    The result is a pure function of its arguments: nothing here or below reads the clock, the
    environment or the filesystem, so two calls with the same model and the same branding produce
    byte-identical files. That is what lets the client kit keep serving a content-addressed
    ``ETag`` for a download that carries two generated projects.

    Args:
        api: The canonical model to generate from.
        python_package_name: The importable package the FastAPI project's modules live in.
            Defaults to the API's title, suffixed ``_server``.
        npm_package_name: The npm package name in the Express project's ``package.json``.
            Defaults to the API's title, suffixed ``-server``. A tenant's configured ``npm``
            package name (SDK-3.4) is the natural caller-supplied value.
        license_header: A tenant's resolved licence text (SDK-3.4), rendered as a comment block at
            the top of every generated source file and quoted in both READMEs.
        max_operations: How many operations get routes. The rest are reported in
            :attr:`ServerStubBundle.skipped` rather than silently dropped.

    Returns:
        The :class:`ServerStubBundle`.
    """
    plan = build_server_stub_plan(api, max_operations=max_operations)
    fastapi = generate_fastapi_stub(plan, package_name=python_package_name, license_header=license_header)
    express = generate_express_stub(plan, package_name=npm_package_name, license_header=license_header)

    files: List[StubFile] = [
        StubFile(path=f"{FASTAPI_DIRECTORY}/{item.path}", text=item.text) for item in fastapi.files
    ]
    files += [
        StubFile(path=f"{EXPRESS_DIRECTORY}/{item.path}", text=item.text) for item in express.files
    ]
    files.sort(key=lambda item: item.path)

    return ServerStubBundle(plan=plan, fastapi=fastapi, express=express, files=tuple(files))
