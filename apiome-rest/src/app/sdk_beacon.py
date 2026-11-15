"""The SDK compatibility beacon contract, ``apiome.sdk.beacon/v1`` — RDG-1.7 / SGD-3.1 (#4736).

A generated SDK whose user explicitly turns the beacon on reports how its calls turned out, so the
API owner learns which released contracts real SDK consumers find incompatible. One beacon event
says exactly five things — and a count, because the SDK aggregates before it sends:

* ``sdk_name`` and ``sdk_version`` — which generated SDK, at which version;
* ``api_version`` and ``spec_revision_id`` — the API version and the published revision the SDK was
  generated from, both baked into the SDK from the kit's compatibility manifest;
* ``operation_id`` — the manifest's operation id;
* ``outcome`` — ``ok``, ``client_error`` (4xx), ``server_error`` (5xx), ``network`` (no response) or
  ``incompatible`` (a 2xx the SDK could not decode against the contract).

There is **no field** for a request or response body, a header, a status code, a latency, a URL, a
host, a credential or anything that identifies the caller, unknown keys are refused, and every
string must match a version- or identifier-shaped pattern, so a source cannot smuggle one in. There is
no timestamp either: the server counts an event on the UTC day it receives it.

This module is the contract only — pure models, no I/O. The storage is apiome-db V380
(``usage_sdk_beacon_daily``); the route is :mod:`app.sdk_beacon_routes`.
"""

from __future__ import annotations

from typing import List, Literal, Optional, Tuple
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "MAX_BEACON_COUNT",
    "MAX_BEACON_EVENTS",
    "OUTCOMES",
    "SDK_BEACON_SCHEMA",
    "BeaconOutcome",
    "SdkBeaconBatch",
    "SdkBeaconEvent",
]

#: The contract's name and version.
SDK_BEACON_SCHEMA = "apiome.sdk.beacon/v1"

#: Outcome categories. Mirrors ``usage_sdk_beacon_outcome_ck`` (V380).
OUTCOMES: Tuple[str, ...] = ("ok", "client_error", "server_error", "network", "incompatible")

BeaconOutcome = Literal["ok", "client_error", "server_error", "network", "incompatible"]

#: Most events one report may carry. An SDK aggregates per (operation, outcome), so a report is short.
MAX_BEACON_EVENTS = 500

#: Most calls one event may count.
MAX_BEACON_COUNT = 10_000

# Patterns mirror the V380 CHECK constraints exactly.
_VERSION_PATTERN = r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$"
_SDK_NAME_PATTERN = r"^[a-z0-9][a-z0-9._/-]{0,63}$"
#: An operation id as the kit manifest prints it: an ``operationId`` (``getPet``), an RPC key
#: (``acme.PetService.GetPet``) or a method-and-path key (``GET /pets/{petId}``).
_OPERATION_PATTERN = r"^[A-Za-z0-9_][A-Za-z0-9_.:/{} -]{0,254}$"


class _Strict(BaseModel):
    """Refuses unknown keys, so no other field can reach storage."""

    model_config = ConfigDict(extra="forbid")


class SdkBeaconEvent(_Strict):
    """How many calls of one operation ended with one outcome.

    Attributes:
        sdk_name: The SDK's name (its module or package, lower case).
        sdk_version: The SDK's own version.
        api_version: The API version the SDK was generated for.
        spec_revision_id: The published revision the SDK was generated from.
        operation_id: The operation, as the kit manifest names it.
        outcome: The outcome category.
        count: How many calls this event stands for.
    """

    sdk_name: str = Field(pattern=_SDK_NAME_PATTERN, description="The SDK's name, lower case (`acme-go`).")
    sdk_version: str = Field(pattern=_VERSION_PATTERN, description="The SDK's own version (`1.4.0`).")
    api_version: str = Field(pattern=_VERSION_PATTERN, description="The API version it was generated for.")
    spec_revision_id: UUID = Field(description="The published revision it was generated from (kit manifest).")
    operation_id: str = Field(pattern=_OPERATION_PATTERN, description="The kit manifest's operation id.")
    outcome: BeaconOutcome = Field(
        description=(
            "`ok`, `client_error` (4xx), `server_error` (5xx), `network` (no response) or "
            "`incompatible` (a 2xx the SDK could not decode against the contract)."
        )
    )
    count: int = Field(default=1, ge=1, le=MAX_BEACON_COUNT, description="Calls this event stands for.")


class SdkBeaconBatch(_Strict):
    """One report from an SDK.

    Attributes:
        schema_id: Always ``apiome.sdk.beacon/v1``.
        source_id: The ``sdk_beacon`` usage source, unless the ``X-Apiome-Usage-Source`` header names it.
        events: The aggregated events.
    """

    schema_id: Literal["apiome.sdk.beacon/v1"] = Field(SDK_BEACON_SCHEMA, alias="schema")
    source_id: Optional[UUID] = None
    events: List[SdkBeaconEvent] = Field(min_length=1, max_length=MAX_BEACON_EVENTS)
