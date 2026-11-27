"""Structural checks for the self-hosted Pact Broker stack (PFX-6.8, #6960).

Docker is not needed: the compose file, Caddyfile and env template are parsed as text/YAML and held
to the posture the docs promise (lean services, no dev defaults, gated migration, only 80/443
published, every required variable documented in the env template).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.pact-broker.yml"
CADDYFILE = ROOT / "deploy" / "Caddyfile.pact-broker"
ENV_EXAMPLE = ROOT / "docker-compose.pact-broker.env.example"


@pytest.fixture(scope="module")
def compose() -> dict:
    """The parsed compose document."""
    return yaml.safe_load(COMPOSE.read_text())


def test_runs_only_the_services_a_broker_needs(compose):
    assert set(compose["services"]) == {"postgres", "migrate", "rest", "caddy", "backup"}
    for left_out in ("mcp", "mock", "minio", "seed", "studio"):
        assert left_out not in compose["services"]


def test_migration_and_backup_never_run_on_plain_up(compose):
    assert compose["services"]["migrate"]["profiles"] == ["migrate"]
    assert compose["services"]["backup"]["profiles"] == ["ops"]
    # REST waits only for the database: schema changes are a deliberate step.
    assert set(compose["services"]["rest"]["depends_on"]) == {"postgres"}


def test_only_tls_ports_are_published(compose):
    for name, svc in compose["services"].items():
        published = svc.get("ports", [])
        if name == "caddy":
            assert sorted(published) == ["443:443", "443:443/udp", "80:80"]
        else:
            assert published == [], f"{name} must not publish a host port"


def test_no_dev_defaults_for_secrets(compose):
    text = COMPOSE.read_text()
    assert "apiome_local_dev" not in text
    for var in ("POSTGRES_PASSWORD", "BETTER_AUTH_SECRET", "BROKER_DOMAIN", "ACME_EMAIL"):
        assert re.search(r"\$\{" + var + r":\?", text), f"{var} must be required"
    assert compose["services"]["rest"]["environment"]["APIOME_ENV"] == "production"
    assert compose["services"]["rest"]["environment"]["APIOME_DOCUMENT_STORE"] == "db"


def test_long_running_services_restart(compose):
    for name in ("postgres", "rest", "caddy"):
        assert compose["services"][name]["restart"] == "unless-stopped"


def test_every_required_variable_is_in_the_env_template():
    template = ENV_EXAMPLE.read_text()
    required = set(re.findall(r"\$\{([A-Z_]+):\?", COMPOSE.read_text()))
    assert required
    for var in required:
        assert re.search(rf"^{var}=", template, re.M), f"{var} missing from the env template"


def test_caddyfile_proxies_the_broker_domain_to_rest():
    text = CADDYFILE.read_text()
    assert "{$BROKER_DOMAIN}" in text
    assert "reverse_proxy rest:8000" in text
    assert "mcp:" not in text and "mock:" not in text


def test_every_mounted_file_exists(compose):
    for volume in compose["services"]["caddy"]["volumes"]:
        if isinstance(volume, str) and volume.startswith("./"):
            assert (ROOT / volume.split(":")[0]).exists()
