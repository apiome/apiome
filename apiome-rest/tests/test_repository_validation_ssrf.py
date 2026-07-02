"""SSRF guard coverage for public clone-URL validation (#3612).

``validate_public_clone_url`` fetches tenant-supplied hosts on two branches that
are NOT pinned to a hardcoded provider API: the GitLab branch (any host
containing "gitlab") and the generic fallback. Both must reject hosts that
resolve to non-public addresses. DNS resolution is mocked to controlled IPs.
"""

from unittest.mock import patch

import pytest

from app import repository_validation, ssrf_guard
from app.repository_validation import parse_gitlab_project_path, validate_public_clone_url


def _resolve_to(*ips):
    return patch.object(ssrf_guard, "_resolve_host_ips", lambda host: list(ips))


def test_gitlab_origin_uses_hostname_and_preserves_port():
    # Regression: urlparse exposes ``hostname``/``port`` (not ``host``).
    origin, enc_path = parse_gitlab_project_path("https://gitlab.example.com:8443/group/proj")
    assert origin == "https://gitlab.example.com:8443"
    assert enc_path == "group%2Fproj"


def test_gitlab_branch_blocks_internal_host():
    # A "gitlab"-containing host that resolves to the metadata IP must be rejected.
    with _resolve_to("169.254.169.254"):
        with pytest.raises(ValueError, match="non-public"):
            validate_public_clone_url("https://gitlab.attacker.internal/group/proj")


def test_generic_branch_blocks_internal_host():
    # Non-provider host resolving to a private address must be rejected before fetch.
    with _resolve_to("10.0.0.5"):
        with pytest.raises(ValueError, match="non-public"):
            validate_public_clone_url("https://git.internal.corp/group/repo.git")


def test_gitlab_branch_allows_public_host_then_fetches():
    # Public host passes the guard; the actual HTTP call is mocked to a 404 so we
    # assert the guard let it through (raising the GitLab-not-found message, not
    # an SSRF rejection).
    class _Resp:
        status_code = 404

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            return _Resp()

    with _resolve_to("93.184.216.34"):
        with patch.object(repository_validation, "build_guarded_client", _Client):
            with pytest.raises(ValueError, match="GitLab returned 404"):
                validate_public_clone_url("https://gitlab.example.com/group/proj")
