"""A route class whose 422 responses never echo what the caller sent — AGX-2.2 (#4534).

Exercised on a throwaway app, so the behaviour is pinned independently of the vault routes that
use it: stock FastAPI echoes the submitted input (for a missing field, the whole body), and the
redacted route keeps only ``type``, ``loc`` and ``msg``.
"""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI
from fastapi.routing import APIRouter
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from app.redacted_validation_route import (
    MASKED_KEY,
    RedactedValidationRoute,
    redact_validation_errors,
)

_SECRET = "sk_live_TOPSECRET_value_123"


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    secret: Optional[str] = None


def _app(route_class=None) -> TestClient:
    """A one-route app, with or without the redacting route class."""
    router = APIRouter(route_class=route_class) if route_class else APIRouter()

    @router.post("/things")
    async def create(body: _Body) -> dict:
        return {"name": body.name}

    @router.get("/things/{count}")
    async def get(count: int) -> dict:
        return {"count": count}

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_stock_fastapi_echoes_the_body_in_a_422():
    """The problem this module exists for: a missing field echoes every other field."""
    response = _app().post("/things", json={"secret": _SECRET})
    assert response.status_code == 422
    assert _SECRET in response.text


def test_the_redacted_route_does_not():
    response = _app(RedactedValidationRoute).post("/things", json={"secret": _SECRET})
    assert response.status_code == 422
    assert _SECRET not in response.text
    assert response.json()["detail"] == [
        {"type": "missing", "loc": ["body", "name"], "msg": "Field required"}
    ]


def test_an_unexpected_key_is_masked():
    response = _app(RedactedValidationRoute).post("/things", json={"name": "n", _SECRET: "x"})
    (error,) = response.json()["detail"]
    assert error["type"] == "extra_forbidden"
    assert error["loc"] == ["body", MASKED_KEY]
    assert _SECRET not in response.text


def test_path_and_type_errors_are_redacted_too():
    response = _app(RedactedValidationRoute).get(f"/things/{_SECRET}")
    assert response.status_code == 422
    assert _SECRET not in response.text
    (error,) = response.json()["detail"]
    assert error["loc"] == ["path", "count"]


def test_a_valid_request_is_untouched():
    response = _app(RedactedValidationRoute).post("/things", json={"name": "n", "secret": _SECRET})
    assert response.status_code == 200
    assert response.json() == {"name": "n"}


def test_redact_validation_errors_keeps_only_type_loc_and_msg():
    errors = [
        {
            "type": "string_too_long",
            "loc": ("body", "secret"),
            "msg": "String should have at most 4 characters",
            "input": _SECRET,
            "ctx": {"max_length": 4},
            "url": "https://errors.pydantic.dev/",
        },
        {"type": "extra_forbidden", "loc": ("body", _SECRET), "msg": "Extra inputs", "input": 1},
        {"type": "missing", "msg": "Field required", "input": {"secret": _SECRET}},
    ]
    assert redact_validation_errors(errors) == [
        {
            "type": "string_too_long",
            "loc": ("body", "secret"),
            "msg": "String should have at most 4 characters",
        },
        {"type": "extra_forbidden", "loc": ("body", MASKED_KEY), "msg": "Extra inputs"},
        {"type": "missing", "msg": "Field required"},
    ]
    # The input list is not mutated.
    assert errors[0]["input"] == _SECRET
