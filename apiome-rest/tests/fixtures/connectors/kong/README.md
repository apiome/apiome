# Kong connector fixtures (CDG-1.2, #5953)

- `konnect_control_plane.json` — one Konnect control plane (`prod-eu`), as `GET /v2/control-planes/{id}` returns it.
- `konnect_entities.json` — its core entities as the Konnect / Admin API list endpoints return them:
  3 services, 7 routes, 4 plugins (one global, one service-scoped auth plugin, one route-scoped
  `rate-limiting`, one custom `acme-audit-trail` the adapter does not model) and 1 consumer.
  `tests/kong_fake.py` serves them in small pages.
- `declarative/*.kong.yaml` — the declarative file each service is equivalent to. A sync of the
  fake control plane must produce exactly these bytes (`tests/test_kong_connector_source.py`).
  If the assembler changes on purpose, regenerate them from the source and review the diff.
