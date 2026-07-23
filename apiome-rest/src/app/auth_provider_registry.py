"""Server-side OAuth provider registry for provider-config CRUD (OLO-8.4, #4970).

The canonical registry lives in the UI (``apiome-ui/lib/auth/provider-registry.ts``, OLO-2.3): it
names every sign-in provider this codebase knows about and each provider's status. The REST
provider-config surface (:mod:`app.auth_provider_config_routes`) needs the same facts server-side
to:

* **validate** a ``provider_id`` in ``PUT /v1/admin/auth-providers/{provider_id}`` against the
  known slugs (an unknown slug is a 404 — and the V196 table's own CHECK would reject it anyway),
* refuse to **enable** a ``coming-soon`` provider (no sign-in factory exists for it yet), and
* enforce **required-field completeness** before a provider is enabled.

This module is a small, deliberately-duplicated projection of that registry — REST cannot import
TypeScript, and the set of providers changes rarely (adding one is already a multi-surface edit,
per the UI registry's own doc). The slugs here MUST stay in lockstep with ``PROVIDER_REGISTRY`` in
the UI and with the ``auth_provider_config_provider_id_check`` CHECK in migration V196.

Required-field completeness (``required_fields``): to be *enabled* through the DB, a provider must
have a ``client_id`` and a ``client_secret`` available in its stored row. REST cannot see the UI
process's env, so it validates completeness against the DB row only — an operator enabling a
provider supplies both there (the secret is write-only and sealed via OLO-8.3). A provider left
with ``enabled = null`` is governed by env-derived enablement (OLO-8.5) and is not completeness-
checked here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# Provider lifecycle, mirroring ``ProviderStatus`` in the UI registry:
#   * "available"   — implemented end-to-end; may be enabled once configured.
#   * "coming-soon" — advertised as a roadmap teaser; never enabled (no sign-in factory yet).
STATUS_AVAILABLE = "available"
STATUS_COMING_SOON = "coming-soon"

# Config fields required for a provider to be enabled through the DB. Both are stored on the
# ``auth_provider_config`` row: ``client_id`` (a column) and ``client_secret`` (the sealed
# ``client_secret_encrypted``/``enc_key_id`` pair). Kept as a shared constant so the routes and
# tests reference one definition.
REQUIRED_FIELDS: Tuple[str, ...] = ("client_id", "client_secret")


@dataclass(frozen=True)
class ProviderDescriptor:
    """One sign-in provider this codebase knows about (enabled or not).

    Attributes:
        id: Provider slug — matches the UI registry id, the value stored in
            ``external_auth_providers.provider``, and the V196 CHECK. Never rename an id.
        label: Human-readable name used on admin cards ("GitHub", "Microsoft").
        status: :data:`STATUS_AVAILABLE` or :data:`STATUS_COMING_SOON`.
        required_fields: Config fields that must be present for the provider to be enabled;
            empty for ``coming-soon`` providers (nothing can enable them).
    """

    id: str
    label: str
    status: str
    required_fields: Tuple[str, ...]


# Every provider this codebase knows about, in display order — the server-side projection of
# ``PROVIDER_REGISTRY`` (provider-registry.ts). ``google``/``aws`` are ``coming-soon`` placeholders.
PROVIDER_REGISTRY: Tuple[ProviderDescriptor, ...] = (
    ProviderDescriptor("github", "GitHub", STATUS_AVAILABLE, REQUIRED_FIELDS),
    ProviderDescriptor("gitlab", "GitLab", STATUS_AVAILABLE, REQUIRED_FIELDS),
    ProviderDescriptor("azure", "Microsoft", STATUS_AVAILABLE, REQUIRED_FIELDS),
    ProviderDescriptor("google", "Google / GCP", STATUS_COMING_SOON, ()),
    ProviderDescriptor("aws", "AWS", STATUS_COMING_SOON, ()),
)

_BY_ID: Dict[str, ProviderDescriptor] = {p.id: p for p in PROVIDER_REGISTRY}


def get_provider_descriptor(provider_id: str) -> Optional[ProviderDescriptor]:
    """Look up a registry entry by slug.

    Args:
        provider_id: Provider slug (e.g. ``"github"``).

    Returns:
        The descriptor, or ``None`` for a slug the registry does not know.
    """
    return _BY_ID.get(provider_id)


def known_provider_ids() -> List[str]:
    """Return every known provider slug, in display order."""
    return [p.id for p in PROVIDER_REGISTRY]
