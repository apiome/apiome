"""A route class whose 422 responses never echo what the caller sent — AGX-2.2 (#4534).

FastAPI answers a malformed body with ``422`` and a ``detail`` list built from pydantic's errors.
Each error carries an ``input``, and for a missing field that input is the *whole enclosing
object*. On a route that accepts a secret this means the secret goes straight back out in the
response body: an over-long API key or a body missing one field returns everything else that was
sent. From there it can end up in proxy logs, browser devtools, CI output and support tickets.

:class:`RedactedValidationRoute` closes that path for any router that sets it as its
``route_class``. It catches the :class:`~fastapi.exceptions.RequestValidationError` raised while
the request is parsed and re-raises one that keeps only ``type``, ``loc`` and ``msg``. Those are
enough to fix the request, and pydantic never interpolates the input into them. For
``extra_forbidden`` the last ``loc`` segment is the offending *key*, which a caller could have
filled with a secret, so it is masked as well. The original exception is not chained, so the
input doesn't reach the error log through ``__context__`` either.

The app-wide handler in ``app.main`` still renders the envelope, so a redacted ``422`` looks
exactly like every other ``422``, only without echoed values.
"""

from __future__ import annotations

from typing import Any, Callable, Coroutine, Dict, Iterable, List

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

__all__ = ["MASKED_KEY", "RedactedValidationRoute", "redact_validation_errors"]

#: What an ``extra_forbidden`` error's offending key is replaced with.
MASKED_KEY = "<unexpected field>"

#: The only error fields a redacted ``422`` keeps.
_KEPT_FIELDS = ("type", "loc", "msg")


def redact_validation_errors(errors: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Strip everything a validation error could echo back from the request.

    Args:
        errors: pydantic / FastAPI error dicts (``RequestValidationError.errors()``).

    Returns:
        New dicts carrying only ``type``, ``loc`` and ``msg``. ``input``, ``ctx`` and ``url`` are
        dropped, and an ``extra_forbidden`` error's last ``loc`` segment (the unexpected key
        itself) becomes :data:`MASKED_KEY`.
    """
    redacted: List[Dict[str, Any]] = []
    for error in errors:
        kept = {name: error[name] for name in _KEPT_FIELDS if name in error}
        loc = list(kept.get("loc") or ())
        if kept.get("type") == "extra_forbidden" and loc:
            loc[-1] = MASKED_KEY
        if "loc" in kept:
            kept["loc"] = tuple(loc)
        redacted.append(kept)
    return redacted


class RedactedValidationRoute(APIRoute):
    """An :class:`~fastapi.routing.APIRoute` whose request-validation errors echo no input."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        """Wrap the default handler so a validation failure is re-raised redacted.

        Returns:
            The wrapped ASGI request handler.
        """
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError as exc:
                # ``from None``: the original error (and the input it holds) must not ride along
                # as ``__context__`` into the error log.
                raise RequestValidationError(redact_validation_errors(exc.errors())) from None

        return handler
