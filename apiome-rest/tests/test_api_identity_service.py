"""Unit tests for cross-format API identity heuristics (MFI-6.4, #4410)."""

from app.api_identity_service import rank_identity_suggestions


def test_rank_suggestions_by_title_and_metadata():
    anchor = {
        "name": "Acme User API",
        "identity_name": "UserService",
        "identity_namespace": "acme.v1",
        "format_metadata": {"package": "acme.v1"},
    }
    candidates = [
        {
            "project_id": "p2",
            "name": "Acme User API",
            "slug": "acme-user-api-openapi",
            "publishable": True,
            "source_format": "openapi",
            "protocol": "rest",
            "format_metadata": {"package": "acme.v1"},
            "identity_name": "UserService",
            "identity_namespace": "acme.v1",
        },
        {
            "project_id": "p3",
            "name": "Unrelated",
            "slug": "unrelated",
            "publishable": False,
            "source_format": "graphql",
            "protocol": "graphql",
            "format_metadata": {},
            "identity_name": None,
            "identity_namespace": None,
        },
    ]
    suggestions = rank_identity_suggestions(
        anchor=anchor,
        anchor_ops={"GetUser", "ListUsers"},
        candidates=candidates,
        candidate_ops={
            "p2": {"GetUser", "ListUsers"},
            "p3": set(),
        },
    )
    assert len(suggestions) == 1
    assert suggestions[0].project_id == "p2"
    assert suggestions[0].score > 0
    assert "matching title" in suggestions[0].reason
