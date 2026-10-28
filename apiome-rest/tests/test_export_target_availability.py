"""A target this deployment cannot run is refused up front, with its reason — E1-6 (#6221).

No shipped emitter declares ``required_tools`` today, so these tests give one a tool this runtime
lacks and check every path agrees with the registry: the targets list marks it unavailable with
the reason, and a real export (resolve, dispatch, job submit) refuses it with that reason before
any emit — while a dry run (fidelity only) still answers.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.emitter import get_emitter
from app.export_dispatch import dispatch_from_source
from app.export_job_engine import ExportJobStartRequest, schedule_export_job
from app.export_service import ExportError, ensure_target_available, resolve_emitter
from tests.test_export_multi_target import _source

MISSING_TOOL = "definitely-not-installed-tool"


@pytest.fixture
def graphql_needs_a_missing_tool():
    emitter_cls = get_emitter("graphql")
    with patch.object(emitter_cls, "required_tools", (MISSING_TOOL,)):
        yield emitter_cls


def test_the_descriptor_says_why(graphql_needs_a_missing_tool):
    descriptor = graphql_needs_a_missing_tool.descriptor()
    assert descriptor.available is False and descriptor.needs_toolchain is True
    assert MISSING_TOOL in descriptor.unavailable_reason


def test_resolving_an_unavailable_target_refuses_with_the_reason(graphql_needs_a_missing_tool):
    with pytest.raises(ExportError) as excinfo:
        resolve_emitter("graphql")
    assert excinfo.value.status_code == 422
    assert "not available in this deployment" in str(excinfo.value)
    assert MISSING_TOOL in str(excinfo.value)


def test_an_available_target_passes():
    ensure_target_available(get_emitter("graphql"))


def test_a_real_dispatch_refuses_but_a_dry_run_still_measures(graphql_needs_a_missing_tool):
    with pytest.raises(ExportError, match=MISSING_TOOL):
        dispatch_from_source(_source(), "graphql", dry_run=False, confirm=True, persistence=None)
    dry = dispatch_from_source(_source(), "graphql", dry_run=True, confirm=True, persistence=None)
    assert dry.emit is None and dry.fidelity is not None


async def test_a_job_for_an_unavailable_target_is_refused_at_submit(graphql_needs_a_missing_tool):
    request = ExportJobStartRequest(artifact="artifact-1", target="graphql")
    with pytest.raises(ExportError, match=MISSING_TOOL):
        await schedule_export_job("acme", "550e8400-e29b-41d4-a716-446655440000", request)
