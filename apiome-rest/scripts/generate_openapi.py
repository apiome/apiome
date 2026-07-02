#!/usr/bin/env python3
"""
Generate OpenAPI specification (JSON and YAML) from the apiome-rest FastAPI app.

Run from the apiome-rest directory with PYTHONPATH=src:
    uv run python scripts/generate_openapi.py
    # or
    PYTHONPATH=src python scripts/generate_openapi.py

Output is written to openapi.json and openapi.yaml in the apiome-rest directory.
"""

import json
import sys
from pathlib import Path

# Ensure project root is on path so app can be imported
project_root = Path(__file__).resolve().parent.parent
src = project_root / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

import yaml

# Import app after path is set
from app.main import app


def main() -> None:
    spec = app.openapi()
    out_dir = project_root  # write to apiome-rest/

    json_path = out_dir / "openapi.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2)
    print(f"Wrote {json_path}")

    yaml_path = out_dir / "openapi.yaml"
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(spec, f, sort_keys=False, default_flow_style=False, allow_unicode=True)
    print(f"Wrote {yaml_path}")


if __name__ == "__main__":
    main()
