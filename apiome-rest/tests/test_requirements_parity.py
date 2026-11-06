"""The Docker image's ``requirements.txt`` declares every runtime dependency ``pyproject.toml`` does.

The image installs ``requirements.txt`` (see ``Dockerfile``), while local runs and CI install from
``pyproject.toml``; a dependency added to one only (``pyarrow`` was) passes every test and then fails
in the deployed service.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
#: Installed by the Dockerfile's own ``pip install`` line, next to ``requirements.txt``.
_DOCKERFILE_EXTRAS = {"bcrypt", "email-validator"}


def _name(requirement: str) -> str:
    """The normalized distribution name of a requirement line (``uvicorn[standard]>=1`` → ``uvicorn``)."""
    return re.split(r"[\[<>=!~;\s]", requirement.strip(), maxsplit=1)[0].lower().replace("_", "-")


def test_requirements_txt_lists_every_pyproject_dependency() -> None:
    declared = {_name(dep) for dep in tomllib.loads((_ROOT / "pyproject.toml").read_text())["project"]["dependencies"]}
    lines = (_ROOT / "requirements.txt").read_text().splitlines()
    installed = {_name(line) for line in lines if line.strip() and not line.lstrip().startswith("#")}
    missing = sorted(declared - installed - _DOCKERFILE_EXTRAS)
    assert not missing, f"add to apiome-rest/requirements.txt (the Docker image installs it): {missing}"
