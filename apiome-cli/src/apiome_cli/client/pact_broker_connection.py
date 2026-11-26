"""Where ``apiome pact`` sends its requests, and with which credential — PFX-4.1 (#6938).

Pact tooling is configured with two environment variables, ``PACT_BROKER_BASE_URL`` and
``PACT_BROKER_TOKEN``. ``apiome pact`` reads them as well as the usual ``APIOME_*`` settings, so a
pipeline that already exports them for ``pact-broker`` needs nothing new.

Precedence, highest first:

1. the command's ``--broker-base-url`` / ``--broker-token`` (``pact-broker``'s ``-b`` / ``-k``);
2. the root ``--base-url`` / ``--api-key`` flags;
3. ``PACT_BROKER_BASE_URL`` / ``PACT_BROKER_TOKEN``;
4. ``APIOME_BASE_URL`` / ``APIOME_API_KEY`` / ``APIOME_TENANT_ID``, the dotenv files and the
   user config file.

A broker base URL takes one of two forms:

* the **path form** ``https://<api>/v1/tenants/<tenant>/pact-broker`` — it names the API root and
  the workspace, so every ``apiome pact`` command works with it alone;
* the **tenant-host alias** ``https://<tenant>.<suffix>`` (PFX-1.2) — it reaches the Pact Broker
  routes only, so the commands that call Apiome's own routes (``list-pacticipants``,
  ``describe-version --latest``, ``verify``) refuse it with the reason.

Basic auth (PFX-4.2, #6939): Apiome's broker maps basic auth onto an API key — the **password** is
the key and the username is ignored. So when no token or key is configured by any of the above,
``PACT_BROKER_PASSWORD`` is used as the API key. ``PACT_BROKER_USERNAME`` alone, without a
password, is reported instead of sending nothing.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote, urlsplit

import typer
from pydantic import HttpUrl, SecretStr

from apiome_cli.cli_context import insecure_from_context, root_flag_given, settings_from_context
from apiome_cli.client.errors import CliError
from apiome_cli.client.http import RestClient
from apiome_cli.client.tenant_scope import require_tenant_slug
from apiome_cli.config import CliSettings
from apiome_cli.exit_codes import EXIT_ERROR

#: The environment variables Pact tooling reads.
ENV_BASE_URL = "PACT_BROKER_BASE_URL"
ENV_TOKEN = "PACT_BROKER_TOKEN"
ENV_USERNAME = "PACT_BROKER_USERNAME"
ENV_PASSWORD = "PACT_BROKER_PASSWORD"

#: ``<root>/v1/tenants/<tenant>/pact-broker`` — the path form of a broker base URL.
_PATH_FORM = re.compile(r"^(?P<root>.*?)/v1/tenants/(?P<tenant>[^/]+)/pact-broker/?$")


@dataclass(frozen=True)
class BrokerAddress:
    """A broker base URL, read.

    Attributes:
        root: What the HTTP client is pointed at — the API root (path form) or the alias host.
        tenant: The workspace the URL names; ``None`` for the tenant-host alias.
    """

    root: str
    tenant: Optional[str]


def parse_broker_base_url(url: str) -> BrokerAddress:
    """Read a Pact Broker base URL.

    Args:
        url: ``https://<api>/v1/tenants/<tenant>/pact-broker`` or ``https://<tenant>.<suffix>``.

    Returns:
        The API root and workspace of the path form, or the host of the alias form.

    Raises:
        ValueError: when the URL is not http(s), or has a path that is neither form.
    """
    text = url.strip()
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"{text!r} is not an http(s) URL")
    if parts.query or parts.fragment:
        raise ValueError(f"{text!r} has a query or fragment; give the broker base URL only")
    origin = f"{parts.scheme}://{parts.netloc}"
    path = parts.path.rstrip("/")
    if not path:
        return BrokerAddress(root=origin, tenant=None)
    match = _PATH_FORM.match(path)
    if match is None:
        raise ValueError(
            f"{text!r} is not a Pact Broker base URL: use https://<api>/v1/tenants/<tenant>/pact-broker "
            "or a tenant-host alias https://<tenant>.<suffix>"
        )
    return BrokerAddress(root=origin + match.group("root"), tenant=match.group("tenant"))


@dataclass(frozen=True)
class BrokerConnection:
    """A ready client and the paths it addresses.

    Attributes:
        client: The HTTP client (API key sent as ``X-API-Key``).
        tenant_slug: The workspace, or ``None`` when only the alias host is known.
        alias: Whether the client points at a tenant-host alias (broker routes only).
    """

    client: RestClient
    tenant_slug: Optional[str]
    alias: bool

    def broker_path(self, suffix: str) -> str:
        """A Pact Broker route: ``/v1/tenants/{t}/pact-broker{suffix}``, or ``{suffix}`` on an alias.

        Args:
            suffix: The path after the broker base, starting with ``/`` (segments already escaped).

        Returns:
            The path for :class:`RestClient`.
        """
        if self.alias:
            return suffix
        return f"/v1/tenants/{quote(self.tenant_slug or '', safe='')}/pact-broker{suffix}"

    def api_path(self, suffix: str, *, command: str) -> str:
        """One of Apiome's own tenant routes: ``/v1/tenants/{t}{suffix}``.

        Args:
            suffix: The path after the tenant segment, starting with ``/``.
            command: The command asking, named in the refusal.

        Returns:
            The path for :class:`RestClient`.

        Raises:
            CliError: on a tenant-host alias, which serves the Pact Broker routes only.
        """
        return f"/v1/tenants/{quote(self.tenant(command=command), safe='')}{suffix}"

    def tenant(self, *, command: str) -> str:
        """The workspace slug, for commands whose paths are built elsewhere.

        Args:
            command: The command asking, named in the refusal.

        Returns:
            The tenant slug.

        Raises:
            CliError: on a tenant-host alias, which names no workspace path.
        """
        if self.alias or not self.tenant_slug:
            raise CliError(
                f"{command} calls Apiome's own API, which a tenant-host alias does not serve: set "
                f"{ENV_BASE_URL} to https://<api>/v1/tenants/<tenant>/pact-broker, or pass --broker-base-url "
                "in that form",
                exit_code=EXIT_ERROR,
            )
        return self.tenant_slug


def resolve_broker_settings(
    ctx: typer.Context,
    *,
    broker_base_url: Optional[str],
    broker_token: Optional[str],
    environ: Optional[dict[str, str]] = None,
) -> tuple[CliSettings, Optional[BrokerAddress]]:
    """Merge the Pact Broker settings into the CLI settings, by the module's precedence.

    Args:
        ctx: The command context (root flags, env file).
        broker_base_url: ``--broker-base-url``.
        broker_token: ``--broker-token``.
        environ: The environment (tests); ``os.environ`` when omitted.

    Returns:
        The settings to use and, when a broker base URL applied, its parsed address.

    Raises:
        CliError: when the broker base URL is malformed, or a basic-auth username is set without a
            password.
    """
    env = os.environ if environ is None else environ
    settings = settings_from_context(ctx)

    url = broker_base_url
    if not url and not root_flag_given(ctx, "base_url"):
        url = env.get(ENV_BASE_URL) or None
    token = broker_token
    if not token and not root_flag_given(ctx, "api_key"):
        token = env.get(ENV_TOKEN) or None

    address: Optional[BrokerAddress] = None
    update: dict[str, object] = {}
    if url:
        try:
            address = parse_broker_base_url(url)
        except ValueError as exc:
            raise CliError(f"broker base URL: {exc}", exit_code=EXIT_ERROR) from exc
        update["base_url"] = HttpUrl(address.root)
        if address.tenant:
            update["tenant_id"] = address.tenant
    if token:
        update["api_key"] = SecretStr(token.strip())
    if update:
        settings = settings.model_copy(update=update)

    if settings.api_key_value() is None:
        password = (env.get(ENV_PASSWORD) or "").strip()
        if password:
            # Basic auth: the password is the API key (the username is ignored by the server too).
            settings = settings.model_copy(update={"api_key": SecretStr(password)})
        elif env.get(ENV_USERNAME):
            raise CliError(
                f"{ENV_USERNAME} is set but {ENV_PASSWORD} is not: Apiome's Pact Broker reads the "
                f"workspace API key from the password. Set {ENV_PASSWORD} (or {ENV_TOKEN}) to the key",
                exit_code=EXIT_ERROR,
            )
    return settings, address


def connect(
    ctx: typer.Context,
    *,
    broker_base_url: Optional[str] = None,
    broker_token: Optional[str] = None,
    environ: Optional[dict[str, str]] = None,
) -> BrokerConnection:
    """Resolve the broker address and credential, and build the client.

    Args:
        ctx: The command context.
        broker_base_url: ``--broker-base-url``.
        broker_token: ``--broker-token``.
        environ: The environment (tests).

    Returns:
        The connection.

    Raises:
        CliError: when the URL is malformed, no API key or token is configured, or no workspace
            can be determined.
    """
    settings, address = resolve_broker_settings(
        ctx, broker_base_url=broker_base_url, broker_token=broker_token, environ=environ
    )
    if settings.api_key_value() is None:
        raise CliError(
            f"No credential: set {ENV_TOKEN}, {ENV_PASSWORD} or APIOME_API_KEY to a workspace API key, "
            "or pass --broker-token",
            exit_code=EXIT_ERROR,
        )
    client = RestClient(settings, verify=not insecure_from_context(ctx))
    if address is not None and address.tenant is None:
        return BrokerConnection(client=client, tenant_slug=None, alias=True)
    if address is not None:
        return BrokerConnection(client=client, tenant_slug=address.tenant, alias=False)
    return BrokerConnection(client=client, tenant_slug=require_tenant_slug(settings, client), alias=False)


def segment(value: str) -> str:
    """One path segment, escaped (``/`` included)."""
    return quote(value, safe="")
